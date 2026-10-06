"""Standalone worker; the browser and web process do not own task lifetimes."""
import threading
from .simulation import execute
from .store import Conflict


def step(store):
    store.due_meetings()
    task = store.claim()
    if task is None:
        return False
    try:
        if task["mode"]=="real_case":
            from .case import execute as execute_case
            body=execute_case(store,task)
        else:
            body = execute(store, task)
        store.complete(task, body)
    except Conflict:
        # A newer lease owns recovery. Never let this stale worker fail its task.
        if task["mode"]=="real_case":store.fail(task,"真实任务冲突或额度用完；不自动重发，请查看调用记录")
        return True
    except Exception as error:
        store.fail(task, error)
    return True


def run(store, stop=None, interval=1):
    stop = stop or threading.Event()
    while not stop.is_set():
        if not step(store):
            stop.wait(interval)
