"""Bounded live CLI acceptance, synthetic tools only; no upstream reproduction."""
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from labcouncil.store import Store
from labcouncil.worker import step
from labcouncil.brief import normalize

store=Store(ROOT/'workspaces/codex-acceptance/state.sqlite3')
idea='验收Codex后台：只调用一次synthetic_regression，value=clean，再prepare_meeting。不要查公开资料。用大白话解释拟合直线和只猜均值的差别，不声称论文复现。'
brief=normalize(None,idea,'research')
brief['resources']='自有CPU合成基准；已登录Codex CLI；后台最多八次CLI启动，组会最多一次。'
brief['requirements']='只做指定小实验后准备组会，不重复运行；报告简短，区分实测和未验证。'
pid=store.create_project('【Codex工程验收】两轮实验与组会',idea,mode='research',backend='codex_cli',budget=4,api_budget=8,qa_api_budget=1,brief=brief)
print(json.dumps({'project_id':pid},ensure_ascii=False),flush=True)
started=time.monotonic()
while step(store):
    p=store.project(pid)
    print(json.dumps({'round':p['version'],'tasks':[(t['role'],t['status'],t['error']) for t in p['tasks']],'requests':len(p['model_requests'])},ensure_ascii=False),flush=True)
p=store.project(pid)
if any(t['status']=='failed' for t in p['tasks']): raise RuntimeError('Round one failed; inspect ledger')
mid=store.open_meeting(pid)
print(store.ask(mid,'这次实际验证了什么，还有什么没有验证？'),flush=True)
brief={**brief,'idea':'第二轮验收：继承第一轮证据，只做一次synthetic_regression，value=outlier，再prepare_meeting；比较异常点出现前后的结果，不重复clean实验。'}
store.confirm(mid,1,brief['idea'],'outlier',brief)
while step(store):
    p=store.project(pid)
    print(json.dumps({'round':p['version'],'tasks':[(t['role'],t['status'],t['error']) for t in p['tasks']],'requests':len(p['model_requests'])},ensure_ascii=False),flush=True)
p=Store(store.database).project(pid)
store.open_meeting(pid)
assert p['version']==2 and len(p['input_history'])==2
assert all(t['status']=='completed' for t in p['tasks'])
assert any(o['body']['action']=='synthetic_regression' and o['body']['value']=='outlier' for o in p['tool_operations'])
assert all(r['request']['model']=='gpt-6.1-sol' and r['request']['reasoning_effort']=='high' for r in p['model_requests'])
result={'project_id':pid,'elapsed_seconds':round(time.monotonic()-started,2),
    'execution':p['execution'],'rounds':p['version'],'tasks':len(p['tasks']),
    'artifacts':p['artifacts'],'tool_operations':p['tool_operations'],'model_requests':p['model_requests'],
    'source_requests':len(p['source_requests']),'discussion':store.meeting(mid)['discussion'],
    'notice':'Synthetic engineering acceptance only. CLI arguments pin model/effort; events do not independently attest server model.'}
Path(__file__).with_name('result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print('ACCEPTANCE PASSED',flush=True)
