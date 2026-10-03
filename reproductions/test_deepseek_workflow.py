"""Offline integrity/stop checks; these tests do not simulate scientific validation."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from check_deepseek_workflow import (
    EXPECTED, Workflow, run_experiment, validate_report, verify_artifact,
)


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.artifact, self.manifest = run_experiment(self.root, "experiment-0001", EXPECTED[1])

    def test_saved_predictions_and_metrics_can_be_independently_recomputed(self):
        result = verify_artifact(self.root, self.artifact, self.manifest)
        self.assertTrue(result["verified"])
        metrics = result["results"][0]["metrics"]["mse"]
        # A broad ground-truth expectation for this synthetic low-noise relationship.
        self.assertLess(metrics["linear"], 0.5)
        self.assertGreater(metrics["baseline"], 5)

    def test_tampered_csv_is_rejected(self):
        path = self.root / self.artifact["files"][0]["path"]
        path.write_text(path.read_text() + "test,0,0,0,0\n")
        with self.assertRaisesRegex(ValueError, "CSV hash mismatch"):
            verify_artifact(self.root, self.artifact, self.manifest)

    def test_changed_metric_is_rejected_by_recomputation(self):
        artifact = copy.deepcopy(self.artifact)
        artifact["results"][0]["metrics"]["mse"]["linear"] = 1000
        with self.assertRaisesRegex(ValueError, "recomputation"):
            verify_artifact(self.root, artifact, self.manifest)

    def test_invented_report_number_is_rejected(self):
        report = {"task_version": 1, "evidence_refs": ["experiment-0001"],
                  "observations": [{"seed": 7, "metric": "mse", "linear": 999, "baseline": 999}],
                  "conclusion": "Unverified claim", "limitations": ["Synthetic data"]}
        with self.assertRaisesRegex(ValueError, "differs from evidence"):
            validate_report(report, 1, self.artifact, "executor")

    def test_stale_task_version_is_rejected(self):
        report = {"task_version": 1, "evidence_refs": ["experiment-0001"],
                  "verified": True, "limitations": ["Synthetic data"]}
        with self.assertRaisesRegex(ValueError, "task version mismatch"):
            validate_report(report, 2, self.artifact, "reviewer")

    def test_registered_history_does_not_invalidate_current_evidence(self):
        report = {"task_version": 1, "evidence_refs": ["previous-registered", "experiment-0001"],
                  "verified": True, "limitations": ["Synthetic data"]}
        validate_report(report, 1, self.artifact, "reviewer", ["previous-registered", "experiment-0001"])
        report["evidence_refs"] = ["invented", "experiment-0001"]
        with self.assertRaisesRegex(ValueError, "references mismatch"):
            validate_report(report, 1, self.artifact, "reviewer", ["previous-registered", "experiment-0001"])

    def test_exhausted_budget_prevents_any_network_call(self):
        workflow = Workflow(self.root, {"DEEPSEEK_API_KEY": "offline-placeholder"}, {"api_calls": 12})
        with patch("urllib.request.urlopen", side_effect=AssertionError("Network must not be used")):
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                workflow.call("unused", [], {})

    def test_completed_continuation_does_not_dispatch_again(self):
        workflow = Workflow(self.root, {"DEEPSEEK_API_KEY": "offline-placeholder"},
                            {"status": "completed"})
        with patch.object(workflow, "phase", side_effect=AssertionError("Must not redispatch")):
            result = workflow.run("continue")
        self.assertEqual(result["new_api_calls"], 0)
        self.assertEqual(result["new_tool_calls"], 0)

    def test_prior_attempts_count_toward_shared_network_budget(self):
        workflow = Workflow(self.root, {"DEEPSEEK_API_KEY": "offline-placeholder"},
                            {"api_calls": 9, "prior_api_calls": 3})
        with patch("urllib.request.urlopen", side_effect=AssertionError("Network must not be used")):
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                workflow.call("unused", [], {})


if __name__ == "__main__":
    unittest.main()
