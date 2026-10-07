import argparse
import json
import signal
import threading
from .store import Store
from .worker import run, step
from .web import make_server


def main():
    parser = argparse.ArgumentParser(description="LabCouncil 本地组会；默认模拟，真实后台可选本机 Codex CLI 或 DeepSeek key")
    parser.add_argument("command", choices=["serve", "worker", "demo", "start", "status", "stop"])
    parser.add_argument("--database", default="workspaces/labcouncil/state.sqlite3")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--once", action="store_true", help="worker 只处理一个任务")
    parser.add_argument("--instance-id", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.command in ("start", "status", "stop"):
        from . import lifecycle
        if args.command == "start":
            result = lifecycle.start(args.database, args.port)
        else:
            result = getattr(lifecycle, args.command)(args.database)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    store = Store(args.database)
    if args.command == "demo":
        identifier = store.create_project("组会演示：一次方向调整", "比较拟合直线与只猜平均值；先用平稳数据，再由我决定是否加入异常点。")
        while step(store):
            pass
        meeting = store.open_meeting(identifier)
        print(json.dumps({"project_id": identifier, "meeting_id": meeting, "simulation": True}, ensure_ascii=False))
    elif args.command == "worker":
        if args.once:
            print(json.dumps({"worked": step(store)}))
        else:
            stop = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            signal.signal(signal.SIGINT, lambda *_: stop.set())
            run(store, stop)
    else:
        with make_server(store, args.port, args.instance_id) as server:
            signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown,daemon=True).start())
            print(f"组会界面：http://127.0.0.1:{server.server_address[1]}（默认模拟；另开 worker 才会执行任务）", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
