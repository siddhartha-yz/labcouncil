"use strict";
const content = document.querySelector("#content");
const message = document.querySelector("#message");
let currentProject = null;
let currentMeeting = null;
const drafts = new Map();
let navigation = 0;
const roles = {researcher:"资料角色",executor:"计算角色",reviewer:"复核角色"};
const roleName=(role,simulated=true)=>roles[role]+(simulated?" · 模拟":" · 真实 Flash");
function setMode(real){document.querySelector(".badge").textContent=real?"合成案例 · 真实 Flash":"本地模拟原型";document.querySelector("footer").textContent=real?"角色与问答使用真实 DeepSeek Flash。数据为合成，工具范围固定；不是自主科研或论文复现。":"当前角色和答复由固定程序模拟。没有模型调用、文献检索或真实科研结论。";}
function caseNumbers(a){if(a.body.simulation!==false||!a.body.results)return "";return `<div class="muted">预测与测试数据的偏差（越小越接近）。每行是一次独立重复：</div><ul>${a.body.results.map(r=>`<li>重复 ${r.seed}：平方误差 ${r.metrics.linear.mse.toFixed(3)}，只猜均值 ${r.metrics.baseline.mse.toFixed(3)}；绝对误差 ${r.metrics.linear.mae.toFixed(3)}；典型偏差（中位数） ${r.metrics.linear.median_absolute_error.toFixed(3)}</li>`).join("")}</ul>`;}
function caseInputs(a){const p=a.body.parameters;if(a.body.simulation!==false||!p)return "";return `<p class="notice">实际工具输入：${p.test_outlier_fraction===0?"干净测试标签":`测试标签 ${Math.round(p.test_outlier_fraction*100)}% 加入异常点`}；${p.seeds.length} 次重复。模型文字需与这些输入核对。</p>`;}
function requestPanel(p){if(p.execution.mode!=="real_case")return "";const bg=p.model_requests.filter(r=>r.category==="background").length,qa=p.model_requests.length-bg;const known=p.model_requests.filter(r=>r.usage&&Number.isFinite(r.usage.total_tokens)),unknown=p.model_requests.length-known.length;return `<section class="panel"><h2>真实模型调用与用量</h2><p>后台请求 ${bg}/${p.execution.api_budget} · 组会请求 ${qa}/${p.execution.qa_api_budget}。失败和超时也占次数，不自动重试。</p><p>已知用量 ${known.reduce((n,r)=>n+r.usage.total_tokens,0)} tokens${unknown?`；${unknown} 次用量尚未知`:""}。人民币费用未知；没有 token 硬上限。</p><details><summary>查看每次请求和实际返回</summary><ul>${p.model_requests.map(r=>`<li><a href="/api/model-requests/${esc(r.id)}" target="_blank" rel="noopener">${esc(r.phase)} · ${esc(r.status)}</a>${r.error?`：${esc(r.error)}`:""}</li>`).join("")}</ul></details><details><summary>查看独立保存的工具结果</summary><ul>${(p.tool_operations||[]).map(o=>`<li><a href="/api/tool-operations/${esc(o.id)}" target="_blank" rel="noopener">${esc(o.body.tool)} · 完整输入和结果</a></li>`).join("")||"<li>早期记录仅保存在角色原始证据中。</li>"}</ul></details></section>`;}
const statuses = {queued:"等待执行",running:"正在运行",completed:"已完成",failed:"运行失败",cancelled:"已被新计划取代"};
const esc = x => String(x ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const when = t => new Date(t*1000).toLocaleString("zh-CN");
const selectedName = (s,real=false) => real?(s==="outlier"?"测试标签含约一成异常点":"干净数据"):(s === "outlier" ? "含一个异常点" : "平稳数据");
function announce(text, error=false) {message.textContent=text;message.className=error?"error":"";}
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {cache:"no-store"} : {method:"POST",headers:{"Content-Type":"application/json","X-LabCouncil":"local"},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "操作失败，请刷新后再试");
  return result;
}
async function action(event, work) {
  event.preventDefault();
  const button=event.currentTarget.querySelector("button[type=submit]") || event.currentTarget;
  if (button.disabled) return;
  button.disabled=true;
  try {await work();} catch(error) {announce(error.message,true);} finally {button.disabled=false;}
}
async function sidebar() {
  const result=await api("/api/projects");
  const nav=document.querySelector("#projects");
  nav.innerHTML=result.projects.length ? result.projects.map(p=>`<button class="project-link ${p.id===currentProject?"active":""}" data-project="${esc(p.id)}">${esc(p.title)}<small>第 ${p.version} 轮 · ${p.paused?"已暂停":p.mode==="real_case"?"真实 Flash 案例":"模拟任务"}</small></button>`).join("") : '<p class="muted">还没有项目。先提交一个想法，走一遍组会流程。</p>';
  nav.querySelectorAll("[data-project]").forEach(b=>b.addEventListener("click",()=>showProject(b.dataset.project).catch(e=>announce(e.message,true))));
  return result.projects;
}
function scenarios(value="clean",real=false) {if(real)return `<option value="clean" ${value==="clean"?"selected":""}>干净测试数据：一次重复</option><option value="outlier" ${value==="outlier"?"selected":""}>测试集含异常点：三次重复</option>`;return `<option value="clean" ${value==="clean"?"selected":""}>平稳数据：5 个点</option><option value="outlier" ${value==="outlier"?"selected":""}>含异常点：最后一个点增加 6</option>`;}
function newProject() {
  navigation++;currentProject=null;currentMeeting=null;setMode(false);
  content.innerHTML=`<section class="hero"><p class="eyebrow">IDEA → EVIDENCE → MEETING</p><h1>把一个想法带进组会</h1><p>先走一遍：后台准备材料，你读报告、追问、确认下一步，研究组再继续。</p></section><div class="notice">选择模拟演示不用 API。真实 Flash 模式会调用本机已配置的 key，但仍限于这个合成计算案例，不能实现任意 idea。</div><form id="create" class="panel form-grid"><label class="wide">项目名称<input name="title" maxlength="120" required placeholder="例如：异常点会怎样影响拟合？"></label><label class="wide">研究想法与本轮要回答的问题<textarea name="idea" maxlength="4000" required placeholder="写清楚你想知道什么，以及什么结果能回答它。"></textarea></label><label>运行方式<select name="mode"><option value="simulation">模拟演示：不调用模型</option><option value="real_case">真实 Flash：合成研究案例</option></select></label><label>案例输入<select name="scenario">${scenarios()}</select></label><label>真实后台请求次数上限<input name="api_budget" type="number" min="0" max="100" value="12" required></label><label>真实组会请求次数上限<input name="qa_api_budget" type="number" min="0" max="100" value="1" required></label><label>准备组会材料的时间（本机时区）<input name="meeting_at" type="datetime-local"><span class="muted">可留空，随时手动开会。需 worker 在线。</span></label><label>后台角色任务总预算<input name="budget" type="number" min="0" max="100" value="9" required><span class="muted">每个角色执行一次计 1；每轮共 3。不是 token 或费用。</span></label><label>组会问答次数总预算<input name="qa_budget" type="number" min="0" max="100" value="6" required></label><div class="wide"><button class="primary" type="submit">创建项目，开始第一轮</button></div></form>`;
  document.querySelector("#create [name=mode]").addEventListener("change",e=>{const select=document.querySelector("#create [name=scenario]");select.innerHTML=scenarios(select.value,e.target.value==="real_case");});
  document.querySelector("#create").addEventListener("submit", e=>action(e,async()=>{
    const form=new FormData(e.currentTarget);
    const result=await api("/api/projects",{title:form.get("title"),idea:form.get("idea"),scenario:form.get("scenario"),mode:form.get("mode"),api_budget:Number(form.get("api_budget")),qa_api_budget:Number(form.get("qa_api_budget")),budget:Number(form.get("budget")),qa_budget:Number(form.get("qa_budget")),meeting_at:form.get("meeting_at")?new Date(form.get("meeting_at")).getTime()/1000:null});
    announce("项目已创建。worker 会依次准备输入、计算和复核；每轮做完后等待你的下一次决定。");
    await showProject(result.id);
  }));
  sidebar().catch(e=>announce(e.message,true));
}
function evidenceCards(artifacts) {
  return artifacts.map(a=>`<article class="card"><p class="role">${esc(roleName(a.role,a.body.simulation!==false))} · 第 ${a.version} 轮</p><h3>${a.role==="researcher"?"准备了什么":a.role==="executor"?"得到什么结果":"核对了什么"}</h3>${caseInputs(a)}<p>${esc(a.body.summary)}</p>${caseNumbers(a)}<p class="muted">${esc(a.body.simulation===false?"合成案例。数值复算与模型文字准确性分别检查。":a.role==="researcher"?"固定合成输入，没有论文来源。":a.role==="executor"?"在同一批数据上拟合和评分，尚未检查新数据。":"独立程序复算，只验证这批数据的算术。")}</p>${a.body.simulation===false?`<details><summary>模型给出的限制说明</summary><ul>${(a.body.report?.limitations||[a.body.limitation]).map(x=>`<li>${esc(x)}</li>`).join("")}</ul></details>`:""}<a href="/api/evidence/${esc(a.id)}" target="_blank" rel="noopener">打开原始证据 ↗</a></article>`).join("");
}
async function showProject(id) {
  const ticket=++navigation;
  currentProject=id;currentMeeting=null;
  const p=await api(`/api/projects/${id}`);
  if(ticket!==navigation)return;
  currentProject=id;currentMeeting=null;
  const real=p.execution.mode==="real_case";setMode(real);
  const tasks=p.tasks.filter(t=>t.version===p.version);
  const artifacts=p.artifacts.filter(a=>a.version===p.version);
  const pending=tasks.filter(t=>t.status==="queued").length;
  content.innerHTML=`<section class="hero"><p class="eyebrow">我的研究项目 · 第 ${p.version} 轮</p><h1>${esc(p.title)}</h1><p class="direction">${esc(p.idea)}</p><span class="pill">${esc(selectedName(p.scenario,real))}</span></section><div class="budget"><div><strong>${p.used} / ${p.budget}</strong><small>已用后台角色任务</small></div><div><strong>${p.qa_used} / ${p.qa_budget}</strong><small>已用组会问答次数</small></div><div><strong>${tasks.filter(t=>t.status==="completed").length} / 3</strong><small>本轮完成角色</small></div></div>${p.paused?'<div class="notice">项目已暂停，不会启动新任务。正在执行的短任务可以结束并保存。</div>':""}${pending&&p.used>=p.budget?'<div class="notice">后台角色任务预算已用完，剩余任务等待。你仍可读证据、开会，或在设置中增加预算。</div>':""}<div class="actions"><button class="primary" id="start-meeting">查看或开始本轮组会</button><button id="refresh">刷新进度</button><span class="muted">${p.meeting_at?`定时准备：${when(p.meeting_at)}`:"没有待执行的定时组会"}</span></div><div class="grid">${tasks.map(t=>`<article class="card"><p class="role">${esc(roleName(t.role,!real))}</p><span class="pill status-${esc(t.status)}">${esc(statuses[t.status])}</span><details><summary>本轮任务指令</summary><p class="muted direction">${esc(t.instruction)}</p></details>${t.error?`<p>${esc(t.error)}</p>`:""}</article>`).join("")}</div><div class="section-top"><h2>最新报告与证据</h2><span class="muted">${real?"真实模型与本地工具产物 · 合成数据":"全部为模拟角色产物"}</span></div>${real?'<div class="notice">数值复算通过仅说明计算一致。模型报告仍可能把输入场景说错；请结合实际工具输入和原始证据阅读。</div>':""}${artifacts.length?`<div class="grid">${evidenceCards(artifacts)}</div>`:'<div class="panel muted">还没有报告。如果状态一直等待，请按说明启动独立 worker。</div>'}<section class="panel"><h2>已保存的组会</h2><div class="history">${p.meetings.map(m=>`<div class="history-item"><div>第 ${m.version} 轮 · ${when(m.created)}<br><small class="muted">${m.status==="closed"?"决定已确认，会后任务已派发":"待你评审"}</small></div><button data-meeting="${esc(m.id)}">打开组会</button></div>`).join("")||'<p class="muted">组会开始后，报告会冻结为当时的版本。</p>'}</div></section>${requestPanel(p)}<details><summary>项目设置：暂停、预算与下次组会</summary><form id="configure" class="panel form-grid"><label>后台角色任务总上限<input type="number" name="budget" min="0" max="100" value="${p.budget}" required></label><label>组会问答次数总上限<input type="number" name="qa_budget" min="0" max="100" value="${p.qa_budget}" required></label><label>执行状态<select name="paused"><option value="false" ${!p.paused?"selected":""}>继续执行</option><option value="true" ${p.paused?"selected":""}>暂停新任务</option></select></label><label>准备组会时间（本机时区）<input type="datetime-local" name="meeting_at"><span class="muted">留空会取消尚未到时的安排。</span></label><div class="wide"><button type="submit">保存设置</button></div></form></details>`;
  document.querySelector("#start-meeting").addEventListener("click",e=>action(e,async()=>{const m=await api(`/api/projects/${id}/meeting`,{});await showMeeting(m.id);}));
  document.querySelector("#refresh").addEventListener("click",()=>showProject(id).catch(e=>announce(e.message,true)));
  content.querySelectorAll("[data-meeting]").forEach(b=>b.addEventListener("click",()=>showMeeting(b.dataset.meeting).catch(e=>announce(e.message,true))));
  document.querySelector("#configure").addEventListener("submit",e=>action(e,async()=>{const f=new FormData(e.currentTarget);await api(`/api/projects/${id}/configure`,{paused:f.get("paused")==="true",budget:Number(f.get("budget")),qa_budget:Number(f.get("qa_budget")),meeting_at:f.get("meeting_at")?new Date(f.get("meeting_at")).getTime()/1000:null});announce("设置已保存。");await showProject(id);}));
  await sidebar();
}
async function showMeeting(id) {
  const ticket=++navigation;
  currentMeeting=id;
  const m=await api(`/api/meetings/${id}`);
  if(ticket!==navigation)return;
  currentProject=m.project_id;currentMeeting=id;
  const s=m.snapshot;const real=s.simulation===false;setMode(real);
  const draft=drafts.get(id)||m.draft||{revision:0,instruction:real?"给测试标签加入约一成异常点，使用三个预设重复，比较三种误差并独立复算。只保留合成案例的有限结论。":"加入一个异常点，再比较误差，并复算关键结果。只保留这个小例子的结论。",scenario:"outlier"};
  const unfinished=s.tasks.filter(t=>t.status!=="completed");
  content.innerHTML=`<section class="hero"><p class="eyebrow">GROUP MEETING · 第 ${m.version} 轮</p><h1>先看证据，再定下一步</h1><p>做了什么、能说明什么、还有什么没做。你的确认会成为下一轮任务。</p><span class="pill">${m.status==="closed"?"组会已结束":"等待你评审"}</span></section><div class="actions"><button id="back">返回项目最新进度</button><span class="muted">报告截止：${when(s.cutoff)}</span></div><div class="notice">${esc(s.notice)}${unfinished.length?` 截止时还有 ${unfinished.length} 个角色未完成；本场材料并不完整。`:""}</div><div class="grid">${evidenceCards(s.artifacts)}</div>${!s.artifacts.length?'<div class="panel muted">开会时还没有产物。你可以返回项目读最新报告；本场快照不会自动补入它们。</div>':""}<section class="panel"><h2>追问与讨论</h2><p class="muted">${real?"当前答复使用真实 Flash，只依据这场快照。一次追问占一次真实组会请求；讨论不会派单。":"当前答复是程序模板，会引用快照；并非语言模型对任意问题的回答。讨论不会自动改变任务。"}</p><div id="discussion">${m.discussion.map(d=>`<div class="conversation"><strong>你的问题</strong><p>${esc(d.question)}</p><strong>${real?"真实 Flash 答复":"模拟角色答复"}</strong><p>${esc(d.answer)}</p></div>`).join("")||'<p class="muted">可以从“这些结果能说明什么？”开始。</p>'}</div>${m.status!=="closed"?`<form id="ask"><label>向组会追问<textarea name="question" maxlength="1000" required placeholder="例如：复核检查了哪些证据？"></textarea></label><button type="submit">${real?"向 Flash 追问并保存答复":"保存问题，查看模拟答复"}</button></form>`:""}</section><section class="panel"><h2>${m.decision?"已确认的下一轮决定":"编辑下一轮方向"}</h2>${m.decision?`<p class="direction">${esc(m.decision.instruction)}</p><p>第 ${m.decision.to_version} 轮 · ${esc(selectedName(m.decision.scenario,real))}</p><p class="muted">决定已保存。重复确认不会再派单。</p>`:`<p class="muted">自由文字会保存为任务指令。${real?"真实模型只调用本案例的受控工具，依据所选场景计算；不会自动编写新实验。":"模拟计算只执行所选的数据场景；不是自动编写新实验。"}</p><form id="confirm"><label>下一轮要做什么<textarea name="instruction" maxlength="4000" required>${esc(draft.instruction)}</textarea></label><label>下一轮演示输入<select name="scenario">${scenarios(draft.scenario,real)}</select></label><p id="draft-status" class="muted">${m.draft?`草稿已保存 · 版本 ${m.draft.revision} · ${when(m.draft.edited)}`:"草稿尚未保存。保存草稿不会派发任务；确认决定才会。"}</p><div class="actions"><button id="save-draft" type="button">保存草稿，不派单</button><button class="primary" type="submit">确认决定并启动第 ${m.version+1} 轮</button></div></form>`}</section>`;
  document.querySelector("#back").addEventListener("click",()=>showProject(m.project_id).catch(e=>announce(e.message,true)));
  const ask=document.querySelector("#ask");
  if(ask) ask.addEventListener("submit",e=>action(e,async()=>{const f=new FormData(e.currentTarget);if(real)announce("正在依据快照向 Flash 追问，请稍候；本次会计入调用次数。");await api(`/api/meetings/${id}/ask`,{question:f.get("question")});await showMeeting(id);announce("追问已保存；下一轮方向仍需你单独确认。");}));
  const confirm=document.querySelector("#confirm");
  if(confirm) confirm.addEventListener("input",()=>{const f=new FormData(confirm);drafts.set(id,{instruction:f.get("instruction"),scenario:f.get("scenario"),revision: (drafts.get(id)||draft).revision||0});document.querySelector("#draft-status").textContent="内容已编辑，尚未保存这次修改。";});
  const saveDraft=document.querySelector("#save-draft");
  if(saveDraft) saveDraft.addEventListener("click",e=>action(e,async()=>{const f=new FormData(confirm);const saved=await api(`/api/meetings/${id}/draft`,{expected_revision:(drafts.get(id)||draft).revision||0,instruction:f.get("instruction"),scenario:f.get("scenario")});drafts.set(id,saved);await showMeeting(id);announce("草稿已保存，没有派发新任务。确认决定后才会开始下一轮。");}));
  if(confirm) confirm.addEventListener("submit",e=>action(e,async()=>{const f=new FormData(e.currentTarget);const d=await api(`/api/meetings/${id}/confirm`,{expected_version:m.version,instruction:f.get("instruction"),scenario:f.get("scenario")});announce(`决定已确认，第 ${d.to_version} 轮任务已派发。`);await showMeeting(id);}));
  await sidebar();
}
document.querySelector("#new-project").addEventListener("click",newProject);
if(location.protocol==="file:"){document.querySelector("#new-project").disabled=true;announce("你正在预览 HTML 文件。请从本地服务地址打开，才能连接数据库和后台 worker。",true);}else (async()=>{try {const list=await sidebar();if(list.length)await showProject(list[0].id);else newProject();}catch(e){announce(`连接本地服务失败：${e.message}`,true);}})();
setInterval(async()=>{if(!currentProject||currentMeeting||document.activeElement?.matches("input,textarea,select")||document.querySelector("details[open]"))return;try{await showProject(currentProject);}catch(e){announce(e.message,true);}},4000);
