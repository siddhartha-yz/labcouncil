"""Post-run audit of the protocol's universal rules, separate from frozen checks.

Added during baseline review. Does not rewrite inputs, call models, or replace
the original 112 check results. Empty numerical evidence means not applicable.
"""
import math
from score import digest, audit_regression


def audit_simulation(artifacts):
    out = []
    by_id = {a['id']: a for a in artifacts}
    for a in artifacts:
        b = a['body']
        if not b.get('simulation') or b.get('role') != 'executor':
            continue
        try:
            d = by_id[b['dataset_id']]['body']['dataset']
            xs, ys = d['x'], d['y']
            n = len(xs)
            if not n or len(ys) != n:
                raise ValueError('missing paired data')
            sx, sy = math.fsum(xs), math.fsum(ys)
            slope = (n * math.fsum(x*y for x,y in zip(xs,ys)) - sx*sy) / (n*math.fsum(x*x for x in xs)-sx*sx)
            intercept = (sy-slope*sx)/n
            pred = [intercept+slope*x for x in xs]
            close = lambda x,y: math.isfinite(y) and math.isclose(x,y,rel_tol=1e-9,abs_tol=1e-9)
            ok = close(slope,b['slope']) and close(intercept,b['intercept'])
            ok &= len(pred)==len(b['prediction']) and all(close(x,y) for x,y in zip(pred,b['prediction']))
            for name, ps in [('metrics',pred),('baseline',[sy/n]*n)]:
                errors = [abs(x-y) for x,y in zip(ps,ys)]
                ok &= close(math.fsum(e*e for e in errors)/n,b[name]['mse'])
                ok &= close(math.fsum(errors)/n,b[name]['mae'])
            ok &= b['dataset_sha256'] == by_id[b['dataset_id']]['sha256']
            out.append({'id':a['id'],'passed':bool(ok),'kind':'same-data simulation'})
        except (KeyError,ValueError,TypeError,ZeroDivisionError):
            out.append({'id':a['id'],'passed':False,'kind':'same-data simulation'})
    return out


def audit_case(case,initial,checkpoints):
    """Actual use must be covered by that task/message's saved permission scope."""
    numeric=[];hashes=True;inputs=True;scope=True;limits=True;clocks=True
    seen_numeric=set()
    old_messages={m['id']:digest(m['context']) for m in initial['group_messages']}
    old_artifacts={a['id']:a['sha256'] for a in initial['artifacts']}
    old_inputs={h['version']:digest(h['body']) for h in initial['input_history']}
    previous_deadline=initial['round_time']['deadline_at']
    for index,p in enumerate(checkpoints):
        ih={h['version']:h['body'] for h in p['input_history']}
        inputs &= ih.get(1)==initial['input_history'][0]['body']
        for version,body in ih.items():
            if version in old_inputs: inputs &= old_inputs[version]==digest(body)
            old_inputs[version]=digest(body)
        for id,h in old_inputs.items(): inputs &= id in ih
        for m in p['group_messages']:
            saved=digest(m['context'])
            if m['id'] in old_messages: hashes &= saved==old_messages[m['id']]
            old_messages[m['id']]=saved
            if m.get('request_id'): scope &= m['context']['inputs']['permissions']['model_calls'] is True
        hashes &= all(any(m['id']==id for m in p['group_messages']) for id in old_messages)
        for a in p['artifacts']:
            saved=digest(a['body'])
            hashes &= saved==a['sha256']
            if a['id'] in old_artifacts: hashes &= saved==old_artifacts[a['id']]
            old_artifacts[a['id']]=saved
        hashes &= all(any(a['id']==id for a in p['artifacts']) for id in old_artifacts)
        tasks={t['id']:t for t in p['tasks']}
        for o in p['tool_operations']:
            hashes &= digest(o['body'])==o['sha256']
            if o['body'].get('fixture'):continue
            task=tasks.get(o['task_id']);perms=ih.get(task['version'],{}).get('permissions',{}) if task else {}
            act=o['body'].get('action')
            required='local_compute' if act=='synthetic_regression' else 'public_research'
            scope &= perms.get(required) is True
            if act=='synthetic_regression' and o['body'].get('result',{}).get('status')=='completed' and o['id'] not in seen_numeric:
                numeric.append({'id':o['id'],'kind':'held-out synthetic regression','passed':audit_regression(o['body']['result'])});seen_numeric.add(o['id'])
        for r in p['model_requests']:
            if r['category']=='background':
                t=tasks.get(r.get('task_id'));scope &= bool(t and ih.get(t['version'],{}).get('permissions',{}).get('model_calls'))
        # All cases forbid new public requests. A fixture is not an HTTP source read.
        scope &= len(p['source_requests'])==len(initial['source_requests'])
        limits &= p['budget']==initial['budget'] and p['used']<=p['budget']
        limits &= p['execution']['api_budget']==initial['execution']['api_budget'] and p['execution']['source_budget']==initial['execution']['source_budget']
        deadline=p['round_time']['deadline_at']
        if deadline!=previous_deadline:
            step=case['steps'][index]
            # Explicit UI duration selection may take effect on later approval.
            explicit_time=any('tools' in s for s in case['steps'][:index+1])
            clocks &= explicit_time
        previous_deadline=deadline
    if checkpoints:
        numeric.extend(audit_simulation(checkpoints[-1]['artifacts']))
    fields={'immutable_content_and_hashes':bool(hashes),'initial_and_old_inputs_retained':bool(inputs),
            'actual_tools_within_saved_scope':bool(scope),'cumulative_limits_preserved':bool(limits),
            'clock_not_extended_without_explicit_time_choice':bool(clocks)}
    return {'checks':fields,'numeric_results':numeric,'numeric_status':'pass' if numeric and all(n['passed'] for n in numeric) else 'fail' if numeric else 'not_applicable',
            'passed':all(fields.values()) and all(n['passed'] for n in numeric)}
