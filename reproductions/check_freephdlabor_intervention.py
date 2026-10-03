"""Check a pinned upstream callback with real smolagents memory, without an LLM.

This is a component behavior check, not a replication of scientific results.
Each case runs in a child process so incomplete input cannot hang the runner.
"""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime


PIN = "9102d18a161037294d3d963b2799351aa724c58b"
CASES = ("no_input", "modify", "new_task", "cancel", "incomplete_input")


def run_case(repo, case):
    sys.path.insert(0, str(repo))
    from smolagents.memory import AgentMemory, TaskStep
    from freephdlabor.interaction.callback_tools import make_user_input_step_callback
    from freephdlabor.interaction.user_inststep import UserInstructionStep
    from queue import Queue
    from types import SimpleNamespace

    assert importlib.metadata.version("smolagents") == "1.20.0"
    queue = Queue()
    memory = AgentMemory(system_prompt="Component check; no model is called.")
    agent = SimpleNamespace(memory=memory)
    callback = make_user_input_step_callback(queue)
    inputs = {
        "no_input": [],
        "modify": ["interrupt", "Add a matched baseline.", "", "", "m"],
        "new_task": ["interrupt", "Check the raw results.", "", "", "n"],
        "cancel": ["interrupt", "", ""],
        "incomplete_input": ["interrupt", "Add a matched baseline."],
    }
    for line in inputs[case]:
        queue.put(line)
    # Preserve proof that an expected timeout occurs inside the callback.
    print("CALLBACK_STARTED", flush=True)
    callback(None, agent)
    if case in ("no_input", "cancel"):
        assert memory.steps == []
    elif case == "modify":
        assert len(memory.steps) == 1
        assert isinstance(memory.steps[0], UserInstructionStep)
        assert memory.steps[0].user_instruction == "Add a matched baseline."
        assert "Add a matched baseline." in memory.steps[0].to_messages()[0].content[0]["text"]
        callback(None, agent)
        assert len(memory.steps) == 1, "A later callback duplicated the instruction"
    elif case == "new_task":
        assert len(memory.steps) == 1
        assert type(memory.steps[0]) is TaskStep
        assert memory.steps[0].task == "Check the raw results."
    else:
        raise AssertionError("Incomplete input unexpectedly returned")
    print("CASE_CONFIRMED", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", choices=CASES)
    args = parser.parse_args()
    repo = args.repo.resolve()
    sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if sha != PIN:
        raise SystemExit(f"Expected pinned commit {PIN}, got {sha}")
    if subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True).strip():
        raise SystemExit("Upstream checkout must be clean")
    if args.case:
        run_case(repo, args.case)
        return
    if args.output is None:
        parser.error("--output is required when running all cases")
    results = []
    for case in CASES:
        command = [sys.executable, str(Path(__file__).resolve()), str(repo), "--case", case]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=8)
            ok = completed.returncode == 0 and "CASE_CONFIRMED" in completed.stdout
            results.append({"case": case, "outcome": "confirmed" if ok else "failed",
                            "exit_code": completed.returncode,
                            "stdout": completed.stdout, "stderr": completed.stderr})
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout or b""
            stderr = error.stderr or b""
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            expected = case == "incomplete_input" and "CALLBACK_STARTED" in stdout
            results.append({"case": case, "outcome": "observed_block" if expected else "failed",
                            "timeout_seconds": 8, "stdout": stdout, "stderr": stderr})
    source = repo / "freephdlabor/interaction/callback_tools.py"
    report = {
        "scope": "component behavior only; no LLM, socket transport, full agent loop, or scientific results",
        "timestamp": datetime.now().astimezone().isoformat(),
        "upstream_commit": sha,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "smolagents": importlib.metadata.version("smolagents"),
        "model_calls": 0,
        "fixtures": "Queue inputs and an agent-shaped object holding real AgentMemory",
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    for result in results:
        print(result["case"], result["outcome"])
    if any(result["outcome"] == "failed" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
