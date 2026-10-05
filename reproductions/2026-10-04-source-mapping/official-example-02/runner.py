#!/usr/bin/env python3
"""Execute original notebook cells for team selection, with a real bounded client."""
import argparse,datetime,importlib,importlib.metadata,json,os,subprocess,sys,threading,time
from pathlib import Path
from types import SimpleNamespace
from check_deepseek_connectivity import load_config,redact
from check_virtual_lab_meeting import source_hashes,digest,save
PIN='2a3654b67729972b7e2a8145adad4ec06f0164af'

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--upstream',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 root=a.upstream.resolve();out=a.output.resolve();assert subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()==PIN
 assert not subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True).strip()
 config=load_config(Path('.env'));assert config['DEEPSEEK_MODEL']=='deepseek-flash'
 out.mkdir(parents=True,exist_ok=False)
 before=source_hashes(root);notebook=root/'nanobody_design/run_nanobody_design.ipynb'
 cells=json.loads(notebook.read_text())['cells'];selected={str(n):''.join(cells[n]['source']) for n in (0,2,3,4)}
 save(out/'executed-cells.json',selected)
 record={'upstream_commit':PIN,'package_version':'1.1.0','notebook_sha256':digest(notebook),
 'script_sha256':digest(Path(__file__)),'started_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'source_before':before,'dependencies':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()},
 'model_change':'gpt-4o-2024-08-06 -> deepseek-flash','request_cap':6,'scope':'Official first notebook stage, changed model; no nanobody design pipeline.'}
 sys.path[:0]=[str(root/'src'),str(root/'nanobody_design')]
 from openai import OpenAI,NOT_GIVEN
 from tiktoken import get_encoding
 os.environ['TIKTOKEN_CACHE_DIR']=str(out/'tokenizer-cache')
 lock=threading.Lock();count=[0];usage={};errors=[]
 client=OpenAI(api_key=config['DEEPSEEK_API_KEY'],base_url='https://api.deepseek.com',timeout=45,max_retries=0)
 def event(item):
  with lock:
   with (out/'api-events.jsonl').open('a') as f:f.write(json.dumps(redact(item,config['DEEPSEEK_API_KEY']),ensure_ascii=False)+'\n')
 def create(**kwargs):
  with lock:
   count[0]+=1;cid=count[0]
  if cid>6 or kwargs['model']!='deepseek-flash':raise ValueError('Request budget/model mismatch')
  kwargs={k:v for k,v in kwargs.items() if v is not NOT_GIVEN}
  if kwargs.get('tools'):raise ValueError('Unexpected external tools')
  kwargs.update(max_tokens=1024,extra_body={'thinking':{'type':'disabled'}})
  event({'kind':'request','call_id':cid,'kwargs':kwargs});start=time.monotonic()
  try:response=client.chat.completions.create(**kwargs)
  except Exception as error:
   with lock:errors.append({'call_id':cid,'error_type':type(error).__name__})
   event({'kind':'failure','call_id':cid,'error_type':type(error).__name__})
   raise RuntimeError('Bounded provider request failed') from None
  body=response.model_dump(mode='json');event({'kind':'response','call_id':cid,'response':body,'elapsed_seconds':time.monotonic()-start})
  with lock:
   for k in ('prompt_tokens','completion_tokens','total_tokens'):usage[k]=usage.get(k,0)+(body.get('usage') or {}).get(k,0)
  if response.choices[0].finish_reason!='stop' or not response.choices[0].message.content:
   with lock:errors.append({'call_id':cid,'failure':'truncated_or_empty'})
   raise ValueError('Truncated or empty response')
  return response
 original_assistant_create=client.beta.assistants.create
 def assistant_create(**kwargs):
  with lock:
   count[0]+=1;cid=count[0]
  if cid>6 or kwargs['model']!='deepseek-flash':raise ValueError('Request budget/model mismatch')
  event({'kind':'request','route':'POST /assistants','call_id':cid,'kwargs':kwargs})
  try:
   response=original_assistant_create(**kwargs)
  except Exception as error:
   failure={'call_id':cid,'error_type':type(error).__name__,'http_status':getattr(error,'status_code',None)}
   with lock:errors.append(failure)
   event({'kind':'failure',**failure})
   raise RuntimeError('Original Assistants route request failed; see HTTP status') from None
  event({'kind':'response','call_id':cid,'created_assistant_id':response.id})
  raise RuntimeError('Assistant creation succeeded; later endpoints outside diagnostic budget')
 client.beta.assistants.create=assistant_create
 module=importlib.import_module('virtual_lab.run_meeting');module.OpenAI=lambda:client
 import concurrent.futures
 original_wait=concurrent.futures.wait
 def recorded_wait(fs,*args,**kwargs):
  result=original_wait(fs,*args,**kwargs)
  exceptions=[type(f.exception()).__name__ if f.exception() is not None else None for f in result.done]
  event({'kind':'completed_futures','exception_types':exceptions})
  return result
 concurrent.futures.wait=recorded_wait
 previous=Path.cwd()
 try:
  get_encoding('cl100k_base')
  os.chdir(out);namespace={}
  exec(compile(selected['0'],str(notebook)+':cell0','exec'),namespace)
  namespace['principal_investigator'].model='deepseek-flash'
  for n in ('2','3','4'):exec(compile(selected[n],str(notebook)+':cell'+n,'exec'),namespace)
  assert namespace['num_iterations']==5 and len(namespace['team_selection_summaries'])==5
  directory=out/'discussions/team_selection'
  for name in [f'discussion_{i}' for i in range(1,6)]+['merged']:
   discussion=json.loads((directory/(name+'.json')).read_text());assert discussion[-1]['agent']=='Principal Investigator' and discussion[-1]['message'].strip()
   assert (directory/(name+'.md')).exists()
  assert count[0]==6 and not errors
  record['status']='mechanical_checks_passed'
 except Exception as error:record.update(status='failed',failure_type=type(error).__name__)
 finally:
  os.chdir(previous);record.update(api_attempts=count[0],usage=usage,request_errors=errors,source_after=source_hashes(root))
  record['source_unchanged']=record['source_after']==before
  save(out/'metadata.json',redact(record,config['DEEPSEEK_API_KEY']))
 print(json.dumps({k:record.get(k) for k in ('status','api_attempts','usage','failure_type','source_unchanged')}))
if __name__=='__main__':main()
