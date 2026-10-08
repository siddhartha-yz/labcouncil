"""Contrasting everyday phrases and effective controls, separate from novice scores."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from labcouncil.brief import normalize
from labcouncil.chat import send, begin, finish, permission_patch
from labcouncil.conversation import control_intent, resources, preferences
from labcouncil.store import Store, Conflict

class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'state.sqlite3')
        b=normalize(None,'检查数据','research');b['permissions'].update(model_calls=True,public_research=True,local_compute=True)
        self.pid=self.store.create_project('对照','检查数据',mode='research',brief=b)
    def tearDown(self):self.tmp.cleanup()
    def test_commands_and_contrasting_non_commands(self):
        for text in ['稍等，先别干活','别忙了，等我回来再弄','先不要工作']:
            self.assertEqual(control_intent(text),'pause')
        for text in ['暂停以后怎么恢复？','如果先停一下会怎样','教程说“先停一下”','不要暂停','别取消','不要撤回']:
            self.assertIsNone(control_intent(text))
        self.assertEqual(control_intent('不要再扣费了'),'stop_spending')
    def test_permission_questions_do_not_grant(self):
        for text in ['可不可以上网找资料？','如果允许调用模型','教程写着“允许模型调用”']:
            self.assertEqual(permission_patch(text),{})
        self.assertFalse(permission_patch('不要上网查公开资料了')['public_research'])
    def test_candidate_preferences_can_include_polite_question(self):
        self.assertTrue(preferences('能不能写简单点，缩写解释一下？'))
        self.assertFalse(preferences('教程写着“报告写简单点”'))
        self.assertIn('旧电脑',resources('我只剩一台旧电脑和两百行表格'))
    def test_withdrawal_is_effective_and_durable_without_rewriting_inputs(self):
        before=deepcopy(self.store.project(self.pid)['input_history'])
        reply=send(self.store,self.pid,'不要上网查公开资料了','withdrawal-0001')
        self.assertEqual(reply['status'],'completed')
        p=Store(Path(self.tmp.name)/'state.sqlite3').project(self.pid)
        self.assertFalse(p['current_inputs']['body']['permissions']['public_research'])
        self.assertEqual(p['input_history'],before)
        task=self.store.claim()
        with self.assertRaises(Conflict):self.store.reserve_source(task,'contrast-source','https://example.com')
    def test_stop_spending_blocks_new_reservations(self):
        send(self.store,self.pid,'不要再扣费了','withdrawal-0002')
        with self.assertRaises(Conflict):self.store.reserve_request(self.pid,'background','plan',{})
        self.assertTrue(self.store.project(self.pid)['paused'])
        self.assertEqual(self.store.project(self.pid)['model_requests'],[])
    def test_urgent_stop_fences_an_older_in_flight_proposal(self):
        turn,_=begin(self.store,self.pid,'检查一下数据','older-message-01')
        send(self.store,self.pid,'先停一下','urgent-stop-01')
        b=deepcopy(turn['context']['inputs'])
        with self.assertRaises(Conflict):finish(self.store,'older-message-01','旧答复',brief=b,start_work=True)
        self.assertTrue(self.store.project(self.pid)['paused'])
    def test_new_goal_does_not_reset_the_unused_clock(self):
        pid=self.store.create_project('模拟','检查数据')
        before=self.store.project(pid)['round_time']['deadline_at']
        send(self.store,pid,'先核对保存的数据','new-goal-0001')
        self.assertEqual(self.store.project(pid)['round_time']['deadline_at'],before)
    def test_withdrawal_and_new_time_keep_both_intents(self):
        send(self.store,self.pid,'禁止本地计算。投入60分钟。','replacement-01')
        p=self.store.project(self.pid)
        self.assertFalse(p['current_inputs']['body']['permissions']['local_compute'])
        self.assertEqual(p['group_proposal']['brief']['work_time']['duration_minutes'],60)
        self.assertFalse(p['group_proposal']['approved'])

if __name__=='__main__':unittest.main()
