#!/usr/bin/env python3
"""Fetch official archive and date-candidate metadata without claiming equivalence."""
import argparse
import datetime
import json
from pathlib import Path
import urllib.request

URLS={
'virtual-lab-tags':'https://api.github.com/repos/zou-group/virtual-lab/tags?per_page=100',
'virtual-lab-publication-constants':'https://api.github.com/repos/zou-group/virtual-lab/contents/src/virtual_lab/constants.py?ref=2a3654b67729972b7e2a8145adad4ec06f0164af',
'virtual-lab-publication-pyproject':'https://api.github.com/repos/zou-group/virtual-lab/contents/pyproject.toml?ref=2a3654b67729972b7e2a8145adad4ec06f0164af',
'freephdlabor-commit-history':'https://api.github.com/repos/ltjed/freephdlabor/commits?per_page=100',
'virtual-lab-publication-commit':'https://api.github.com/repos/zou-group/virtual-lab/commits?until=2025-07-29T23%3A59%3A59Z&per_page=1',
'freephdlabor-paper-date-commit':'https://api.github.com/repos/ltjed/freephdlabor/commits?until=2025-10-17T13%3A13%3A32Z&per_page=1',
}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=False)
 for name,url in URLS.items():
  result={'url':url,'retrieved_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
   'meaning':'Official archive metadata or last chronological candidate; date does not prove paper version.'}
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'LabCouncil-reproduction-audit','Accept':'application/json'}),timeout=25) as r:data=json.load(r)
   if name=='virtual-lab-tags':
    result['tags']=data
   elif name.endswith(('constants','pyproject')):
    import base64
    result.update(git_blob_sha=data.get('sha'),html_url=data.get('html_url'),source=base64.b64decode(data['content']).decode())
   elif isinstance(data,list):
    result['commits']=[{'sha':x['sha'],'html_url':x['html_url'],'commit':{
      'date':x['commit']['committer']['date'],'message':x['commit']['message'],'tree':x['commit']['tree']}} for x in data]
   else:result.update(id=data.get('id'),metadata=data.get('metadata'),files=data.get('files'),links=data.get('links'))
  except Exception as e:result.update(failure_type=type(e).__name__,failure=str(e))
  (a.output/(name+'.json')).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
  print(name,result.get('failure_type') or 'retrieved',flush=True)
if __name__=='__main__':main()
