"""Small public-source adapters. No credentials, redirects or upstream execution."""
import base64
import fcntl
import hashlib
import json
from pathlib import Path
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from .store import encode, Conflict

ROOT = Path(__file__).resolve().parents[1]
REPO = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z')
ARXIV = re.compile(r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?\Z')
SHA = re.compile(r'[a-f0-9]{40}\Z')
LOCK = threading.Lock()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate(action, value):
    if action in ('search_papers', 'search_repositories'):
        if not isinstance(value,str) or not value.strip() or len(value) > 200 or any(ord(c)<32 for c in value):
            raise ValueError('检索词需要一到二百字符')
        return value.strip()
    pattern = REPO if action == 'inspect_repository' else ARXIV if action == 'read_abstract' else None
    if pattern is None or not isinstance(value,str) or not pattern.fullmatch(value) or '..' in value:
        raise ValueError('只接受公开仓库名称或arXiv编号；不接受任意网址')
    return value


def _network(url, headers):
    # All callers build URLs from validated identifiers and these fixed hosts.
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('api.github.com','export.arxiv.org') or parsed.port or parsed.username:
        raise ValueError('公开工具网址越界')
    request = urllib.request.Request(url,headers=headers)
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request,timeout=15) as response:
        raw = response.read(262145)
        if len(raw)>262144: raise ValueError('资料超过二百五十六KiB上限')
        return raw,response.status


def _fetch_once(store, task, url, attempt, allow_new=True):
    # Attempt 1 retains the original cache identity, including historical errors.
    identity = url if attempt == 1 else encode({'url':url,'attempt':attempt})
    fingerprint = hashlib.sha256(identity.encode()).hexdigest()
    row,fresh = store.reserve_source(task,fingerprint,url,allow_new)
    if row is None: return None
    if not fresh:
        saved = store.source_record(row['id'])
        return {**saved,'cached':True}
    headers = {'User-Agent':'LabCouncil/0.1 (https://github.com/siddhartha-yz/labcouncil)',
        'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2026-03-10'}
    http_status = None
    started = time.monotonic()
    if attempt > 1: time.sleep(2)
    try:
        if urllib.parse.urlsplit(url).hostname == 'export.arxiv.org':
            # Shared across workers/databases on this host, single connection + 3s spacing.
            path = ROOT/'workspaces'/'arxiv-request.lock';path.parent.mkdir(parents=True,exist_ok=True)
            with LOCK, path.open('a+') as handle:
                fcntl.flock(handle,fcntl.LOCK_EX)
                handle.seek(0)
                raw_time = handle.read()
                delay = max(0,3-(time.time()-float(raw_time or 0)))
                time.sleep(min(delay,3))
                handle.seek(0);handle.truncate();handle.write(str(time.time()));handle.flush()
                try: raw,http_status = _network(url,headers)
                finally:
                    handle.seek(0);handle.truncate();handle.write(str(time.time()));handle.flush()
        else:
            raw,http_status = _network(url,headers)
        body = {'text':raw.decode('utf-8'),'raw_sha256':hashlib.sha256(raw).hexdigest()}
        status = 'completed'
    except urllib.error.HTTPError as error:
        http_status = error.code;error.close()
        body,status = {'error':'公开接口HTTP错误，不重试','retryable':False},'error'
    except (OSError,ValueError,TimeoutError) as error:
        body,status = {'error':'公开资料连接、大小或编码检查失败',
            'retryable':_transient(error),
            'error_type':type(error).__name__,'reason_type':type(getattr(error,'reason',None)).__name__,
            'errno':getattr(error,'errno',None)},'error'
    body.update(transport='urllib',attempt_number=attempt,elapsed_seconds=round(time.monotonic()-started,3))
    store.finish_source(row['id'],body,status,http_status)
    return {**store.source_record(row['id']),'cached':False}


TRANSIENT = ('SSLEOFError','ConnectionResetError','ConnectionAbortedError','TimeoutError','gaierror')


def _transient(error):
    reason = getattr(error,'reason',error)
    return not isinstance(reason,ssl.SSLCertVerificationError) and type(reason).__name__ in TRANSIENT


def fetch(store, task, url):
    allowed = store.project(task['project_id'])['current_inputs']['body']['permissions'].get('retry_public_reads',False)
    records = []
    for attempt in range(1,4):
        try: current = _fetch_once(store,task,url,attempt,attempt == 1 or allowed)
        except Conflict:
            if not records: raise
            return {**row,'attempt_records':records,'retry_stopped':True}
        if current is None: break
        row = current
        body = row.get('body') or {}
        records.append({**{k:row[k] for k in ('id','url','status','sha256','cached','http_status')},
            **{k:body[k] for k in ('error_type','reason_type','errno','transport','attempt_number','elapsed_seconds') if k in body}})
        # Legacy records can be retried only when their recorded class is known.
        retryable = body.get('retryable', body.get('reason_type') in TRANSIENT or body.get('error_type') in TRANSIENT)
        if row['status'] != 'error' or row['http_status'] is not None or not retryable: break
    return {**row,'attempt_records':records}


def retrieve(store,task,action,value):
    value = validate(action,value)
    records = [];sources = []
    def read(path, arxiv=False):
        row = fetch(store,task,('https://export.arxiv.org/api/query?' if arxiv else 'https://api.github.com/')+path)
        records.extend(row['attempt_records'])
        if row['status'] != 'completed': raise ValueError('接口未返回可用资料；错误或未知尝试已保留')
        return row['body']['text']
    try:
        if action in ('search_papers','read_abstract'):
            params = {'search_query':value,'max_results':3} if action=='search_papers' else {'id_list':value,'max_results':1}
            raw = read(urllib.parse.urlencode(params),True)
            if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper(): raise ValueError('不接受XML实体')
            root = ET.fromstring(raw);ns={'a':'http://www.w3.org/2005/Atom'}
            sources = []
            for entry in root.findall('a:entry',ns)[:3]:
                identifier = entry.findtext('a:id','',ns).split('/abs/')[-1]
                validate('read_abstract',identifier)
                sources.append({'kind':'paper_abstract','id':identifier,'url':'https://arxiv.org/abs/'+identifier,
                    'title':' '.join(entry.findtext('a:title','',ns).split()),
                    'abstract':entry.findtext('a:summary','',ns)[:10000],
                    'authors':[a.findtext('a:name','',ns) for a in entry.findall('a:author',ns)],
                    'published':entry.findtext('a:published','',ns),'updated':entry.findtext('a:updated','',ns),
                    'verification':'只读取元数据和摘要，未读全文、未复现实验'})
        elif action == 'search_repositories':
            result = json.loads(read('search/repositories?'+urllib.parse.urlencode({'q':value,'per_page':3})))
            sources = []
            for item in result.get('items',[])[:3]:
                name = validate('inspect_repository',item['full_name'])
                sources.append({'kind':'repository_search','id':name,'url':'https://github.com/'+name,
                    'title':name,'description':item.get('description'),'verification':'检索条目，尚未读取代码或复现'})
        else:
            meta = json.loads(read('repos/'+value))
            if meta.get('private') is not False: raise ValueError('仅允许公开仓库')
            sources = [{'kind':'repository_metadata','id':value,'url':'https://github.com/'+value,'title':value,
                'description':meta.get('description'),'license':(meta.get('license') or {}).get('spdx_id'),
                'verification':'仅读取公开元信息；尚未取得commit或README，未执行代码'}]
            commit = json.loads(read('repos/'+value+'/commits?per_page=1'))[0]['sha']
            if not SHA.fullmatch(commit): raise ValueError('仓库commit无效')
            sources[0].update(commit=commit,verification='已取得commit；尚未读取README，未执行代码')
            result = json.loads(read('repos/'+value+'/readme?'+urllib.parse.urlencode({'ref':commit})))
            if result.get('encoding')!='base64': raise ValueError('README编码无效')
            readme = base64.b64decode(result['content']).decode('utf-8')
            sources = [{'kind':'repository_readme','id':value+'@'+commit,'url':'https://github.com/'+value+'/tree/'+commit,
                'title':value,'commit':commit,'license':(meta.get('license') or {}).get('spdx_id'),
                'readme':readme[:16000],'readme_truncated':len(readme)>16000,
                'readme_sha256':hashlib.sha256(readme.encode()).hexdigest(),
                'verification':'固定commit的README；未执行仓库代码、未验证作者成绩'}]
        return {'status':'completed','sources':sources,'http_requests':records}
    except (ValueError,KeyError,TypeError,IndexError,ET.ParseError,Conflict):
        return {'status':'error','sources':sources,'http_requests':records,
            'error':'公开资料未能读取、额度已到或格式不符合预期；实际尝试见请求账本'}
