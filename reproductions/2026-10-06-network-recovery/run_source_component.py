from pathlib import Path
import hashlib,json
from labcouncil.store import Store,encode
from labcouncil.brief import normalize
from labcouncil.sources import retrieve
root=Path('reproductions/2026-10-06-network-recovery')
s=Store('workspaces/network-recovery/source-state.sqlite3')
assert not s.projects(), 'Existing fixture must not be overwritten or silently rerun'
b=normalize(None,'工程验收：读取摘要和固定版本README','research')
b.update(resources='HTTP上限12；模型请求0；不执行上游代码',requirements='原文和失败均保存；不得声称论文复现')
b['permissions'].update(public_research=True,retry_public_reads=True,local_compute=False)
b['permissions'].update(model_calls=False,local_compute=True)
pid=s.create_project('公开资料恢复·组件验收',b['idea'],brief=b,mode='simulation',api_budget=0,qa_api_budget=0,source_budget=12)
t=s.claim(lease_seconds=300)
results={}
for action,value in [('read_abstract','2602.08990'),('inspect_repository','InternScience/scp')]:
    results[action]=retrieve(s,t,action,value)
    print(action,results[action]['status'],len(results[action]['http_requests']),flush=True)
s.save_operation(t,{'kind':'source_component','results':results,'notice':'Codex组件验收，模型请求0'})
s.fail(t,'组件测试结束，不运行其他模拟任务')
s.configure(pid,True,9,0)
# Cache replay in a confirmed engineering-only round.
m=s.open_meeting(pid);s.confirm(m,1,b['idea'],'clean',b);s.configure(pid,False,9,0)
restarted=Store(s.database);t2=restarted.claim(lease_seconds=300)
before=len(restarted.project(pid)['source_requests'])
# Success is cached. Failure replay may advance within three attempts if slots remain;
# disable retries in replay inputs so the cache check makes no requests.
b['permissions']['retry_public_reads']=False
restarted.fail(t2,'cache-only fixture');m2=restarted.open_meeting(pid);restarted.confirm(m2,2,b['idea'],'clean',b)
t3=restarted.claim(lease_seconds=300)
replay={action:retrieve(restarted,t3,action,value) for action,value in [('read_abstract','2602.08990'),('inspect_repository','InternScience/scp')]}
# A successful response after an earlier retry must still be discoverable with retry disabled.
restarted.fail(t3,'组件缓存检查结束');restarted.configure(pid,True,9,0)
p=restarted.project(pid)
export={'project_id':pid,'component_only':True,'model_requests':len(p['model_requests']),'source_budget':12,'source_count':len(p['source_requests']),
    'cache_new_requests':len(p['source_requests'])-before,'results':{},'replay_status':{k:v['status'] for k,v in replay.items()},'requests':p['source_requests']}
for action,result in results.items():
    export['results'][action]={'status':result['status'],'http_requests':result['http_requests'],'sources':[{k:v for k,v in source.items() if k not in ('abstract','readme')} for source in result['sources']]}
root.joinpath('source-component.json').write_text(json.dumps(export,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:export[k] for k in ('project_id','model_requests','source_count','cache_new_requests','replay_status')},ensure_ascii=False))
