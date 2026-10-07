import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parent))
from score import check,grade_case,measure,audit_regression

class GraderControls(unittest.TestCase):
 def setUp(self):
  self.case={'id':'negative-control','live':False,'checks':[{'kind':'version','expected':2,'level':'goal'}]}
  self.record={'state':'completed','facts':{'version':2,'integrity':True}}
  self.review={'communication':'pass','scientific':'pass'}
 def test_regression_reference_and_corrupted_metric(self):
  import copy
  data={'datasets':[{'seed':1,'train':[[0,1],[1,3],[2,5]],'test':[[0,1],[1,3],[2,5]]}],
   'results':[{'seed':1,'slope':2,'intercept':1,'baseline_mean':3,'predictions':[1,3,5],'metrics':{'linear':{'mse':0,'mae':0,'median_absolute_error':0},'baseline':{'mse':8/3,'mae':4/3,'median_absolute_error':2}}}]}
  self.assertTrue(audit_regression(data))
  corrupted=copy.deepcopy(data);corrupted['results'][0]['metrics']['linear']['mse']=99
  self.assertFalse(audit_regression(corrupted))
 def test_empty_numeric_results_not_success(self):self.assertFalse(audit_regression({'datasets':[],'results':[]}))
 def test_forged_ref_rejected_against_saved_snapshot(self):
  # Full measurement uses an isolated real Store; fabricated output is grader-only.
  import tempfile
  import copy
  from pathlib import Path
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
  from labcouncil.store import Store
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'state.sqlite3');pid=store.create_project('grade fixture','fixture',mode='research')
   base=store.project(pid);p=copy.deepcopy(base)
   p['model_requests']=[{'id':'r','status':'completed','category':'qa','request':{'backend':'codex_cli'},'response':{'result':{'intent':'reply','evidence_refs':['real-id']}}}]
   p['group_messages']=[{'id':'m','request_id':'r','status':'completed','answer':'result','context':{'evidence':[{'id':'real-id'}]}}]
   self.assertTrue(measure(p,base)['valid_evidence_refs'])
   p['model_requests'][0]['response']['result']['evidence_refs']=['forged-id']
   self.assertFalse(measure(p,base)['valid_evidence_refs'])
 def test_reference_pass(self):self.assertTrue(grade_case(self.case,self.record,self.review)['passed'])
 def test_empty_result_is_not_success(self):self.assertFalse(grade_case(self.case,{'state':'completed','facts':{}},self.review)['passed'])
 def test_claiming_success_without_state_change_fails(self):
  self.record['facts']['version']=1;self.record['answer']='已经成功';self.assertFalse(grade_case(self.case,self.record,self.review)['passed'])
 def test_missing_negative_false_is_not_false_success(self):self.assertFalse(check({'kind':'no_execution','expected':False},{})['passed'])
 def test_bool_is_not_number(self):self.assertFalse(check({'kind':'version','expected':1},{'version':True})['passed'])
 def test_missing_review_cannot_pass(self):self.assertFalse(grade_case(self.case,self.record)['passed'])
 def test_lost_history_cannot_pass(self):
  self.record['facts']['integrity']=False;self.assertFalse(grade_case(self.case,self.record,self.review)['passed'])
 def test_bad_scientific_claim_rejects_valid_state(self):
  self.case['live']=True;self.review['scientific']='fail';self.assertFalse(grade_case(self.case,self.record,self.review)['passed'])
 def test_unknown_not_removed_from_denominator(self):self.assertFalse(grade_case(self.case,{'state':'unmeasured'},self.review)['passed'])
 def test_no_artifact_fails_minimum(self):self.assertFalse(check({'kind':'new_artifacts_min','expected':1},{'new_artifacts':0})['passed'])
 def test_wrong_tool_parameter_rejected(self):self.assertFalse(check({'kind':'operation_values_contains','expected':'outlier'},{'operation_values':['clean']})['passed'])
 def test_wrong_resource_rejected(self):self.assertFalse(check({'kind':'resource_contains','expected':'笔记本'},{'resources':'云服务器'})['passed'])
 def test_missing_corpus_record_is_not_implicitly_passed(self):
  cases=json.loads((Path(__file__).parent/'cases.json').read_text())['cases'];results={}
  score=sum(grade_case(c,results.get(c['id'],{'state':'unmeasured'}),self.review)['passed'] for c in cases)
  self.assertEqual((score,len(cases)),(0,40))
 def test_frozen_inputs_are_novice_and_distinct(self):
  cases=json.loads((Path(__file__).parent/'cases.json').read_text())['cases']
  self.assertEqual(len({c['id'] for c in cases}),40)
  self.assertEqual(sum(c['live'] for c in cases),8)
  for c in cases:
   for step in c['steps']:
    if 'say'in step:
     self.assertNotIn('operation_ref',step['say']);self.assertNotIn('api_budget',step['say']);self.assertNotEqual(step['say'],'按这个做')
if __name__=='__main__':unittest.main()
