#!/usr/bin/env python3
"""Retrospective scores from saved comparison evidence; never calls a model."""
import argparse
import hashlib
import json
from pathlib import Path

from check_comparison import check_report
from check_deepseek_workflow import verify_artifact

ARMS = ('single', 'multi', 'human')
TASKS = ('clean', 'outliers')
DIMENSIONS = ('numbers_and_refs', 'full_experiment_coverage', 'agent_evidence_verification')


def score_run(root):
    row = {'run': root.name, 'status': 'missing', 'host_integrity_passed': False,
           'passes': dict.fromkeys(DIMENSIONS, False), 'requests': None,
           'verification_claim_supported': None}
    try:
        state = json.loads((root / 'state.json').read_text())
        row.update(status=state['status'], requests=state['api_calls'])
        if state['status'] != 'completed':
            return row
        report = json.loads((root / 'final-report.json').read_text())
        events = [json.loads(line) for line in (root / 'events.jsonl').read_text().splitlines()]
        actual_verified = {
            e['result']['evidence_id'] for e in events
            if e.get('kind') == 'tool_result' and e.get('name') == 'verify'
            and isinstance(e.get('result'), dict) and e['result'].get('verified') is True
            and e.get('arguments', {}).get('evidence_id') == e['result'].get('evidence_id')
        }
        for artifact in state['artifacts']:
            verify_artifact(root, artifact, state['manifests'][artifact['evidence_id']])
        checks = check_report(report, {**state, 'verified': sorted(actual_verified)})
        valid = checks['valid_json_schema'] and checks['numeric_and_refs_valid']
        row.update(host_integrity_passed=True,
                   verification_claim_supported=checks['verification_claim_supported'],
                   passes={'numbers_and_refs': valid,
                           'full_experiment_coverage': valid and checks['three_seeds'] and checks['three_metrics_each_seed'],
                           'agent_evidence_verification': valid and checks['all_report_evidence_verified']})
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        row['audit_error'] = 'saved_record_missing_or_invalid'
    return row


def build(root):
    # Keep the registered denominator, even when an expected run is absent/failed.
    rows = []
    for arm in ARMS:
        for task in TASKS:
            for repeat in (1, 2):
                rows.append({**score_run(root / f'{task}-{arm}-{repeat}'), 'arm': arm})
    groups = []
    for arm in ARMS:
        subset = [r for r in rows if r['arm'] == arm]
        dimensions = {d: {'passed': sum(r['passes'][d] for r in subset), 'total': len(subset)}
                      for d in DIMENSIONS}
        for dimension in dimensions.values():
            dimension['score'] = round(100 * dimension['passed'] / dimension['total'], 1)
        groups.append({'arm': arm, 'dimensions': dimensions,
                       'evidence_index': round(sum(d['score'] for d in dimensions.values()) / 3, 1),
                       'known_requests': sum(r['requests'] for r in subset if r['requests'] is not None),
                       'unknown_request_runs': sum(r['requests'] is None for r in subset)})
    return {'scorecard_version': 'retrospective-v1',
            'scope': 'Two synthetic tasks, three workflows, two repetitions. Not a general research score.',
            'formula': 'dimension = 100 * passing runs / 4; evidence_index = equal mean of three dimensions',
            'weights_selected_after_original_runs': True,
            'unmeasured': ['semantic accuracy rate', 'report readability', 'scientific novelty',
                           'human time efficiency', 'public benchmark performance', 'Codex CLI performance'],
            'groups': groups, 'runs': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, default=Path(__file__).resolve().parent / '2026-10-05-comparison' / 'runs')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = build(args.runs)
    result['scorer_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    raw = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        if args.output.exists():
            raise SystemExit('Output exists; use a new path to preserve the old scorecard.')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw)
    print(raw, end='')


if __name__ == '__main__':
    main()
