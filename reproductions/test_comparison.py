"""Check that report scoring cannot credit forged evidence or verification."""
import copy
import tempfile
import unittest
from pathlib import Path
from check_comparison import check_report
from check_deepseek_workflow import run_experiment,verify_artifact

class EvidenceScoring(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        artifact,manifest=run_experiment(self.root,'evidence-1',{
            'task_version':1,'seeds':[7,19,31],'outlier_fraction':0.1,
            'metrics':['mse','mae','median_absolute_error']})
        verify_artifact(self.root,artifact,manifest)
        self.state={'artifacts':[artifact],'verified':['evidence-1']}
        self.report={'evidence_refs':['evidence-1'],'observations':[
            {'seed':r['seed'],'metric':metric,**values} for r in artifact['results'] for metric,values in r['metrics'].items()],
            'conclusion':'Bounded observed result only.','limitations':['Synthetic data.'],'verification_refs':['evidence-1']}
    def test_valid_evidence_and_complete_coverage(self):
        self.assertTrue(all(check_report(self.report,self.state).values()))
    def test_forged_verification_not_credited(self):
        self.state['verified']=[]
        checks=check_report(self.report,self.state)
        self.assertTrue(checks['numeric_and_refs_valid'])
        self.assertFalse(checks['verification_claim_supported'])
    def test_stale_baseline_and_bool_rejected(self):
        for value in (12.888358499556563, True):
            with self.subTest(value=value):
                report=copy.deepcopy(self.report);report['observations'][0]['baseline']=value
                self.assertFalse(check_report(report,self.state)['numeric_and_refs_valid'])
    def test_missing_seeds_cannot_pass_coverage(self):
        self.report['observations']=[r for r in self.report['observations'] if r['seed']==7]
        checks=check_report(self.report,self.state)
        self.assertTrue(checks['numeric_and_refs_valid'])
        self.assertFalse(checks['three_seeds']);self.assertFalse(checks['three_metrics_each_seed'])
if __name__=='__main__':unittest.main()
