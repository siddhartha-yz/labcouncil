#!/usr/bin/env python3
"""Pre-registered bounded comparison; human review is an explicit checkpoint."""
import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time
import urllib.error
import urllib.request
from check_deepseek_connectivity import ENDPOINT,load_config,redact
from check_deepseek_workflow import run_experiment,verify_artifact,write_json,digest

ARMS=('single','multi','human')
TASKS={'clean':0.0,'outliers':0.1}
METRICS=('mse','mae','median_absolute_error')
SCHEMA=('Return only JSON with evidence_refs (array of real IDs), observations '
        '(array of {seed,metric,linear,baseline}), conclusion (string), limitations (string array), '
        'verification_refs (array of actually verified IDs). Copy numbers; do not claim experiments or verification you did not execute.')
TOOLS=[{'type':'function','function':{'name':'experiment','description':'Compute fixed regression and matched baseline; save CSV. Allowed seeds 7,19,31; metrics mse,mae,median_absolute_error.',
        'parameters':{'type':'object','properties':{'seeds':{'type':'array','items':{'type':'integer'}},
           'metrics':{'type':'array','items':{'type':'string'}}},'required':['seeds','metrics'],'additionalProperties':False}}},
       {'type':'function','function':{'name':'verify','description':'Independently verify an existing evidence ID from saved CSV.',
        'parameters':{'type':'object','properties':{'evidence_id':{'type':'string'}},'required':['evidence_id'],'additionalProperties':False}}}]

def check_report(report,state):
    checks={'valid_json_schema':False,'numeric_and_refs_valid':False,'three_seeds':False,
            'three_metrics_each_seed':False,'verification_claim_supported':False}
    if not isinstance(report,dict):return checks
    checks['valid_json_schema']=all(k in report for k in ('evidence_refs','observations','conclusion','limitations','verification_refs')) and isinstance(report.get('observations'),list) and isinstance(report.get('limitations'),list) and bool(report['limitations'])
    try:
        refs=report['evidence_refs'];assert isinstance(refs,list) and refs and len(set(refs))==len(refs)
        artifacts={a['evidence_id']:a for a in state['artifacts']}
        assert all(r in artifacts for r in refs)
        expected={}
        for ref in refs:
            for row in artifacts[ref]['results']:
                for metric,values in row['metrics'].items():expected[(row['seed'],metric)]=values
        observations={}
        for row in report['observations']:
            pair=(row['seed'],row['metric']);assert pair in expected and pair not in observations
            for model in ('linear','baseline'):
                value=row[model];assert type(value) in (float,int) and math.isfinite(value)
                assert math.isclose(value,expected[pair][model],abs_tol=1e-4,rel_tol=1e-4)
            observations[pair]=row
        assert observations and isinstance(report['conclusion'],str) and report['conclusion'].strip()
        checks['numeric_and_refs_valid']=True
        checks['three_seeds']={s for s,m in observations}=={7,19,31}
        checks['three_metrics_each_seed']=set(observations)=={(s,m) for s in (7,19,31) for m in METRICS}
        verified=report['verification_refs'];assert isinstance(verified,list)
        checks['verification_claim_supported']=bool(verified) and set(verified).issubset(state['verified']) and set(refs).issubset(verified)
    except (AssertionError,KeyError,TypeError,ValueError):pass
    return checks

class Run:
    def __init__(self,root,config,state):self.root,self.config,self.state=root,config,state
    def save(self):write_json(self.root/'state.json',redact(self.state,self.config['DEEPSEEK_API_KEY']))
    def event(self,event):
        with (self.root/'events.jsonl').open('a') as f:f.write(json.dumps(redact(event,self.config['DEEPSEEK_API_KEY']),ensure_ascii=False)+'\n')
    def call(self,messages,stage,force=False,tools=True):
        s=self.state
        if s['api_calls']>=6:raise RuntimeError('Per-run API budget exhausted')
        payload={'model':'deepseek-flash','messages':messages,'thinking':{'type':'disabled'},
            'temperature':0.3,'max_tokens':1024,'response_format':{'type':'json_object'},'stream':False}
        if tools:
            payload['tools']=TOOLS
            payload['tool_choice']={'type':'function','function':{'name':'experiment'}} if force else 'auto'
        s['api_calls']+=1;self.save();call_id=s['api_calls']
        self.event({'kind':'request','stage':stage,'call_id':call_id,'payload':payload})
        request=urllib.request.Request(ENDPOINT,data=json.dumps(payload).encode(),headers={
            'Content-Type':'application/json','Authorization':'Bearer '+self.config['DEEPSEEK_API_KEY']})
        start=time.monotonic()
        try:
            with urllib.request.urlopen(request,timeout=45) as response:body=json.load(response)
        except (urllib.error.URLError,TimeoutError,OSError) as error:
            self.event({'kind':'failure','call_id':call_id,'error_type':type(error).__name__,'elapsed_seconds':time.monotonic()-start})
            raise RuntimeError('Provider or transport failure; no retry') from None
        self.event({'kind':'response','stage':stage,'call_id':call_id,'response':body,'elapsed_seconds':time.monotonic()-start})
        for k in ('prompt_tokens','completion_tokens','total_tokens'):s['usage'][k]+=body.get('usage',{}).get(k,0)
        self.save();choice=body['choices'][0]
        if choice['finish_reason'] not in ('stop','tool_calls'):raise ValueError('Truncated or interrupted response')
        return {k:v for k,v in choice['message'].items() if k in ('role','content','tool_calls') and v is not None}
    def tools(self,message,stage):
        outputs=[]
        for call in message.get('tool_calls',[]):
            name=call['function']['name'];args=json.loads(call['function']['arguments']);s=self.state
            try:
                if name=='experiment':
                    seeds=args['seeds'];metrics=args['metrics']
                    if set(args)!= {'seeds','metrics'} or not seeds or len(seeds)!=len(set(seeds)) or not set(seeds).issubset({7,19,31}) or any(type(n)!=int for n in seeds) or not metrics or len(metrics)!=len(set(metrics)) or not set(metrics).issubset(METRICS):raise ValueError('Invalid registered experiment input')
                    if stage=='draft' and (seeds!=[7] or metrics!=['mse']):raise ValueError('Draft must use seed 7 and mse')
                    spec={'task_version':1,'seeds':sorted(seeds),'outlier_fraction':TASKS[s['task']],'metrics':sorted(metrics)}
                    duplicate=next((a for a in s['artifacts'] if a['parameters']==spec),None)
                    if duplicate:
                        result=duplicate;self.event({'kind':'duplicate_request','stage':stage,'arguments':args,'evidence_id':result['evidence_id']})
                    else:
                        if len(s['artifacts'])>=2 or s['seed_units']+len(seeds)>6:raise ValueError('Compute budget reached')
                        evidence_id='evidence-'+str(len(s['artifacts'])+1)
                        result,manifest=run_experiment(self.root,evidence_id,spec)
                        s['artifacts'].append(result);s['manifests'][evidence_id]=manifest;s['seed_units']+=len(seeds)
                elif name=='verify':
                    if set(args)!= {'evidence_id'} or s['verify_calls']>=2:raise ValueError('Verification budget or arguments invalid')
                    artifact=next(a for a in s['artifacts'] if a['evidence_id']==args['evidence_id'])
                    result=verify_artifact(self.root,artifact,s['manifests'][artifact['evidence_id']])
                    s['verify_calls']+=1;s['verified'].append(artifact['evidence_id'])
                else:raise ValueError('Tool outside allowlist')
                self.event({'kind':'tool_result','stage':stage,'name':name,'arguments':args,'result':result})
            except (ValueError,KeyError,StopIteration,TypeError) as error:
                result={'tool_error':type(error).__name__,'message':str(error)}
                self.event({'kind':'tool_rejected','stage':stage,'name':name,'arguments':args,'result':result})
            self.save();outputs.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(result)})
        return outputs
    def stage(self,messages,name,force=False):
        first=self.call(messages,name,force=force);messages.append(first)
        outputs=self.tools(first,name);messages+=outputs
        if outputs:
            last=self.call(messages+[{'role':'user','content':'No further tool calls in this stage. '+SCHEMA}],name,tools=False)
            messages.append(last)
        else:
            # A report without tools leaves the second slot unused; never invent extra evidence.
            last=first
        report=json.loads(last['content']);write_json(self.root/(name+'-report.json'),report)
        return report,messages
    def draft(self):
        s=self.state;messages=[{'role':'system','content':'You are the executor for a bounded synthetic regression study. '+SCHEMA},
            {'role':'user','content':f"Task {s['task']}: Does OLS outperform a matched training-mean predictor on {'clean labels' if s['task']=='clean' else '10% test-label outliers of magnitude 10 with clean training data'}? Begin with seed 7 and mse only; produce a preliminary report. Full budget allows seeds 7,19,31 and mse,mae,median_absolute_error. Do not claim general scientific value."}]
        report,history=self.stage(messages,'draft',force=True)
        s.update(draft=report,history=history,status='awaiting_human' if s['arm']=='human' else 'draft_ready');self.save()
    def finish(self,feedback=None):
        s=self.state;history=s['history'];arm=s['arm']
        if arm=='human':
            assert feedback and feedback['human_confirmed'] is True and type(feedback['review_minutes']) in (int,float) and feedback['review_minutes']>=0
            decision=feedback['tasks'][s['task']];assert isinstance(decision,str) and decision.strip()
            s['human_feedback']=feedback;history=history+[{'role':'user','content':'Real user meeting feedback: '+decision}]
        if arm=='single':
            review_messages=history+[{'role':'user','content':'Self-review your preliminary evidence and use verification if useful. Identify gaps before finalizing. '+SCHEMA}]
        else:
            review_messages=[{'role':'system','content':'You are an independent evidence reviewer. Critique the method and use verify if useful. '+SCHEMA},
                {'role':'user','content':json.dumps({'task':s['task'],'draft':s['draft'],'artifacts':s['artifacts'],
                    'human_feedback':s.get('human_feedback',{}).get('tasks',{}).get(s['task'])})}]
        review,_=self.stage(review_messages,'review')
        final_messages=history+[{'role':'user','content':'Review feedback: '+json.dumps(review)+'. Improve evidence if needed and give the final bounded report. '+SCHEMA}]
        final,_=self.stage(final_messages,'final')
        s.update(final=final,checks=check_report(final,s),status='completed');self.save()


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--output',type=Path,required=True)
 p.add_argument('--mode',choices=('nonhuman','human-drafts','human-finish'),required=True)
 p.add_argument('--feedback',type=Path)
 a=p.parse_args();config=load_config(Path('.env'));assert config['DEEPSEEK_MODEL']=='deepseek-flash'
 out=a.output.resolve()
 if not out.exists():out.mkdir(parents=True)
 arms=('single','multi') if a.mode=='nonhuman' else ('human',)
 feedback=json.loads(a.feedback.read_text()) if a.mode=='human-finish' else None
 for repeat in (1,2):
  for task in TASKS:
   for arm in (arms if repeat%2 else tuple(reversed(arms))):
    root=out/f'{task}-{arm}-{repeat}'
    if a.mode=='human-finish':
        state=json.loads((root/'state.json').read_text());assert state['status']=='awaiting_human'
    else:
        root.mkdir(exist_ok=False)
        state={'task':task,'arm':arm,'repeat':repeat,'status':'started','python':platform.python_version(),
            'script_sha256':digest(Path(__file__)),'experiment_tool_sha256':digest(Path(__file__).with_name('check_deepseek_workflow.py')),
            'started_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'api_calls':0,
            'usage':dict.fromkeys(('prompt_tokens','completion_tokens','total_tokens'),0),
            'artifacts':[],'manifests':{},'verified':[],'verify_calls':0,'seed_units':0}
    run=Run(root,config,state);run.save()
    try:
        if a.mode!='human-finish':run.draft()
        if a.mode!='human-drafts':run.finish(feedback)
    except Exception as error:
        state.update(status='failed',failure_type=type(error).__name__,failure=str(error));run.save()
    print(root.name,state['status'],state['api_calls'],flush=True)
if __name__=='__main__':main()
