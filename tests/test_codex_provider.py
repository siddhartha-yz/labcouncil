"""Real subprocess adapter tests; fixture binary never calls a model."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from labcouncil.codex_provider import CodexProvider, output_schema
from labcouncil.store import Store, Conflict
from labcouncil.brief import normalize


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.store=Store(self.root/'state.sqlite3')
        self.pid=self.store.create_project('CLI fixture','验证CLI边界',mode='research',backend='codex_cli',api_budget=4)
        self.capture=self.root/'argv.json'
        self.binary=self.root/'codex-fixture'
        self.fixture()
        self.provider=CodexProvider(str(self.binary),timeout=2)

    def tearDown(self): self.temp.cleanup()

    def fixture(self, behavior='valid'):
        script=f'''#!{sys.executable}
import json,sys,time,os
from pathlib import Path
args=sys.argv[1:]
Path({str(self.capture)!r}).write_text(json.dumps(args))
prompt=sys.stdin.read()
print(json.dumps({{"type":"thread.started","thread_id":"fixture-session"}}),flush=True)
behavior={behavior!r}
if behavior=="sleep":
    Path({str(self.root/'child.pid')!r}).write_text(str(os.getpid()))
    time.sleep(20)
if behavior=="nonzero":sys.exit(5)
if behavior=="tool":print(json.dumps({{"type":"item.completed","item":{{"type":"command_execution"}}}}))
if behavior=="warning":print(json.dumps({{"type":"item.completed","item":{{"type":"error"}}}}))
print(json.dumps({{"type":"item.completed","item":{{"type":"agent_message"}}}}))
print(json.dumps({{"type":"turn.completed","usage":{{"input_tokens":100,"cached_input_tokens":20,"output_tokens":7}}}}))
answer=Path(args[args.index("--output-last-message")+1])
properties=json.loads(Path(args[args.index("--output-schema")+1]).read_text())["properties"]
result={{"action":"prepare_meeting","value":"","plan":"整理已有结果","reason":"等待审查"}}
if "summary" in properties:
    result={{"summary":"fixture简报","limitations":["未调用真实模型"],"evidence_refs":["operation:fixture"]}}
    if "next_step" in properties:result.update(next_step="人工审查",findings=[])
answer.write_text("broken" if behavior=="invalid" else json.dumps(result))
'''
        self.binary.write_text(script);self.binary.chmod(0o700)

    def call(self):
        from labcouncil.research import TOOL
        task=self.store.claim()
        return self.provider.call(self.store,self.pid,'background','research-plan',
            [{'role':'system','content':'JSON only'}],TOOL,True,task)

    def request(self): return self.store.project(self.pid)['model_requests'][-1]

    def test_exact_model_effort_and_structured_tool_mapping(self):
        message,rid=self.call()
        args=json.loads(self.capture.read_text())
        self.assertEqual(args[args.index('--model')+1],'gpt-6.1-sol')
        self.assertIn('model_reasoning_effort="high"',args)
        self.assertIn('--ignore-user-config',args);self.assertIn('--ephemeral',args)
        self.assertEqual(args[args.index('--sandbox')+1],'read-only')
        self.assertIn('shell_tool',args);self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',args)
        self.assertEqual(json.loads(message['tool_calls'][0]['function']['arguments'])['action'],'prepare_meeting')
        saved=Store(self.store.database).request_record(rid)
        self.assertEqual(saved['status'],'completed');self.assertIsNone(saved['http_status'])
        self.assertEqual(saved['usage']['total_tokens'],107)
        self.assertEqual(saved['response']['thread_id'],'fixture-session')
        self.assertIn('internal model turns',saved['request']['invocation_accounting'])

    def test_quota_blocks_process_before_start(self):
        with self.store.connection(write=True) as con:con.execute('UPDATE project_execution SET api_budget=0 WHERE project_id=?',(self.pid,))
        self.assertIsNone(self.store.claim())
        with self.assertRaises(Conflict):
            self.provider.call(self.store,self.pid,'background','research-report',[{'role':'user','content':'JSON'}])
        self.assertFalse(self.capture.exists());self.assertEqual(self.store.project(self.pid)['model_requests'],[])

    def test_denied_model_permission_blocks_process(self):
        brief=normalize(None,'权限关闭','research');brief['permissions']['model_calls']=False
        pid=self.store.create_project('权限关闭',brief['idea'],mode='research',backend='codex_cli',brief=brief)
        with self.assertRaises(Conflict):self.provider.call(self.store,pid,'background','research-report',[])
        self.assertFalse(self.capture.exists())

    def test_nonzero_exit_charged_without_fallback_or_retry(self):
        self.fixture('nonzero')
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.request()['error'],'codex_nonzero_exit')
        self.assertEqual(len(self.store.project(self.pid)['model_requests']),1)
        self.assertEqual(self.request()['response']['exit_code'],5)

    def test_invalid_final_output_is_not_completed(self):
        self.fixture('invalid')
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.request()['status'],'error')
        self.assertEqual(self.request()['usage']['total_tokens'],107)

    def test_timeout_kills_process_and_preserves_unknown_usage(self):
        self.fixture('sleep');self.provider.timeout=.3
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.request()['error'],'codex_timeout');self.assertIsNone(self.request()['usage'])
        child=int((self.root/'child.pid').read_text())
        with self.assertRaises(ProcessLookupError):os.kill(child,0)
        self.assertEqual(len(self.store.project(self.pid)['model_requests']),1)

    def test_unexpected_cli_execution_fails_closed(self):
        self.fixture('tool')
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.request()['error'],'unexpected_cli_tool')

    def test_startup_diagnostic_is_not_a_tool_execution(self):
        self.fixture('warning');self.call()
        self.assertEqual(self.request()['status'],'completed')

    def test_backend_survives_round_confirmation(self):
        mid=self.store.open_meeting(self.pid)
        self.store.confirm(mid,1,'继续核对','outlier')
        p=Store(self.store.database).project(self.pid)
        self.assertEqual(p['execution']['backend'],'codex_cli')
        self.assertEqual(p['execution']['model'],'gpt-6.1-sol')
        self.assertEqual(p['execution']['reasoning_effort'],'high')
        self.assertIn('gpt-6.1-sol',p['current_inputs']['plan']['executor'])
        self.assertEqual(len(p['input_history']),2)

    def test_old_database_migration_preserves_evidence(self):
        pid=self.store.create_project('旧模拟项目','不改变历史')
        from labcouncil.worker import step
        with self.store.connection(write=True) as con:con.execute('UPDATE projects SET paused=1 WHERE id=?',(self.pid,))
        while step(self.store):pass
        before=self.store.project(pid)['artifacts']
        with self.store.connection(write=True) as con:con.execute('ALTER TABLE project_execution DROP COLUMN backend')
        p=Store(self.store.database).project(pid)
        self.assertEqual(p['artifacts'],before);self.assertEqual(p['execution']['backend'],'deepseek')

    def test_parent_death_terminates_cli(self):
        self.fixture('sleep')
        launcher=Path(__file__).resolve().parents[1]/'labcouncil/_codex_process.py'
        holder=self.root/'holder.py'
        holder.write_text('import subprocess,sys,os,time\n'
            +f'p=subprocess.Popen([sys.executable,{str(launcher)!r},str(os.getpid()),{str(self.binary)!r}],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL)\n'
            +'time.sleep(20)\n')
        parent=subprocess.Popen([sys.executable,str(holder)],start_new_session=True)
        child=None
        def child_is_running():
            try:
                # Reaping can remove /proc between any existence check and read.
                stat=Path(f'/proc/{child}/stat').read_text()
            except (FileNotFoundError, ProcessLookupError):
                return False
            return stat.rsplit(')',1)[1].split()[0]!='Z'
        try:
            deadline=time.monotonic()+3
            while not (self.root/'child.pid').exists() and time.monotonic()<deadline:time.sleep(.02)
            child=int((self.root/'child.pid').read_text())
            parent.kill();parent.wait(timeout=3)
            deadline=time.monotonic()+3
            while child_is_running() and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertFalse(child_is_running(),'Codex process survived its parent')
        finally:
            if parent.poll() is None:os.killpg(parent.pid,signal.SIGKILL);parent.wait()
            if child and child_is_running():
                try:os.kill(child,signal.SIGKILL)
                except ProcessLookupError:pass

    def test_report_and_qa_schemas_have_required_boundary_fields(self):
        self.assertEqual(set(output_schema('research-meeting',None,False)['required']),{'answer','evidence_refs'})
        self.assertEqual(set(output_schema('research-report',None,False)['required']),{'summary','limitations','evidence_refs','next_step','findings'})
        self.assertEqual(set(output_schema('executor-report',None,False)['required']),{'summary','limitations','evidence_refs'})

    def test_default_report_deadline_has_headroom_in_task_lease(self):
        self.provider.timeout=None
        task=self.store.claim()
        self.assertGreater(task['lease_until']-time.time(),590)
        self.provider.call(self.store,self.pid,'background','research-report',
            [{'role':'system','content':'JSON only'}],task=task)
        self.assertEqual(self.request()['request']['timeout_seconds'],180)
        self.assertEqual(self.request()['status'],'completed')


if __name__=='__main__':unittest.main()
