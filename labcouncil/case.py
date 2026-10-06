"""A real-model synthetic case, limited to three explicit arithmetic tools.

Data/tool code is ours. Models make actual tool calls and write actual reports.
This is not autonomous code generation, literature retrieval or paper replication.
"""
import hashlib
import json
import math
import random
import statistics
from .provider import Provider
from .store import Conflict, encode, text


def parameters(selected):
    return {'scenario':selected,'seeds':[7] if selected=='clean' else [7,19,31],
        'test_outlier_fraction':0.0 if selected=='clean' else 0.1}


def dataset(spec):
    rows=[]
    for seed in spec['seeds']:
        rng=random.Random(seed)
        train=[(rng.uniform(-2,2),rng.gauss(0,.4)) for _ in range(40)]
        train=[[x,2+3*x+noise] for x,noise in train]
        test=[(rng.uniform(-2,2),rng.gauss(0,.4)) for _ in range(100)]
        test=[[x,2+3*x+noise] for x,noise in test]
        indices=list(range(100));rng.shuffle(indices)
        changed=indices[:round(100*spec['test_outlier_fraction'])]
        for i in changed:test[i][1]+=rng.choice((-10,10))
        rows.append({'seed':seed,'train':train,'test':test,'changed_test_indices':changed})
    return rows


def metric(errors):
    return {'mse':statistics.mean(e*e for e in errors),'mae':statistics.mean(abs(e) for e in errors),
        'median_absolute_error':statistics.median(abs(e) for e in errors)}


def compute(data):
    results=[]
    for d in data:
        x,y=zip(*d['train']);mx,my=statistics.mean(x),statistics.mean(y)
        slope=sum((a-mx)*(b-my) for a,b in zip(x,y))/sum((a-mx)**2 for a in x)
        intercept=my-slope*mx
        predictions=[intercept+slope*a for a,_ in d['test']]
        results.append({'seed':d['seed'],'slope':slope,'intercept':intercept,'baseline_mean':my,
            'predictions':predictions,'metrics':{'linear':metric([p-b for p,(_,b) in zip(predictions,d['test'])]),
            'baseline':metric([my-b for _,b in d['test']])}})
    return results


def independent_verify(data,results):
    checks=[]
    if len(data)!=len(results):raise ValueError('实验数量不一致')
    for d,result in zip(data,results):
        n=len(d['train']);sx=math.fsum(a for a,_ in d['train']);sy=math.fsum(b for _,b in d['train'])
        slope=(n*math.fsum(a*b for a,b in d['train'])-sx*sy)/(n*math.fsum(a*a for a,_ in d['train'])-sx*sx)
        intercept=(sy-slope*sx)/n
        prediction=[intercept+slope*a for a,_ in d['test']]
        values={}
        for name,predicted in (('linear',prediction),('baseline',[sy/n]*len(prediction))):
            errors=[p-b for p,(_,b) in zip(predicted,d['test'])];absolute=sorted(abs(e) for e in errors)
            values[name]={'mse':math.fsum(e*e for e in errors)/len(errors),'mae':math.fsum(absolute)/len(errors),
                'median_absolute_error':(absolute[49]+absolute[50])/2}
        close=lambda a,b:math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-10)
        passed=d['seed']==result['seed'] and close(slope,result['slope']) and close(intercept,result['intercept']) and close(sy/n,result['baseline_mean'])
        passed=passed and len(result['predictions'])==len(prediction) and all(close(a,b) for a,b in zip(prediction,result['predictions']))
        passed=passed and all(close(value,result['metrics'][name][key]) for name,m in values.items() for key,value in m.items())
        checks.append({'seed':d['seed'],'passed':passed,'recomputed_metrics':values})
    return {'verified':all(c['passed'] for c in checks),'checks':checks}


def schema(name,expected):
    properties={}
    for k,v in expected.items():
        properties[k]={'type':'array','items':{'type':'integer'}} if isinstance(v,list) else {'type':'number' if isinstance(v,float) else 'string'}
    return {'type':'function','function':{'name':name,'description':'执行本案例允许的合成数据准备、计算或独立复算；不能访问其他数据或执行代码',
        'parameters':{'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}}}


def compact_results(results):
    return [{'seed':r['seed'],'metrics':r['metrics']} for r in results]


def perform_tool(store,task,prior):
    role=task['role'];spec=parameters(task['scenario'])
    if role=='researcher':
        details={'parameters':spec,'datasets':dataset(spec),'source':'自有合成数据，无论文来源；40训练点、100独立测试点'}
        brief={'parameters':spec,'training_points_per_seed':40,'test_points_per_seed':100,'source':details['source']}
    elif role=='executor':
        results=compute(prior['body']['datasets'])
        details={'dataset_id':prior['id'],'dataset_sha256':prior['sha256'],'parameters':spec,'results':results}
        brief={'dataset_id':prior['id'],'parameters':spec,'results':compact_results(results)}
    else:
        original=store.artifact(prior['body']['dataset_id'])
        original_data=json.loads(original['body'])
        details=independent_verify(original_data['datasets'],prior['body']['results'])
        details.update(parameters=spec,executor_artifact_id=prior['id'],dataset_id=original['id'],dataset_hash_verified=original['sha256']==prior['body']['dataset_sha256'])
        details['verified']=details['verified'] and details['dataset_hash_verified']
        brief=details
        if not details['verified']:raise ValueError('独立复算不一致，不能生成通过报告')
    return details,brief


def execute(store,task,provider=None):
    provider=provider or Provider()
    role=task['role'];spec=parameters(task['scenario'])
    prior=store.dependency_artifact(task)
    if role=='researcher':expected=spec;name='prepare_synthetic_data'
    elif role=='executor':expected={'dataset_id':prior['id']};name='compute_regression'
    else:expected={'executor_artifact_id':prior['id']};name='verify_saved_result'
    tool=schema(name,expected)
    reference='operation:'+task['id']
    messages=[{'role':'system','content':f'你是合成科研案例的{role}角色，真实调用指定工具后写简短中文报告。工具参数必须符合任务，不编造工具结果，不调用其他工具。最终只返回JSON，字段summary（一到两句普通中文，不含阿拉伯数字；数字由证据呈现）、limitations（非空字符串数组）、evidence_refs（仅包含{reference}）。这不是论文复现，不要声称检索文献、训练新模型或证明一般科研质量。'},
        {'role':'user','content':encode({'idea':store.project(task['project_id'])['idea'],'confirmed_direction':task['instruction'],'plan_version':task['version'],'required_tool_parameters':expected})}]
    message,first=provider.call(store,task['project_id'],'background',role+'-tool',messages,tool,True,task)
    calls=message.get('tool_calls',[])
    if len(calls)!=1 or calls[0].get('function',{}).get('name')!=name:raise ValueError('实际模型没有按协议请求唯一允许工具')
    arguments=json.loads(calls[0]['function']['arguments'])
    if arguments!=expected or any(type(v) is bool for v in arguments.values()):raise ValueError('实际工具参数不符合本轮任务')
    # Execute only after validating the actual model tool call.
    details,brief=perform_tool(store,task,prior)
    operation={'id':task['id'],'tool':name,'arguments':arguments,'result':brief}
    store.save_operation(task,{**operation,'full_result':details})
    messages.extend([message,{'role':'tool','tool_call_id':calls[0]['id'],'content':encode({'evidence_ref':reference,**brief})}])
    report_message,second=provider.call(store,task['project_id'],'background',role+'-report',messages,tool,False,task)
    if report_message.get('tool_calls'):raise ValueError('报告阶段不能重复执行工具')
    report=json.loads(report_message.get('content',''))
    summary=text(report.get('summary'),'模型报告',500)
    if any(c.isdigit() for c in summary):raise ValueError('简报包含协议禁止的数值；请读原始响应，不自动重试')
    if report.get('evidence_refs')!=[reference] or not isinstance(report.get('limitations'),list) or not report['limitations'] or not all(isinstance(x,str) and x.strip() for x in report['limitations']):raise ValueError('报告缺少有效证据引用或限制')
    return {'simulation':False,'synthetic':True,'source':'真实 DeepSeek Flash + 本地受控工具','role':role,'task_id':task['id'],'plan_version':task['version'],
        'direction':task['instruction'],'summary':summary,'report':report,'operation':operation,'model_request_ids':[first,second],
        'limitation':'合成课题、固定工具和输入场景；未检索文献，未自动写代码，未证明真实科研效果。',**details}


def answer_meeting(store,meeting_id,question,provider=None):
    m=store.meeting(meeting_id);artifacts=m['snapshot']['artifacts']
    if not artifacts:raise Conflict('本场快照还没有证据，先等工作完成再开始新一轮组会')
    ids=[a['id'] for a in artifacts]
    evidence=[{'id':a['id'],'role':a['role'],'summary':a['body']['summary'],'parameters':a['body'].get('parameters'),'results':compact_results(a['body'].get('results',[])),'verification':a['body'].get('checks'),'limitations':a['body'].get('report',{}).get('limitations')} for a in artifacts]
    messages=[{'role':'system','content':'只依据固定快照用普通中文回答追问，解释观察、限制和未完成工作。不生成或确认下一轮任务，不声称查阅论文。输出JSON：answer（最多六百字）、evidence_refs（引用提供的真实证据ID，非空）。'},
        {'role':'user','content':encode({'question':question,'evidence':evidence,'snapshot_notice':m['snapshot']['notice']})}]
    response,_=(provider or Provider()).call(store,m['project_id'],'qa','meeting-question',messages,meeting_id=meeting_id)
    result=json.loads(response.get('content',''))
    answer=text(result.get('answer'),'组会答复',1000)
    refs=result.get('evidence_refs')
    if not isinstance(refs,list) or not refs or not all(isinstance(x,str) and x in ids for x in refs):raise ValueError('组会答复缺少有效快照证据引用')
    answer='【真实 Flash · 合成案例】'+answer+'\n证据：'+', '.join(refs)
    store.append_real_answer(meeting_id,question,answer)
    return answer
