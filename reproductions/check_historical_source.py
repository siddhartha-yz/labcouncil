#!/usr/bin/env python3
"""Audit selected official historical files; no arbitrary URL or credential use."""
import argparse,ast,base64,datetime,hashlib,json,urllib.request
from pathlib import Path
FILES={
 'virtual-lab-pyproject':('zou-group/virtual-lab','2a3654b67729972b7e2a8145adad4ec06f0164af','pyproject.toml'),
 'freephdlabor-initial-base':('ltjed/freephdlabor','e95ce84ffbf9c4c234e616cdf20b3854ea0273b5','freephdlabor/agents/base_research_agent.py'),
 'freephdlabor-initial-callback':('ltjed/freephdlabor','e95ce84ffbf9c4c234e616cdf20b3854ea0273b5','freephdlabor/interaction/callback_tools.py'),
 'freephdlabor-initial-environment':('ltjed/freephdlabor','e95ce84ffbf9c4c234e616cdf20b3854ea0273b5','environment.yml'),
}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 for name,(repo,ref,path) in FILES.items():
  url=f'https://api.github.com/repos/{repo}/contents/{path}?ref={ref}'
  result={'url':url,'commit':ref,'date_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'LabCouncil-audit'}),timeout=25) as response:data=json.load(response)
   raw=base64.b64decode(data['content']);text=raw.decode();result.update(git_blob_sha=data['sha'],sha256=hashlib.sha256(raw).hexdigest())
   if path.endswith('.py'):
    tree=ast.parse(text);result['selected_function_hashes']={}
    for node in ast.walk(tree):
     if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in ('save_memory','resume_memory','callback','_read_until_double_enter'):
      segment=ast.get_source_segment(text,node);result['selected_function_hashes'][node.name]=hashlib.sha256(segment.encode()).hexdigest()
      result.setdefault('selected_function_lines',{})[node.name]=[node.lineno,node.end_lineno]
   elif path.endswith('.toml'):result['source']=text
   else:result['pinned_runtime_lines']=[line for line in text.splitlines() if any(x in line for x in ('python=','smolagents==','openai==','litellm==','torch=='))]
  except Exception as e:result.update(failure_type=type(e).__name__,failure=str(e))
  (a.output/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n');print(name,result.get('failure_type') or 'retrieved',flush=True)
if __name__=='__main__':main()
