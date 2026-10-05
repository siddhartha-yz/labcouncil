#!/usr/bin/env python3
"""Actual pinned individual meeting, critic, saved-summary follow-up."""
import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from check_deepseek_connectivity import load_config, redact
from check_virtual_lab_meeting import COMMIT, RecordedCompletions, digest, save, source_hashes


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream',type=Path,required=True)
    p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();root=args.upstream.resolve();out=args.output.resolve()
    assert subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()==COMMIT
    assert subprocess.run(['git','-C',str(root),'diff','--quiet','HEAD','--','src']).returncode==0
    config=load_config(Path('.env'));assert config['DEEPSEEK_MODEL']=='deepseek-flash'
    out.mkdir(parents=True,exist_ok=False)
    hashes=source_hashes(root);record={'upstream_commit':COMMIT,'source_before':hashes,
        'script_sha256':digest(Path(__file__)),'evidence_sha256':digest(args.evidence),
        'human_confirmed':False,'request_limit':4,'status':'started'}
    save(out/'metadata.json',record)
    os.environ['TIKTOKEN_CACHE_DIR']='/tmp/labcouncil-tiktoken-cache'
    sys.path.insert(0,str(root/'src'))
    from openai import OpenAI, NOT_GIVEN
    from virtual_lab import Agent
    from virtual_lab.utils import load_summaries
    module=importlib.import_module('virtual_lab.run_meeting')
    critic=module.SCIENTIFIC_CRITIC
    module.SCIENTIFIC_CRITIC=Agent(critic.title,critic.expertise,critic.goal,critic.role,'deepseek-flash')
    client=OpenAI(api_key=config['DEEPSEEK_API_KEY'],base_url='https://api.deepseek.com',timeout=45,max_retries=0)
    recorder=RecordedCompletions(client,out,config['DEEPSEEK_API_KEY'],NOT_GIVEN)
    module.OpenAI=lambda:SimpleNamespace(chat=SimpleNamespace(completions=recorder))
    agent=Agent('Researcher','regression validation','preserve evidence and critique provenance','revise a bounded validation plan','deepseek-flash')
    evidence=json.loads(args.evidence.read_text());critique='SOURCE_CRITIQUE_SEED7'
    context=(f'Source artifact {args.evidence}; SHA256 {digest(args.evidence)}. '
             f'Source-specific critique {critique}: one clean seed=7 MSE does not establish robustness across seeds or outliers. '
             'Future trials are planned, not executed. Recorded evidence: '+json.dumps(evidence))
    rules=('Keep under 180 words. Preserve source ID SOURCE_CRITIQUE_SEED7 in the final summary and next meeting. '
           'Explicitly label seeds 7,19,31 with outliers as planned, not executed. Preserve the observed MSE values. '
           'Use the upstream Markdown summary format. Do not claim human approval or new experimental results.',)
    try:
        summaries=()
        for number in (1,2):
            name=f'individual-{number}';recorder.meeting=name
            agenda=('Critically assess the recorded evidence and specify the next validation plan.' if number==1 else
                    'Carry forward the source critique and unexecuted validation plan from the saved previous summary.')
            inputs={'agenda':agenda,'contexts':[context] if number==1 else [],'summaries':summaries,
                    'agenda_rules':rules,'num_rounds':1 if number==1 else 0}
            save(out/(name+'-inputs.json'),inputs)
            result=module.run_meeting(meeting_type='individual',agenda=agenda,save_dir=out,save_name=name,
                team_member=agent,contexts=tuple(inputs['contexts']),summaries=summaries,agenda_rules=rules,
                num_rounds=inputs['num_rounds'],temperature=0,pubmed_search=False,return_summary=True)
            transcript=json.loads((out/(name+'.json')).read_text())
            assert result==transcript[-1]['message']
            speakers=[turn['agent'] for turn in transcript if turn['agent']!='User']
            assert speakers==(['Researcher','Scientific Critic','Researcher'] if number==1 else ['Researcher'])
            assert critique in result
            for seed in ('7','19','31'):assert seed in result
            record.setdefault('checks',[]).append({'meeting':name,'speakers':speakers,'saved_summary_equal':True,
                 'critique_id_preserved':True,'separate_semantic_review_required':True})
            summaries=load_summaries([out/(name+'.json')]);assert summaries==(result,)
        assert recorder.calls==4
        record['status']='mechanical_checks_passed'
    except Exception as error:
        record.update(status='failed',failure_type=type(error).__name__)
    finally:
        record.update(api_calls=recorder.calls,usage=recorder.usage,source_after=source_hashes(root))
        record['source_unchanged']=record['source_after']==hashes
        save(out/'metadata.json',redact(record,config['DEEPSEEK_API_KEY']))
    print(json.dumps({k:record.get(k) for k in ('status','api_calls','usage','failure_type','source_unchanged')}))

if __name__=='__main__':main()
