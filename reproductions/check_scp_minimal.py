"""An actual upstream SCP stdio client/server check with a small custom tool."""
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reproductions/2026-10-06-scp-minimal"
WORK = ROOT / "workspaces/scp-minimal"


def server():
    from scp.server.fastmcp import FastMCP
    app = FastMCP("LabCouncil arithmetic check")

    @app.tool()
    def mean_squared_error(actual: list[float], predicted: list[float]) -> dict:
        """Calculate MSE on finite equal-length nonempty vectors."""
        if not actual or len(actual) != len(predicted):
            raise ValueError("Vectors must be nonempty and have equal lengths")
        if not all(math.isfinite(x) for x in actual + predicted):
            raise ValueError("Vectors must contain only finite values")
        return {"n": len(actual), "mse": sum((a-p)**2 for a,p in zip(actual,predicted))/len(actual)}

    app.run(transport="stdio")


async def client():
    from scp import ClientSession, StdioServerParameters, stdio_client
    WORK.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    record = OUTPUT / "stdio-result.json"
    if record.exists():
        raise RuntimeError("Refusing to overwrite previous result")
    # The child cwd has no .env; parent does not read the repository's .env.
    params = StdioServerParameters(command=sys.executable,
        args=[str(Path(__file__).resolve()), "--server"], cwd=WORK,
        env={"PYTHON_DOTENV_DISABLED": "1"})
    events = []
    def save():
        record.write_text(json.dumps({"events": events, "completed": False}, indent=2, ensure_ascii=False))
    print("Starting upstream stdio transport", flush=True)
    async def on_message(message):
        events.append({"transport_message": str(message)})
        save()
    with (OUTPUT / "attempt-02-server-stderr.txt").open("w") as stderr:
        async with stdio_client(params, errlog=stderr) as (read, write):
            print("Transport started; initializing session", flush=True)
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=5), message_handler=on_message) as session:
                events.append({"initialize": (await session.initialize()).model_dump(mode="json")})
                save()
                events.append({"tools": (await session.list_tools()).model_dump(mode="json")})
                save()
                cases = [
                    ("valid", "mean_squared_error", {"actual": [1,3,5,7,9], "predicted": [5,5,5,5,5]}),
                    ("length_error", "mean_squared_error", {"actual": [1,3], "predicted": [1]}),
                    ("type_error", "mean_squared_error", {"actual": ["invalid"], "predicted": [1]}),
                    ("unknown_tool", "no_such_tool", {}),
                    ("valid_after_errors", "mean_squared_error", {"actual": [1,3,5,7,9], "predicted": [1,3,5,7,9]}),
                ]
                for label, name, args in cases:
                    result = await session.call_tool(name, args)
                    events.append({"case": label, "arguments": args,
                                   "response": result.model_dump(mode="json")})
                    save()
    calls = {e["case"]: e["response"] for e in events if "case" in e}
    first = json.loads(calls["valid"]["content"][0]["text"])
    last = json.loads(calls["valid_after_errors"]["content"][0]["text"])
    expected = sum(x*x for x in (-4,-2,0,2,4))/5
    checks = {"independent_mse": first["mse"] == expected == 8,
              "valid_after_errors": last["mse"] == 0 and not calls["valid_after_errors"]["isError"],
              "negative_cases": all(calls[k]["isError"] for k in ("length_error", "type_error", "unknown_tool"))}
    record.write_text(json.dumps({"events": events, "checks": checks,
        "model_calls": 0, "hosted_hub_verified": False}, indent=2, ensure_ascii=False))
    print(json.dumps(checks))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    if "--output-dir" in sys.argv:
        OUTPUT = Path(sys.argv[sys.argv.index("--output-dir")+1]).absolute()
        OUTPUT.mkdir(parents=True, exist_ok=True)
    if "--compat" in sys.argv:
        OUTPUT = OUTPUT / "compatibility-attempt"
        OUTPUT.mkdir(exist_ok=True)
    if "--trace" in sys.argv:
        OUTPUT = OUTPUT / "trace-attempt"
        OUTPUT.mkdir(exist_ok=True)
    if "--unrestricted" in sys.argv:
        OUTPUT = OUTPUT / "unrestricted-control"
        OUTPUT.mkdir(exist_ok=True)
    if "--server" in sys.argv:
        server()
    else:
        asyncio.run(client())
