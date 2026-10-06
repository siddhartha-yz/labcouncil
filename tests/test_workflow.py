import concurrent.futures
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from labcouncil.simulation import execute
from labcouncil.store import Conflict, Store
from labcouncil.worker import step


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)/"state.sqlite3"
        self.store = Store(self.path)
        self.project = self.store.create_project("测试项目", "先检查平稳数据", budget=9)

    def tearDown(self):
        self.directory.cleanup()

    def finish_round(self):
        while step(self.store):
            pass

    def test_two_rounds_preserve_evidence_and_decision(self):
        self.finish_round()
        first = self.store.project(self.project)
        self.assertEqual(first["used"], 3)
        self.assertTrue(first["artifacts"][-1]["body"]["verified"])
        meeting = self.store.open_meeting(self.project)
        answer = self.store.ask(meeting, "复核检查了什么？")
        self.assertIn("模拟", answer)
        decision = self.store.confirm(meeting, 1, "加入一个异常点再核验", "outlier")
        self.finish_round()
        final = self.store.project(self.project)
        self.assertEqual(final["version"], 2)
        self.assertEqual(final["used"], 6)
        self.assertEqual(len(final["artifacts"]), 6)
        self.assertEqual(final["artifacts"][0]["body"]["dataset"]["y"][-1], 9)
        self.assertEqual(final["artifacts"][3]["body"]["dataset"]["y"][-1], 15)
        self.assertTrue(final["artifacts"][-1]["body"]["verified"])
        self.assertEqual(self.store.meeting(meeting)["decision"], decision)
        self.assertEqual(len(self.store.meeting(meeting)["snapshot"]["artifacts"]), 3)

    def test_concurrent_confirmation_is_idempotent(self):
        meeting = self.store.open_meeting(self.project)
        def confirm(_):
            return Store(self.path).confirm(meeting, 1, "相同决定", "outlier")
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(confirm, range(10)))
        self.assertEqual(len({r["id"] for r in results}), 1)
        p = self.store.project(self.project)
        self.assertEqual(len(p["decisions"]), 1)
        self.assertEqual(len(p["tasks"]), 6)
        self.assertEqual(p["version"], 2)
        with self.assertRaises(Conflict):
            self.store.confirm(meeting, 1, "另一条决定", "clean")

    def test_stale_version_and_invalid_version_rejected(self):
        meeting = self.store.open_meeting(self.project)
        for value in ("1", True, None):
            with self.assertRaises(ValueError):
                self.store.confirm(meeting, value, "方向", "clean")
        with self.assertRaises(Conflict):
            self.store.confirm(meeting, 0, "方向", "clean")
        self.assertEqual(self.store.project(self.project)["version"], 1)

    def test_budget_stops_before_start_and_qa_separate(self):
        self.store.configure(self.project, False, 1, 1)
        self.finish_round()
        p = self.store.project(self.project)
        self.assertEqual(p["used"], 1)
        self.assertEqual(len(p["artifacts"]), 1)
        self.assertEqual(p["tasks"][1]["attempts"], 0)
        meeting = self.store.open_meeting(self.project)
        self.store.ask(meeting, "问题一")
        with self.assertRaises(Conflict):
            self.store.ask(meeting, "问题二")
        self.assertEqual(self.store.project(self.project)["used"], 1)
        self.store.configure(self.project, False, 3, 1)
        self.finish_round()
        self.assertEqual(len(self.store.project(self.project)["artifacts"]), 3)

    def test_pause_then_resume_and_zero_budget(self):
        self.store.configure(self.project, True, 9, 6)
        self.assertFalse(step(self.store))
        self.store.configure(self.project, False, 0, 6)
        self.assertFalse(step(self.store))
        self.store.configure(self.project, False, 3, 6)
        self.assertTrue(step(self.store))

    def test_expired_worker_fenced_and_retry_not_charged_twice(self):
        first = self.store.claim()
        result = execute(self.store, first)
        with self.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET lease_until=? WHERE id=?", (time.time()-1, first["id"]))
        second = Store(self.path).claim()
        self.assertEqual(second["id"], first["id"])
        self.assertNotEqual(first["owner"], second["owner"])
        with self.assertRaises(Conflict):
            self.store.complete(first, result)
        self.store.complete(second, execute(self.store, second))
        self.assertEqual(self.store.project(self.project)["used"], 1)
        self.assertEqual(len(self.store.project(self.project)["artifacts"]), 1)
        with self.assertRaises(Conflict):
            self.store.complete(second, result)

    def test_lease_retry_limit_and_failed_dependency(self):
        for _ in range(3):
            task = self.store.claim()
            with self.store.connection(write=True) as con:
                con.execute("UPDATE tasks SET lease_until=? WHERE id=?", (time.time()-1, task["id"]))
        self.assertIsNone(self.store.claim())
        p = self.store.project(self.project)
        self.assertEqual(p["tasks"][0]["status"], "failed")
        self.assertEqual(p["used"], 1)
        self.assertEqual(p["tasks"][1]["attempts"], 0)

    def test_late_old_round_result_kept_only_as_history(self):
        old = self.store.claim()
        meeting = self.store.open_meeting(self.project)
        self.store.confirm(meeting, 1, "改变方向", "outlier")
        self.store.complete(old, execute(self.store, old))
        p = self.store.project(self.project)
        self.assertEqual(p["artifacts"][0]["version"], 1)
        self.assertEqual([t["status"] for t in p["tasks"] if t["version"] == 1], ["completed", "cancelled", "cancelled"])
        self.finish_round()
        new_meeting = self.store.open_meeting(self.project)
        self.assertTrue(all(a["version"] == 2 for a in self.store.meeting(new_meeting)["snapshot"]["artifacts"]))

    def test_snapshot_stays_fixed_when_tasks_finish(self):
        meeting = self.store.open_meeting(self.project)
        snapshot = self.store.meeting(meeting)["snapshot"]
        self.finish_round()
        self.assertEqual(self.store.meeting(meeting)["snapshot"], snapshot)
        self.assertEqual(snapshot["artifacts"], [])

    def test_saved_draft_survives_restart_without_dispatching(self):
        meeting = self.store.open_meeting(self.project)
        first = self.store.save_draft(meeting, 0, "草稿：加入异常点", "outlier")
        self.assertEqual(Store(self.path).meeting(meeting)["draft"], first)
        self.assertEqual(self.store.project(self.project)["version"], 1)
        self.assertEqual(len(self.store.project(self.project)["tasks"]), 3)
        with self.assertRaises(Conflict):
            self.store.save_draft(meeting, 0, "过期页面的内容", "clean")
        second = self.store.save_draft(meeting, 1, "修改后的草稿", "outlier")
        self.assertEqual(second["revision"], 2)
        self.store.confirm(meeting, 1, second["instruction"], second["scenario"])
        with self.assertRaises(Conflict):
            self.store.save_draft(meeting, 2, "不能修改已确认决定", "clean")

    def test_database_enforces_evidence_and_snapshot_immutability(self):
        self.finish_round()
        p = self.store.project(self.project)
        a = p["artifacts"][0]
        canonical = self.store.artifact(a["id"])["body"]
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), a["sha256"])
        meeting = self.store.open_meeting(self.project)
        with self.assertRaises(sqlite3.IntegrityError), self.store.connection(write=True) as con:
            con.execute("UPDATE artifacts SET body='{}' WHERE id=?", (a["id"],))
        with self.assertRaises(sqlite3.IntegrityError), self.store.connection(write=True) as con:
            con.execute("UPDATE meetings SET snapshot='{}' WHERE id=?", (meeting,))

    def test_scheduled_meeting_only_once_and_no_auto_confirm(self):
        self.store.configure(self.project, False, 9, 6, meeting_at=time.time()-1)
        first = self.store.due_meetings()
        self.assertEqual(len(first), 1)
        self.assertEqual(self.store.due_meetings(), [])
        self.assertEqual(self.store.project(self.project)["version"], 1)
        self.assertIsNone(self.store.meeting(first[0])["decision"])
        self.store.configure(self.project, False, 9, 6, meeting_at=time.time()-1)
        self.assertEqual(self.store.due_meetings(), first)
        self.assertEqual(self.store.due_meetings(), [])

    def test_restart_in_independent_process_preserves_queue(self):
        repo = Path(__file__).resolve().parents[1]
        for _ in range(3):
            proc = subprocess.run([sys.executable, "-m", "labcouncil", "worker", "--once", "--database", str(self.path)], cwd=repo, capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        fourth = subprocess.run([sys.executable, "-m", "labcouncil", "worker", "--once", "--database", str(self.path)], cwd=repo, capture_output=True, text=True, timeout=10)
        self.assertFalse(json.loads(fourth.stdout)["worked"])
        p = Store(self.path).project(self.project)
        self.assertEqual(len(p["artifacts"]), 3)
        self.assertEqual(p["used"], 3)

    def test_reviewer_detects_wrong_computation(self):
        step(self.store)
        task = self.store.claim()
        wrong = execute(self.store, task)
        wrong["metrics"]["mse"] = 99
        self.store.complete(task, wrong)
        step(self.store)
        result = self.store.project(self.project)["artifacts"][-1]["body"]
        self.assertFalse(result["verified"])
        self.assertFalse(result["checks"]["mse"])

    def test_atomic_artifact_and_completion_roll_back_together(self):
        task = self.store.claim()
        with self.store.connection(write=True) as con:
            con.execute("CREATE TRIGGER reject_complete BEFORE UPDATE OF status ON tasks WHEN NEW.status='completed' BEGIN SELECT RAISE(ABORT,'injected failure'); END;")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.complete(task, execute(self.store, task))
        p = self.store.project(self.project)
        self.assertEqual(p["artifacts"], [])
        self.assertEqual(p["tasks"][0]["status"], "running")

    def test_input_validation_never_creates_partial_project(self):
        initial = len(self.store.projects())
        for kwargs in ({"budget": True}, {"budget": -1}, {"qa_budget": 101}, {"selected": "arbitrary"}, {"meeting_at": float("nan")}):
            with self.assertRaises(ValueError):
                self.store.create_project("项目", "想法", **kwargs)
        self.assertEqual(len(self.store.projects()), initial)


if __name__ == "__main__":
    unittest.main()
