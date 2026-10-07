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

    def test_unlimited_qa_and_settings_without_legacy_qa_budget(self):
        _,_,raw=self.request('POST','/api/projects',{'title':'问答不限次数','idea':'保留历史','qa_budget':0})
        pid=json.loads(raw)['id']
        while step(self.store):pass
        _,_,raw=self.request('POST',f'/api/projects/{pid}/meeting',{})
        mid=json.loads(raw)['id']
        for i in range(8):
            self.assertEqual(self.request('POST',f'/api/meetings/{mid}/ask',{'question':f'追问{i}'})[0],200)
        self.assertEqual(self.request('POST',f'/api/projects/{pid}/configure',{'paused':True,'budget':9})[0],200)
        _,_,raw=self.request('GET',f'/api/projects/{pid}')
        p=json.loads(raw)
        self.assertTrue(p['execution']['qa_unlimited'])
        self.assertEqual(p['qa_used'],8)
        self.assertEqual(p['qa_budget'],0)
        self.assertTrue(p['paused'])

    def test_round_time_is_confirmed_through_http(self):
        from labcouncil.brief import normalize
        b=normalize(None,'控制本轮投入','simulation')
        b['work_time']={'duration_minutes':45}
        status,_,raw=self.request('POST','/api/projects',{'title':'每轮时间预算','idea':b['idea'],'brief':b})
        self.assertEqual(status,201)
        pid=json.loads(raw)['id']
        _,_,raw=self.request('GET',f'/api/projects/{pid}')
        p=json.loads(raw)
        self.assertEqual(p['round_time']['duration_minutes'],45)
        self.assertEqual(p['round_time']['deadline_at']-p['round_time']['started_at'],2700)
        self.assertIn('45分钟',p['current_inputs']['plan']['work_window'])

    def test_group_chat_can_discuss_and_arrange_work_without_meeting_controls(self):
        _,_,raw=self.request('POST','/api/projects',{'title':'持续群聊','idea':'原目标'})
        pid=json.loads(raw)['id']
        def say(message,mid):
            status,_,raw=self.request('POST',f'/api/projects/{pid}/chat',{'message':message,'message_id':mid})
            self.assertEqual(status,200)
            return json.loads(raw)
        say('现在进度怎么样？','http-chat-0001')
        self.assertEqual(self.store.project(pid)['meetings'],[])
        say('我在想接下来先核对原始数据','http-chat-0002')
        self.assertEqual(self.store.project(pid)['version'],1)
        first=say('按这个做','http-chat-0003')
        self.assertEqual(first,say('按这个做','http-chat-0003'))
        p=self.store.project(pid)
        self.assertEqual(p['version'],2)
        self.assertEqual(len(p['group_messages']),3)
        self.assertEqual(p['input_history'][0]['body']['idea'],'原目标')
        self.assertEqual(p['current_inputs']['body']['idea'],'我在想接下来先核对原始数据')

    def test_backend_selected_through_http_and_invalid_value_atomic(self):
        status,_,raw=self.request('POST','/api/projects',{'title':'CLI HTTP fixture','idea':'保留模型配置','mode':'research','backend':'codex_cli'})
        self.assertEqual(status,201)
        pid=json.loads(raw)['id']
        status,_,raw=self.request('GET',f'/api/projects/{pid}')
        execution=json.loads(raw)['execution']
        self.assertEqual(execution['backend'],'codex_cli')
        self.assertEqual(execution['model'],'gpt-6.1-sol')
        self.assertEqual(execution['reasoning_effort'],'high')
        self.assertEqual(self.store.projects()[0]['backend'],'codex_cli')
        self.assertEqual(self.request('POST','/api/projects',{'title':'invalid','idea':'不能换型号','backend':'unknown'})[0],400)
        self.assertEqual(len(self.store.projects()),1)

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

    def test_public_source_cap_is_preserved_in_http_creation(self):
        status,_,raw=self.request('POST','/api/projects',{'title':'bounded','idea':'check','source_budget':3})
        self.assertEqual(status,201)
        self.assertEqual(self.store.project(json.loads(raw)['id'])['execution']['source_budget'],3)
        self.assertEqual(self.request('POST','/api/projects',{'title':'invalid','idea':'check','source_budget':25})[0],400)
