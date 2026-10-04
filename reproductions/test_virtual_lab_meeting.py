"""Offline checks for ambiguity at the upstream Markdown/JSON boundary."""

import json
import unittest

from check_virtual_lab_meeting import validate_summary


class SummaryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.evidence = {"evidence_id": "fixture", "results": [{"metrics": {"mse": {"linear": 1, "baseline": 2}}}]}
        self.report = {"evidence_refs": ["fixture"], "observed_mse": {"linear": 1, "baseline": 2},
                       "limitations": ["Test fixture only"], "next_steps": ["Repeat"],
                       "new_experiments_executed": False}
        self.block = '```json\n' + json.dumps(self.report) + '\n```'

    def test_single_block_keeps_the_original_text_summary_usable(self):
        self.assertEqual(validate_summary('### Summary\nText\n' + self.block, self.evidence, False), self.report)

    def test_two_conflicting_blocks_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unambiguous"):
            validate_summary(self.block + '\n' + self.block, self.evidence, False)

    def test_structured_claim_of_new_experiments_is_rejected(self):
        self.report['new_experiments_executed'] = True
        with self.assertRaisesRegex(ValueError, "claims experiments"):
            validate_summary(json.dumps(self.report), self.evidence, False)

    def test_single_trailing_object_is_accepted_without_rewriting_text(self):
        self.assertEqual(validate_summary('### Summary\nText\n' + json.dumps(self.report), self.evidence, False), self.report)

    def test_two_unfenced_objects_are_rejected(self):
        text = json.dumps(self.report) + '\n' + json.dumps(self.report)
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            validate_summary(text, self.evidence, False)

    def test_text_after_object_is_rejected(self):
        text = '### Summary\n' + json.dumps(self.report) + '\nUnverified extra conclusions'
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            validate_summary(text, self.evidence, False)

    def test_block_and_unfenced_object_are_rejected_together(self):
        text = self.block + '\n' + json.dumps(self.report)
        with self.assertRaisesRegex(ValueError, 'violation'):
            validate_summary(text, self.evidence, False)


if __name__ == '__main__':
    unittest.main()
