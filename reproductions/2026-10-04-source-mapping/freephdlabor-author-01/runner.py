#!/usr/bin/env python3
"""Zero-provider-request restore check using initial source and core dependency pins."""
import argparse,contextlib,hashlib,importlib.metadata,io,json,os,platform,subprocess,sys
from pathlib import Path
import check_freephdlabor_agent as base
from check_freephdlabor_recovery import inspect

PIN='e95ce84ffbf9c4c234e616cdf20b3854ea0273b5'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--upstream',type=Path,required=True);p.add_argument('--saved',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 root=a.upstream.resolve();a.output.mkdir(parents=True,exist_ok=False)
 for pkg,version in [('smolagents','1.20.0'),('openai','1.60.2'),('pydantic','2.11.7')]:assert importlib.metadata.version(pkg)==version
 base.PIN=PIN;base.upstream(root)
 from smolagents import OpenAIServerModel
 from freephdlabor.agents.base_research_agent import BaseResearchAgent
 model=OpenAIServerModel(model_id='deepseek-flash',api_base='https://api.deepseek.com',api_key='OFFLINE_NOT_SENT')
 agent=BaseResearchAgent(model,agent_name='probe',workspace_dir=str(a.saved.resolve()),tools=[],enable_auto_compaction=False,verbosity_level=0)
 capture=io.StringIO()
 with contextlib.redirect_stdout(capture):agent.resume_memory()
 result={'upstream_commit':PIN,'python':platform.python_version(),'author_python_pin':'3.11.10; actual patch differs',
    'dependencies':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()},
    'scope':'Offline saved-file restoration; dependency core only, not full author conda environment or live initial agent loop.',
    'api_requests':0,'restore':inspect(agent),'restore_stdout':capture.getvalue(),
    'memory_sha256':base.sha(a.saved/'probe/probe_memory.jsonl')}
 # Original launcher starts tracing before argument parsing. No keys, no dotenv loading,
 # and only loopback tracing are allowed in this zero-request precheck.
 env={'PATH':os.environ.get('PATH',''),'LANG':'C.UTF-8','PYTHONPATH':str(root),'PHOENIX_COLLECTOR_ENDPOINT':'http://127.0.0.1:6006/v1/traces'}
 code='import sys,runpy,dotenv; dotenv.load_dotenv=lambda *a,**k:False; sys.argv=[sys.argv[1],"--help"]; runpy.run_path(sys.argv[0],run_name="__main__")'
 try:
  process=subprocess.run([sys.executable,'-c',code,str(root/'launch_multiagent.py')],env=env,cwd=root,capture_output=True,text=True,timeout=15)
  (a.output/'launcher-stdout.txt').write_text(process.stdout);(a.output/'launcher-stderr.txt').write_text(process.stderr)
  result['launcher']={'command':'Original launch_multiagent.py --help; sanitized environment; dotenv disabled','exit_code':process.returncode}
 except subprocess.TimeoutExpired as error:
  result['launcher']={'timeout_seconds':15}
  (a.output/'launcher-stdout.txt').write_bytes(error.stdout or b'');(a.output/'launcher-stderr.txt').write_bytes(error.stderr or b'')
 base.save(a.output/'assessment.json',result);print(json.dumps(result['restore']))
if __name__=='__main__':main()
