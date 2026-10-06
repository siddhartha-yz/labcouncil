"""Bounded Flash requests, with durable reservation before network I/O."""
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

from reproductions.check_deepseek_connectivity import ENDPOINT, load_config, redact

ROOT=Path(__file__).resolve().parents[1]


class Provider:
    def __init__(self, config=None, endpoint=ENDPOINT, timeout=40):
        self.config=config if config is not None else load_config(ROOT/'.env')
        if self.config.get('DEEPSEEK_MODEL')!='deepseek-flash':
            raise ValueError('这个案例仅允许 deepseek-flash；没有静默模型替换')
        self.endpoint,self.timeout=endpoint,timeout

    def call(self,store,project_id,category,phase,messages,tool=None,require_tool=False,task=None,meeting_id=None):
        payload={'model':'deepseek-flash','messages':messages,'thinking':{'type':'disabled'},
            'temperature':0,'max_tokens':768,'stream':False,'response_format':{'type':'json_object'}}
        if tool:
            payload['tools']=[tool]
            payload['tool_choice']={'type':'function','function':{'name':tool['function']['name']}} if require_tool else 'none'
        if len(json.dumps(payload,ensure_ascii=False).encode())>20000:
            raise ValueError('案例模型输入超过二万字节限制')
        key=self.config['DEEPSEEK_API_KEY']
        safe_payload=redact(payload,key)
        identifier=store.reserve_request(project_id,category,phase,safe_payload,task,meeting_id)
        request=urllib.request.Request(self.endpoint,data=json.dumps(payload).encode(),
            headers={'Content-Type':'application/json','Authorization':'Bearer '+key},method='POST')
        started=time.monotonic()
        try:
            with urllib.request.urlopen(request,timeout=self.timeout) as response:
                status=response.status
                raw=response.read(262145)
                if len(raw)>262144:raise ValueError('响应超过案例上限')
                body=json.loads(raw,parse_constant=lambda value: (_ for _ in ()).throw(ValueError('非有限数字')))
        except urllib.error.HTTPError as error:
            status=error.code
            error.close()
            store.finish_request(identifier,http_status=status,error='provider_http_error',elapsed=time.monotonic()-started)
            raise ValueError(f'真实模型 HTTP {status}；这次请求已计入，不自动重试') from None
        except (OSError,ValueError,TimeoutError):
            store.finish_request(identifier,error='transport_or_response_error',elapsed=time.monotonic()-started)
            raise ValueError('真实模型传输或响应失败；这次请求已计入，不自动重试') from None
        body=redact(body,key)
        store.finish_request(identifier,response=body,http_status=status,elapsed=time.monotonic()-started)
        if not isinstance(body,dict) or body.get('model')!='deepseek-flash':raise ValueError('实际响应模型不符合案例协议')
        choice=body.get('choices',[{}])[0]
        if choice.get('finish_reason') not in ('stop','tool_calls'):raise ValueError('真实模型响应截断，不能记作完成')
        message=choice.get('message')
        if not isinstance(message,dict):raise ValueError('真实模型消息无效')
        return {k:v for k,v in message.items() if k in ('role','content','tool_calls','reasoning_content') and v is not None},identifier
