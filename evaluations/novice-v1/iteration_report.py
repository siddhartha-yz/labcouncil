#!/usr/bin/env python3
"""Render subsequent unchanged-corpus runs with the baseline's strict graders.

Explicit host reviews and observed browser results are required. This does not
run models, infer communication success from artifacts, or rewrite prior runs.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
from audit import audit_case
from score import grade_case

HERE=Path(__file__).parent

def read(p):return json.loads(p.read_text())
def write(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def pct(n,d):return round(100*n/d,2) if d else None

def render(root, browser, baseline):
    out=root/'review'
    out.mkdir(exist_ok=False)
    frozen=root/'frozen-evaluation'
    cases=read(frozen/'cases.json')['cases'];bc=read(frozen/'browser-cases.json')['cases']
    old=read(baseline/'review/scores.json')
    # Refuse to present different inputs as a baseline improvement.
    for name in ('cases.json','browser-cases.json'):
        if (frozen/name).read_bytes()!=(baseline/'frozen-evaluation'/name).read_bytes():
            raise ValueError('different corpus: '+name)
    records={r['id']:r for r in read(root/'records.json')}
    reviews=read(root/'reviews.json');bs={r['id']:r for r in read(browser/'browser-results.json')}
    grades=[];audits={};states={}
    for c in cases:
        id=c['id'];r=records.get(id,{'state':'unmeasured'})
        g=grade_case(c,r,reviews.get(id))
        initial=root/id/'initial-state.json'
        a=audit_case(c,read(initial),[read(p) for p in sorted((root/id).glob('checkpoint-*.json'))]) if initial.exists() else {'passed':False,'checks':{},'numeric_results':[],'numeric_status':'unmeasured'}
        audits[id]=a;g['universal_audit']=a;g['passed']=bool(g['passed'] and a['passed'])
        g['status']='pass' if g['passed'] else 'unmeasured' if r['state']!='completed' else 'fail'
        grades.append(g)
        p=root/id/'final-state.json'
        if p.exists():states[id]=read(p)
    bg=[bs.get(c['id'],{'id':c['id'],'passed':False,'status':'unmeasured','observation':'未操作'}) for c in bc]
    cp=sum(g['passed'] for g in grades);bp=sum(g['passed'] for g in bg);n=len(cases)+len(bc)
    lanes={}
    for name,ids in [('本机回执与控制',[c['id'] for c in cases if not c['live']]),('真实Codex交互',[c['id'] for c in cases if c['live']])]:
        passed=sum(g['passed'] for g in grades if g['id'] in ids)
        lanes[name]={'passed':passed,'total':len(ids),'score':pct(passed,len(ids))}
    lanes['实际浏览器操作']={'passed':bp,'total':len(bc),'score':pct(bp,len(bc))}
    checks=[x for g in grades for x in g['checks']];critical=[x for x in checks if x['level']=='critical']
    requests=[r for p in states.values() for r in p['model_requests']]
    settings=read(root/'run-settings.json')
    score={'passed':cp+bp,'total':n,'score':pct(cp+bp,n),'target_met':100*(cp+bp)/n>=80,
        'baseline':{'passed':old['passed'],'total':old['total'],'score':old['score']},'lanes':lanes,
        'objective_checks':{'passed':sum(x['passed'] for x in checks),'total':sum(len(c['checks']) for c in cases)},
        'critical_checks':{'passed':sum(x['passed'] for x in critical),'total':sum(x['level']=='critical' for c in cases for x in c['checks'])},
        'cli_launches':read(root/'launch-budget.json'),'model_requests':len(requests),
        'request_status':dict(Counter(r['status'] for r in requests)), 'request_categories':dict(Counter(r['category'] for r in requests)),
        'usage':{k:sum((r.get('usage') or {}).get(k,0) for r in requests) for k in ['input_tokens','output_tokens','cached_input_tokens','reasoning_output_tokens','total_tokens']},
        'billed_cost':'unavailable; tokens are not dollars','case_wall_seconds':sum(r.get('elapsed',0) for r in records.values()),
        'unmeasured_within_selected_scope':sum(g['status']=='unmeasured' for g in grades+bg),
        'grades':grades,'browser_results':bg,'run_settings':settings,
        'judgement_limits':'Synthetic, designer-seen corpus; host review, no independent blind review or recruited users. No open paper reproduction or generalization proof.'}
    write(out/'scores.json',score);write(out/'reviews.json',reviews);write(out/'universal-audits.json',audits)
    write(out/'scoring-code.json',{'recorded_utc':datetime.now(timezone.utc).isoformat(),'same_as_baseline':{f:hashlib.sha256((HERE/f).read_bytes()).hexdigest()==read(baseline/'review/scoring-addendum.json')['supplement_hashes'][f] for f in ['audit.py','test_audit.py']},'hashes':{f:hashlib.sha256((HERE/f).read_bytes()).hexdigest() for f in ['score.py','audit.py','test_score.py','test_audit.py','iteration_report.py']},'grader_control_tests':25})
    (out/'CASEBOOK.md').write_bytes((frozen/'CASEBOOK.md').read_bytes())
    esc=html.escape;cards=[];md=['# 菜鸟测评：修复后完整复测','',f'严格跑通 **{cp+bp}/{n}，{score["score"]}/100**；原基线 {old["passed"]}/{old["total"]}，{old["score"]}/100。','',
        '题目、112项状态检查、完整性审计与严格判定未改。整套复测保留失败与未测分母；答复可用性和科研表述仍由宿主逐条审查，未做独立盲审。','',
        '| 路径 | 通过/总数 | 分数 |','|---|---:|---:|']
    for name,v in lanes.items():md.append(f'| {name} | {v["passed"]}/{v["total"]} | {v["score"]} |')
    md+=['',f'局部状态检查：{score["objective_checks"]["passed"]}/{score["objective_checks"]["total"]}；关键检查：{score["critical_checks"]["passed"]}/{score["critical_checks"]["total"]}。不替代整体跑通率。','',
        f'真实请求 {len(requests)} 次：{score["request_status"]}；测试保护拦下的调用尝试 {len(score["cli_launches"]["blocked_attempts"])} 次。公开资料读取为0，本轮只验证平台行为与受控合成实验。','',
        '## 全部场景','', '| 编号 | 场景 | 结果 | 审查依据 |','|---|---|---|']
    dialogue=['# 全部实际对话','', '本机回执、固定夹具和真实模型答复分别标明；不能把固定回执当模型理解能力。','']
    for c,g in zip(cases,grades):
        review=reviews.get(c['id'],{});reason=review.get('reason','未审查');msgs=states.get(c['id'],{}).get('group_messages',[])
        label='通过' if g['passed'] else '未通过'
        md.append(f'| {c["id"]} | {c["title"]} | {label} | {reason} |')
        dialogue += [f'## {c["id"]} {c["title"]}：{label}','',f'初始原话：{c["opening"]}','',f'怎样才算帮到用户：{c["good_response"]}','',f'审查：{reason}','']
        messages=''
        for m in msgs:
            origin='真实模型' if m.get('request_id') else '本机程序回执'
            dialogue += [f'用户：{m["user_text"]}','',f'答复（{origin}）：{m["answer"]}','']
            messages+=f'<div class="msg user"><small>用户</small><p>{esc(m["user_text"])}</p></div><div class="msg"><small>{origin}</small><p>{esc(m["answer"])}</p></div>'
        failed=[f'{x["kind"]}：预期{x["expected"]}，实际{x["actual"]}' for x in g['checks'] if not x['passed']]
        failed += [k for k,v in g['universal_audit']['checks'].items() if not v]
        cards.append(f'<details class="case" data-status="{g["status"]}" data-lane="{"live" if c["live"] else "local"}"><summary>{c["id"]} {esc(c["title"])}<span>{label}</span></summary><div class="inside"><h3>用户刚来时说</h3><p class="opening">{esc(c["opening"])}</p><h3>怎样才算帮到了他</h3><p>{esc(c["good_response"])}</p><h3>本轮实际观察</h3><p>{esc(reason)}</p><h3>实际聊天</h3>{messages}<details><summary>状态与证据核对</summary><pre>{esc(json.dumps({"未通过检查":failed,"独立算术核验":g["universal_audit"]["numeric_status"]},ensure_ascii=False,indent=2))}</pre></details></div></details>')
    for c,g in zip(bc,bg):
        label='通过' if g['passed'] else '未通过';note=g['observation']
        md.append(f'| {c["id"]} | {c["title"]} | {label} | {note} |')
        shots=''
        for name in g.get('screenshots',[]):
            (out/name).write_bytes((browser/name).read_bytes())
            shots+=f'<a href="{esc(name)}"><img src="{esc(name)}" loading="lazy" alt="{esc(c["id"])}实际操作截图"></a>'
        cards.append(f'<details class="case" data-status="{g["status"]}" data-lane="browser"><summary>{c["id"]} {esc(c["title"])}<span>{label}</span></summary><div class="inside"><h3>第一次使用的人要做什么</h3><p>{esc(c["task"])}</p><h3>怎样才算跑通</h3><p>{esc(c["pass"])}</p><h3>实际操作</h3><p>{esc(note)}</p><div class="proofs">{shots}</div></div></details>')
    md += ['','补充对照与等待中暂停/免费演示的检查另存于浏览器目录，未加入48条的分子或分母。','',
        '这些题目已被设计者看过，修复后成绩可以证明已知失败得到改善，不能证明所有新用户都能跑通。未测试真实手机软键盘、长时间开放研究、上游论文复现或真实研究优越性。原基线和修复过程中的局部检查完整保留。','']
    (out/'RESULTS.md').write_text('\n'.join(md));(out/'DIALOGUES.md').write_text('\n'.join(dialogue))
    metrics=f'<div><strong>{score["score"]} / 100</strong><small>严格跑通 {cp+bp}/{n} · 原基线 {old["score"]}</small></div>'
    for name,v in lanes.items():metrics+=f'<div><strong>{v["passed"]}/{v["total"]}</strong><small>{name}</small></div>'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LabCouncil 新手测试 · 修复后完整复测</title><style>
*{box-sizing:border-box}body{margin:0;background:#f7f8f5;color:#29312b;font:16px/1.7 system-ui,sans-serif}main{max-width:1040px;margin:auto;padding:44px 24px}h1{font-size:34px;line-height:1.35;font-weight:650}h2{font-size:23px}h3{font-size:16px;margin-top:24px}small{display:block;color:#657167}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:28px 0}.metrics>div{border:1px solid #dee5dc;border-radius:12px;background:white;padding:20px}.metrics strong{font-size:29px}.notice{background:#edf3e8;padding:20px 24px;border-left:4px solid #68896b;border-radius:10px}.case{background:white;border:1px solid #dfe5db;border-radius:12px;margin:12px 0}.case>summary{display:flex;justify-content:space-between;gap:16px;padding:18px 20px;cursor:pointer}.case span{white-space:nowrap;font-size:14px}.case[data-status=fail]>summary{color:#9b4c35}.inside{padding:0 24px 24px}.msg{background:#f6f7f3;padding:14px 18px;border-radius:12px;margin:12px 0}.msg.user{background:#eef4e8;margin-left:5%}.msg p{white-space:pre-wrap;overflow-wrap:anywhere;margin:5px 0}.opening{background:#edf2e7;padding:14px 18px;border-radius:10px}nav{display:flex;gap:8px;flex-wrap:wrap;position:sticky;top:0;background:#f7f8f5;padding:14px 0}button{font:inherit;border:1px solid #dce2d8;border-radius:24px;background:white;padding:7px 16px;cursor:pointer}button[aria-pressed=true]{background:#3b5540;color:white}.proofs{display:flex;gap:12px;flex-wrap:wrap}.proofs img{max-width:100%;width:360px;max-height:650px;object-fit:contain;object-position:top;border:1px solid #ddd;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#3b6143}footer{font-size:14px;color:#657167;margin-top:30px}.case[hidden]{display:none}@media(max-width:680px){main{padding:24px 16px}h1{font-size:28px}.metrics{grid-template-columns:1fr 1fr}.metrics>div{padding:16px}}</style><main><small>LabCouncil / 菜鸟测评 v1 / 同题同标准完整复测</small><h1>普通人这样说，<br>现在接得住了吗？</h1><p>48个场景使用原来的输入、要求和严格评分。打开任一项，可以核对用户原话、实际答复、状态和截图。</p><div class="metrics">METRICS</div><div class="notice"><strong>TARGET</strong><p>暂停、反悔和收回权限先在本机生效；资源、时长与写作偏好进入安排；修改目标继续沿用原截止时间；实验工具明确支持范围。</p><p>这些是合成场景，设计者见过题目，宿主逐条审查。分数说明已知问题的改善，尚不能代替真实新用户和独立盲测。</p></div><h2>查看全部场景</h2><nav><button data-filter="all" aria-pressed="true">全部48条</button><button data-filter="fail" aria-pressed="false">未跑通 FAILED 条</button><button data-filter="live" aria-pressed="false">真实模型8条</button><button data-filter="browser" aria-pressed="false">浏览器8条</button></nav><p id="count">显示48条场景</p>CARDS<footer>FOOTER<p><a href="CASEBOOK.md">完整测试集</a> · <a href="RESULTS.md">完整结果</a> · <a href="DIALOGUES.md">全部实际对话</a> · <a href="scores.json">原始分数</a></p></footer></main><script>document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('nav button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));let n=0;document.querySelectorAll('.case').forEach(c=>{let f=b.dataset.filter;c.hidden=!(f==='all'||f==='fail'&&c.dataset.status!=='pass'||c.dataset.lane===f);if(!c.hidden)n++});document.querySelector('#count').textContent='显示'+n+'条场景'});</script></html>'''
    footer=f'具体状态检查 {score["objective_checks"]["passed"]}/{score["objective_checks"]["total"]}；关键检查 {score["critical_checks"]["passed"]}/{score["critical_checks"]["total"]}。评分器控制25条通过。真实请求{len(requests)}次，公开读取0次；账单金额不可得。原基线全部保留。'
    page=page.replace('METRICS',metrics).replace('TARGET','本套测试达到80分门槛。' if score['target_met'] else '本套测试仍未达到80分门槛。').replace('FAILED',str(n-cp-bp)).replace('CARDS','\n'.join(cards)).replace('FOOTER',footer)
    (out/'index.html').write_text(page)
    return score

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--run',type=Path,required=True);a.add_argument('--browser',type=Path,required=True);a.add_argument('--baseline',type=Path,required=True);args=a.parse_args()
    s=render(args.run,args.browser,args.baseline)
    print(json.dumps({k:s[k] for k in ['passed','total','score','target_met','lanes']},ensure_ascii=False))
