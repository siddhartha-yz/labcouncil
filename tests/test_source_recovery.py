"""Offline failure/review/quota boundaries; not evidence of network reliability."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
import ssl
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
from labcouncil.brief import normalize
from labcouncil.sources import fetch,retrieve
from labcouncil.store import Store,Conflict
from tests.test_research import FixtureProvider
from labcouncil.research import execute

URL='https://api.github.com/search/repositories?q=recovery'

def eof(): return urllib.error.URLError(ssl.SSLEOFError(8,'fixture unexpected EOF'))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'state.sqlite3';self.store=Store(self.db)
        self.brief=normalize(None,'检查公开资料','research')
        self.brief['permissions'].update(public_research=True,retry_public_reads=True)
        self.pid=self.store.create_project('恢复边界','fixture',mode='research',brief=self.brief,source_budget=4)
        self.task=self.store.claim()
    def tearDown(self):self.tmp.cleanup()
    def test_connection_failure_then_success_records_each_attempt_and_reuses_cache(self):
        with patch('labcouncil.sources._network',side_effect=[eof(),(b'{"items":[]}',200)]) as net,patch('labcouncil.sources.time.sleep'):
            result=fetch(self.store,self.task,URL)
            self.assertEqual(result['status'],'completed');self.assertEqual(len(result['attempt_records']),2)
            self.store.fail(self.task,'fixture');m=self.store.open_meeting(self.pid)
            disabled=deepcopy(self.brief);disabled['permissions']['retry_public_reads']=False
            self.store.confirm(m,1,disabled['idea'],'clean',disabled)
            again=fetch(Store(self.db),self.store.claim(),URL)
            self.assertTrue(again['cached']);self.assertEqual(net.call_count,2)
        rows=self.store.project(self.pid)['source_requests']
        self.assertEqual([r['attempt_number'] for r in rows],[1,2])
        self.assertEqual([r['status'] for r in rows],['error','completed'])
        self.assertTrue(all(r['transport']=='urllib' for r in rows))
    def test_three_failures_are_per_project_not_per_round(self):
        with patch('labcouncil.sources._network',side_effect=eof()) as net,patch('labcouncil.sources.time.sleep'):
            fetch(self.store,self.task,URL)
            self.store.fail(self.task,'fixture');m=self.store.open_meeting(self.pid)
            self.store.confirm(m,1,self.brief['idea'],'clean',self.brief);task=self.store.claim()
            fetch(self.store,task,URL)
            self.assertEqual(net.call_count,3)
        self.assertEqual(len(self.store.project(self.pid)['source_requests']),3)
    def test_unknown_certificate_and_http_error_are_not_retried(self):
        fingerprint=hashlib.sha256(URL.encode()).hexdigest()
        self.store.reserve_source(self.task,fingerprint,URL)
        with patch('labcouncil.sources._network') as net:
            self.assertEqual(fetch(self.store,self.task,URL)['status'],'started');net.assert_not_called()
        failures=[urllib.error.URLError(ssl.SSLCertVerificationError(1,'fixture')),urllib.error.HTTPError(URL,429,'fixture',{},None)]
        for i,error in enumerate(failures):
            with patch('labcouncil.sources._network',side_effect=error) as net:
                fetch(self.store,self.task,URL+'&case='+str(i));self.assertEqual(net.call_count,1)
    def test_quota_exhaustion_during_retries_preserves_partial_evidence(self):
        # One slot remains; a retry must not make a fifth request.
        for i in range(3): self.store.reserve_source(self.task,str(i),'https://api.github.com/repos/a/b')
        with patch('labcouncil.sources._network',side_effect=eof()) as net,patch('labcouncil.sources.time.sleep'):
            result=retrieve(self.store,self.task,'search_repositories','recovery')
            self.assertEqual(net.call_count,1);self.assertEqual(result['status'],'error')
            self.assertEqual(len(result['http_requests']),1)
        self.assertEqual(len(self.store.project(self.pid)['source_requests']),4)
    def test_new_version_fences_retry_after_first_failure(self):
        def network(*args):
            m=self.store.open_meeting(self.pid);self.store.confirm(m,1,self.brief['idea'],'clean',self.brief)
            raise eof()
        with patch('labcouncil.sources._network',side_effect=network) as net,patch('labcouncil.sources.time.sleep'):
            result=fetch(self.store,self.task,URL)
            self.assertEqual(net.call_count,1);self.assertTrue(result['retry_stopped'])
        self.assertEqual(len(self.store.project(self.pid)['source_requests']),1)
    def test_review_enables_failed_operation_retry_but_same_round_duplicate_stops(self):
        # Old permissions do not authorize retries; a later explicit review does.
        self.store.fail(self.task,'fixture');m=self.store.open_meeting(self.pid)
        old=deepcopy(self.brief);old['permissions'].pop('retry_public_reads')
        self.store.confirm(m,1,old['idea'],'clean',old)
        task=self.store.claim();provider=FixtureProvider([('search_repositories','recovery')]*3)
        with patch('labcouncil.sources._network',side_effect=eof()) as net:
            body=execute(self.store,task,provider);self.store.complete(task,body);self.assertEqual(net.call_count,1)
        m=self.store.open_meeting(self.pid);self.store.confirm(m,2,self.brief['idea'],'clean',self.brief)
        with patch('labcouncil.sources._network',return_value=(b'{"items":[]}',200)) as net,patch('labcouncil.sources.time.sleep'):
            task=self.store.claim();body=execute(self.store,task,provider);self.store.complete(task,body)
            self.assertEqual(body['result']['status'],'completed');self.assertEqual(net.call_count,1)
            task=self.store.claim();body=execute(self.store,task,provider);self.store.complete(task,body)
            self.assertEqual(body['result']['status'],'duplicate');self.assertEqual(net.call_count,1)
    def test_legacy_execution_migration_preserves_model_caps(self):
        with self.store.connection(write=True) as con:
            con.execute('ALTER TABLE project_execution DROP COLUMN source_budget')
        migrated=Store(self.db).project(self.pid)['execution']
        self.assertEqual(migrated['source_budget'],24);self.assertEqual(migrated['api_budget'],18)
        self.assertEqual(migrated['qa_api_budget'],3)
    def test_invalid_http_caps_rejected_and_zero_cap_blocks_network(self):
        for cap in (-1,25,True):
            with self.assertRaises(ValueError):self.store.create_project('bad','fixture',source_budget=cap)
        pid=self.store.create_project('zero','fixture',mode='research',brief=self.brief,source_budget=0)
        self.store.fail(self.task,'fixture');task=self.store.claim()
        self.assertEqual(task['project_id'],pid)
        with patch('labcouncil.sources._network') as net:
            with self.assertRaises(Conflict):fetch(self.store,task,URL)
            net.assert_not_called()
