"""Bounded, offline probes of unchanged functions from pinned upstream sources."""
from __future__ import annotations

import ast
import glob
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reproductions/2026-10-05-shanghai-lab"
PINS = {
    "internagent": "fa8c3eedfa9751d3752ea6eb49220b303ac2397d",
    "internagents": "4a5f2ab2879ebd4f806155c796e247da94bb1625",
}


def extract(path: Path, names: set[str], namespace: dict) -> dict:
    raw = path.read_bytes()
    tree = ast.parse(raw, filename=str(path))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in nodes} != names:
        raise RuntimeError("Missing upstream function")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "functions": {node.name: {"start": node.lineno, "end": node.end_lineno} for node in nodes},
    }


def main() -> None:
    for name, pin in PINS.items():
        repo = ROOT / "workspaces/upstreams" / name
        actual = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        if actual != pin:
            raise RuntimeError(f"Wrong upstream revision: {name}")
        if subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True).strip():
            raise RuntimeError(f"Upstream modified: {name}")

    resume_namespace = {"os": os, "osp": os.path, "glob": glob, "json": json}
    resume_source = extract(
        ROOT / "workspaces/upstreams/internagent/launch_discovery.py",
        {"load_resume_state", "_scan_completed_rounds"}, resume_namespace,
    )
    with tempfile.TemporaryDirectory(prefix="shanghai-probe-", dir=ROOT / "workspaces") as tmp:
        launch = Path(tmp) / "partial_launch"
        completed = launch / "session_001/idea_a/run_0"
        completed.mkdir(parents=True)
        (completed / "final_info.json").write_text("{}\n")
        (launch / "session_001/idea_b/run_0").mkdir(parents=True)
        logger = logging.getLogger("offline_probe")
        partial = resume_namespace["load_resume_state"](str(launch), logger)
        (completed / "final_info.json").unlink()
        empty = resume_namespace["load_resume_state"](str(launch), logger)

    # Explicit max_turns bypasses the environment-reading branch of the original helper.
    goal_namespace = {"Any": Any, "GOAL_CONTINUATION_TURNS_KEY": "goalContinuationTurns"}
    goal_source = extract(
        ROOT / "workspaces/upstreams/internagents/internagents/agent_graph.py",
        {"_goal_status", "_goal_continuation_turns", "_should_continue_goal"}, goal_namespace,
    )
    goal_cases = []
    for status, turns, used in [("active", 0, 100), ("active", 0, 0), ("complete", 0, 100), ("active", 50, 100)]:
        state = {"goal": {"status": status, "tokenBudget": 100, "tokensUsed": used}, "goalContinuationTurns": turns}
        goal_cases.append({"input": state, "max_turns": 50, "continue": goal_namespace["_should_continue_goal"](state, max_turns=50)})

    record = {
        "date": "2026-10-05",
        "method": "Unchanged AST function bodies; explicit standard-library dependencies; no full framework import",
        "pins": PINS, "api_calls": 0, "installed_dependencies": 0,
        "source_files": [resume_source, goal_source],
        "resume_probe": {
            "fixture": "One session, two ideas, only idea_a has run_0/final_info.json; no discovery_summary.json",
            "partial_completed_rounds": partial["completed_rounds"],
            "no_results_completed_rounds": empty["completed_rounds"],
        },
        "goal_probe": goal_cases,
        "limits": "Function-level probes only. No UI, model, GPU, SSH, SCP, process-restart or scientific-result reproduction.",
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "boundary-results.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"resume": record["resume_probe"], "goal_continue": [c["continue"] for c in goal_cases], "api_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
