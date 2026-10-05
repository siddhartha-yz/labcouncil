#!/usr/bin/env python3
"""Additional negative-path checks; preserve initial attempts and upstream code."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from check_freephdlabor_agent import make_agent, save, sha


def inspect(agent):
    result={'task':getattr(agent,'task',None),'executor_variables':sorted(agent.python_executor.state),
            'step_types':[type(s).__name__ for s in agent.memory.steps]}
    for name,func in [('full_steps',agent.memory.get_full_steps),('messages',agent.write_memory_to_messages)]:
        try:
            value=func();result[name]={'usable':True,'count':len(value)}
        except Exception as error:
            result[name]={'usable':False,'error_type':type(error).__name__,'message':str(error)}
    return result


def child(args):
    out=args.output.resolve();root=args.upstream.resolve()
    live=args.mode in ('continue','backup_crash')
    agent,calls,attempts=make_agent(root,out,'no_input',live)
    if args.mode=='disconnect':
        from freephdlabor.interaction.callback_tools import setup_user_input_socket,make_user_input_step_callback
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        queue=setup_user_input_socket(port=port)
        with socket.create_connection(('127.0.0.1',port),timeout=3) as s:
            s.sendall(b'interrupt\nUnfinished test review\n')
        deadline=time.monotonic()+3
        while queue.qsize()<2 and time.monotonic()<deadline:time.sleep(.01)
        assert queue.qsize()==2
        print('TCP_DISCONNECTED_CALLBACK_STARTED',flush=True)
        make_user_input_step_callback(queue)(None,agent)
        raise AssertionError('Incomplete disconnected TCP instruction unexpectedly returned')
    if args.mode=='backup_crash':
        from freephdlabor.agents.context_compaction import ContextMonitoringCallback
        from smolagents.memory import ActionStep
        monitor=ContextMonitoringCallback(model=agent.model,token_threshold=100000)
        def boundary(step,agent):
            agent.save_memory()
            save(out/'crash-boundary.json',{'exit':73,'state':inspect(agent),
                 'current_action_type':type(step).__name__,'calls':calls})
            os._exit(73)
        agent.step_callbacks.register(ActionStep,monitor)
        agent.step_callbacks.register(ActionStep,boundary)
        agent.run('Set checkpoint_value = 37. Call evaluate("linear") in your first separate action. Do not finish or import anything in that action.')
        raise AssertionError('Expected process exit 73')
    capture=io.StringIO()
    with contextlib.redirect_stdout(capture):agent.resume_memory()
    before=inspect(agent)
    result={'restore':before,'restore_stdout':capture.getvalue(),'api_calls':0}
    if args.mode=='continue':
        task=next((s.task for s in agent.memory.steps if hasattr(s,'task')),None)
        old=len(calls)
        try:
            answer=agent.run(task,reset=False,max_steps=3)
            result['answer']=str(answer)
        except Exception as error:
            result['continuation_error']={'type':type(error).__name__,'message':str(error)}
        result.update(api_calls=attempts[0],prior_tool_calls=old,added_tool_calls=calls[old:],after=inspect(agent))
    backup=out/'memory_backup/full_conversation_backup.jsonl'
    result['incremental_backup_entries']=len(backup.read_text().splitlines()) if backup.exists() else 0
    save(out/'recovery-assessment.json',result)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream',type=Path,required=True)
    p.add_argument('--initial',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=('all','audit','continue','backup_crash','disconnect'),default='all')
    args=p.parse_args()
    if args.mode!='all':child(args);return
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    save(out/'provenance.json',{'script_sha256':sha(Path(__file__)),
        'base_runner_sha256':sha(Path(__file__).with_name('check_freephdlabor_agent.py')),
        'source_initial':str(args.initial),'changes':'Separate serializers; fresh-process continuation; incremental-backup crash; real TCP disconnection.'})
    statuses=[]
    def execute(folder,mode,timeout):
        cmd=[sys.executable,str(Path(__file__).resolve()),'--upstream',str(args.upstream),'--output',str(folder),'--mode',mode]
        try:
            done=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
            (folder/(mode+'-stdout.txt')).write_text(done.stdout)
            (folder/(mode+'-stderr.txt')).write_text(done.stderr)
            statuses.append({'directory':folder.name,'mode':mode,'exit_code':done.returncode})
        except subprocess.TimeoutExpired as error:
            (folder/(mode+'-stdout.txt')).write_bytes(error.stdout or b'')
            (folder/(mode+'-stderr.txt')).write_bytes(error.stderr or b'')
            statuses.append({'directory':folder.name,'mode':mode,'timeout_seconds':timeout,
                'inside_callback':b'TCP_DISCONNECTED_CALLBACK_STARTED' in (error.stdout or b'')})
    for case in ('no_input','modify','new_task','cancel','crash'):
        folder=out/case;shutil.copytree(args.initial/case,folder)
        execute(folder,'continue' if case in ('no_input','crash') else 'audit',200)
        print(case,'audited',flush=True)
    folder=out/'backup_crash';folder.mkdir();execute(folder,'backup_crash',65);execute(folder,'audit',15)
    folder=out/'disconnect';folder.mkdir();execute(folder,'disconnect',8)
    save(out/'process-results.json',statuses)

if __name__=='__main__':main()
