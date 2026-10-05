"""Launch original InternAgentS behind a bounded, credential-isolating local proxy."""
from __future__ import annotations
import http.server
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request

from check_deepseek_connectivity import load_config, redact, ENDPOINT

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "workspaces/upstreams/internagents"
TRIAL = ROOT / "workspaces/internagents-trial"
PROJECT = TRIAL / "project"
PROXY_PORT = 23490
PORTS = {"backend": 23491, "runtime": 23492, "ui": 23493}


def prepare():
    PROJECT.mkdir(parents=True, exist_ok=True)
    (PROJECT / "data.csv").write_text("x,y\n0,1\n1,3\n2,5\n3,7\n4,9\n")
    config = json.loads((REPO / "deepagent.config.json").read_text())
    config.update({"model_provider": "openai_compatible", "openai_compatible_model": "deepseek-flash",
                   "openai_compatible_base_url": f"http://127.0.0.1:{PROXY_PORT}/v1",
                   "authorization_mode": "all", "skills": {"enabled": False},
                   "web_search": {"enabled": False},
                   "backend": {"type": "local_shell", "root_dir": str(PROJECT), "inherit_env": False},
                   "interrupt_on": {name: {"allowed_decisions": ["approve", "reject"]} for name in
                                    ["execute", "write_file", "edit_file", "read_file", "ls", "glob", "grep"]}})
    (TRIAL / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    resources = {"default_resource": "local", "resources": [{"id": "local", "label": "Trial", "backend": "local_shell",
                 "workspace": str(PROJECT), "remote_url": f"http://127.0.0.1:{PORTS['runtime']}", "remote_assistant_id": "agent", "enabled": True}]}
    (TRIAL / "resources.json").write_text(json.dumps(resources, indent=2) + "\n")
    (TRIAL / "empty.env").write_text("")


def main():
    prepare()
    credentials = load_config(ROOT / ".env")
    if credentials["DEEPSEEK_MODEL"] != "deepseek-flash":
        raise RuntimeError("Trial requires the previously verified deepseek-flash model")
    key = credentials["DEEPSEEK_API_KEY"]
    lock = threading.Lock()
    previous_records = TRIAL / "proxy-records.json"
    requests = json.loads(previous_records.read_text()) if previous_records.exists() else []

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def send_json(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/status":
                self.send_json(200, {"forwarded": len(requests), "max_requests": 12, "ports": PORTS})
            else:
                self.send_json(404, {})

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            if self.path != "/v1/chat/completions" or not 0 < size <= 60000:
                self.send_json(400, {"error": {"message": "Trial request rejected"}})
                return
            payload = json.loads(self.rfile.read(size))
            if payload.get("model") != "deepseek-flash":
                self.send_json(400, {"error": {"message": "Trial model rejected"}})
                return
            with lock:
                if len(requests) >= 12:
                    self.send_json(429, {"error": {"message": "External trial request limit reached"}})
                    return
                record = {"number": len(requests) + 1, "started": time.time(), "original_request": payload.copy()}
                requests.append(record)
            payload["max_tokens"] = 1024
            payload["thinking"] = {"type": "disabled"}
            if payload.get("stream"):
                payload["stream_options"] = {"include_usage": True}
            record["forwarded_request"] = payload
            request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
                                            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            started = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    record["http_status"] = response.status
                    self.send_response(response.status)
                    self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    body = bytearray()
                    while chunk := response.readline():
                        body.extend(chunk)
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    record["response_body"] = body.decode("utf-8", errors="replace")
                    self.close_connection = True
            except urllib.error.HTTPError as error:
                record["http_status"] = error.code
                record["error_body"] = error.read().decode("utf-8", errors="replace")
                self.send_json(error.code, {"error": {"message": "Upstream request failed"}})
            except Exception as error:
                record["error_type"] = type(error).__name__
                self.send_json(502, {"error": {"message": "Upstream transport failed"}})
            finally:
                record["elapsed_seconds"] = round(time.monotonic() - started, 3)
                (TRIAL / "proxy-records.json").write_text(json.dumps(redact(requests, key), ensure_ascii=False, indent=2) + "\n")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", PROXY_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {name: value for name, value in os.environ.items() if not any(word in name.upper() for word in ["KEY", "TOKEN", "SECRET", "PASSWORD", "LANGSMITH", "LANGCHAIN", "DEEPSEEK", "OPENAI", "ANTHROPIC", "GOOGLE", "GEMINI"])}
    env.update({"INTERNAGENT_ENV_FILE": str(TRIAL / "empty.env"), "PYTHON_DOTENV_DISABLED": "1",
                "DEEPAGENT_CONFIG": str(TRIAL / "config.json"), "INTERNAGENT_RESOURCES_FILE": str(TRIAL / "resources.json"),
                "INTERNAGENTS_MODEL_PROVIDER": "openai_compatible", "OPENAI_API_KEY": "trial-placeholder",
                "OPENAI_BASE_URL": f"http://127.0.0.1:{PROXY_PORT}/v1", "DEEPAGENT_MODEL": "deepseek-flash",
                "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false", "LANGGRAPH_AUTH_TYPE": "noop",
                "LANGSMITH_ENDPOINT": "http://127.0.0.1:9", "LANGCHAIN_ENDPOINT": "http://127.0.0.1:9",
                "NEXT_TELEMETRY_DISABLED": "1", "INTERNAGENTS_SKIP_INSTALL": "1", "INTERNAGENTS_OPEN_BROWSER": "0",
                "INTERNAGENT_GOAL_MAX_AUTO_TURNS": "2",
                "INTERNAGENTS_BACKEND_PORT": str(PORTS["backend"]), "INTERNAGENTS_LOCAL_RUNTIME_PORT": str(PORTS["runtime"]),
                "INTERNAGENTS_UI_PORT": str(PORTS["ui"])})
    with (TRIAL / "launcher.log").open("a") as log:
        child = subprocess.Popen(["bash", "scripts/dev.sh"], cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        (TRIAL / "launcher-pid.json").write_text(json.dumps({"pid": child.pid, "ports": PORTS}) + "\n")
        def stop(*_):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
            server.shutdown()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        print(json.dumps({"started_original_launcher": True, "ports": PORTS}), flush=True)
        code = child.wait()
        server.shutdown()
        print(json.dumps({"launcher_exit": code, "forwarded": len(requests)}), flush=True)


if __name__ == "__main__":
    main()
