"""Offline supplier fixtures: never count these as real Flash validation."""
import concurrent.futures
import http.server
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from labcouncil.case import answer_meeting, execute
from labcouncil.provider import Provider
from labcouncil.store import Conflict, Store


class SupplierFixture(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.seen.append(request)
        status=self.server.reply_sequence.pop(0) if self.server.reply_sequence else self.server.reply_status
        if self.server.delay:time.sleep(self.server.delay)
        if status!=200:body={'error':'offline fixture rejection'}
        elif isinstance(request.get('tool_choice'),dict):
            expected=json.loads(request['messages'][-1]['content'])['required_tool_parameters']
            message={'role':'assistant','content':None,'tool_calls':[{'id':'fixture-tool','type':'function','function':{'name':request['tools'][0]['function']['name'],'arguments':json.dumps(expected)}}]}
            body={'model':'deepseek-flash','choices':[{'message':message,'finish_reason':'tool_calls'}]}
        else:
            final=request['messages'][-1]
            if final['role']=='tool':
                ref=json.loads(final['content'])['evidence_ref']
                report={'summary':'已完成受控工具检查，结果仅适用于合成案例。','limitations':['合成数据，不是论文复现'],'evidence_refs':[ref]}
            else:
                refs=[x['id'] for x in json.loads(final['content'])['evidence']]
                report={'answer':'仅依据快照回答，尚不能推广。','evidence_refs':refs}
            body={'model':'deepseek-flash','choices':[{'message':{'role':'assistant','content':json.dumps(report,ensure_ascii=False)},'finish_reason':'stop'}]}
        if status==200 and self.server.include_usage:body['usage']={'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}
        wire=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Length',str(len(wire)));self.end_headers()
        try:self.wfile.write(wire)
        except (BrokenPipeError,ConnectionResetError):pass


class RealCaseTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)/'state.sqlite3';self.store=Store(self.path)
        self.project=self.store.create_project('供应商 fixture','测试真实流程的接口边界',mode='real_case',api_budget=12,qa_api_budget=1)
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),SupplierFixture)
        self.server.daemon_threads=True;self.server.seen=[];self.server.reply_status=200;self.server.reply_sequence=[];self.server.include_usage=True;self.server.delay=0
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.provider=Provider({'DEEPSEEK_API_KEY':'unit-fixture-placeholder','DEEPSEEK_MODEL':'deepseek-flash'},f'http://127.0.0.1:{self.server.server_address[1]}',timeout=.1)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3);self.folder.cleanup()
    def finish_round(self):
        while task:=self.store.claim():self.store.complete(task,execute(self.store,task,self.provider))
    def test_two_rounds_tools_reports_and_qa_are_separate(self):
        self.finish_round();m=self.store.open_meeting(self.project)
        answer=answer_meeting(self.store,m,'为什么能相信这个算数？',self.provider)
        self.assertIn('真实 Flash',answer)
        self.store.confirm(m,1,'增加异常点和重复次数','outlier');self.finish_round()
        p=self.store.project(self.project)
        self.assertEqual(len(p['model_requests']),13);self.assertEqual(len(self.server.seen),13)
        self.assertEqual(len(p['artifacts']),6);self.assertTrue(p['artifacts'][-1]['body']['verified'])
        self.assertEqual(len(p['artifacts'][0]['body']['datasets']),1);self.assertEqual(len(p['artifacts'][3]['body']['datasets']),3)
        self.assertEqual(p['qa_used'],1)
        for request in p['model_requests']:
            if request['category']=='background' and request['phase'].endswith('-report'):
                tool_result=json.loads(request['request']['messages'][-1]['content'])
                self.assertIn('parameters',tool_result)
        self.assertEqual(p['artifacts'][-1]['body']['parameters']['test_outlier_fraction'],.1)
        with self.assertRaises(Conflict):answer_meeting(self.store,self.store.open_meeting(self.project),'额度用完',self.provider)
        self.assertEqual(len(self.server.seen),13)
    def test_tool_not_executed_before_or_without_valid_model_call(self):
        self.server.reply_status=429;task=self.store.claim()
        with patch('labcouncil.case.perform_tool') as tool:
            with self.assertRaises(ValueError):execute(self.store,task,self.provider)
            tool.assert_not_called()
        self.assertEqual(len(self.server.seen),1)
        request=self.store.project(self.project)['model_requests'][0]
        self.assertEqual(request['status'],'error');self.assertEqual(request['http_status'],429)
    def test_missing_usage_remains_unknown_and_restart_keeps_attempt(self):
        self.server.include_usage=False;task=self.store.claim()
        body=execute(self.store,task,self.provider);self.store.complete(task,body)
        saved=Store(self.path).project(self.project)['model_requests']
        self.assertEqual(len(saved),2);self.assertTrue(all(r['usage'] is None for r in saved))
        self.assertNotIn('unit-fixture-placeholder',json.dumps(saved))
    def test_timeout_is_charged_without_retry(self):
        self.server.delay=.3;task=self.store.claim()
        with self.assertRaises(ValueError):execute(self.store,task,self.provider)
        self.assertEqual(len(self.server.seen),1)
        self.assertEqual(len(Store(self.path).project(self.project)['model_requests']),1)
    def test_report_failure_keeps_actual_tool_result(self):
        self.server.reply_sequence=[200,429];task=self.store.claim()
        with self.assertRaises(ValueError):execute(self.store,task,self.provider)
        p=self.store.project(self.project)
        self.assertEqual(len(p['artifacts']),0);self.assertEqual(len(p['tool_operations']),1)
        operation=self.store.operation_record(task['id'])
        self.assertEqual(len(operation['body']['full_result']['datasets'][0]['train']),40)
        self.assertEqual(len(operation['body']['full_result']['datasets'][0]['test']),100)
        self.assertEqual(len(self.server.seen),2)
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError),self.store.connection(write=True) as con:
            con.execute("UPDATE tool_operations SET body='{}' WHERE id=?",(task['id'],))
    def test_arithmetic_verification_detects_incorrect_saved_metric(self):
        from labcouncil.case import dataset,compute,independent_verify,parameters
        data=dataset(parameters('outlier'));result=compute(data);result[1]['metrics']['linear']['mse']=99
        checked=independent_verify(data,result)
        self.assertFalse(checked['verified']);self.assertFalse(checked['checks'][1]['passed'])
    def test_concurrent_reservation_hard_limit_and_unknown_not_refunded(self):
        # No network calls: race for twelve slots in the persistent ledger.
        def reserve(i):
            try:return Store(self.path).reserve_request(self.project,'background','fixture',{'i':i})
            except Conflict:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:ids=list(pool.map(reserve,range(20)))
        self.assertEqual(sum(x is not None for x in ids),12)
        with self.assertRaises(Conflict):Store(self.path).reserve_request(self.project,'background','extra',{})
        self.assertEqual(len(self.server.seen),0)
    def test_real_expired_lease_stops_instead_of_reissuing(self):
        task=self.store.claim();rid=self.store.reserve_request(self.project,'background','started',{},task=task)
        with self.store.connection(write=True) as con:con.execute('UPDATE tasks SET lease_until=? WHERE id=?',(time.time()-1,task['id']))
        self.assertIsNone(Store(self.path).claim())
        p=self.store.project(self.project)
        self.assertEqual(p['tasks'][0]['status'],'failed');self.assertEqual(p['model_requests'][0]['status'],'unknown')
        self.assertEqual(p['model_requests'][0]['id'],rid);self.assertEqual(len(self.server.seen),0)
    def test_existing_m1_database_upgrades_without_changing_evidence(self):
        legacy=Store(Path(self.folder.name)/'old.sqlite3');pid=legacy.create_project('旧项目','模拟原型')
        from labcouncil.worker import step
        while step(legacy):pass
        before=legacy.project(pid)['artifacts'];m=legacy.open_meeting(pid);snapshot=legacy.meeting(m)['snapshot']
        with legacy.connection(write=True) as con:
            con.execute('DROP TABLE model_requests');con.execute('DROP TABLE project_execution')
        upgraded=Store(legacy.database)
        self.assertEqual(upgraded.project(pid)['artifacts'],before);self.assertEqual(upgraded.meeting(m)['snapshot'],snapshot)
        self.assertEqual(upgraded.project(pid)['execution']['mode'],'simulation')


if __name__=='__main__':unittest.main()
