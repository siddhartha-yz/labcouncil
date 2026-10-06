"""Original SciLab HTTP API; custom tool, explicit local-only Flask binding."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reproductions/2026-10-06-scp-minimal"
WORK = ROOT / "workspaces/scp-minimal"
PORT = 23495


def server():
    from scp.lab.server import SciLabServer
    app = SciLabServer("LabCouncilLocal")

    @app.tool()
    def mean_squared_error(actual: list[float], predicted: list[float]) -> dict:
        if not actual or len(actual) != len(predicted):
            raise ValueError("Vectors must have equal nonzero lengths")
        return {"n": len(actual), "mse": sum((a-p)**2 for a,p in zip(actual,predicted))/len(actual)}

    # run_http ignores its host argument and binds 0.0.0.0. Use the original
    # Flask application directly, without remote registration or source changes.
    app.flask_app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


def client():
    from scp.lab.client import SciLabClient
    from requests import HTTPError
    record = OUTPUT / "http-result.json"
    if record.exists():
        raise RuntimeError("Refusing to overwrite an existing attempt")
    WORK.mkdir(parents=True, exist_ok=True)
    env = {"PATH": os.environ["PATH"], "PYTHON_DOTENV_DISABLED": "1"}
    with (OUTPUT / "http-server-stdout.txt").open("w") as stdout, (OUTPUT / "http-server-stderr.txt").open("w") as stderr:
        child = subprocess.Popen([sys.executable, str(Path(__file__).absolute()), "--server"],
            cwd=WORK, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            deadline = time.monotonic()+10
            while True:
                try:
                    with urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1) as response:
                        health = json.load(response)
                    break
                except OSError:
                    if time.monotonic() > deadline or child.poll() is not None:
                        raise RuntimeError("Original edge server did not start")
                    time.sleep(.1)
            client = SciLabClient(f"http://127.0.0.1:{PORT}")
            events = [{"health": health}, {"tools": [t.model_dump(mode="json") for t in client.list_tools()]}]
            for label,name,args in [
                ("valid","mean_squared_error", {"actual":[1,3,5,7,9],"predicted":[5,5,5,5,5]}),
                ("length_error","mean_squared_error", {"actual":[1,3],"predicted":[1]}),
                ("unknown_tool","no_such_tool", {}),
                ("valid_after_errors","mean_squared_error", {"actual":[1,3,5,7,9],"predicted":[1,3,5,7,9]})]:
                try:
                    contents = client.call_tool(name,args)
                    events.append({"case":label,"arguments":args,"contents":[c.model_dump(mode="json") for c in contents]})
                except HTTPError as error:
                    events.append({"case":label,"arguments":args,"http_status":error.response.status_code,"error_body":error.response.text})
            calls = {e["case"]:e for e in events if "case" in e}
            first = json.loads(calls["valid"]["contents"][0]["text"])
            final = json.loads(calls["valid_after_errors"]["contents"][0]["text"])
            checks={"independent_mse":first["mse"]==sum(x*x for x in (-4,-2,0,2,4))/5==8,
                    "valid_after_errors":final["mse"]==0,
                    "invalid_length_rejected":calls["length_error"].get("http_status")==500,
                    "unknown_tool_rejected":calls["unknown_tool"].get("http_status")==500}
            record.write_text(json.dumps({"events":events,"checks":checks,"model_calls":0,
                "binding_adapter":"original flask_app.run(host=127.0.0.1), not run_http", "hub_verified":False},indent=2,ensure_ascii=False))
            print(json.dumps(checks))
            if not all(checks.values()):
                raise SystemExit(1)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()


if __name__ == "__main__":
    if "--output-dir" in sys.argv:
        OUTPUT = Path(sys.argv[sys.argv.index("--output-dir")+1]).absolute()
        OUTPUT.mkdir(parents=True, exist_ok=True)
    if "--server" in sys.argv:
        server()
    else:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(124))
        client()
