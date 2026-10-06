"""Real LangGraph interrupt test of one extracted upstream function.

The remote provider is a deterministic fixture, not RemoteGraph or a model.
No SDK patching, upstream edits, API key or service launch.
"""
import argparse
import ast
import asyncio
import difflib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['LANGCHAIN_TRACING_V2'] = 'false'

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.func import task
from langgraph.types import Command, interrupt

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'workspaces/upstreams/internagents/internagents/agent_graph.py'
KEY = 'remoteRuntimePendingInterrupt'
OLD = '''    try:
        while True:
            result = await remote.ainvoke(payload, config=remote_config)
            interrupt_value = _remote_interrupt_value(result)
            if interrupt_value is None:
                break
            payload = Command(resume=interrupt(interrupt_value))
    except Exception as exc:
        message = _remote_runtime_exception_message(resource, exc)
        raise RuntimeError(message) from exc
'''
NEW = '''    while True:
        try:
            result = await remote.ainvoke(payload, config=remote_config)
        except Exception as exc:
            message = _remote_runtime_exception_message(resource, exc)
            raise RuntimeError(message) from exc
        interrupt_value = _remote_interrupt_value(result)
        if interrupt_value is None:
            break
        payload = Command(resume=interrupt(interrupt_value))
'''
TASK_CALL = '''    @task(name="resume_remote_runtime_call")
    async def invoke_once(resume_value: Any) -> Any:
        return await remote.ainvoke(Command(resume=resume_value), config=remote_config)

'''


class State(TypedDict, total=False):
    remoteRuntimePendingInterrupt: dict | None
    result: str
    approvals: list[str]


class RemoteFixture:
    def __init__(self, mode='normal'):
        self.mode = mode
        self.calls = []

    async def ainvoke(self, payload, config):
        self.calls.append(payload.resume)
        if self.mode == 'error':
            raise OSError('synthetic remote unavailable')
        if self.mode == 'invalid':
            return None
        if payload.resume == 'approve-first':
            return {'__interrupt__':[{'value':{'action':'second-approval'}}]}
        if payload.resume == 'approve-second':
            return {'result':'completed'}
        raise ValueError('Unexpected fixture decision')


class StatefulRemoteFixture(RemoteFixture):
    """Tracks approvals like a separately checkpointed runtime.

    Unlike the first fixture, replaying the previous decision cannot produce
    the same interrupt again: that runtime has already advanced.
    """
    def __init__(self):
        super().__init__('stateful')
        self.phase = 0

    async def ainvoke(self, payload, config):
        self.calls.append(payload.resume)
        expected = ('approve-first', 'approve-second')[self.phase]
        if payload.resume != expected:
            raise ValueError(f'Approval replay mismatch: expected {expected}, got {payload.resume}')
        self.phase += 1
        if self.phase == 1:
            return {'__interrupt__':[{'value':{'action':'second-approval'}}]}
        return {'result':'completed'}


class RuntimeState(TypedDict, total=False):
    read_approval: str
    write_approval: str
    result: str
    approvals: list[str]


class CheckpointedRuntimeFixture:
    """Local LangGraph runtime with its own real checkpoints, no HTTP/LLM."""
    def __init__(self):
        self.calls = []
        graph = StateGraph(RuntimeState)
        def read_node(state):
            return {'read_approval':interrupt({'action':'first-approval'})}
        def write_node(state):
            decision = interrupt({'action':'second-approval'})
            return {'write_approval':decision,'approvals':[state['read_approval'],decision],'result':'completed'}
        graph.add_node('read',read_node);graph.add_node('write',write_node)
        graph.add_edge(START,'read');graph.add_edge('read','write');graph.add_edge('write',END)
        self.app = graph.compile(checkpointer=MemorySaver())
        self.config = {'configurable':{'thread_id':'separate-runtime-fixture'}}

    async def initialize(self):
        await self.app.ainvoke({},self.config)

    async def ainvoke(self,payload,config):
        self.calls.append(payload.resume)
        return await self.app.ainvoke(payload,self.config)


def load_function(source):
    tree = ast.parse(source)
    selected = [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in ('_resume_remote_runtime','_remote_interrupt_value','_sanitize_remote_runtime_config')]
    constants = [n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REMOTE_RUNTIME_PARENT_CONFIG_KEYS' for t in n.targets)]
    # Keep interrupt parsing/config sanitizing unchanged. These two helpers are
    # deliberately fixtures: error wording and goal accounting are out of scope.
    namespace = {'Command':Command,'interrupt':interrupt,'task':task,
        'REMOTE_RUNTIME_PENDING_INTERRUPT_KEY':KEY,
        '_remote_runtime_exception_message':lambda resource,error:str(error),
        '_with_goal_continuation_accounting':lambda state,result:result}
    module = ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*constants,*selected],type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),str(SOURCE),'exec'),namespace)
    return namespace['_resume_remote_runtime']


async def run_case(function, mode='normal', wrong_resource=False, second_decision='approve-second'):
    if mode == 'checkpointed-runtime':
        remote = CheckpointedRuntimeFixture()
        await remote.initialize()
    else:
        remote=StatefulRemoteFixture() if mode == 'stateful' else RemoteFixture(mode)
    async def node(state, config):
        return await function(remote,SimpleNamespace(id='fixture'),state,config)
    graph=StateGraph(State)
    graph.add_node('resume',node);graph.add_edge(START,'resume');graph.add_edge('resume',END)
    app=graph.compile(checkpointer=MemorySaver())
    config={'configurable':{'thread_id':'synthetic-case'}}
    pending={'resourceId':'wrong' if wrong_resource else 'fixture','value':{'action':'first-approval'}}
    steps=[]
    async def invoke(payload):
        try:
            result=await app.ainvoke(payload,config)
            result=dict(result)
            if '__interrupt__' in result:
                result['__interrupt__']=[{'value':i.value,'id':i.id} for i in result['__interrupt__']]
            steps.append({'result':result})
            return True
        except Exception as error:
            steps.append({'error_type':type(error).__name__,'message':str(error),'cause_type':type(error.__cause__).__name__ if error.__cause__ else None})
            return False
    await invoke({KEY:pending})
    if not wrong_resource:
        success=await invoke(Command(resume='approve-first'))
        if success and mode in ('normal','stateful','checkpointed-runtime'):
            await invoke(Command(resume=second_decision))
    snapshot=await app.aget_state(config)
    return {'steps':steps,'remote_calls':remote.calls,'pending_nodes':list(snapshot.next),'final_values':dict(snapshot.values)}


async def main(output):
    if output.exists():raise RuntimeError('Refusing to overwrite an existing attempt')
    original=SOURCE.read_text()
    assert original.count(OLD)==1
    candidate=original.replace(OLD,NEW,1)
    durable = candidate.replace('    while True:\n        try:\n            result = await remote.ainvoke(payload, config=remote_config)',TASK_CALL+'    while True:\n        try:\n            result = await invoke_once(payload.resume)',1)
    before=load_function(original);after=load_function(candidate)
    durable_function=load_function(durable)
    records={'original':await run_case(before),'candidate':await run_case(after),
        'remote_error':await run_case(after,'error'),'invalid_response':await run_case(after,'invalid'),
        'wrong_resource':await run_case(after,wrong_resource=True),
        'candidate_stateful_remote':await run_case(after,'stateful'),
        'candidate_checkpointed_runtime':await run_case(after,'checkpointed-runtime'),
        'durable_checkpointed_runtime':await run_case(durable_function,'checkpointed-runtime'),
        'durable_stateful_remote':await run_case(durable_function,'stateful'),
        'durable_remote_error':await run_case(durable_function,'error'),
        'candidate_denial':await run_case(after,'checkpointed-runtime',second_decision='deny-second'),
        'durable_denial':await run_case(durable_function,'checkpointed-runtime',second_decision='deny-second')}
    checks={
        'original_wraps_second_interrupt':records['original']['steps'][-1].get('cause_type')=='GraphInterrupt',
        'candidate_pauses_on_second_approval':records['candidate']['steps'][1].get('result',{}).get('__interrupt__',[{}])[0].get('value')=={'action':'second-approval'},
        'candidate_completes_after_both_approvals':records['candidate']['final_values'].get('result')=='completed' and not records['candidate']['pending_nodes'],
        'real_remote_failure_still_errors':records['remote_error']['steps'][-1].get('cause_type')=='OSError',
        'invalid_remote_response_still_errors':records['invalid_response']['steps'][-1].get('error_type')=='RuntimeError',
        'wrong_resource_never_invoked':not records['wrong_resource']['remote_calls'],
        'candidate_replay_problem_detected':records['candidate_stateful_remote']['steps'][-1].get('cause_type')=='ValueError' and records['candidate_stateful_remote']['remote_calls']==['approve-first','approve-first'],
        'candidate_wrong_decision_in_real_checkpoints_detected':records['candidate_checkpointed_runtime']['final_values'].get('approvals')==['approve-first','approve-first'] and records['candidate_checkpointed_runtime']['remote_calls']==['approve-first','approve-first'],
        'durable_preserves_distinct_decisions':records['durable_checkpointed_runtime']['final_values'].get('approvals')==['approve-first','approve-second'],
        'durable_calls_each_resume_once':records['durable_checkpointed_runtime']['remote_calls']==['approve-first','approve-second'],
        'durable_stateful_remote_completes':records['durable_stateful_remote']['final_values'].get('result')=='completed',
        'durable_real_remote_failure_still_errors':records['durable_remote_error']['steps'][-1].get('cause_type')=='OSError',
        'simple_candidate_loses_denial':records['candidate_denial']['final_values'].get('approvals')==['approve-first','approve-first'],
        'durable_preserves_denial_payload':records['durable_denial']['final_values'].get('approvals')==['approve-first','deny-second']}
    output.mkdir(parents=True)
    (output/'candidate.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='a/internagents/agent_graph.py',tofile='b/internagents/agent_graph.py')))
    # The helper uses the public task API; patch includes its required import.
    durable = durable.replace('from langgraph.types import Command, interrupt','from langgraph.func import task\nfrom langgraph.types import Command, interrupt',1)
    (output/'durable-candidate.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),durable.splitlines(True),fromfile='a/internagents/agent_graph.py',tofile='b/internagents/agent_graph.py')))
    record={'source_sha256':hashlib.sha256(original.encode()).hexdigest(),'langgraph_version':importlib.metadata.version('langgraph'),'records':records,'checks':checks,'model_calls':0,'remote_provider':'deterministic fixture','full_service_retested':False}
    (output/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(checks))
    if not all(checks.values()):raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True)
    asyncio.run(main(parser.parse_args().output_dir))
