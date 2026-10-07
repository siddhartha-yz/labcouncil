"""Round-time budgets, confirmed inputs and continuity; no model requests."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from labcouncil.brief import normalize, round_time
from labcouncil.store import Store, Conflict
from labcouncil.worker import step



class BriefTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'state.sqlite3')
        self.brief=normalize(None,'检查初始数据','simulation')
        self.brief.update(resources='公开合成数据；本机短计算',requirements='先复算，不重复已完成实验')

    def tearDown(self):
        self.temp.cleanup()

    def project(self,brief=None,mode='simulation'):
        return self.store.create_project('输入连续性测试','原始项目目标',mode=mode,brief=brief or self.brief)

    def test_five_inputs_survive_draft_restart_and_confirmation(self):
        pid=self.project()
        while step(self.store):pass
        before=self.store.project(pid)
        m=self.store.open_meeting(pid)
        next_brief=deepcopy(self.brief)
        next_brief.update(idea='增加异常点，继续原有项目',resources='同一数据；减少本机计算',requirements='保留第一轮并解释变化')
        next_brief['work_time']={'duration_minutes':90}
        saved=self.store.save_draft(m,0,next_brief['idea'],'outlier',next_brief)
        restarted=Store(self.store.database)
        self.assertEqual(restarted.meeting(m)['draft'],saved)
        self.assertEqual(restarted.project(pid)['version'],1)
        self.assertEqual(len(restarted.project(pid)['tasks']),3)
        decision=restarted.confirm(m,1,next_brief['idea'],'outlier',next_brief)
        after=restarted.project(pid)
        self.assertEqual(after['current_inputs']['body'],next_brief)
        self.assertEqual(after['input_history'][0]['body'],self.brief)
        self.assertEqual(after['artifacts'],before['artifacts'])
        self.assertEqual(after['input_history'][0]['plan'],before['current_inputs']['plan'])
        self.assertEqual(after['idea'],'原始项目目标')
        self.assertEqual(len(after['tasks']),6)
        self.assertEqual(restarted.meeting(m)['snapshot']['inputs']['body'],self.brief)
        self.assertEqual(restarted.confirm(m,1,next_brief['idea'],'outlier',next_brief),decision)
        changed=deepcopy(next_brief);changed['resources']='另一台机器'
        with self.assertRaises(Conflict):restarted.confirm(m,1,next_brief['idea'],'outlier',changed)
        self.assertEqual(len(restarted.project(pid)['tasks']),6)
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError),restarted.connection(write=True) as con:
            con.execute("UPDATE round_inputs SET body='{}' WHERE project_id=?",(pid,))

    def test_round_budget_boundary_survives_restart_and_does_not_reset(self):
        b=deepcopy(self.brief);b['work_time']={'duration_minutes':2}
        with patch('labcouncil.store.time.time',return_value=1000):pid=self.project(b)
        inputs=self.store.project(pid)['current_inputs']
        self.assertFalse(round_time(inputs,1119)['expired'])
        self.assertTrue(round_time(inputs,1120)['expired'])
        self.assertEqual(round_time(inputs,1120)['remaining_seconds'],0)
        task=self.store.claim(now=1119)
        self.assertEqual(task['project_id'],pid)
        self.assertIsNone(self.store.claim(now=1120))
        restarted=Store(self.store.database)
        self.assertIsNone(restarted.claim(now=1121))
        p=restarted.project(pid)
        self.assertEqual(p['round_time']['deadline_at'],1120)
        self.assertEqual(p['used'],1)
        self.assertEqual(sum(t['status']=='cancelled' for t in p['tasks']),2)
        self.assertEqual(sum(e['kind']=='round_time_expired' for e in p['events']),1)

    def test_expired_round_is_not_charged_and_does_not_starve_another_project(self):
        b=deepcopy(self.brief);b['work_time']={'duration_minutes':1}
        with patch('labcouncil.store.time.time',return_value=1000):blocked=self.project(b)
        with patch('labcouncil.store.time.time',return_value=1059):permitted=self.project()
        task=self.store.claim(now=1060)
        self.assertEqual(task['project_id'],permitted)
        self.assertEqual(self.store.project(blocked)['used'],0)
        self.assertTrue(all(t['attempts']==0 for t in self.store.project(blocked)['tasks']))

    def test_started_task_can_save_after_round_deadline(self):
        b=deepcopy(self.brief);b['work_time']={'duration_minutes':1}
        with patch('labcouncil.store.time.time',return_value=1000):pid=self.project(b)
        with patch('labcouncil.store.time.time',return_value=1059):task=self.store.claim()
        from labcouncil.simulation import execute
        with patch('labcouncil.store.time.time',return_value=1061):
            self.store.complete(task,execute(self.store,task))
            self.assertIsNone(self.store.claim())
        self.assertEqual(len(self.store.project(pid)['artifacts']),1)

    def test_next_round_starts_a_new_clock_but_draft_and_pause_do_not(self):
        with patch('labcouncil.store.time.time',return_value=1000):pid=self.project()
        m=self.store.open_meeting(pid)
        before=self.store.meeting(m)['snapshot']
        self.store.configure(pid,True,9)
        self.store.save_draft(m,0,'下一轮目标','clean',dict(self.brief,idea='下一轮目标'))
        self.assertEqual(Store(self.store.database).project(pid)['round_time']['deadline_at'],8200)
        with patch('labcouncil.store.time.time',return_value=9000):
            self.store.confirm(m,1,'下一轮目标','clean')
        p=self.store.project(pid)
        self.assertEqual(p['round_time']['started_at'],9000)
        self.assertEqual(p['round_time']['deadline_at'],16200)
        self.assertEqual(self.store.meeting(m)['snapshot'],before)
        self.assertEqual(p['input_history'][0]['created'],1000)

    def test_research_step_saves_after_deadline_without_enqueuing_another_step(self):
        from tests.test_research import FixtureProvider
        from labcouncil.research import execute
        b=deepcopy(self.brief);b['work_time']={'duration_minutes':1}
        b['permissions'].update(model_calls=True,public_research=True)
        with patch('labcouncil.store.time.time',return_value=1000):
            pid=self.project(b,'research')
            task=self.store.claim()
            with patch('labcouncil.sources._network',return_value=(b'{"items":[]}',200)):
                provider=FixtureProvider([('search_repositories','fixture')])
                body=execute(self.store,task,provider)
        self.assertTrue(body['continue_work'])
        context=json.loads(provider.seen[0][-1]['content'])
        self.assertEqual(context['time_context']['remaining_seconds'],60)
        with patch('labcouncil.store.time.time',return_value=1061):
            self.store.complete(task,body)
            self.assertIsNone(self.store.claim())
        p=self.store.project(pid)
        self.assertEqual(len(p['artifacts']),1)
        self.assertEqual(len(p['tasks']),1)
        self.assertIn('工作时长已到',next(json.loads(e['body'])['reason'] for e in p['events'] if e['kind']=='research_stopped'))

    def test_legacy_daily_schedule_is_preserved_but_not_used_to_block(self):
        pid=self.project()
        old=deepcopy(self.brief)
        old['work_time']={'all_day':False,'start':'22:00','end':'02:00','timezone':'Asia/Shanghai'}
        from labcouncil.store import encode
        with self.store.connection(write=True) as con:
            con.execute('DROP TRIGGER inputs_no_update')
            con.execute('UPDATE round_inputs SET body=? WHERE project_id=?',(encode(old),pid))
        restarted=Store(self.store.database)
        p=restarted.project(pid)
        self.assertEqual(p['current_inputs']['body'],old)
        self.assertTrue(p['round_time']['legacy_default'])
        self.assertIsNotNone(restarted.claim(now=p['current_inputs']['created']+1))
        m=restarted.open_meeting(pid)
        restarted.confirm(m,1,'沿用旧资料','clean')
        self.assertEqual(restarted.project(pid)['current_inputs']['body']['work_time'],{'duration_minutes':120})
        self.assertEqual(restarted.meeting(m)['snapshot']['inputs']['body'],old)

    def test_permission_denial_stops_start_and_model_reservation(self):
        b=deepcopy(self.brief);b['permissions']['local_compute']=False
        pid=self.project(b)
        self.assertIsNone(self.store.claim())
        self.assertEqual(self.store.project(pid)['used'],0)
        real=self.project(mode='real_case') # Model permission remains explicitly false.
        self.assertIsNone(self.store.claim())
        with self.assertRaises(Conflict):self.store.reserve_request(real,'background','permission-check',{})
        self.assertEqual(self.store.project(real)['model_requests'],[])

    def test_invalid_five_inputs_create_no_partial_project(self):
        invalid=[]
        for duration in (0,-1,10081,True,'60',None,1.5):
            b=deepcopy(self.brief);b['work_time']={'duration_minutes':duration};invalid.append(b)
        b=deepcopy(self.brief);b['work_time']={'duration_minutes':60,'unexpected':True};invalid.append(b)
        b=deepcopy(self.brief);b['permissions']['model_calls']='yes';invalid.append(b)
        b=deepcopy(self.brief);b['idea']=' ';invalid.append(b)
        for b in invalid:
            with self.assertRaises(ValueError):self.project(b)
        self.assertEqual(self.store.projects(),[])

    def test_legacy_records_get_marked_defaults_without_rewriting_snapshots(self):
        pid=self.project();m=self.store.open_meeting(pid)
        snapshot=self.store.meeting(m)['snapshot']
        self.store.confirm(m,1,'历史上已确认的新目标','outlier')
        with self.store.connection(write=True) as con:
            con.execute('DROP TABLE round_inputs')
        upgraded=Store(self.store.database)
        self.assertTrue(upgraded.project(pid)['current_inputs']['legacy'])
        self.assertEqual(upgraded.project(pid)['input_history'],[])
        self.assertEqual(upgraded.project(pid)['current_inputs']['body']['idea'],'历史上已确认的新目标')
        self.assertEqual(upgraded.meeting(m)['snapshot'],snapshot)
