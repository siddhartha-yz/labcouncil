"use strict";
const content = document.querySelector("#content");
const message = document.querySelector("#message");
let currentProject = null;
let currentMeeting = null;
const drafts = new Map();
let navigation = 0;
const roles = {researcher:"资料角色 · 模拟",executor:"计算角色 · 模拟",reviewer:"复核角色 · 模拟"};
const statuses = {queued:"等待执行",running:"正在运行",completed:"已完成",failed:"运行失败",cancelled:"已被新计划取代"};
const esc = x => String(x ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const when = t => new Date(t*1000).toLocaleString("zh-CN");
const selectedName = s => s === "outlier" ? "含一个异常点" : "平稳数据";
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
  nav.innerHTML=result.projects.length ? result.projects.map(p=>`<button class="project-link ${p.id===currentProject?"active":""}" data-project="${esc(p.id)}">${esc(p.title)}<small>第 ${p.version} 轮 · ${p.paused?"已暂停":"模拟任务"}</small></button>`).join("") : '<p class="muted">还没有项目。先提交一个想法，走一遍组会流程。</p>';
  nav.querySelectorAll("[data-project]").forEach(b=>b.addEventListener("click",()=>showProject(b.dataset.project).catch(e=>announce(e.message,true))));
  return result.projects;
}
function scenarios(value="clean") {return `<option value="clean" ${value==="clean"?"selected":""}>平稳数据：5 个点</option><option value="outlier" ${value==="outlier"?"selected":""}>含异常点：最后一个点增加 6</option>`;}
function newProject() {
  navigation++;currentProject=null;currentMeeting=null;
  content.innerHTML=`<section class="hero"><p class="eyebrow">IDEA → EVIDENCE → MEETING</p><h1>把一个想法带进组会</h1><p>先走一遍：后台准备材料，你读报告、追问、确认下一步，研究组再继续。</p></section><div class="notice">当前是流程演示：你填写的想法会被保存，计算仍限定为两种合成数据。接入真实模型和研究工具后，才能按任意 idea 开展工作。</div><form id="create" class="panel form-grid"><label class="wide">项目名称<input name="title" maxlength="120" required placeholder="例如：异常点会怎样影响拟合？"></label><label class="wide">研究想法与本轮要回答的问题<textarea name="idea" maxlength="4000" required placeholder="写清楚你想知道什么，以及什么结果能回答它。"></textarea></label><label>演示输入<select name="scenario">${scenarios()}</select></label><label>准备组会材料的时间（本机时区）<input name="meeting_at" type="datetime-local"><span class="muted">可留空，随时手动开会。需 worker 在线。</span></label><label>后台模拟任务总预算<input name="budget" type="number" min="0" max="100" value="9" required><span class="muted">每个角色执行一次计 1；每轮共 3。不是 token 或费用。</span></label><label>组会模拟问答总预算<input name="qa_budget" type="number" min="0" max="100" value="6" required></label><div class="wide"><button class="primary" type="submit">创建项目，开始第一轮</button></div></form>`;
  document.querySelector("#create").addEventListener("submit", e=>action(e,async()=>{
    const form=new FormData(e.currentTarget);
    const result=await api("/api/projects",{title:form.get("title"),idea:form.get("idea"),scenario:form.get("scenario"),budget:Number(form.get("budget")),qa_budget:Number(form.get("qa_budget")),meeting_at:form.get("meeting_at")?new Date(form.get("meeting_at")).getTime()/1000:null});
    announce("项目已创建。worker 会依次准备输入、计算和复核；每轮做完后等待你的下一次决定。");
    await showProject(result.id);
  }));
  sidebar().catch(e=>announce(e.message,true));
}
function evidenceCards(artifacts) {
  return artifacts.map(a=>`<article class="card"><p class="role">${esc(roles[a.role])} · 第 ${a.version} 轮</p><h3>${a.role==="researcher"?"准备了什么":a.role==="executor"?"得到什么结果":"核对了什么"}</h3><p>${esc(a.body.summary)}</p><p class="muted">${esc(a.role==="researcher"?"固定合成输入，没有论文来源。":a.role==="executor"?"在同一批数据上拟合和评分，尚未检查新数据。":"独立程序复算，只验证这批数据的算术。")}</p><a href="/api/evidence/${esc(a.id)}" target="_blank" rel="noopener">打开原始证据 ↗</a></article>`).join("");
}
async function showProject(id) {
  const ticket=++navigation;
  currentProject=id;currentMeeting=null;
  const p=await api(`/api/projects/${id}`);
  if(ticket!==navigation)return;
  currentProject=id;currentMeeting=null;
  const tasks=p.tasks.filter(t=>t.version===p.version);
  const artifacts=p.artifacts.filter(a=>a.version===p.version);
  const pending=tasks.filter(t=>t.status==="queued").length;
  content.innerHTML=`<section class="hero"><p class="eyebrow">我的研究项目 · 第 ${p.version} 轮</p><h1>${esc(p.title)}</h1><p class="direction">${esc(p.idea)}</p><span class="pill">${esc(selectedName(p.scenario))}</span></section><div class="budget"><div><strong>${p.used} / ${p.budget}</strong><small>已用后台模拟任务</small></div><div><strong>${p.qa_used} / ${p.qa_budget}</strong><small>已用组会模拟问答</small></div><div><strong>${tasks.filter(t=>t.status==="completed").length} / 3</strong><small>本轮完成角色</small></div></div>${p.paused?'<div class="notice">项目已暂停，不会启动新任务。正在执行的短任务可以结束并保存。</div>':""}${pending&&p.used>=p.budget?'<div class="notice">后台模拟预算已用完，剩余任务等待。你仍可读证据、开会，或在设置中增加预算。</div>':""}<div class="actions"><button class="primary" id="start-meeting">查看或开始本轮组会</button><button id="refresh">刷新进度</button><span class="muted">${p.meeting_at?`定时准备：${when(p.meeting_at)}`:"没有待执行的定时组会"}</span></div><div class="grid">${tasks.map(t=>`<article class="card"><p class="role">${esc(roles[t.role])}</p><span class="pill status-${esc(t.status)}">${esc(statuses[t.status])}</span><p class="muted direction">${esc(t.instruction)}</p>${t.error?`<p>${esc(t.error)}</p>`:""}</article>`).join("")}</div><div class="section-top"><h2>最新报告与证据</h2><span class="muted">全部为模拟角色产物</span></div>${artifacts.length?`<div class="grid">${evidenceCards(artifacts)}</div>`:'<div class="panel muted">还没有报告。如果状态一直等待，请按说明启动独立 worker。</div>'}<section class="panel"><h2>已保存的组会</h2><div class="history">${p.meetings.map(m=>`<div class="history-item"><div>第 ${m.version} 轮 · ${when(m.created)}<br><small class="muted">${m.status==="closed"?"决定已确认，会后任务已派发":"待你评审"}</small></div><button data-meeting="${esc(m.id)}">打开组会</button></div>`).join("")||'<p class="muted">组会开始后，报告会冻结为当时的版本。</p>'}</div></section><details><summary>项目设置：暂停、预算与下次组会</summary><form id="configure" class="panel form-grid"><label>后台模拟任务总上限<input type="number" name="budget" min="0" max="100" value="${p.budget}" required></label><label>组会模拟问答总上限<input type="number" name="qa_budget" min="0" max="100" value="${p.qa_budget}" required></label><label>执行状态<select name="paused"><option value="false" ${!p.paused?"selected":""}>继续执行</option><option value="true" ${p.paused?"selected":""}>暂停新任务</option></select></label><label>准备组会时间（本机时区）<input type="datetime-local" name="meeting_at"><span class="muted">留空会取消尚未到时的安排。</span></label><div class="wide"><button type="submit">保存设置</button></div></form></details>`;
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
  const s=m.snapshot;
  const draft=drafts.get(id)||m.draft||{revision:0,instruction:"加入一个异常点，再比较误差，并复算关键结果。只保留这个小例子的结论。",scenario:"outlier"};
  const unfinished=s.tasks.filter(t=>t.status!=="completed");
  content.innerHTML=`<section class="hero"><p class="eyebrow">GROUP MEETING · 第 ${m.version} 轮</p><h1>先看证据，再定下一步</h1><p>做了什么、能说明什么、还有什么没做。你的确认会成为下一轮任务。</p><span class="pill">${m.status==="closed"?"组会已结束":"等待你评审"}</span></section><div class="actions"><button id="back">返回项目最新进度</button><span class="muted">报告截止：${when(s.cutoff)}</span></div><div class="notice">${esc(s.notice)}${unfinished.length?` 截止时还有 ${unfinished.length} 个角色未完成；本场材料并不完整。`:""}</div><div class="grid">${evidenceCards(s.artifacts)}</div>${!s.artifacts.length?'<div class="panel muted">开会时还没有产物。你可以返回项目读最新报告；本场快照不会自动补入它们。</div>':""}<section class="panel"><h2>追问与讨论</h2><p class="muted">当前答复是程序模板，会引用快照；并非语言模型对任意问题的回答。讨论不会自动改变任务。</p><div id="discussion">${m.discussion.map(d=>`<div class="conversation"><strong>你的问题</strong><p>${esc(d.question)}</p><strong>模拟角色答复</strong><p>${esc(d.answer)}</p></div>`).join("")||'<p class="muted">可以从“这些结果能说明什么？”开始。</p>'}</div>${m.status!=="closed"?'<form id="ask"><label>向组会追问<textarea name="question" maxlength="1000" required placeholder="例如：复核检查了哪些证据？"></textarea></label><button type="submit">保存问题，查看模拟答复</button></form>':""}</section><section class="panel"><h2>${m.decision?"已确认的下一轮决定":"编辑下一轮方向"}</h2>${m.decision?`<p class="direction">${esc(m.decision.instruction)}</p><p>第 ${m.decision.to_version} 轮 · ${esc(selectedName(m.decision.scenario))}</p><p class="muted">决定已保存。重复确认不会再派单。</p>`:`<p class="muted">自由文字会保存为任务指令。模拟计算目前只执行下面选择的数据场景；不是自动编写新实验。</p><form id="confirm"><label>下一轮要做什么<textarea name="instruction" maxlength="4000" required>${esc(draft.instruction)}</textarea></label><label>下一轮演示输入<select name="scenario">${scenarios(draft.scenario)}</select></label><p id="draft-status" class="muted">${m.draft?`草稿已保存 · 版本 ${m.draft.revision} · ${when(m.draft.edited)}`:"草稿尚未保存。保存草稿不会派发任务；确认决定才会。"}</p><div class="actions"><button id="save-draft" type="button">保存草稿，不派单</button><button class="primary" type="submit">确认决定并启动第 ${m.version+1} 轮</button></div></form>`}</section>`;
  document.querySelector("#back").addEventListener("click",()=>showProject(m.project_id).catch(e=>announce(e.message,true)));
  const ask=document.querySelector("#ask");
  if(ask) ask.addEventListener("submit",e=>action(e,async()=>{const f=new FormData(e.currentTarget);await api(`/api/meetings/${id}/ask`,{question:f.get("question")});await showMeeting(id);announce("追问已保存；下一轮方向仍需你单独确认。");}));
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
