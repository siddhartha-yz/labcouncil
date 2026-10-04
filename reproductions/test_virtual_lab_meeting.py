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


if __name__ == '__main__':
    unittest.main()
