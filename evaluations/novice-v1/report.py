#!/usr/bin/env python3
"""Render saved baseline + explicit reviews; never runs models or fixes platform."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import html
import json
from pathlib import Path
from audit import audit_case
from score import grade_case
HERE=Path(__file__).parent

def read(p):return json.loads(p.read_text())
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def pct(n,d):return round(100*n/d,2) if d else None

def main():
 a=argparse.ArgumentParser();a.add_argument('--run',required=True);a.add_argument('--browser',required=True);args=a.parse_args()
 root=Path(args.run);br=Path(args.browser);out=root/'review';out.mkdir(exist_ok=False)
 frozen=root/'frozen-evaluation';cases=read(frozen/'cases.json')['cases'];browser_cases=read(frozen/'browser-cases.json')['cases']
 records={r['id']:r for r in read(root/'records.json')};reviews=read(root/'reviews.json');bs={r['id']:r for r in read(br/'browser-results.json')}
 grades=[];audits={}
 for c in cases:
  r=records.get(c['id'],{'state':'unmeasured'});g=grade_case(c,r,reviews.get(c['id']))
  initial=root/c['id']/'initial-state.json'
  audit=audit_case(c,read(initial),[read(p) for p in sorted((root/c['id']).glob('checkpoint-*.json'))]) if initial.exists() else {'passed':False,'checks':{},'numeric_results':[],'numeric_status':'unmeasured'}
  audits[c['id']]=audit;g['universal_audit']=audit;g['passed']=bool(g['passed'] and audit['passed']);g['status']='pass' if g['passed'] else 'unmeasured' if r['state']!='completed' else 'fail';grades.append(g)
 bg=[bs.get(c['id'],{'id':c['id'],'passed':False,'status':'unmeasured','observation':'未操作'}) for c in browser_cases]
 cp=sum(g['passed'] for g in grades);bp=sum(g['passed'] for g in bg)
 checks=[x for g in grades for x in g['checks']];critical=[x for x in checks if x['level']=='critical']
 lanes={}
 for name,ids in [('本机回执与控制',[c['id'] for c in cases if not c['live']]),('真实Codex交互',[c['id'] for c in cases if c['live']])]:
  passed=sum(g['passed'] for g in grades if g['id'] in ids);lanes[name]={'passed':passed,'total':len(ids),'score':pct(passed,len(ids))}
 lanes['实际浏览器操作']={'passed':bp,'total':len(browser_cases),'score':pct(bp,len(browser_cases))}
 states=[read(root/c['id']/'final-state.json') for c in cases if (root/c['id']/'final-state.json').exists()]
 requests=[r for p in states for r in p['model_requests']]
 usage={k:sum((r.get('usage') or {}).get(k,0) for r in requests) for k in ['input_tokens','output_tokens','cached_input_tokens','reasoning_output_tokens','total_tokens']}
 categories={}
 for category in dict.fromkeys(c['category'] for c in cases):
  ids=[c['id'] for c in cases if c['category']==category];categories[category]={'passed':sum(g['passed'] for g in grades if g['id'] in ids),'total':len(ids)}
 score={'passed':cp+bp,'total':len(cases)+len(browser_cases),'score':pct(cp+bp,len(cases)+len(browser_cases)),
        'dialogue':{'passed':cp,'total':len(cases),'score':pct(cp,len(cases))},'lanes':lanes,'categories':categories,
        'objective_checks':{'passed':sum(x['passed'] for x in checks),'total':112},'critical_checks':{'passed':sum(x['passed'] for x in critical),'total':80},
        'unmeasured_within_selected_scope':sum(g['status']=='unmeasured' for g in grades+bg),
        'cli_launches':read(root/'launch-budget.json'),'model_requests':len(requests),'request_status':dict(Counter(r['status'] for r in requests)),
        'request_categories':dict(Counter(r['category'] for r in requests)),'usage':usage,'billed_cost':'unavailable; tokens are not dollars',
        'case_wall_seconds':sum(r.get('elapsed',0) for r in records.values()),'grades':grades,'browser_results':bg}
 write(out/'scores.json',score);write(out/'reviews.json',reviews);write(out/'universal-audits.json',audits)
 write(out/'scoring-addendum.json',{'recorded_utc':datetime.now(timezone.utc).isoformat(),'original_manifest':read(root/'manifest.json'),
   'note':'Original 112 checks unchanged. Supplement audits existing protocol universal requirements; no new model calls.',
   'supplement_hashes':{f:hashlib.sha256((HERE/f).read_bytes()).hexdigest() for f in ['audit.py','test_audit.py','report.py','AUDIT-NOTE.md']},'grader_controls_before_execution':17,'supplement_controls_after_execution':8})
 (out/'CASEBOOK.md').write_bytes((frozen/'CASEBOOK.md').read_bytes())
 def yn(x):return '通过' if x else '未通过'
 md=['# 菜鸟测评：首轮结果','',f'**严格跑通率：{cp+bp}/{len(cases)+len(browser_cases)}，{score["score"]} / 100。** 这次暴露了问题，还不能说平台已经适合第一次使用的人。','',
 '“跑通”要求：想法与限制被理解、实际操作遵约、答复可用；有报告、请求成功或按钮能点，都不单独等于跑通。','',
 '输入和期望先固定，再测当前版本。40条HTTP多轮场景 + 8条真实浏览器旅程；全部保留在分母中。宿主模拟菜鸟表达和操作，没有招募真实用户，也没有独立盲审。','',
 '| 层次 | 跑通 / 场景数 | 分数 |','|---|---:|---:|']
 for name,v in lanes.items():md.append(f'| {name} | {v["passed"]}/{v["total"]} | {v["score"]} |')
 md+=['',f'具体状态检查：**{score["objective_checks"]["passed"]}/112**；其中关键检查 **{score["critical_checks"]["passed"]}/80**。这是局部检查比例，不替代完整跑通率。','',
 '## 先看这几条普通人说的话','',
 '| 用户说 | 实際发生 |','|---|---|',
 '| “别忙了，等我回来再弄。” | 没有暂停；相同情境的“先停一下”能暂停。 |',
 '| “先别再花钱了，有什么现成的就直接给我看。” | 尝试进入模型。测试保护挡住1次真实启动；不能说平台已遵守。 |',
 '| “想比较两个办法。我只有一台笔记本，先弄二十分钟就好。” | 仍是默认120分钟，资源栏未整理。 |',
 '| “刚才那个别做了，我改主意了。” | 待确认安排没有撤回。 |',
 '| “加一点坏数据进去，再试一下。原来的结果留着。” | 旧结果保留、新实验实际保存；自己提出约5%，实际用了10%。最后答复诚实指出偏差。 |','',
 '## 哪些实际做到了','',
 '- 8条实际浏览器流程通过：首页起草、选择工具/确认、未选工具的说明、草稿刷新、手机成果页、提交后断连恢复、阅读位置、停止原因。固定程序夹具明确标记，不计为模型研究成果。',
 '- 23次真实Codex CLI请求均完成：17次聊天，6次后台规划/报告。真实一轮与两轮工作都留下了工具结果、报告及引用。',
 '- 五点固定演示和3次研究工具输出做了独立数值复算，共4份计算产物，均对上。没有数值实验的案例记为“不适用”。',
 '- 真实答复会说明合成材料、摘要不等于复现、新数据泛化尚未知、报告失败与工具保存不同，以及恶意资料不是用户指令。','',
 '## 不能因此称为整体成功','',
 '- 口语的撤回、暂停、拒绝再花钱会漏识别，缺少模型权限时很多具体困惑只得到同一模板。聊天原文保存了，资源和偏好却没进入工作安排。',
 '- E05/E06未经用户选择新时长，直接交代任务后截止时间延后约21.91秒和26.15秒。模型说“不重新计时”，系统却重置了时钟。',
 '- E06的5%计划跑成10%，三个异常数据种子中两个没有配对干净对照；原计划的无关系对照也没做。报告如实保留缺口，仍不等于执行满足安排。',
 '- API恢复R01和界面恢复提示U06分别验收；不冒充每条API题都由浏览器走过。','',
 '## 测试本身也保留缺陷','',
 '第一次完整尝试因驱动中文编码错误无效，0次模型启动；校准又发现异常处理模块被同名变量遮蔽。旧目录保留，修好驱动后小范围验证，再完成这一次有效基线。无效运行不计为40个平台失败，也不挑选多次模型运行的最佳成绩。',
 '执行前17条评分器正负控制通过；审查时补了8条，专门防空数值被误算验证和计时暗增，共25条控制通过。原112项检查和输入哈希没有改；补充审计独立记录，未重新请求模型。','',
 '## 实际投入与范围','',
 f'- 有效对话/状态运行约{score["case_wall_seconds"]/60:.2f}分钟，另有题目设计、驱动校准、浏览器操作与宿主审查；不能把CLI运行时间当整个工作的时间。',
 f'- 模型启动{score["cli_launches"]["started"]}/28；另有1次被测试保护拦下的尝试。记录tokens：输入{usage["input_tokens"]:,}，输出{usage["output_tokens"]:,}，总计{usage["total_tokens"]:,}，缓存输入{usage["cached_input_tokens"]:,}（输入的子集）。实际账单金额不可得。',
 '- 公开资料请求0次，不下载真实论文或运行上游仓库；没有测试任意代码、GPU训练、真实研究优越性或长周期自主研究。',
 '- 所有场景是合成的，设计者见过全套题，contrast不是盲测；这套基线能复现失败，不能证明泛化或估计模型稳定性。','',
 '## 下一版优先改什么','',
 '1. 先让“暂停/取消/别花钱/别上网”的普通话在模型调用之前生效。',
 '2. 初始消息与后续补充要整理资源、时长与偏好；缺信息时问一个关键问题，提供能直接点的下一步。',
 '3. 改目标沿用截止时间；工具能力不能实现5%时，先说明支持范围，不承诺后跑10%。',
 '4. 保留本次基线，修复后整套重跑；另采集未见用户的真实表达和独立试用记录。','',
 '## 全部场景结果','', '| 编号 | 场景 | 跑通 | 具体检查 | 宿主审查依据 |','|---|---|---|---|---|']
 for c,g in zip(cases,grades):
  n=sum(x['passed'] for x in g['checks']);note=reviews.get(c['id'],{}).get('reason','未审查')
  md.append(f'| {c["id"]} | {c["title"]} | {yn(g["passed"])} | {n}/{len(g["checks"])} | {note} |')
 for c,g in zip(browser_cases,bg):md.append(f'| {c["id"]} | {c["title"]} | {yn(g["passed"])} | 实际界面 | {g["observation"]} |')
 md+=['','完整输入见 [CASEBOOK.md](CASEBOOK.md)；逐条真实消息与答复见 [DIALOGUES.md](DIALOGUES.md)。JSON评分保留在 scores.json，原始SQLite、请求与检查点在父目录对应场景中。','']
 (out/'RESULTS.md').write_text('\n'.join(md))
 lines=['# 逐条消息和实际答复','','固定夹具、工具卡生成的命令、真实模型答复和本机回执均保留。不得把本机回执称为模型理解成功。','']
 cards=[]
 esc=html.escape
 for c,g in zip(cases,grades):
  state_path=root/c['id']/'final-state.json';p=read(state_path) if state_path.exists() else {};msgs=p.get('group_messages',[])
  lines += [f'## {c["id"]} {c["title"]}：{yn(g["passed"])}','',f'初始用户原话：{c["opening"]}','',f'期望：{c["good_response"]}','',f'审查：{reviews.get(c["id"],{}).get("reason","未审查")}','']
  dialogue=''
  for m in msgs:
   source='真实模型' if m.get('request_id') else '本机程序回执'
   lines += [f'用户：{m["user_text"]}','',f'实际答复（{source}）：','',m['answer'],'']
   dialogue+=f'<div class="msg user"><small>用户说</small><p>{esc(m["user_text"])}</p></div><div class="msg"><small>{source}</small><p>{esc(m["answer"])}</p></div>'
  fails=[f'{x["kind"]}：预期{x["expected"]}，实际{x["actual"]}' for x in g['checks'] if not x['passed']]
  universal=[k for k,v in g['universal_audit']['checks'].items() if not v]
  debug=json.dumps({'failed_checks':fails,'failed_universal_audits':universal,'numeric':g['universal_audit']['numeric_status']},ensure_ascii=False,indent=2)
  cards.append(f'<details class="case" data-status="{g["status"]}" data-lane="{"live" if c["live"] else "local"}"><summary><b>{c["id"]} {esc(c["title"])}</b><span class="{g["status"]}">{yn(g["passed"])}</span></summary><div class="inside"><small>{esc(c["persona"])} · {esc(c["category"])} · {"真实Codex交互" if c["live"] else "本机回执与控制"}</small><h3>用户刚来时说</h3><p class="opening">{esc(c["opening"])}</p><h3>怎样才算帮到了他</h3><p>{esc(c["good_response"])}</p><h3>这次观察</h3><p>{esc(reviews.get(c["id"],{}).get("reason","未审查"))}</p><h3>实际聊天</h3>{dialogue}<details><summary>核对实际状态</summary><pre>{esc(debug)}</pre></details></div></details>')
 for c,g in zip(browser_cases,bg):
  screenshots=''
  for name in g.get('screenshots',[]):
   (out/name).write_bytes((br/name).read_bytes());screenshots+=f'<a href="{esc(name)}"><img src="{esc(name)}" alt="{c["id"]}实际验收截图" loading="lazy"></a>'
  cards.append(f'<details class="case" data-status="{g["status"]}" data-lane="browser"><summary><b>{c["id"]} {esc(c["title"])}</b><span class="{g["status"]}">{yn(g["passed"])}</span></summary><div class="inside"><small>实际浏览器操作 · 固定程序夹具</small><h3>第一次用的人要做什么</h3><p>{esc(c["task"])}</p><h3>怎样才算顺手</h3><p>{esc(c["pass"])}</p><h3>实际观察</h3><p>{esc(g["observation"])}</p><div class="proofs">{screenshots}</div></div></details>')
 (out/'DIALOGUES.md').write_text('\n'.join(lines))
 page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>第一次用 LabCouncil · 测试集与首轮结果</title><style>
+:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#f8f8f5;color:#252b27;font:16px/1.7 system-ui,-apple-system,sans-serif}main{max-width:1040px;margin:auto;padding:48px 24px}small{color:#646e66}h1{font-size:34px;line-height:1.25;font-weight:650;margin:10px 0 16px}h2{font-size:23px;margin-top:36px}h3{font-size:16px;margin:24px 0 8px}p{margin:8px 0 16px}.intro{max-width:770px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:28px 0}.metric{background:white;padding:20px;border:1px solid #e5e8e1;border-radius:14px}.metric strong{display:block;font-size:29px;line-height:1.3}.metric small{display:block;margin-top:7px}.notice{padding:20px 24px;background:#fff3e5;border-radius:12px;border-left:4px solid #cb8950}.notice p:last-child{margin:0}a{color:#345e41}nav{display:flex;gap:8px;flex-wrap:wrap;position:sticky;top:0;padding:14px 0;background:#f8f8f5;z-index:1}button{font:inherit;border:1px solid #dce1d7;background:white;border-radius:30px;padding:7px 16px;cursor:pointer}button[aria-pressed=true]{background:#344d3b;color:white;border-color:#344d3b}.case{background:white;border:1px solid #e2e6de;border-radius:12px;margin:10px 0}.case>summary{padding:19px 20px;display:flex;align-items:center;justify-content:space-between;gap:20px;cursor:pointer;list-style:none}.case>summary:before{content:'＋';color:#738374}.case[open]>summary:before{content:'－'}.case summary b{font-weight:560;flex:1}.case summary span{font-size:13px;white-space:nowrap}.pass{color:#376944}.fail{color:#a75334}.inside{padding:0 24px 24px}.opening{padding:15px 18px;border-radius:10px;background:#edf1e7}.msg{padding:14px 18px;background:#f6f6f3;border-radius:12px;margin:12px 0;max-width:94%}.msg p{white-space:pre-wrap;margin:4px 0}.msg.user{margin-left:auto;background:#edf3e7}.proofs{display:flex;gap:15px;flex-wrap:wrap}.proofs img{max-width:100%;width:360px;height:auto;max-height:680px;object-fit:contain;object-position:top;border-radius:8px;border:1px solid #ddd}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}footer{color:#646e66;font-size:14px;padding:30px 0}.case[hidden]{display:none}@media(max-width:680px){main{padding:26px 16px}.metrics{grid-template-columns:1fr 1fr}h1{font-size:28px}.inside{padding:0 16px 16px}.case>summary{padding:16px 12px}.metric{padding:16px}.metric strong{font-size:24px}}</style><main>
+<small>LabCouncil / 菜鸟测评 v1 / 冻结后首次有效基线</small><h1>如果第一次用的人这样说，<br>我们接得住吗？</h1><p class="intro">不用权限口令，不用写实验方案，也不知道按钮背后的规则。48个场景先固定，再实测当前平台；点击下方任一项，可以看用户原话、期望、实际答复与失败原因。</p>
+<div class="metrics">METRICS</div><div class="notice"><p><strong>现在还不能说“第一次用也能顺利跑通”。</strong></p><p>“别忙了，等我回来再弄”没有暂停；“别再花钱”仍尝试调用模型。真实实验有结果，但自动延长了计时，5%的安排跑成10%。这些都留在失败里。</p></div>
+<h2>先看具体场景</h2><p><small>48个都是合成场景；宿主模拟使用，并非48名真人试用。界面通过率与研究交互通过率分别展示。严格通过要求状态、约束和用户帮助同时成立。</small></p><nav aria-label="筛选测试场景"><button aria-pressed="true" data-filter="all">全部48条</button><button aria-pressed="false" data-filter="fail">未跑通24条</button><button aria-pressed="false" data-filter="live">真实模型8条</button><button aria-pressed="false" data-filter="browser">浏览器8条</button></nav><p id="visible-count" aria-live="polite">显示48条场景</p>CARDS
+<footer><p>具体状态检查100/112，关键检查76/80；局部检查不是完整跑通率。评分器17条预先控制＋8条审查补充控制，共25条通过；原始输入与112项检查未改。23次真实CLI请求完成；0次公开论文读取。没有开放仓库复现、真人试用或独立盲审。</p><p><a href="CASEBOOK.md">完整测试集</a> · <a href="RESULTS.md">完整结果</a> · <a href="DIALOGUES.md">全部实际对话</a> · <a href="scores.json">原始分数</a></p><p>首轮无效驱动运行与全部失败保留。下一轮应修复后整套重跑，并采集未见用户的真实表达。</p></footer></main><script>document.querySelectorAll('nav button').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('nav button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));let count=0;document.querySelectorAll('.case').forEach(c=>{const f=b.dataset.filter;c.hidden=!(f==='all'||f==='fail'&&c.dataset.status!=='pass'||c.dataset.lane===f);if(!c.hidden)count++});document.querySelector('#visible-count').textContent='显示'+count+'条场景'}));</script></html>'''.replace('\n+','\n')
 metrics=f'<div class="metric"><strong>{score["score"]} / 100</strong><small>整体 · {cp+bp}/48跑通</small></div>'
 for name,v in lanes.items():metrics+=f'<div class="metric"><strong>{v["passed"]}/{v["total"]}</strong><small>{name}</small></div>'
 page=page.replace('METRICS',metrics).replace('CARDS','\n'.join(cards)).replace('未跑通24条',f'未跑通{48-cp-bp}条')
 (out/'index.html').write_text(page)
 print(json.dumps({'review':str(out),'passed':cp+bp,'total':48,'score':score['score'],'lanes':lanes},ensure_ascii=False))
if __name__=='__main__':main()
