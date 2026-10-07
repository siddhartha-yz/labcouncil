"""Offline research adapters and loop boundaries, not actual-model evidence."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
from labcouncil.brief import normalize
from labcouncil.store import Store,Conflict,encode
from labcouncil.research import execute,answer_meeting
from labcouncil.sources import retrieve,fetch,validate,NoRedirect,_network


class FixtureProvider:
    def __init__(self,actions): self.actions=iter(actions);self.seen=[];self.plan_failed=False
    def call(self,store,pid,category,phase,messages,tool=None,require_tool=False,task=None,meeting_id=None):
        self.seen.append(messages)
        rid=store.reserve_request(pid,category,phase,{'fixture':True,'messages':messages},task,meeting_id)
        if require_tool:
            action,value=next(self.actions)
            args={'action':action,'value':value,'plan':'依据资源安排一个短任务，完成后查看证据。','reason':'先确认资料范围，保留来源。'}
            result={'role':'assistant','tool_calls':[{'id':'fixture','type':'function','function':{'name':'choose_research_action','arguments':encode(args)}}]}
        elif category=='qa':
            refs=[e['id'] for e in json.loads(messages[-1]['content'])['evidence']]
            result={'content':encode({'answer':'只是读取资料，尚未复現。','evidence_refs':refs})}
        else:
            if self.plan_failed: raise ValueError('fixture report failure')
            ref=json.loads(messages[-1]['content'])['evidence_ref']
            context=json.loads(messages[-1]['content'])
            findings=[{'finding':'已有工具记录可审查。','verification':'仅检查离线fixture。','evidence_refs':[i['id']]} for i in context.get('result',{}).get('meeting_evidence',{}).get('items',[])[:3]]
            result={'content':encode({'findings':findings,'summary':'已保存这一步的真实工具状态。','limitations':['读取摘要和说明不能验证作者结论。'], 'next_step':'继续核对已有证据并准备组会。','evidence_refs':[ref]})}
        store.finish_request(rid,response={'fixture':True},http_status=200)
        return result,rid


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'state.sqlite3')
        self.brief=normalize(None,'检查自动科研仓库与论文，不执行上游代码','research')
        self.brief['permissions'].update(model_calls=True,public_research=True,local_compute=False)
        self.pid=self.store.create_project('research fixture','原始目标',mode='research',budget=20,api_budget=20,qa_api_budget=1,brief=self.brief)
    def tearDown(self): self.temp.cleanup()
    def run_step(self,provider):
        task=self.store.claim();body=execute(self.store,task,provider);self.store.complete(task,body);return task
    def test_read_source_choose_next_and_stop_with_round_context(self):
        provider=FixtureProvider([('search_repositories','auto research'),('prepare_meeting',''),('prepare_meeting','')])
        raw=encode({'items':[{'full_name':'owner/research','description':'fixture'}]}).encode()
        with patch('labcouncil.sources._network',return_value=(raw,200)) as net:
            self.run_step(provider)
            p=self.store.project(self.pid);self.assertEqual(len(p['tasks']),2)
            self.assertEqual(len(p['source_requests']),1)
            self.run_step(provider);self.assertIsNone(self.store.claim());self.assertEqual(net.call_count,1)
        m=self.store.open_meeting(self.pid)
        answer_meeting(self.store,m,'复现了吗？',provider)
        with self.assertRaises(Conflict): answer_meeting(self.store,m,'再次问',provider)
        new=deepcopy(self.brief);new['idea']='沿用原证据，再检查计划'
        self.store.confirm(m,1,new['idea'],'clean',new)
        restarted=Store(self.store.database)
        self.assertEqual(len(restarted.project(self.pid)['input_history']),2)
        self.run_step(provider)
        context=json.loads(provider.seen[-2][-1]['content'])
        self.assertEqual(context['known_sources'][0]['id'],'owner/research')
        self.assertEqual(context['previous_steps'][0]['version'],1)
        self.assertEqual(context['confirmed_inputs_excerpt']['idea'],new['idea'])
        self.assertEqual(len(self.store.project(self.pid)['model_requests']),7)
    def test_duplicate_action_across_rounds_never_reexecutes(self):
        provider=FixtureProvider([('synthetic_regression','outlier')]*2)
        b=deepcopy(self.brief);b['permissions']['local_compute']=True
        m=self.store.open_meeting(self.pid);self.store.confirm(m,1,b['idea'],'outlier',b)
        self.run_step(provider);self.run_step(provider)
        p=self.store.project(self.pid);self.assertEqual(p['artifacts'][-1]['body']['result']['status'],'duplicate')
        self.assertTrue(p['artifacts'][0]['body']['result']['verification']['verified'])
        self.assertIsNone(self.store.claim())
    def test_unauthorized_model_and_source_or_compute_do_not_execute(self):
        task=self.store.claim()
        b=deepcopy(self.brief);b['permissions']['public_research']=False
        m=self.store.open_meeting(self.pid);self.store.confirm(m,1,b['idea'],'clean',b)
        with self.assertRaises(Conflict): fetch(self.store,task,'https://api.github.com/repos/a/b')
        task=self.store.claim()
        with patch('labcouncil.sources._network') as net:
            with self.assertRaises(Conflict):execute(self.store,task,FixtureProvider([('search_repositories','test')]))
            net.assert_not_called()
        self.store.fail(task,'fixture');m=self.store.open_meeting(self.pid)
        b['permissions']['model_calls']=False;self.store.confirm(m,2,b['idea'],'clean',b)
        self.assertIsNone(self.store.claim())
    def test_request_attempt_cache_error_unknown_and_hash(self):
        task=self.store.claim();url='https://api.github.com/search/repositories?q=fixture'
        err=urllib.error.HTTPError(url,429,'fixture',{},None)
        with patch('labcouncil.sources._network',side_effect=err) as net:
            one=fetch(self.store,task,url);two=fetch(self.store,task,url)
            self.assertEqual(one['status'],'error');self.assertTrue(two['cached']);self.assertEqual(net.call_count,1)
        unknown,_=self.store.reserve_source(task,'unknown','https://api.github.com/repos/a/b')
        cached=fetch(self.store,task,url);self.assertEqual(cached['http_status'],429)
        with self.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET lease_until=? WHERE id=?',(time.time()-1,task['id']))
        self.store.claim()
        self.assertEqual(self.store.source_record(unknown['id'])['status'],'unknown')
        with self.assertRaises(sqlite3.IntegrityError),self.store.connection(write=True) as con:
            con.execute("UPDATE source_requests SET body='{}' WHERE id=?",(one['id'],))
    def test_six_step_and_api_caps_enqueue_atomically(self):
        provider=FixtureProvider([('search_repositories',f'query{i}') for i in range(7)])
        with patch('labcouncil.sources._network',return_value=(b'{"items":[]}',200)):
            for _ in range(6):self.run_step(provider)
        self.assertIsNone(self.store.claim());p=self.store.project(self.pid)
        self.assertEqual(len(p['tasks']),6);self.assertEqual(len(p['model_requests']),12)
        pid=self.store.create_project('two request cap','fixture',mode='research',api_budget=2,brief=self.brief)
        with patch('labcouncil.sources._network',return_value=(b'{"items":[]}',200)):
            self.run_step(FixtureProvider([('search_repositories','one')]))
        self.assertIsNone(self.store.claim());self.assertEqual(len(self.store.project(pid)['tasks']),1)
    def test_report_failure_preserves_source_and_tool_no_recovery_calls(self):
        task=self.store.claim();provider=FixtureProvider([('search_repositories','once')]);provider.plan_failed=True
        with patch('labcouncil.sources._network',return_value=(b'{"items":[]}',200)):
            with self.assertRaises(ValueError):execute(self.store,task,provider)
        self.store.fail(task,'fixture failure');restarted=Store(self.store.database)
        self.assertEqual(len(restarted.project(self.pid)['tool_operations']),1)
        self.assertEqual(len(restarted.project(self.pid)['source_requests']),1)
        self.assertIsNone(restarted.claim())
    def test_pinned_readme_and_arxiv_abstract_format(self):
        task=self.store.claim();sha='a'*40
        replies=[encode({'private':False,'license':{'spdx_id':'MIT'}}).encode(),encode([{'sha':sha}]).encode(),
            encode({'encoding':'base64','content':base64.b64encode(b'fixture instructions').decode()}).encode()]
        with patch('labcouncil.sources._network',side_effect=[(r,200) for r in replies]) as net:
            result=retrieve(self.store,task,'inspect_repository','owner/repo')
            self.assertEqual(result['status'],'completed');self.assertEqual(result['sources'][0]['commit'],sha)
            self.assertIn('ref='+sha,net.call_args[0][0])
        atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2501.12345v2</id><title>Fixture</title><summary>Abstract only</summary></entry></feed>'
        with patch('labcouncil.sources._network',return_value=(atom,200)),patch('labcouncil.sources.time.sleep'):
            result=retrieve(self.store,task,'read_abstract','2501.12345v2')
        self.assertEqual(result['sources'][0]['kind'],'paper_abstract')
        self.assertEqual(len(result['http_requests']),1)
    def test_ssrf_path_redirect_and_source_http_cap(self):
        for action,value in [('inspect_repository','../secret'),('inspect_repository','http://127.0.0.1'),('read_abstract','../../.env')]:
            with self.assertRaises(ValueError):validate(action,value)
        with self.assertRaises(ValueError):_network('http://127.0.0.1:8765',{})
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'http://127.0.0.1'))
        task=self.store.claim()
        for i in range(24):self.store.reserve_source(task,str(i),'https://api.github.com/repos/a/b')
        with self.assertRaises(Conflict):self.store.reserve_source(task,'overflow','https://api.github.com/repos/a/b')

    def test_json_mode_missing_keyword_fails_before_any_request(self):
        from labcouncil.provider import Provider
        provider=Provider({'DEEPSEEK_API_KEY':'offline-fixture','DEEPSEEK_MODEL':'deepseek-flash'})
        task=self.store.claim()
        with patch('labcouncil.provider.urllib.request.urlopen') as net:
            with self.assertRaises(ValueError):provider.call(self.store,self.pid,'background','bad-format',[{'role':'user','content':'缺少输出格式说明'}],task=task)
            net.assert_not_called()
        self.assertEqual(self.store.project(self.pid)['model_requests'],[])

    def test_large_context_is_labelled_bounded_and_keeps_source_ids(self):
        from labcouncil.research import prompt_content
        data={'question':'问题'*1000,'sources':[{'id':str(i),'url':'https://arxiv.org/abs/2501.12345','abstract_excerpt':'内容'*10000} for i in range(18)]}
        raw=prompt_content(data)
        self.assertLessEqual(len(raw.encode()),15000)
        result=json.loads(raw)
        self.assertEqual([x['id'] for x in result['sources']],[str(i) for i in range(18)])
        self.assertIn('节选',result['context_notice'])

    def test_lease_expiry_and_new_version_fence_source_writes(self):
        task=self.store.claim();row,_=self.store.reserve_source(task,'one','https://api.github.com/repos/a/b')
        m=self.store.open_meeting(self.pid);self.store.confirm(m,1,self.brief['idea'],'clean',self.brief)
        with self.assertRaises(Conflict):self.store.reserve_source(task,'two','https://api.github.com/repos/c/d')
        self.store.fail(task,'fixture')
        new=self.store.claim();body={'kind':'research','summary':'fixture','continue_work':True}
        with self.store.connection(write=True) as con:con.execute('UPDATE tasks SET lease_until=? WHERE id=?',(time.time()-1,new['id']))
        with self.assertRaises(Conflict):self.store.complete(new,body)
        self.assertEqual(self.store.project(self.pid)['artifacts'],[])

    def test_partial_metadata_survives_commit_network_failure(self):
        task=self.store.claim()
        replies=[(b'{"private":false,"description":"fixture","license":null}',200),urllib.error.URLError(OSError('fixture'))]
        with patch('labcouncil.sources._network',side_effect=replies) as net:
            result=retrieve(self.store,task,'inspect_repository','owner/partial')
            self.assertEqual(result['status'],'error')
            self.assertEqual(result['sources'][0]['kind'],'repository_metadata')
            self.assertNotIn('commit',result['sources'][0]);self.assertEqual(net.call_count,2)
            again=retrieve(self.store,task,'inspect_repository','owner/partial')
            self.assertEqual(again['sources'],result['sources']);self.assertEqual(net.call_count,2)

    def test_meeting_freezes_orphan_tool_result_and_qa_can_cite_it(self):
        provider=FixtureProvider([('search_repositories','partial')]);provider.plan_failed=True;task=self.store.claim()
        with patch('labcouncil.sources._network',return_value=(b'{"items":[]}',200)):
            with self.assertRaises(ValueError):execute(self.store,task,provider)
        self.store.fail(task,'fixture report validation failed')
        m=self.store.open_meeting(self.pid);snapshot=self.store.meeting(m)['snapshot']
        self.assertEqual(snapshot['artifacts'],[])
        self.assertEqual(snapshot['tool_operations'][0]['task_id'],task['id'])
        self.assertEqual(len(snapshot['source_requests']),1)
        answer=answer_meeting(self.store,m,'工具证据还在吗？',provider)
        self.assertIn('operation:'+task['id'],answer)
        self.assertEqual(self.store.meeting(m)['snapshot'],snapshot)
