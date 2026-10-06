import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from labcouncil.store import Store
from labcouncil.web import make_server
from labcouncil.worker import step


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name)/"state.sqlite3")
        self.server = make_server(self.store, 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.directory.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        standard = {"Content-Type": "application/json", "X-LabCouncil": "local"}
        if headers:
            standard.update(headers)
        payload = json.dumps(body) if body is not None else None
        connection.request(method, path, payload, standard)
        response = connection.getresponse()
        data = response.read()
        result = response.status, dict(response.getheaders()), data
        connection.close()
        return result

    def test_actual_http_workflow_and_evidence(self):
        status, _, body = self.request("POST", "/api/projects", {"title":"HTTP 流程", "idea":"检查证据"})
        self.assertEqual(status, 201)
        identifier = json.loads(body)["id"]
        while step(self.store):
            pass
        status, _, body = self.request("POST", f"/api/projects/{identifier}/meeting", {})
        self.assertEqual(status, 200)
        meeting = json.loads(body)["id"]
        draft = {"expected_revision":0,"instruction":"尚未确认的方向","scenario":"outlier"}
        status, _, body = self.request("POST", f"/api/meetings/{meeting}/draft", draft)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["revision"], 1)
        self.assertEqual(self.store.project(identifier)["version"], 1)
        self.assertEqual(self.request("POST", f"/api/meetings/{meeting}/draft", draft)[0], 409)
        status, _, body = self.request("POST", f"/api/meetings/{meeting}/ask", {"question":"这些结果能说明什么？"})
        self.assertEqual(status, 200)
        self.assertIn("模拟", json.loads(body)["answer"])
        decision = {"expected_version":1,"instruction":"加入异常点再算","scenario":"outlier"}
        status, _, first = self.request("POST", f"/api/meetings/{meeting}/confirm", decision)
        self.assertEqual(status, 200)
        status, _, repeated = self.request("POST", f"/api/meetings/{meeting}/confirm", decision)
        self.assertEqual(first, repeated)
        while step(self.store):
            pass
        status, _, body = self.request("GET", f"/api/projects/{identifier}")
        project = json.loads(body)
        self.assertEqual(project["version"], 2)
        self.assertEqual(len(project["artifacts"]), 6)
        artifact_id = project["artifacts"][-1]["id"]
        _, _, data = self.request("GET", f"/api/evidence/{artifact_id}")
        evidence = json.loads(data)
        canonical = json.dumps(evidence["body"], ensure_ascii=False, sort_keys=True, separators=(",",":"), allow_nan=False)
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), evidence["sha256"])

    def test_cross_site_and_rebinding_mutations_blocked(self):
        for headers in ({"Origin":"https://unrelated.example"}, {"Host":"evil.example"}, {"X-LabCouncil":""}):
            status, _, _ = self.request("POST", "/api/projects", {"title":"x","idea":"y"}, headers=headers)
            self.assertEqual(status, 403)
        self.assertEqual(self.store.projects(), [])

    def test_five_inputs_travel_through_http_draft_and_confirmation(self):
        from labcouncil.brief import normalize
        brief=normalize(None,'第一轮目标','simulation')
        brief['resources']='自有公开数据'
        status,_,raw=self.request('POST','/api/projects',{'title':'五项输入','idea':brief['idea'],'brief':brief})
        self.assertEqual(status,201)
        pid=json.loads(raw)['id']
        _,_,raw=self.request('POST',f'/api/projects/{pid}/meeting',{})
        mid=json.loads(raw)['id']
        brief={**brief,'idea':'第二轮目标','requirements':'继承原有数据和规划'}
        body={'expected_revision':0,'instruction':brief['idea'],'scenario':'outlier','brief':brief}
        self.assertEqual(self.request('POST',f'/api/meetings/{mid}/draft',body)[0],200)
        self.assertEqual(self.store.project(pid)['version'],1)
        body={**body,'expected_version':1}
        self.assertEqual(self.request('POST',f'/api/meetings/{mid}/confirm',body)[0],200)
        status,_,raw=self.request('GET',f'/api/projects/{pid}')
        self.assertEqual(status,200)
        project=json.loads(raw)
        self.assertEqual(project['current_inputs']['body'],brief)
        self.assertEqual(len(project['input_history']),2)
        self.assertEqual(len(project['tasks']),6)

    def test_invalid_requests_and_no_file_traversal(self):
        self.assertEqual(self.request("POST", "/api/projects", ["bad"])[0], 400)
        self.assertEqual(self.request("POST", "/api/projects", {"title":"x","idea":"y","budget":"9"})[0], 400)
        self.assertEqual(self.request("POST", "/api/projects", {"title":"x","idea":"y"}, headers={"Content-Type":"text/plain"})[0], 415)
        for path in ("/../.env", "/.env", "/api/evidence/missing", "/workspaces/state.sqlite3"):
            self.assertEqual(self.request("GET", path)[0], 404)

    def test_static_ui_available_with_csp(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("本地模拟原型", body.decode())
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("GET", "/app.js")[0], 200)
        self.assertEqual(self.request("GET", "/style.css")[0], 200)


if __name__ == "__main__":
    unittest.main()
