#!/usr/bin/env python3
"""Alternative official archive and DOI registrar metadata; no credentials."""
import argparse,datetime,json,urllib.request
from pathlib import Path
URLS={'zenodo-export':'https://zenodo.org/records/15320491/export/json',
      'datacite':'https://api.datacite.org/dois/10.5281/zenodo.15320491'}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 for name,url in URLS.items():
  record={'url':url,'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'LabCouncil-source-audit','Accept':'application/json'}),timeout=25) as r:data=json.load(r)
   if name=='datacite':
    attrs=data['data']['attributes'];record['metadata']={k:attrs.get(k) for k in ('doi','url','version','titles','dates','relatedIdentifiers','descriptions','publicationYear')}
   else:record['metadata']=data
  except Exception as error:record.update(failure_type=type(error).__name__,failure=str(error))
  (a.output/(name+'.json')).write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n');print(name,record.get('failure_type') or 'retrieved',flush=True)
if __name__=='__main__':main()
