"""Audit the public, abridged record offline; no network/model calls."""
import json
from pathlib import Path
root=Path(__file__).resolve().parent
component=json.loads((root/'source-component.json').read_text())
p=json.loads((root/'loop.json').read_text())
assert component['component_only'] and component['model_requests']==0
assert component['source_count']==4 and component['source_budget']==12
assert component['cache_new_requests']==0
assert all(r['status']=='completed' and r['http_status']==200 for r in component['requests'])
assert all(r['status']=='completed' for r in component['results'].values())
assert all(x=='completed' for x in component['replay_status'].values())
assert p['version']==2 and len(p['input_history'])==2
assert len(p['artifacts'])==3 and len(p['tool_operations'])==3
assert len(p['decisions'])==1 and len(p['meetings'])==1
rs=p['model_requests'];http=p['source_requests']
assert len(rs)==7 and len(http)==4
assert all(r['status']=='completed' and r['http_status']==200 for r in rs+http)
assert sum(r['category']=='background' for r in rs)==p['execution']['api_budget']==6
assert sum(r['category']=='qa' for r in rs)==p['execution']['qa_api_budget']==1
assert sum(r['usage']['total_tokens'] for r in rs)==11821
assert [a['body']['action'] for a in p['artifacts']]==['read_abstract','inspect_repository','prepare_meeting']
assert [t['status'] for t in p['tasks']]==['completed','completed','completed','queued']
assert p['current_inputs']['body']['work_time']['all_day'] is False
assert p['current_inputs']['body']['permissions']['retry_public_reads'] is False
meeting=p['meetings'][0]
assert meeting['status']=='closed' and len(meeting['discussion'])==1
assert len(meeting['snapshot']['artifacts'])==3
assert meeting['snapshot']['inputs']['body']==p['input_history'][0]['body']
assert all(len(r['sha256'])==64 and len(r['raw_sha256'])==64 for r in http)
print('PASS: recorded source reads, cache, request caps, usage and retained meeting/inputs. Scientific correctness is not established by this audit.')
