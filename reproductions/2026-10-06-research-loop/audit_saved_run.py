"""Offline audit/export of existing records. Never issues a request or runs a task."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


def audit(database,pid):
    with sqlite3.connect(database) as con:
        con.row_factory=sqlite3.Row
        project=dict(con.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone())
        rows={table:[dict(r) for r in con.execute(f'SELECT * FROM {table} WHERE project_id=? ORDER BY created',(pid,))]
              for table in ('tasks','artifacts','tool_operations','source_requests','model_requests','round_inputs','meetings','decisions','events')}
        execution=dict(con.execute('SELECT * FROM project_execution WHERE project_id=?',(pid,)).fetchone())
        discussion=[dict(r) for r in con.execute('SELECT d.* FROM discussion d JOIN meetings m ON m.id=d.meeting_id WHERE m.project_id=? ORDER BY d.created',(pid,))]
    for table in ('artifacts','tool_operations','source_requests'):
        for row in rows[table]:
            if row['body'] is not None:
                assert hashlib.sha256(row['body'].encode()).hexdigest()==row['sha256'],(table,row['id'])
    background=[r for r in rows['model_requests'] if r['category']=='background'];qa=[r for r in rows['model_requests'] if r['category']=='qa']
    assert len(background)<=execution['api_budget'] and len(qa)<=execution['qa_api_budget']
    assert len(rows['source_requests'])<=24
    assert len({r['fingerprint'] for r in rows['source_requests']})==len(rows['source_requests'])
    assert all(t['attempts']==1 for t in rows['tasks'])
    assert not any(t['status'] in ('running','queued') for t in rows['tasks'])
    for request in rows['model_requests']:
        if request['status']=='completed':assert json.loads(request['response'])['model']=='deepseek-flash'
    for source in rows['source_requests']:
        assert source['url'].startswith(('https://api.github.com/','https://export.arxiv.org/'))
    usage=[json.loads(r['usage']) for r in rows['model_requests'] if r['usage']]
    checks={'background_requests':len(background),'qa_requests':len(qa),'known_tokens':sum(u['total_tokens'] for u in usage),
        'unknown_usage_requests':len(rows['model_requests'])-len(usage),'source_attempts':len(rows['source_requests']),
        'successful_source_attempts':sum(r['status']=='completed' for r in rows['source_requests']),
        'tasks':len(rows['tasks']),'failed_tasks':sum(t['status']=='failed' for t in rows['tasks']),
        'artifacts':len(rows['artifacts']),'saved_tool_operations':len(rows['tool_operations']),
        'input_versions':len(rows['round_inputs']),'meetings':len(rows['meetings']),'engineering_confirmations':len(rows['decisions']),
        'discussion':len(discussion),'hashes_verified':True,'pending_tasks':0,'automatic_task_retries':0}
    # Public export omits complete upstream bodies. Model text and program state are ours.
    sources=[{k:v for k,v in r.items() if k not in ('body',)} for r in rows['source_requests']]
    artifacts=[]
    for r in rows['artifacts']:
        body=json.loads(r['body'])
        result=body.get('result',{})
        body['result']={**result,'sources':[{k:v for k,v in s.items() if k not in ('readme','abstract')} for s in result.get('sources',[])]}
        artifacts.append({**r,'body':body})
    calls=[{k:v for k,v in r.items() if k not in ('request','response')} for r in rows['model_requests']]
    return {'project':project,'execution':execution,'checks':checks,'tasks':rows['tasks'],'sources':sources,'artifacts':artifacts,
        'calls':calls,'inputs':[{**r,'body':json.loads(r['body']),'plan':json.loads(r['plan'])} for r in rows['round_inputs']],
        'decisions':rows['decisions'],'events':[{**r,'body':json.loads(r['body'])} for r in rows['events']],'discussion':discussion,
        'export_notice':'Full source/model responses remain local. Artifact hashes refer to full original canonical body, not this abridged export.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('database');parser.add_argument('project_id');parser.add_argument('--output',required=True)
    args=parser.parse_args();result=audit(args.database,args.project_id)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result['checks'],ensure_ascii=False,indent=2))
