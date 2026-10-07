"""Meeting synthesis must use saved tool evidence, not only the last stop action."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from labcouncil.brief import normalize
from labcouncil.research import execute,answer_meeting,checked_findings,prompt_content,meeting_materials,meeting_evidence,format_meeting_answer
from labcouncil.store import Store,encode
from tests.test_research import FixtureProvider

class SynthesisTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'state.sqlite3')
        self.brief=normalize(None,'检查协议与记忆机制','research');self.brief['permissions'].update(public_research=True,local_compute=False)
        self.pid=self.s.create_project('synthesis','fixture',mode='research',brief=self.brief,api_budget=14)
    def tearDown(self):self.tmp.cleanup()
    def step(self,provider):
        task=self.s.claim();body=execute(self.s,task,provider);self.s.complete(task,body);return task,body
    def test_final_report_receives_source_and_prior_operation_refs(self):
        provider=FixtureProvider([('search_repositories','protocol'),('prepare_meeting','')])
        raw=b'{"items":[{"full_name":"owner/protocol","description":"Fixture protocol for tools"}]}'
        with patch('labcouncil.sources._network',return_value=(raw,200)) as net:
            first,_=self.step(provider);second,body=self.step(provider)
            self.assertEqual(net.call_count,1)
        context=json.loads(provider.seen[-1][-1]['content'])
        item=context['result']['meeting_evidence']['items'][0]
        self.assertEqual(item['id'],'operation:'+first['id'])
        self.assertEqual(item['result']['sources'][0]['description'],'Fixture protocol for tools')
        self.assertEqual(body['report']['findings'][0]['evidence_refs'],[item['id']])
        m=self.s.open_meeting(self.pid)
        snapshot=self.s.meeting(m)['snapshot']
        self.assertEqual(snapshot['artifacts'][-1]['body']['result']['meeting_evidence']['items'][0]['id'],item['id'])
        self.assertIn('operation:'+second['id'],context['allowed_evidence_refs'])
        constraints=context['execution_constraints']
        self.assertEqual(constraints['remaining_background_requests_after_report'],10)
        self.assertFalse(constraints['permissions']['local_compute'])
        self.assertIn('论文全文读取',constraints['unavailable'])
    def test_failed_model_report_still_contributes_tools_to_next_round_and_qa(self):
        provider=FixtureProvider([('search_repositories','partial'),('prepare_meeting','')]);provider.plan_failed=True
        task=self.s.claim()
        with patch('labcouncil.sources._network',return_value=(b'{"items":[]}',200)):
            with self.assertRaises(ValueError):execute(self.s,task,provider)
        self.s.fail(task,'fixture report failed');m=self.s.open_meeting(self.pid)
        new=deepcopy(self.brief);new['idea']='继续审查失败与来源'
        self.s.confirm(m,1,new['idea'],'clean',new)
        provider.plan_failed=False;_,body=self.step(provider)
        item=body['result']['meeting_evidence']['items'][0]
        self.assertEqual(item['version'],1);self.assertEqual(item['model_report_status'],'missing_or_failed')
        self.assertEqual(item['result']['status'],'completed');self.assertIsNone(item['model_summary_unverified'])
        m=self.s.open_meeting(self.pid);answer_meeting(self.s,m,'前轮工具证据在哪？',provider)
        qa_context=json.loads(provider.seen[-1][-1]['content'])
        evidence=qa_context['evidence']
        self.assertEqual(qa_context['execution_constraints']['remaining_background_requests'],10)
        self.assertIn('operation:'+task['id'],[i['id'] for i in evidence])
        self.assertEqual(self.s.meeting(m)['snapshot']['artifacts'][0]['body']['result']['meeting_evidence']['items'],[item])
    def test_fabricated_and_empty_findings_references_rejected(self):
        refs={'operation:real'}
        for report in ({},{'findings':[]},{'findings':[{'finding':'x','verification':'y','evidence_refs':['operation:fake']}]},
                       {'findings':[{'finding':'x','verification':'y','evidence_refs':[]}]}):
            with self.assertRaises(ValueError):checked_findings(report,refs,True,True)
        checked_findings({'findings':[]},refs,True,False)
        checked_findings({},refs,False,False)
    def test_no_evidence_meeting_is_explicit_and_does_not_invent_findings(self):
        _,body=self.step(FixtureProvider([('prepare_meeting','')]))
        self.assertEqual(body['result']['meeting_evidence']['items'],[])
        self.assertEqual(body['report']['findings'],[])
    def test_long_source_excerpts_are_bounded_and_prior_records_unchanged(self):
        p=self.s.project(self.pid);task=self.s.claim()
        operations=[]
        for i in range(5):
            p['tasks'].append({'id':str(i),'version':1})
            operations.append({'id':str(i),'task_id':str(i),'sha256':'a'*64,'body':{'action':'read_abstract','value':'2501.12345',
                'result':{'status':'completed','sources':[{'id':str(i),'url':'https://arxiv.org/abs/2501.12345','abstract':'内容'*20000}]}}})
        before=deepcopy(operations);materials=meeting_materials(p,task,operations)
        raw=prompt_content({'result':{'meeting_evidence':materials}})
        self.assertLessEqual(len(raw.encode()),15000)
        self.assertEqual([x['id'] for x in json.loads(raw)['result']['meeting_evidence']['items']],['operation:'+str(i) for i in range(5)])
        self.assertEqual(operations,before)

    def test_failed_final_report_qa_can_cite_original_material_operations(self):
        provider=FixtureProvider([('search_repositories','protocol'),('prepare_meeting','')])
        with patch('labcouncil.sources._network',return_value=(b'{"items":[]}',200)):
            first,_=self.step(provider)
        provider.plan_failed=True;task=self.s.claim()
        with self.assertRaises(ValueError):execute(self.s,task,provider)
        self.s.fail(task,'fixture final report failed');m=self.s.open_meeting(self.pid)
        snapshot=deepcopy(self.s.meeting(m)['snapshot'])
        provider.plan_failed=False
        answer_meeting(self.s,m,'依据在哪里？',provider)
        context=json.loads(provider.seen[-1][-1]['content'])
        self.assertIn('operation:'+first['id'],[i['id'] for i in context['evidence']])
        self.assertEqual(self.s.meeting(m)['snapshot'],snapshot)

    def test_qa_accepts_tool_operation_even_when_its_report_is_saved(self):
        provider=FixtureProvider([('prepare_meeting','')])
        task,_=self.step(provider)
        m=self.s.open_meeting(self.pid)
        before=deepcopy(self.s.meeting(m)['snapshot'])
        reference='operation:'+task['id']
        original_call=provider.call
        def cite_tool(*args,**kwargs):
            _,rid=original_call(*args,**kwargs)
            return {'content':encode({'answer':'这条工具记录已保存在快照。','evidence_refs':[reference]})},rid
        with patch.object(provider,'call',side_effect=cite_tool):
            answer=answer_meeting(self.s,m,'原始工具证据在哪？',provider)
        self.assertIn(reference,answer)
        context=json.loads(provider.seen[-1][-1]['content'])
        self.assertIn(reference,context['allowed_evidence_refs'])
        self.assertIn(reference,[e['id'] for e in context['evidence']])
        self.assertEqual(self.s.meeting(m)['snapshot'],before)
        self.assertEqual(len(self.s.meeting(m)['discussion']),1)

    def test_qa_rejects_missing_foreign_and_post_snapshot_references(self):
        provider=FixtureProvider([('search_repositories','first'),('prepare_meeting','')])
        with patch('labcouncil.sources._network',return_value=(b'{"items":[]}',200)):
            self.step(provider)
        m=self.s.open_meeting(self.pid)
        later,_=self.step(provider)
        evidence=meeting_evidence(self.s.meeting(m)['snapshot'])
        for refs in (None,[],['operation:fake'],['operation:'+later['id']]):
            with self.subTest(refs=refs),self.assertRaises(ValueError):
                format_meeting_answer({'answer':'不能用快照外的证据。','evidence_refs':refs},evidence,'codex_cli')
        self.assertNotIn('operation:'+later['id'],[e['id'] for e in evidence])
        self.assertEqual(self.s.meeting(m)['discussion'],[])
    def test_report_is_told_when_its_own_request_exhausts_budget(self):
        self.s.configure(self.pid,True,9,6)
        pid=self.s.create_project('last pair','fixture',mode='research',brief=self.brief,api_budget=2,source_budget=0)
        provider=FixtureProvider([('prepare_meeting','')])
        self.step(provider)
        context=json.loads(provider.seen[-1][-1]['content'])
        self.assertEqual(context['execution_constraints']['remaining_background_requests_after_report'],0)
        self.assertEqual(len(self.s.project(pid)['model_requests']),2)
        self.assertIsNone(self.s.claim())
