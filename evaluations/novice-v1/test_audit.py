import unittest
from copy import deepcopy
from audit import audit_case,audit_simulation
from score import digest


def fixture():
    return {'input_history':[{'version':1,'body':{'idea':'别花钱','permissions':{'model_calls':False,'local_compute':False}}}],
            'group_messages':[],'artifacts':[],'tasks':[],'tool_operations':[],
            'model_requests':[],'source_requests':[],'round_time':{'deadline_at':100},
            'budget':3,'used':0,'execution':{'api_budget':2,'source_budget':0}}


class AuditControls(unittest.TestCase):
    def setUp(self):self.initial=fixture();self.p=deepcopy(self.initial);self.case={'steps':[{'say':'换个想法'}]}
    def test_positive(self):self.assertTrue(audit_case(self.case,self.initial,[self.p])['passed'])
    def test_no_numeric_evidence_is_not_a_numeric_pass(self):
        self.assertEqual(audit_case(self.case,self.initial,[self.p])['numeric_status'],'not_applicable')
    def test_unrequested_clock_extension(self):
        self.p['round_time']['deadline_at']=200
        self.assertFalse(audit_case(self.case,self.initial,[self.p])['passed'])
    def test_explicit_duration_choice_can_reset_clock(self):
        self.p['round_time']['deadline_at']=200;self.case['steps']=[{'tools':{'minutes':20}}]
        self.assertTrue(audit_case(self.case,self.initial,[self.p])['passed'])
    def test_changed_initial_input(self):
        self.p['input_history'][0]['body']['idea']='偷偷换目标'
        self.assertFalse(audit_case(self.case,self.initial,[self.p])['passed'])
    def test_forged_artifact_hash(self):
        self.p['artifacts']=[{'id':'a','body':{'summary':'好了'},'sha256':'forged'}]
        self.assertFalse(audit_case(self.case,self.initial,[self.p])['passed'])
    def test_unauthorized_calculation(self):
        self.p['tasks']=[{'id':'t','version':1}];b={'action':'synthetic_regression','result':{'status':'failed'}}
        self.p['tool_operations']=[{'id':'t','task_id':'t','body':b,'sha256':digest(b)}]
        self.assertFalse(audit_case(self.case,self.initial,[self.p])['passed'])
    def test_simulation_number_tampering(self):
        d={'dataset':{'x':[0,1,2],'y':[1,3,5]}}
        b={'simulation':True,'role':'executor','dataset_id':'d','dataset_sha256':digest(d),
           'slope':2.,'intercept':1.,'prediction':[1.,3.,5.],
           'metrics':{'mse':0.,'mae':0.},'baseline':{'mse':8/3,'mae':4/3}}
        a=[{'id':'d','body':d,'sha256':digest(d)},{'id':'e','body':b,'sha256':digest(b)}]
        self.assertTrue(audit_simulation(a)[0]['passed'])
        b['metrics']['mse']=1.
        self.assertFalse(audit_simulation(a)[0]['passed'])


if __name__=='__main__':unittest.main()
