"""Offline checks of abridged public records, not scientific-accuracy checks."""
import json
from pathlib import Path
root=Path(__file__).resolve().parent
p=json.loads((root/'first-run.json').read_text());r=json.loads((root/'recheck.json').read_text())
assert p['version']==2 and len(p['input_history'])==2
assert len(p['decisions'])==1 and len(p['meetings'])==2
assert len(p['source_requests'])==4 and all(x['http_status']==200 for x in p['source_requests'])
assert len(p['model_requests'])==9
assert sum(x['category']=='background' for x in p['model_requests'])==p['execution']['api_budget']==8
assert sum(x['category']=='qa' for x in p['model_requests'])==p['execution']['qa_api_budget']==1
assert sum(x['usage']['total_tokens'] for x in p['model_requests'])==20334
assert [t['status'] for t in p['tasks']]==['completed','completed','failed','completed']
assert all(t['attempts']==1 for t in p['tasks'])
truncated=[x for x in p['model_requests'] if x['finish_reason']=='length']
assert len(truncated)==1 and truncated[0]['usage']['completion_tokens']==768
assert 'truncated_model_content' in truncated[0]
ops={o['id']:o for o in p['tool_operations']}
final=[a for a in p['artifacts'] if a['version']==2][0]['body']
items=final['result']['meeting_evidence']['items']
assert len(items)==2 and all(i['version']==1 for i in items)
for item in items:
    assert item['operation_sha256']==ops[item['id'].removeprefix('operation:')]['sha256']
refs={i['id'] for i in items}|{final['operation_ref']}
assert len(final['report']['findings'])==3
assert all(set(f['evidence_refs']) <= refs for f in final['report']['findings'])
assert all(x['task_id'] not in {t['id'] for t in p['tasks'] if t['version']==2} for x in p['source_requests'])
meeting=[m for m in p['meetings'] if m['version']==2][0]
assert len(meeting['discussion'])==1
assert 'remaining_background_requests=0' in meeting['discussion'][0]['answer']
assert '不能断言完整文档没有' in meeting['discussion'][0]['answer']
qa=[x for x in p['model_requests'] if x['category']=='qa'][0]
assert qa['execution_constraints']['remaining_background_requests']==0
assert len(r['model_requests'])==3 and r['execution']['api_budget']==6
assert len(r['source_requests'])==1 and r['execution']['source_budget']==8
assert [t['status'] for t in r['tasks']]==['completed','failed']
assert all(t['attempts']==1 for t in r['tasks'])
assert len([x for x in r['model_requests'] if x['status']=='error'])==1
assert sum(x['usage']['total_tokens'] for x in r['model_requests'] if x['usage'])==2847
assert sum(x['usage'] is None for x in r['model_requests'])==1
print('PASS: one preserved truncation, cross-round evidence, bounded requests, QA correction and stopped recheck failure. No scientific reproduction is established.')
