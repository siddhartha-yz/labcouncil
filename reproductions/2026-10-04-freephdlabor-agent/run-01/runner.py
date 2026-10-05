#!/usr/bin/env python3
"""Pinned real BaseResearchAgent checks. No simulated LLM or upstream edits."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import types
from check_deepseek_connectivity import load_config, redact

PIN = '9102d18a161037294d3d963b2799351aa724c58b'
CASES = ('no_input', 'modify', 'new_task', 'cancel', 'crash')

def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str)+'\n')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def upstream(root):
    assert subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()==PIN
    assert not subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True).strip()
    package=root/'freephdlabor'
    for name, path in [('freephdlabor',package),('freephdlabor.agents',package/'agents')]:
        module=types.ModuleType(name);module.__path__=[str(path)];sys.modules[name]=module
    assert importlib.metadata.version('smolagents')=='1.20.0'

def make_agent(root, output, case, live):
    upstream(root)
    from smolagents import OpenAIServerModel, tool
    from freephdlabor.agents.base_research_agent import BaseResearchAgent
    from freephdlabor.interaction.callback_tools import setup_user_input_socket, make_user_input_step_callback
    config=load_config(Path('.env')) if live else None
    if live and config['DEEPSEEK_MODEL']!='deepseek-flash':
        raise ValueError('Expected deepseek-flash; no request sent')
    model=OpenAIServerModel(model_id='deepseek-flash',api_base='https://api.deepseek.com',
        api_key=config['DEEPSEEK_API_KEY'] if live else 'OFFLINE_NOT_SENT',
        client_kwargs={'timeout':45,'max_retries':0}, max_tokens=768,temperature=0,
        extra_body={'thinking':{'type':'disabled'}})
    events=output/'api-events.jsonl'
    original=model.client.chat.completions.create
    attempts=[0]
    def request(**kwargs):
        if not live or attempts[0]>=4:
            raise RuntimeError('Request budget reached or offline mode')
        attempts[0]+=1
        def event(data):
            with events.open('a') as file:
                file.write(json.dumps(redact(data,config['DEEPSEEK_API_KEY']),ensure_ascii=False)+'\n')
        event({'kind':'request','attempt':attempts[0],'kwargs':kwargs})
        try:
            response=original(**kwargs)
        except Exception as error:
            event({'kind':'failure','attempt':attempts[0],'error_type':type(error).__name__})
            raise RuntimeError('Bounded provider request failed') from None
        event({'kind':'response','attempt':attempts[0],'response':response.model_dump(mode='json')})
        return response
    model.client.chat.completions.create=request
    with socket.socket() as bound:
        bound.bind(('127.0.0.1',0));port=bound.getsockname()[1]
    queue=setup_user_input_socket(port=port)
    calls_path=output/'tool-calls.json'
    calls=json.loads(calls_path.read_text()) if calls_path.exists() else []
    @tool
    def evaluate(predictor: str) -> str:
        """Compute MSE for one fixed predictor on the registered dataset.

        Args:
            predictor: Must be linear or baseline.
        """
        if predictor not in ('linear','baseline') or len(calls)>=8:
            raise ValueError('Tool input or budget rejected')
        y=[1,3,5,7,9]
        predictions=[2*x+1 for x in range(5)] if predictor=='linear' else [5]*5
        item={'call':len(calls)+1,'predictor':predictor,
              'mse':sum((a-b)**2 for a,b in zip(y,predictions))/5,
              'y':y,'predictions':predictions}
        calls.append(item);save(calls_path,calls)
        if len(calls)==1 and case in ('modify','new_task','cancel'):
            lines=['interrupt','',''] if case=='cancel' else [
                'interrupt','TEST_REVIEW_BASELINE: In your next separate action evaluate baseline instead of linear; then finish.','','',
                'm' if case=='modify' else 'n']
            with socket.create_connection(('127.0.0.1',port),timeout=3) as connection:
                connection.sendall(('\n'.join(lines)+'\n').encode())
            deadline=time.monotonic()+3
            while queue.qsize()<len(lines) and time.monotonic()<deadline:
                time.sleep(.01)
            if queue.qsize()<len(lines):raise RuntimeError('TCP input delivery incomplete')
        return json.dumps(item)
    callback=make_user_input_step_callback(queue)
    def crash(step,agent):
        agent.save_memory()
        save(output/'crash-boundary.json',{'exit':73,'step_type':type(step).__name__,
             'task':getattr(agent,'task',None),'state_keys':sorted(agent.state),
             'executor_state_keys':sorted(agent.python_executor.state)})
        os._exit(73)
    agent=BaseResearchAgent(model,agent_name='probe',workspace_dir=str(output),tools=[evaluate],
        enable_auto_compaction=False,verbosity_level=0,max_steps=4,
        step_callbacks=[callback]+([crash] if case=='crash' else []))
    return agent, calls, attempts

def state(agent):
    result={'task':getattr(agent,'task',None),'state_keys':sorted(agent.state),
            'executor_state_keys':sorted(agent.python_executor.state),
            'step_types':[type(step).__name__ for step in agent.memory.steps]}
    try:
        result['steps']=agent.memory.get_full_steps()
        result['messages']=[m.dict() for m in agent.write_memory_to_messages()]
        result['memory_usable']=True
    except Exception as error:
        result['memory_usable']=False
        result['memory_error']={'type':type(error).__name__,'message':str(error)}
    return result

def child(args):
    output=args.output.resolve()
    agent,calls,attempts=make_agent(args.upstream.resolve(),output,args.case,args.mode=='run')
    if args.mode=='resume':
        agent.resume_memory();save(output/'restored-state.json',state(agent));return
    task=('FIXED_TASK_LINEAR: First separate action set checkpoint_value = 37 and call evaluate("linear"). '
          'Do not call final_answer in that first action. On the following action, follow any additional user instruction; '
          'otherwise call evaluate("linear") again. After the second evaluation return a short final_answer. '
          'Do not import anything. Keep actions separate so step callbacks can execute.')
    error=None
    try:
        answer=agent.run(task)
    except Exception as exc:
        answer=None;error={'type':type(exc).__name__,'message':str(exc)}
    agent.save_memory()
    save(output/'original-state.json',state(agent))
    expected='baseline' if args.case in ('modify','new_task') else 'linear'
    save(output/'result.json',{'case':args.case,'calls':calls,'attempts':attempts[0],
         'answer':str(answer),'error':error,'expected_next_predictor':expected,
         'next_tool_matches':len(calls)>=2 and calls[1]['predictor']==expected,
         'checkpoint_in_executor':agent.python_executor.state.get('checkpoint_value')==37})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mode',choices=('all','run','resume'),default='all')
    parser.add_argument('--case',choices=CASES)
    args=parser.parse_args()
    if args.mode!='all':child(args);return
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    root=args.upstream.resolve();upstream(root)
    source={str(p.relative_to(root)):sha(p) for p in (root/'freephdlabor').rglob('*.py')}
    save(output/'provenance.json',{'upstream_commit':PIN,'source_hashes':source,
        'script_sha256':sha(Path(__file__)),
        'dependencies':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}})
    statuses=[]
    for case in CASES:
        folder=output/case;folder.mkdir()
        command=[sys.executable,str(Path(__file__).resolve()),'--upstream',str(root),'--output',str(folder),'--case',case]
        for mode in ('run','resume'):
            try:
                done=subprocess.run(command+['--mode',mode],capture_output=True,text=True,timeout=220 if mode=='run' else 15)
                (folder/(mode+'-stdout.txt')).write_text(done.stdout)
                (folder/(mode+'-stderr.txt')).write_text(done.stderr)
                statuses.append({'case':case,'mode':mode,'exit_code':done.returncode})
            except subprocess.TimeoutExpired as exc:
                (folder/(mode+'-stdout.txt')).write_bytes(exc.stdout or b'')
                (folder/(mode+'-stderr.txt')).write_bytes(exc.stderr or b'')
                statuses.append({'case':case,'mode':mode,'timeout':True})
        print(case,'recorded',flush=True)
    save(output/'process-results.json',statuses)
    assert source=={str(p.relative_to(root)):sha(p) for p in (root/'freephdlabor').rglob('*.py')}

if __name__=='__main__':main()
