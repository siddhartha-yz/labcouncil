"""Loopback-only HTTP API and static UI, using Python's standard library."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit
from .store import Conflict, NotFound

STATIC = Path(__file__).with_name("static")


def handler(store):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LabCouncil/0.1"

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def host_ok(self):
            port = self.server.server_address[1]
            return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

        def do_GET(self):
            if not self.host_ok():
                return self.send(403, {"error": "仅允许本机访问"})
            path = urlsplit(self.path).path
            try:
                if path == "/api/health":
                    return self.send(200, {"ok": True, "default_mode":"simulation","supports_real_case":True, "supports_research":True, "instance_id": self.server.instance_id})
                if path == "/api/projects":
                    return self.send(200, {"projects": store.projects(), "default_mode":"simulation"})
                parts = path.strip("/").split("/")
                if len(parts) == 3 and parts[:2] == ["api", "projects"]:
                    return self.send(200, store.project(parts[2]))
                if len(parts) == 3 and parts[:2] == ["api", "meetings"]:
                    return self.send(200, store.meeting(parts[2]))
                if len(parts) == 3 and parts[:2] == ["api", "evidence"]:
                    a = store.artifact(parts[2])
                    return self.send(200, {**a, "body": json.loads(a["body"]), "hash_format": "UTF-8 JSON, sort_keys=True, ensure_ascii=False, separators=(',',':'), allow_nan=False"})
                if len(parts)==3 and parts[:2]==["api","model-requests"]:
                    return self.send(200,store.request_record(parts[2]))
                if len(parts)==3 and parts[:2]==["api","tool-operations"]:
                    return self.send(200,store.operation_record(parts[2]))
                if len(parts)==3 and parts[:2]==["api","source-requests"]:
                    return self.send(200,store.source_record(parts[2]))
                files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
                if path in files:
                    filename, mime = files[path]
                    return self.send(200, (STATIC / filename).read_bytes(), mime)
                self.send(404, {"error": "找不到这个页面"})
            except NotFound as error:
                self.send(404, {"error": str(error)})
            except Conflict as error:
                self.send(409, {"error": str(error)})

        def do_POST(self):
            port = self.server.server_address[1]
            origin = self.headers.get("Origin")
            if not self.host_ok() or self.headers.get("X-LabCouncil") != "local" or (origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")):
                return self.send(403, {"error": "请求来源无效"})
            if self.headers.get_content_type() != "application/json":
                return self.send(415, {"error": "需要 JSON 请求"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    return self.send(413, {"error": "请求大小无效"})
                body = json.loads(self.rfile.read(length), parse_constant=lambda x: (_ for _ in ()).throw(ValueError("非有限数字")))
                if not isinstance(body, dict):
                    raise ValueError("需要 JSON 对象")
                path = urlsplit(self.path).path.strip("/").split("/")
                if path == ["api", "projects"]:
                    identifier = store.create_project(body.get("title"), body.get("idea"), body.get("scenario", "clean"), body.get("budget", 9), body.get("qa_budget", 6), body.get("meeting_at"),body.get("mode","simulation"),body.get("api_budget",18),body.get("qa_api_budget",3),body.get('brief'),source_budget=body.get('source_budget',24))
                    return self.send(201, {"id": identifier})
                if len(path) == 4 and path[:2] == ["api", "projects"]:
                    if path[3] == "meeting":
                        return self.send(200, {"id": store.open_meeting(path[2])})
                    if path[3] == "configure":
                        store.configure(path[2], body.get("paused"), body.get("budget"), body.get("qa_budget"), body.get("meeting_at"))
                        return self.send(200, {"ok": True})
                if len(path) == 4 and path[:2] == ["api", "meetings"]:
                    if path[3] == "draft":
                        return self.send(200, store.save_draft(path[2], body.get("expected_revision"), body.get("instruction"), body.get("scenario"),body.get('brief')))
                    if path[3] == "ask":
                        return self.send(200, {"answer": store.ask(path[2], body.get("question"))})
                    if path[3] == "confirm":
                        return self.send(200, store.confirm(path[2], body.get("expected_version"), body.get("instruction"), body.get("scenario"),body.get('brief')))
                self.send(404, {"error": "找不到这个操作"})
            except NotFound as error:
                self.send(404, {"error": str(error)})
            except Conflict as error:
                self.send(409, {"error": str(error)})
            except (ValueError, TypeError, UnicodeError) as error:
                self.send(400, {"error": str(error)})

        def log_message(self, format, *args):
            # Do not log request bodies, project instructions, or credentials.
            pass
    return Handler


def make_server(store, port=8765, instance_id=None):
    server = ThreadingHTTPServer(("127.0.0.1", port), handler(store))
    server.daemon_threads = True
    server.instance_id = instance_id
    return server
