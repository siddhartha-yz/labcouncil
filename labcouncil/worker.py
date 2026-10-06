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
        body = execute(store, task)
        store.complete(task, body)
    except Conflict:
        # A newer lease owns recovery. Never let this stale worker fail its task.
        return True
    except Exception as error:
        store.fail(task, error)
    return True


def run(store, stop=None, interval=1):
    stop = stop or threading.Event()
    while not stop.is_set():
        if not step(store):
            stop.wait(interval)
