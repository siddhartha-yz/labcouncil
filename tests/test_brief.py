"""Research inputs, daily windows and context continuity; no model requests."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from labcouncil.brief import normalize, in_work_time
from labcouncil.store import Store, Conflict
from labcouncil.worker import step


def timestamp(raw):
    return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc).timestamp()


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
        next_brief['work_time'].update(all_day=False,start='22:00',end='02:00')
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

    def test_daily_window_and_overnight_use_explicit_timezone(self):
        b=deepcopy(self.brief);b['work_time'].update(all_day=False,start='09:00',end='18:00')
        self.assertFalse(in_work_time(b,timestamp('2026-10-06T00:59:00')))
        self.assertTrue(in_work_time(b,timestamp('2026-10-06T01:00:00')))
        self.assertFalse(in_work_time(b,timestamp('2026-10-06T10:00:00')))
        b['work_time'].update(start='22:00',end='02:00')
        self.assertTrue(in_work_time(b,timestamp('2026-10-06T15:00:00')))
        self.assertTrue(in_work_time(b,timestamp('2026-10-06T17:00:00')))
        self.assertFalse(in_work_time(b,timestamp('2026-10-06T18:00:00')))

    def test_outside_window_not_charged_and_does_not_starve_another_project(self):
        b=deepcopy(self.brief);b['work_time'].update(all_day=False,start='09:00',end='18:00')
        blocked=self.project(b)
        permitted=self.project()
        now=timestamp('2026-10-06T10:00:00')
        task=self.store.claim(now=now)
        self.assertEqual(task['project_id'],permitted)
        self.assertEqual(self.store.project(blocked)['used'],0)
        self.assertTrue(all(t['attempts']==0 for t in self.store.project(blocked)['tasks']))

    def test_started_task_can_finish_after_daily_window(self):
        b=deepcopy(self.brief);b['work_time'].update(all_day=False,start='09:00',end='18:00')
        pid=self.project(b)
        with patch('labcouncil.store.time.time',return_value=timestamp('2026-10-06T09:59:59')):
            task=self.store.claim()
        from labcouncil.simulation import execute
        with patch('labcouncil.store.time.time',return_value=timestamp('2026-10-06T10:00:01')):
            self.store.complete(task,execute(self.store,task))
            self.assertIsNone(self.store.claim())
        self.assertEqual(len(self.store.project(pid)['artifacts']),1)

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
        for start,end in (('25:00','18:00'),('09:00','09:00')):
            b=deepcopy(self.brief);b['work_time'].update(all_day=False,start=start,end=end);invalid.append(b)
        b=deepcopy(self.brief);b['work_time']['timezone']='invalid/timezone';invalid.append(b)
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
