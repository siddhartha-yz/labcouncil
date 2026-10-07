"""Negative controls for scoring saved real evidence, with no model requests."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from score_comparison import build, score_run

RUNS = Path(__file__).resolve().parent / '2026-10-05-comparison' / 'runs'


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'clean-single-1'
        shutil.copytree(RUNS / 'clean-single-1', self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_forged_report_number_gets_no_credit(self):
        path = self.root / 'final-report.json'
        report = json.loads(path.read_text())
        report['observations'][0]['linear'] = 999
        path.write_text(json.dumps(report))
        self.assertFalse(any(score_run(self.root)['passes'].values()))

    def test_state_claim_without_actual_verify_event_gets_no_credit(self):
        path = self.root / 'events.jsonl'
        events = [json.loads(line) for line in path.read_text().splitlines()]
        path.write_text('\n'.join(json.dumps(e) for e in events
                                   if not (e.get('kind') == 'tool_result' and e.get('name') == 'verify')))
        score = score_run(self.root)
        self.assertTrue(score['passes']['numbers_and_refs'])
        self.assertFalse(score['passes']['agent_evidence_verification'])
        self.assertFalse(score['verification_claim_supported'])

    def test_csv_tampering_invalidates_even_correct_looking_report(self):
        path = self.root / 'artifacts/evidence-1/seed-7.csv'
        path.write_text(path.read_text() + 'tampered\n')
        score = score_run(self.root)
        self.assertFalse(score['host_integrity_passed'])
        self.assertFalse(any(score['passes'].values()))

    def test_failed_run_and_missing_runs_stay_in_denominator(self):
        path = self.root / 'state.json'
        state = json.loads(path.read_text()); state['status'] = 'failed'
        path.write_text(json.dumps(state))
        result = build(Path(self.tmp.name))
        self.assertEqual(len(result['runs']), 12)
        for group in result['groups']:
            self.assertEqual(group['evidence_index'], 0)
            self.assertTrue(all(d['total'] == 4 for d in group['dimensions'].values()))

    def test_current_records_match_previous_raw_counts(self):
        result = build(RUNS)
        expected = {'single': [4, 2, 2], 'multi': [4, 4, 0], 'human': [4, 4, 0]}
        for group in result['groups']:
            self.assertEqual([d['passed'] for d in group['dimensions'].values()], expected[group['arm']])
        self.assertTrue(all(r['host_integrity_passed'] for r in result['runs']))
