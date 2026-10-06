"""Linux local service lifecycle with owned-process checks and durable state.

This starts two detached processes, never an OS login/startup service. No model
credentials are inherited. The database is retained when services stop.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
_children = {}


@contextmanager
def lock(database):
    folder = Path(database).absolute().parent
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "service.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield folder


def owned(record):
    if not record or type(record.get("pid")) is not int or not isinstance(record.get("instance"), str):
        return False
    try:
        argv = Path(f"/proc/{record['pid']}/cmdline").read_bytes().split(b"\0")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return False
    expected = [b"-m", b"labcouncil", record["command"].encode(), b"--database", record["database"].encode(), b"--instance-id", record["instance"].encode()]
    return any(argv[n:n+len(expected)] == expected for n in range(len(argv)))


def read_records(folder):
    path = folder / "service.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_records(folder, records):
    temp = folder / "service.json.tmp"
    temp.write_text(json.dumps(records, indent=2))
    os.replace(temp, folder / "service.json")


def status(database):
    with lock(database) as folder:
        records = read_records(folder)
        return {command: {**record, "running": owned(record)} for command, record in records.items()}


def stop_process(record):
    if not owned(record):
        child = _children.pop(record.get("pid"), None) if record else None
        if child and child.poll() is not None:
            child.wait()
        return False
    os.kill(record["pid"], signal.SIGTERM)
    deadline = time.monotonic()+5
    while owned(record) and time.monotonic()<deadline:
        time.sleep(.05)
    # Do not force-kill by a stale PID. Check identity a second time.
    if owned(record):
        os.kill(record["pid"], signal.SIGKILL)
    child = _children.pop(record["pid"], None)
    if child:
        child.wait(timeout=3)
    return True


def stop(database):
    with lock(database) as folder:
        records = read_records(folder)
        stopped = {command: stop_process(record) for command, record in records.items()}
        return {"stopped": stopped, "database_retained": True}


def start(database, port):
    if not 1 <= port <= 65535:
        raise ValueError("端口应为 1–65535")
    database = str(Path(database).absolute())
    with lock(database) as folder:
        records = read_records(folder)
        if any(owned(record) and record.get("database") != database for record in records.values()):
            raise ValueError("同一运行目录已有其他数据库的服务；请为每个实例使用独立目录")
        if owned(records.get("serve")) and records["serve"].get("port") != port:
            raise ValueError("这个数据库的服务正在其他端口运行；请先 stop")
        env = {k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ("KEY","TOKEN","SECRET","PASSWORD","LANGSMITH","LANGCHAIN"))}
        created = []
        try:
            for command in ("serve", "worker"):
                if owned(records.get(command)):
                    continue
                instance = uuid.uuid4().hex
                argv = [sys.executable, "-m", "labcouncil", command, "--database", database, "--instance-id", instance]
                if command == "serve":
                    argv.extend(["--port",str(port)])
                with (folder / f"{command}.log").open("ab") as log:
                    child = subprocess.Popen(argv,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,
                        stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                _children[child.pid] = child
                record = {"pid":child.pid,"command":command,"instance":instance,"database":database,"created":time.time()}
                if command == "serve":
                    record["port"] = port
                records[command] = record
                created.append(record)
                save_records(folder,records)
                if command == "serve":
                    deadline = time.monotonic()+5
                    while True:
                        try:
                            with urlopen(f"http://127.0.0.1:{port}/api/health",timeout=1) as response:
                                health = json.load(response)
                            if health.get("instance_id") != instance:
                                raise ValueError("端口已有其他服务，未替它接管 worker")
                            break
                        except OSError:
                            if child.poll() is not None or time.monotonic()>deadline:
                                raise ValueError("网页服务未启动，请查看本地 serve.log")
                            time.sleep(.05)
                else:
                    time.sleep(.1)
                    if child.poll() is not None:
                        raise ValueError("worker 未启动，请查看本地 worker.log")
        except BaseException:
            for record in reversed(created):
                stop_process(record)
            raise
        return {"url":f"http://127.0.0.1:{port}","simulation":True,
                "services":{command:{**record,"running":owned(record)} for command,record in records.items()}}
