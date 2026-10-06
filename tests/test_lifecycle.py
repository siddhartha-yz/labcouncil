import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from labcouncil.lifecycle import owned, start, status, stop
from labcouncil.store import Store


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)/"state.sqlite3"
        self.store = Store(self.path)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1",0))
            self.port = reservation.getsockname()[1]

    def tearDown(self):
        stop(self.path)
        self.directory.cleanup()

    def wait_complete(self, project):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            result=self.store.project(project)
            if len(result["artifacts"]) == 3:
                return result
            time.sleep(.05)
        self.fail("Background worker did not complete the round")

    def test_detached_start_idempotent_restart_and_stop(self):
        project = self.store.create_project("生命周期", "后台演示")
        first = start(self.path,self.port)
        second = start(self.path,self.port)
        self.assertEqual(first["services"]["serve"]["pid"],second["services"]["serve"]["pid"])
        self.assertEqual(first["services"]["worker"]["pid"],second["services"]["worker"]["pid"])
        self.wait_complete(project)
        before=self.store.project(project)
        stop(self.path)
        self.assertTrue(all(not r["running"] for r in status(self.path).values()))
        self.assertEqual(Store(self.path).project(project)["artifacts"],before["artifacts"])
        third=start(self.path,self.port)
        self.assertNotEqual(first["services"]["worker"]["pid"],third["services"]["worker"]["pid"])
        time.sleep(.15)
        self.assertEqual(self.store.project(project)["used"],3)
        self.assertEqual(len(self.store.project(project)["artifacts"]),3)

    def test_unrelated_pid_is_never_stopped(self):
        unrelated=subprocess.Popen([sys.executable,"-c","import time; time.sleep(15)"])
        try:
            fake={"pid":unrelated.pid,"command":"worker","instance":"fake-marker","database":str(self.path)}
            self.assertFalse(owned(fake))
            (self.path.parent/"service.json").write_text(json.dumps({"worker":fake}))
            self.assertFalse(stop(self.path)["stopped"]["worker"])
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=3)

    def test_different_database_in_same_directory_not_silently_reused(self):
        start(self.path,self.port)
        with self.assertRaises(ValueError):
            start(self.path.with_name("other.sqlite3"),self.port)


if __name__ == "__main__":
    unittest.main()
