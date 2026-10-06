"""Bounded unchanged InternAgent ClaudeCodeRunner against real DeepSeek Flash."""
import http.server
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from check_deepseek_connectivity import load_config, redact

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workspaces/upstreams/internagent"
WORK = ROOT / "workspaces/internagent-claude-backend"
OUTPUT = ROOT / "reproductions/2026-10-06-internagent-autodebug"
CLI = ROOT / "workspaces/claude-code-trial/node_modules/.bin"
PROMPT = "This is a bounded connectivity test. Do not use any tools, read files, or change anything. Reply with exactly LABCOUNCIL_BACKEND_OK."


def child():
    sys.path.insert(0, str(SOURCE))
    from internagent.experiments_utils_claude import ClaudeCodeRunner
    import logging
    logging.basicConfig(level=logging.INFO)
    result = ClaudeCodeRunner(model="deepseek-flash").run(PROMPT, cwd=WORK)
    print(json.dumps({"runner_output": result}, ensure_ascii=False), flush=True)


def host():
    result_file = OUTPUT / "claude-backend-result.json"
    if result_file.exists():
        raise RuntimeError("Refusing to overwrite an existing attempt")
    credentials = load_config(ROOT / ".env")
    if credentials["DEEPSEEK_MODEL"] != "deepseek-flash":
        raise RuntimeError("Flash-only trial")
    key = credentials["DEEPSEEK_API_KEY"]
    records, lock = [], threading.Lock()
    WORK.mkdir(parents=True, exist_ok=True)

    def persist():
        sanitized = redact(records, key)
        (WORK / ("proxy-raw-" + OUTPUT.name + ".json")).write_text(json.dumps(sanitized, indent=2, ensure_ascii=False))
        for entry in sanitized:
            payload = entry.get("forwarded_request", {})
            canonical = json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
            entry.update(request_sha256=hashlib.sha256(canonical).hexdigest(), request_bytes=len(canonical))
            entry["forwarded_request"] = {"model":payload.get("model"), "thinking":payload.get("thinking"),
                "max_tokens":payload.get("max_tokens"),"stream":payload.get("stream"),
                "messages":payload.get("messages"),"tool_names":[t.get("name") for t in payload.get("tools",[])],
                "system_sha256":hashlib.sha256(json.dumps(payload.get("system"),ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
            entry["request_sanitization"] = "Full proprietary CLI system/tool descriptions retained in ignored local raw log; public record has hashes and tool names."
            usage=[]
            for line in entry.get("response_body", "").splitlines():
                if line.startswith("data: "):
                    event=json.loads(line[6:])
                    value=event.get("usage",event.get("message",{}).get("usage"))
                    if value: usage.append(value)
            if usage: entry["usage"]=usage[-1]
        (OUTPUT / "claude-backend-proxy.json").write_text(json.dumps(sanitized,indent=2,ensure_ascii=False))

    class Gateway(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def fail(self, status):
            body = json.dumps({"error": {"type": "invalid_request_error", "message": "Bounded trial request rejected"}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            path = urlsplit(self.path).path
            if path not in ("/v1/messages", "/v1/messages/count_tokens") or not 0 < size <= 100000:
                return self.fail(400)
            payload = json.loads(self.rfile.read(size))
            requested_model = payload.get("model", "")
            if requested_model.replace("[1m]", "") != "deepseek-flash":
                return self.fail(400)
            with lock:
                if len(records) >= 4:
                    return self.fail(429)
                entry = {"attempt": len(records)+1, "path": self.path, "requested_model": requested_model}
                records.append(entry)
            payload.pop("metadata", None)
            payload["model"] = "deepseek-flash"
            if path == "/v1/messages":
                payload.update(max_tokens=512, thinking={"type":"disabled"})
            entry["forwarded_request"] = payload
            persist()
            request = urllib.request.Request("https://api.deepseek.com/anthropic"+path,
                data=json.dumps(payload).encode(), headers={"x-api-key":key,
                "Content-Type":"application/json", "anthropic-version":"2023-06-01"})
            started=time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=35) as response:
                    entry["http_status"]=response.status
                    self.send_response(response.status)
                    self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    collected=bytearray()
                    while chunk:=response.readline():
                        collected.extend(chunk)
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    entry["response_body"]=collected.decode(errors="replace")
                    self.close_connection=True
            except urllib.error.HTTPError as error:
                entry.update(http_status=error.code, response_body=error.read().decode(errors="replace"))
                self.fail(error.code)
            except Exception as error:
                entry["error_type"]=type(error).__name__
                self.fail(502)
            finally:
                entry["elapsed_seconds"]=time.monotonic()-started
                with lock:
                    persist()

    server=http.server.ThreadingHTTPServer(("127.0.0.1",23496),Gateway)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    env={k:v for k,v in os.environ.items() if not any(word in k.upper() for word in ("KEY","TOKEN","SECRET","PASSWORD","ANTHROPIC","CLAUDE","OPENAI","DEEPSEEK","GOOGLE","GEMINI","LANGSMITH","LANGCHAIN"))}
    env.update(PATH=str(CLI)+os.pathsep+env.get("PATH",""),
        ANTHROPIC_BASE_URL="http://127.0.0.1:23496", ANTHROPIC_AUTH_TOKEN="trial-placeholder",
        ANTHROPIC_MODEL="deepseek-flash",ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-flash",
        ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-flash",ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-flash",
        CLAUDE_CODE_SUBAGENT_MODEL="deepseek-flash",CLAUDE_CONFIG_DIR=str(WORK/"cli-config"),
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",DISABLE_TELEMETRY="1",DISABLE_ERROR_REPORTING="1",
        DISABLE_AUTOUPDATER="1",PYTHON_DOTENV_DISABLED="1")
    child_process = subprocess.Popen([sys.executable, str(Path(__file__).absolute()), "--child"],
        cwd=WORK, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    timed_out=False
    try:
        stdout,stderr=child_process.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        timed_out=True
        os.killpg(child_process.pid,signal.SIGKILL)
        stdout,stderr=child_process.communicate()
    finally:
        server.shutdown()
        server.server_close()
    (OUTPUT/"claude-backend-stdout.txt").write_text(redact(stdout,key))
    (OUTPUT/"claude-backend-stderr.txt").write_text(redact(stderr,key))
    version=subprocess.check_output([str(CLI/"claude"),"--version"],text=True).strip()
    result={"cli_version":version,"host_child_exit":child_process.returncode,"timed_out":timed_out,
            "request_attempts":len(records),"max_attempts":4,"max_output_tokens":512,
            "expected_marker_in_output":"LABCOUNCIL_BACKEND_OK" in stdout,
            "original_runner_source_unchanged":True,"full_discovery_loop_verified":False}
    result_file.write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=="__main__":
    if "--attempt-02" in sys.argv:
        OUTPUT = OUTPUT / "backend-attempt-02"
        OUTPUT.mkdir(exist_ok=True)
    child() if "--child" in sys.argv else host()
