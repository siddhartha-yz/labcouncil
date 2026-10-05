"""Operate the original local LangGraph API and save trial state transitions."""
from __future__ import annotations
import argparse
import json
import time
import uuid
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TRIAL = ROOT / "workspaces/internagents-trial"
BASE = "http://127.0.0.1:23491"


def request(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["submit", "budget", "snapshot", "approve", "reject"])
    parser.add_argument("--label", default="state")
    parser.add_argument("--runtime", action="store_true", help="Diagnostic path: bypass coordinator and use unchanged runtime")
    parser.add_argument("--thread-file", default="thread.json")
    args = parser.parse_args()
    global BASE
    if args.runtime:
        BASE = "http://127.0.0.1:23492"
    assistant_id = "agent" if args.runtime else "agent_local"
    if args.action in {"submit", "budget"}:
        thread = request("/threads", {"metadata": {"trial": "labcouncil", "internagents_workspace_path": str(TRIAL / "project")}})
        thread_id = thread["thread_id"]
        (TRIAL / args.thread_file).write_text(json.dumps(thread) + "\n")
        prompt = (
            "这是一个小型验收任务。工作区只有 data.csv，x=0..4，y=1,3,5,7,9。请真实读取文件，"
            "用标准库 csv 计算预测 2*x+1 的 MSE 和训练数据均值预测的 MSE，保存 result.json（linear_mse、mean_mse、n）"
            "和 report.md。报告用简短中文解释做了什么、结果和局限，不超过150字。必须实际执行计算，不能心算后冒充运行。"
            "无需网页搜索、技能、子代理或额外安装，只使用当前工作区。你可以先提出 execute 工具调用，它会等待操作者审批。"
        )
        payload = {"assistant_id": assistant_id, "input": {"messages": [{"type": "human", "content": prompt}]},
                   "config": {"recursion_limit": 35, "configurable": {"internagents_workspace_path": str(TRIAL / "project")}},
                   "durability": "sync"}
        if args.action == "budget":
            now = int(time.time())
            goal = {"id": str(uuid.uuid4()), "threadId": thread_id, "objective": "预算边界验收固定状态",
                    "status": "active", "tokenBudget": 1, "tokensUsed": 0, "timeUsedSeconds": 0,
                    "createdAt": now, "updatedAt": now}
            payload["input"] = {"messages": [{"type": "human", "content":
                "这是合成预算验收。请仅回复收到，不调用任何工具，不改变目标状态；保持 active，以便检查宿主是否按预算停止下一轮。"}], "goal": goal}
        result = request(f"/threads/{thread_id}/runs", payload)
        (TRIAL / f"{args.action}.json").write_text(json.dumps({"payload": payload, "run": result}, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"thread_id": thread_id, "run_id": result["run_id"], "status": result["status"]}))
        return
    thread_id = json.loads((TRIAL / args.thread_file).read_text())["thread_id"]
    state = request(f"/threads/{thread_id}/state")
    if args.action in {"approve", "reject"}:
        tasks = state.get("tasks", [])
        values = [i.get("value", {}) for task in tasks for i in task.get("interrupts", [])]
        if not values:
            raise RuntimeError("No pending interrupt; refusing an ungrounded approval")
        actions = [action for value in values for action in value.get("action_requests", [])]
        if not actions:
            raise RuntimeError("Pending interrupt has no action requests")
        if any(action.get("name") not in {"execute", "read_file", "write_file", "edit_file", "ls", "glob", "grep"} for action in actions):
            raise RuntimeError("Unexpected tool in approval")
        # Print the actual proposed operation for operator inspection before invoking this action.
        decision = {"decisions": [{"type": args.action} for _ in actions]}
        result = request(f"/threads/{thread_id}/runs", {"assistant_id": assistant_id, "command": {"resume": decision},
                         "config": {"recursion_limit": 35}, "durability": "sync"})
        (TRIAL / f"{args.label}-decision.json").write_text(json.dumps({"actions": actions, "decision": decision, "run": result}, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"submitted_decision": args.action, "run_id": result["run_id"]}))
        return
    (TRIAL / f"{args.label}.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    runs = request(f"/threads/{thread_id}/runs")
    values = [i.get("value", {}) for task in state.get("tasks", []) for i in task.get("interrupts", [])]
    messages = state.get("values", {}).get("messages", [])
    print(json.dumps({"next": state.get("next"), "run_statuses": [r["status"] for r in runs], "interrupts": values,
                      "last_message": messages[-1].get("content") if messages else None}, ensure_ascii=False))


if __name__ == "__main__":
    main()
