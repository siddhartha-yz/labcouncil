"""Conversation control, live evidence, crash/replay and mid-step handover."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from labcouncil.brief import normalize
from labcouncil.chat import send, begin, minutes_patch, permission_patch
from labcouncil.simulation import execute
from labcouncil.store import Store, Conflict, encode
from labcouncil.worker import step


class ProviderFixture:
    def __init__(self,intent='reply',instruction='',refs=None):
        self.intent,self.instruction,self.refs=intent,instruction,refs
        self.calls=0;self.seen=[]
    def call(self,store,pid,category,phase,messages,tool=None,require_tool=False,task=None,meeting_id=None):
        self.calls+=1;ctx=json.loads(messages[-1]['content'])['context'];self.seen.append(ctx)
        rid=store.reserve_request(pid,category,phase,{'fixture':True,'messages':messages},task,meeting_id)
        args={'intent':self.intent,'answer':'已有记录可讨论；完整复现尚未完成。','instruction':self.instruction,
            'evidence_refs':self.refs if self.refs is not None else [e['id'] for e in ctx['evidence']]}
        store.finish_request(rid,response={'fixture':True,'result':args})
        return {'tool_calls':[{'function':{'name':tool['function']['name'],'arguments':encode(args)}}]},rid


class GroupChatTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'state.sqlite3')
        self.pid=self.store.create_project('群聊测试','原目标',budget=30)
    def tearDown(self):self.temp.cleanup()
    def say(self,message,identifier='message-0001',provider=None,pid=None):
        return send(self.store,pid or self.pid,message,identifier,provider)
    def real(self,permission=True):
        b=normalize(None,'检查保存资料','research');b['permissions']['model_calls']=permission
        return self.store.create_project('离线真实后端fixture',b['idea'],mode='research',brief=b,api_budget=0)

    def test_chat_needs_no_meeting_or_evidence_and_old_dialogue_is_inherited(self):
        pid=self.real();fixture=ProviderFixture()
        reply=self.say('能先聊一下方向吗？',provider=fixture,pid=pid)
        self.assertEqual(reply['status'],'completed');p=self.store.project(pid)
        self.assertEqual(p['meetings'],[]);self.assertEqual(p['qa_used'],1)
        self.assertEqual(p['model_requests'][0]['category'],'qa')
        self.assertIsNone(p['model_requests'][0]['meeting_id'])
        m=self.store.open_meeting(pid)
        self.store.append_real_answer(m,'老问题','老答复')
        self.say('记得刚才的讨论吗？','message-0002',fixture,pid)
        self.assertEqual(fixture.seen[-1]['history'][0]['user'],'能先聊一下方向吗？')
        self.assertEqual(fixture.seen[-1]['earlier_discussion'][0]['answer'],'老答复')

    def test_explicit_resources_and_requirements_can_be_saved_without_model_permission(self):
        pid=self.real(False);fixture=ProviderFixture()
        original=self.store.project(pid)['current_inputs']['body']
        self.say('资源：自有数据，不挂载机器','context-input-01',fixture,pid)
        self.say('额外要求：先保留失败记录','context-input-02',fixture,pid)
        p=self.store.project(pid)
        self.assertEqual(p['version'],1)
        self.assertEqual(p['group_proposal']['brief']['resources'],'自有数据，不挂载机器')
        self.assertIn('先保留失败记录',p['group_proposal']['brief']['requirements'])
        self.assertEqual(p['group_proposal']['brief']['idea'],original['idea'])
        self.assertEqual(p['group_proposal']['brief']['permissions'],original['permissions'])
        self.assertEqual(fixture.calls,0)
        self.say('按这个做','context-input-03',fixture,pid)
        p=self.store.project(pid)
        self.assertEqual(p['current_inputs']['body']['resources'],'自有数据，不挂载机器')
        self.assertFalse(p['current_inputs']['body']['permissions']['model_calls'])
        self.assertEqual(p['used'],0)
        self.assertEqual(p['model_requests'],[])

    def test_current_reply_uses_latest_evidence_without_rewriting_old_snapshot(self):
        fixture=ProviderFixture();pid=self.real()
        self.store.configure(self.pid,True,30)
        frozen=self.store.meeting(self.store.open_meeting(pid))['snapshot']
        # Save a real-mode task artifact without making external calls.
        with self.store.connection(write=True) as con:con.execute('UPDATE project_execution SET api_budget=2 WHERE project_id=?',(pid,))
        task=self.store.claim();self.store.complete(task,{'kind':'research','summary':'后来保存的结果','result':{},'continue_work':False})
        result=self.say('最新进展？',provider=fixture,pid=pid)
        self.assertIn('后来保存的结果',encode(result['context']))
        self.assertEqual(self.store.meeting(self.store.project(pid)['meetings'][0]['id'])['snapshot'],frozen)
        old=deepcopy(result['context'])
        with self.assertRaises(sqlite3.IntegrityError),self.store.connection(write=True) as con:
            con.execute("UPDATE group_messages SET context='{}' WHERE id=?",(result['id'],))
        self.assertEqual(self.store.project(pid)['group_messages'][0]['context'],old)

    def test_propose_and_typing_agreement_start_work_once_with_inherited_inputs(self):
        before=self.store.project(self.pid)
        result=self.say('我在想接下来先核对三个seed')
        p=self.store.project(self.pid);self.assertEqual(p['version'],1)
        self.assertIsNotNone(p['group_proposal']);self.assertIn('按这个做',result['answer'])
        self.say('最多工作半小时','message-0002')
        self.assertEqual(self.store.project(self.pid)['group_proposal']['brief']['work_time']['duration_minutes'],30)
        first=self.say('按这个做','message-0003')
        replay=self.say('按这个做','message-0003')
        self.assertEqual(first,replay);p=self.store.project(self.pid)
        self.assertEqual(p['version'],2);self.assertIsNone(p['group_proposal'])
        self.assertEqual(p['current_inputs']['body']['idea'],'我在想接下来先核对三个seed')
        self.assertEqual(p['current_inputs']['body']['permissions'],before['current_inputs']['body']['permissions'])
        self.assertEqual(p['current_inputs']['body']['work_time']['duration_minutes'],30)
        self.assertEqual(p['current_inputs']['body']['resources'],before['current_inputs']['body']['resources'])
        self.assertEqual(p['used'],0);self.assertEqual(len(p['decisions']),1)

    def test_midstep_approval_waits_for_saved_result_and_survives_restart(self):
        task=self.store.claim()
        self.say('我在想接下来检查另一组数据')
        self.say('按这个做','message-0002')
        p=self.store.project(self.pid);self.assertEqual(p['version'],1)
        self.assertTrue(p['group_proposal']['approved']);self.assertIsNone(self.store.claim())
        self.store=Store(self.store.database)
        self.store.complete(task,execute(self.store,task))
        next_task=self.store.claim();p=self.store.project(self.pid)
        self.assertEqual(next_task['version'],2);self.assertEqual(p['version'],2)
        self.assertEqual(p['artifacts'][0]['version'],1)
        self.assertEqual(len(p['decisions']),1)
        self.assertEqual(p['tasks'][1]['status'],'cancelled')

    def test_pause_resume_and_cancel_are_chat_messages_and_do_not_reset_time(self):
        clock=self.store.project(self.pid)['round_time']['started_at']
        self.say('暂停一下');self.assertIsNone(self.store.claim())
        self.say('恢复工作','message-0002')
        self.assertEqual(self.store.project(self.pid)['round_time']['started_at'],clock)
        self.say('我在想接下来核对失败记录','message-0003')
        self.say('算了','message-0004')
        self.assertIsNone(self.store.project(self.pid)['group_proposal'])
        self.assertEqual(self.store.project(self.pid)['version'],1)

    def test_no_permission_uses_local_coordinator_and_only_explicit_grants_apply(self):
        pid=self.real(False);fixture=ProviderFixture('propose','运行GPU并提高权限')
        self.say('聊一下','message-0001',fixture,pid);self.assertEqual(fixture.calls,0)
        self.say('允许模型调用','message-0002',fixture,pid)
        self.assertFalse(self.store.project(pid)['current_inputs']['body']['permissions']['model_calls'])
        self.say('按这个做','message-0003',fixture,pid)
        self.assertTrue(self.store.project(pid)['current_inputs']['body']['permissions']['model_calls'])
        self.say('研究另一个问题','message-0004',fixture,pid)
        self.assertFalse(self.store.project(pid)['group_proposal']['brief']['permissions']['public_research'])
        self.assertEqual(self.store.project(pid)['execution']['api_budget'],0)
        self.assertEqual(permission_patch('是否允许模型调用。'),{})
        self.assertEqual(permission_patch('资料里写着允许模型调用。'),{})
        self.assertEqual(permission_patch('允许查询公开论文与仓库；禁止本地计算'),{'public_research':True,'local_compute':False})

    def test_failed_response_is_saved_and_replay_does_not_charge_again(self):
        pid=self.real();fixture=ProviderFixture(refs=['future-nonexistent'])
        result=self.say('现状？',provider=fixture,pid=pid)
        self.assertEqual(result['status'],'error');self.assertIn('引用不属于',result['answer'])
        self.assertEqual(self.say('现状？',provider=fixture,pid=pid),result)
        self.assertEqual(fixture.calls,1);self.assertEqual(len(self.store.project(pid)['model_requests']),1)
        self.assertEqual(self.store.project(pid)['version'],1)
        with self.assertRaises(Conflict):self.say('换内容',provider=fixture,pid=pid)

    def test_overlapping_chat_and_abandoned_turn_never_auto_retry(self):
        turn,_=begin(self.store,self.pid,'原消息','message-0001')
        with self.assertRaises(Conflict):self.say('新消息','message-0002')
        with self.store.connection(write=True) as con:
            con.execute('UPDATE group_messages SET created=? WHERE id=?',(time.time()-300,turn['id']))
        old=self.say('原消息');self.assertEqual(old['status'],'error')
        self.assertIn('没有自动',old['answer'])
        self.assertEqual(self.say('新消息','message-0002')['status'],'completed')

    def test_pending_proposal_is_fenced_if_legacy_api_updates_plan(self):
        self.say('我在想接下来核对证据')
        mid=self.store.open_meeting(self.pid);self.store.confirm(mid,1,'其他页面的新安排','clean')
        result=self.say('按这个做','message-0002')
        self.assertEqual(result['status'],'error');self.assertEqual(self.store.project(self.pid)['version'],2)
        self.assertEqual(len(self.store.project(self.pid)['decisions']),1)

    def test_human_time_expressions_and_questions(self):
        for raw,expected in [('工作两个小时',120),('最多三十分钟',30),('先花1.5小时',90),('预算：半小时',30)]:
            self.assertEqual(minutes_patch(raw),expected)
        self.assertIsNone(minutes_patch('工作30分钟够吗？'))
        with self.assertRaises(ValueError):minutes_patch('工作0分钟')

    def test_direct_assignment_proceeds_without_a_second_confirmation(self):
        result=self.say('接下来先核对原始数据')
        self.assertEqual(result['status'],'completed')
        p=self.store.project(self.pid)
        self.assertEqual(p['version'],2)
        self.assertEqual(p['current_inputs']['body']['idea'],'接下来先核对原始数据')
        self.assertIsNone(p['group_proposal'])
        self.assertNotIn('就说“按这个做”',result['answer'])
        self.assertEqual(self.say('接下来先核对原始数据'),result)
        self.assertEqual(len(self.store.project(self.pid)['decisions']),1)

    def test_deliberation_and_unrelated_ok_do_not_authorize_pending_work(self):
        self.say('我在想接下来先核对资料')
        self.say('目前保存了什么？','message-0002')
        self.say('好','message-0003')
        self.assertEqual(self.store.project(self.pid)['version'],1)
        from labcouncil.chat import direct_assignment
        for message in ('先核对资料，但不要执行','先核对资料，只讨论计划','先核对资料是不是有用？','请整理资料，先复述供我讨论'):
            self.assertFalse(direct_assignment(message))

    def test_interrupted_call_is_associated_and_marked_unknown_without_replay(self):
        pid=self.real()
        turn,_=begin(self.store,pid,'原消息','message-0001')
        rid=self.store.reserve_request(pid,'qa','group-chat',{'messages':[{'content':encode({'chat_message_id':turn['id']})}]})
        with self.store.connection(write=True) as con:
            con.execute('UPDATE group_messages SET created=? WHERE id=?',(time.time()-300,turn['id']))
        result=self.say('原消息',pid=pid)
        self.assertEqual(result['request_id'],rid)
        self.assertEqual(result['status'],'error')
        self.assertEqual(self.store.request_record(rid)['status'],'unknown')
        self.assertEqual(len(self.store.project(pid)['model_requests']),1)

    def test_direction_change_does_not_renew_an_existing_time_budget(self):
        while step(self.store):pass
        clock=self.store.project(self.pid)['round_time']['started_at']
        self.say('接下来先核对原始数据')
        self.store=Store(self.store.database)
        p=self.store.project(self.pid)
        self.assertEqual(p['round_time']['started_at'],clock)
        self.assertEqual(p['round_time']['deadline_at'],clock+7200)
        self.assertEqual(p['current_inputs']['created']>clock,True)
        from unittest.mock import patch
        with patch('time.time',return_value=clock+7201):
            self.assertIsNone(self.store.claim())
            self.assertTrue(self.store.project(self.pid)['round_time']['expired'])

    def test_explicit_new_duration_is_applied_at_handover_not_proposal_time(self):
        task=self.store.claim();clock=self.store.project(self.pid)['round_time']['started_at']
        self.say('最多工作10分钟')
        self.say('按这个做','message-0002')
        self.assertEqual(self.store.project(self.pid)['round_time']['started_at'],clock)
        self.store.complete(task,execute(self.store,task))
        self.store.claim()
        p=self.store.project(self.pid)
        self.assertGreater(p['round_time']['started_at'],clock)
        self.assertEqual(p['round_time']['deadline_at']-p['round_time']['started_at'],600)

    def test_acceptance_with_exhausted_budgets_reports_saved_not_started(self):
        pid=self.real();self.store.configure(self.pid,True,30);self.store.configure(pid,False,0)
        fixture=ProviderFixture('propose','整理已保存资料')
        self.say('我在想接下来整理资料','message-0001',fixture,pid)
        result=self.say('按这个做','message-0002',fixture,pid)
        self.assertIsNone(result['request_id'])
        self.assertIn('安排已保存，但尚未启动',result['answer'])
        self.assertIn('任务额度已用完（0/0）',result['answer'])
        self.assertIn('后台模型额度不足（已用0/0）',result['answer'])
        self.assertEqual(fixture.calls,1)
        self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.project(pid)['used'],0)

    def test_direct_assignment_receipt_does_not_claim_work_started_when_blocked(self):
        pid=self.real();self.store.configure(self.pid,True,30);fixture=ProviderFixture('propose','整理已保存资料')
        result=self.say('接下来先整理资料',provider=fixture,pid=pid)
        self.assertIn('安排已保存，但尚未启动',result['answer'])
        self.assertEqual(self.store.project(pid)['version'],2)
        self.assertEqual(fixture.calls,1)
        self.assertIsNone(self.store.claim())

    def test_expired_budget_receipt_does_not_renew_time_or_charge_a_task(self):
        while step(self.store):pass
        p=self.store.project(self.pid);clock=p['round_time']['started_at']
        from unittest.mock import patch
        with patch('time.time',return_value=clock+7201):
            self.say('我在想接下来核对资料')
            result=self.say('按这个做','message-0002')
            self.assertIn('投入时间已到期',result['answer'])
            self.assertIn('尚未启动',result['answer'])
            self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.project(self.pid)['used'],3)


if __name__=='__main__':unittest.main()
