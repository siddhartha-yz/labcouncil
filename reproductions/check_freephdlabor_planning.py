#!/usr/bin/env python3
"""Real original planner step and fresh-process memory restoration."""
import argparse,json,subprocess,sys
from pathlib import Path
import check_freephdlabor_agent as base
from check_freephdlabor_recovery import inspect
PIN='e95ce84ffbf9c4c234e616cdf20b3854ea0273b5'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--upstream',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--resume',action='store_true');a=p.parse_args();out=a.output.resolve();root=a.upstream.resolve();base.PIN=PIN
 if not a.resume:out.mkdir(parents=True,exist_ok=False)
 base.upstream(root)
 from freephdlabor.agents.base_research_agent import BaseResearchAgent
 from smolagents import OpenAIServerModel
 if a.resume:
  model=OpenAIServerModel(model_id='deepseek-flash',api_base='https://api.deepseek.com',api_key='OFFLINE_NOT_SENT')
  agent=BaseResearchAgent(model,agent_name='probe',workspace_dir=str(out),tools=[],enable_auto_compaction=False,verbosity_level=0)
  agent.resume_memory();base.save(out/'restored.json',{'state':inspect(agent),'plans':[s.plan for s in agent.memory.steps if hasattr(s,'plan')]});return
 shell,_,attempts=base.make_agent(root,out,'no_input',True)
 agent=BaseResearchAgent(shell.model.model,agent_name='probe',workspace_dir=str(out),tools=[shell.tools['evaluate']],planning_interval=1,enable_auto_compaction=False,max_steps=1,verbosity_level=0)
 error=None
 try:answer=agent.run('Make a short plan for this bounded check. Then in one Python code action set checkpoint_value=37, call evaluate("linear"), print its MSE, and call final_answer with that MSE. Do not import modules. This is synthetic, not a scientific discovery.')
 except Exception as e:answer=None;error={'type':type(e).__name__,'message':str(e)}
 agent.save_memory();base.save(out/'original.json',{'upstream_commit':PIN,'script_sha256':base.sha(Path(__file__)),'state':inspect(agent),'plans':[s.plan for s in agent.memory.steps if hasattr(s,'plan')],'api_calls':attempts[0],'answer':str(answer),'error':error})
 cmd=[sys.executable,str(Path(__file__).resolve()),'--upstream',str(root),'--output',str(out),'--resume']
 proc=subprocess.run(cmd,capture_output=True,text=True,timeout=15);(out/'restore-stdout.txt').write_text(proc.stdout);(out/'restore-stderr.txt').write_text(proc.stderr)
 original=json.loads((out/'original.json').read_text());restored=json.loads((out/'restored.json').read_text()) if (out/'restored.json').exists() else {}
 base.save(out/'assessment.json',{'plan_generated':bool(original['plans']),'plan_text_restored':bool(original['plans']) and original['plans']==restored.get('plans'),'restore_exit_code':proc.returncode,'artifact_sha256':base.sha(out/'tool-calls.json') if (out/'tool-calls.json').exists() else None,'api_calls':attempts[0],'scope':'One real planning step; not planning quality or full ManagerAgent.'})
 print((out/'assessment.json').read_text())
if __name__=='__main__':main()
