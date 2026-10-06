"""Offline audit of actual saved data; no API, provider fixture or model rerun."""
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent


def audit():
    project = json.loads((ROOT / 'final-project.json').read_text())
    rows = []
    for version in (1, 2):
        artifacts = {a['role']: a for a in project['artifacts'] if a['version'] == version}
        data = artifacts['researcher']['body']['datasets']
        results = artifacts['executor']['body']['results']
        for d, r in zip(data, results, strict=True):
            # Direct sum formula, independent of the platform's centered fit.
            n = len(d['train'])
            sx = math.fsum(x for x, _ in d['train'])
            sy = math.fsum(y for _, y in d['train'])
            b = (n * math.fsum(x*y for x, y in d['train']) - sx*sy) / (n * math.fsum(x*x for x, _ in d['train']) - sx*sx)
            a = (sy - b*sx)/n
            assert math.isclose(a, r['intercept'], abs_tol=1e-10)
            assert math.isclose(b, r['slope'], abs_tol=1e-10)
            metrics = {}
            for name in ('linear', 'baseline'):
                errors = [(a+b*x if name == 'linear' else sy/n)-y for x, y in d['test']]
                metrics[name] = {'mse': math.fsum(e*e for e in errors)/len(errors),
                    'mae': math.fsum(abs(e) for e in errors)/len(errors),
                    'median_absolute_error': statistics.median(abs(e) for e in errors)}
                for key, value in metrics[name].items():
                    assert math.isclose(value, r['metrics'][name][key], rel_tol=1e-10, abs_tol=1e-10)
            assert len(d['changed_test_indices']) == (0 if version == 1 else 10)
            rows.append({'version': version, 'seed': d['seed'], 'metrics': metrics,
                         'outlier_count': len(d['changed_test_indices']), 'recomputed': True})
        assert artifacts['reviewer']['body']['verified']
    datasets = [a['body']['datasets'] for a in project['artifacts'] if a['role'] == 'researcher']
    first, second = datasets[0][0], datasets[1][0]
    assert first['seed'] == second['seed'] == 7
    assert first['train'] == second['train']
    changed = [i for i, (before, after) in enumerate(zip(first['test'], second['test'], strict=True)) if before != after]
    assert set(changed) == set(second['changed_test_indices']) and len(changed) == 10
    for i in changed:
        assert first['test'][i][0] == second['test'][i][0]
        assert math.isclose(abs(first['test'][i][1]-second['test'][i][1]), 10, abs_tol=1e-12)
    for a in project['artifacts']:
        raw = json.dumps(a['body'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        assert hashlib.sha256(raw).hexdigest() == a['sha256']
    requests = project['model_requests']
    assert len(requests) == 13
    assert all(r['status'] == 'completed' and r['http_status'] == 200 for r in requests)
    assert all(r['response']['model'] == 'deepseek-flash' for r in requests)
    return {'source': 'offline recomputation of actual saved synthetic data', 'rows': rows,
        'seed7_training_unchanged': True, 'seed7_exactly_ten_test_labels_changed': True,
        'artifact_hashes_verified': 6, 'actual_requests': len(requests),
        'known_total_tokens': sum(r['usage']['total_tokens'] for r in requests),
        'unknown_usage_requests': sum(r['usage'] is None for r in requests),
        'semantic_report_validation': 'FAILED: second-round executor and reviewer misdescribe outlier data as clean; manually inspected, not covered by arithmetic assertions'}


if __name__ == '__main__':
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
