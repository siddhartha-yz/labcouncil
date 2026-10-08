"use strict";
const content = document.querySelector("#content"), message = document.querySelector("#message");
let currentProject = null, navigation = 0;
let projectData = null, meetingData = [], refreshing = false;
let transcriptSignature = "", setupSettings = {}, profileTab = "activity", profileSignature = "";
const questionDrafts = new Map();
let noticeTimer = null;
const pendingSends = new Map();
const stopRequests = new Map();
const demoOpening = new Set();
const stopping = new Set();
const sending = new Set();
const entryMarkup = new WeakMap();
let profileReturnFocus = null;
// Tab-local drafts survive reloads, stay separate by group, and never enter the API.
try {
  for (const [key,value] of JSON.parse(sessionStorage.getItem("labcouncil-drafts") || "[]")) {
    if (typeof key === "string" && typeof value === "string") questionDrafts.set(key,value.slice(0,4000));
  }
  for (const [key,value] of JSON.parse(sessionStorage.getItem("labcouncil-pending") || "[]")) {
    if (typeof key === "string" && typeof value?.message === "string" && typeof value.message_id === "string")
      pendingSends.set(key,{...value,error:"页面已刷新，正在核对已保存的消息"});
  }
  for (const [key,value] of JSON.parse(sessionStorage.getItem("labcouncil-stop-pending") || "[]")) {
    if(typeof key === "string" && value?.message === "先停一下" && typeof value.message_id === "string") stopRequests.set(key,value);
  }
} catch (_) { /* Storage may be disabled or contain an older format. */ }
function saveDraft(key,value) {
  if(value) questionDrafts.set(key,value); else questionDrafts.delete(key);
  try { sessionStorage.setItem("labcouncil-drafts",JSON.stringify([...questionDrafts])); } catch (_) { /* Keep in memory. */ }
}
function savePending() {
  try { sessionStorage.setItem("labcouncil-pending",JSON.stringify([...pendingSends])); } catch (_) { /* Keep in memory. */ }
}

const esc = x => String(x ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "\"": "&quot;",
  "'": "&#39;"
}[c]));
const when = t => new Date(t * 1000).toLocaleString("zh-CN");
const states = {
  queued: "等待",
  running: "进行中",
  completed: "完成",
  failed: "失败",
  cancelled: "已停止启动"
};
const roles = {
  researcher: "准备输入",
  executor: "计算实验",
  reviewer: "独立复算"
};
const defaultBrief = () => ({
  idea: "",
  resources: "",
  requirements: "",
  permissions: {
    model_calls: false,
    local_compute: true,
    public_research: false,
    retry_public_reads: false
  },
  work_time: { duration_minutes: 120 }
});
function announce(text, error = false) {
  clearTimeout(noticeTimer);
  message.textContent = text;
  message.className = error ? "error" : "";
  if (text && !error) noticeTimer = setTimeout(() => { message.textContent = ""; }, 5000);
}
function backendLabel(backend) {
  return backend === "codex_cli" ? "Codex CLI · gpt-6.1-sol · high" : "DeepSeek Flash";
}
function backendSelect() {
  return '<label>模型后台<select name="backend"><option value="codex_cli">Codex CLI · gpt-6.1-sol · high（本机登录）</option><option value="deepseek">DeepSeek Flash（本地 key）</option></select></label>';
}
function modeLabel(real, research = false, backend = "deepseek") {
  document.querySelector("footer").textContent = "";
  if (!projectData) document.querySelector("#work-status").textContent=(real ? "" : "程序演示 · ")+"随时聊聊";
}
async function api(path, body) {
  let response;
  try { response = await fetch(path, body === undefined ? { cache: "no-store" } : {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-LabCouncil": "local"
    },
    body: JSON.stringify(body)
  }); } catch (_) { throw new Error("暂时连不上本机服务，请确认服务还在运行"); }
  let result;
  try { result=await response.json(); } catch (_) { throw new Error("没有收到完整的服务答复，原消息仍会保留"); }
  if (!response.ok)
    throw new Error(result.error || "操作失败");
  return result;
}
async function action(e, work) {
  e.preventDefault();
  const b = e.currentTarget.querySelector?.("button[type=submit]") || e.currentTarget;
  if (b.disabled)
    return;
  b.disabled = true;
  try {
    await work();
  } catch (error) {
    announce(error.message, true);
  } finally {
    b.disabled = false;
    if (b.isConnected && b.closest("#composer")) setComposer();
  }
}
async function sidebar() {
  const r = await api("/api/projects");
  document.querySelector("#projects").innerHTML = r.projects.map(p => `<button class="project-link ${p.id === currentProject ? "active" : ""}" data-project="${esc(p.id)}"><span class="group-icon" aria-hidden="true"></span><span class="project-copy"><strong>${esc(p.title)}</strong><small>${p.mode === "simulation" ? "程序演示 · 不调用模型" : p.paused ? "已暂停" : "研究群"}</small></span></button>`).join("") || '<p class="empty-list">还没有研究群</p>';
  document.querySelectorAll("[data-project]").forEach(b => b.addEventListener("click", () => showProject(b.dataset.project).catch(e => announce(e.message, true))));
  filterGroups();
  return r.projects;
}
function filterGroups() {
  const query = document.querySelector("#group-search").value.trim().toLowerCase();
  document.querySelectorAll(".project-link").forEach(b => { b.hidden = !b.textContent.toLowerCase().includes(query); });
}
function scenarioOptions(s = "clean", real = false) {
  return `<option value="clean" ${ s === "clean" ? "selected" : "" }>${ real ? "干净测试数据，一次重复" : "平稳数据" }</option><option value="outlier" ${ s === "outlier" ? "selected" : "" }>${ real ? "测试标签约一成异常，三次重复" : "含异常点" }</option>`;
}
function executorSettings(p = null) {
  const real = p ? p.execution.mode !== "simulation" : false;
  return `<details><summary>当前执行器与实验设置</summary><p class="muted">研究模式：每步由所选模型根据输入与已保存资料选择检索、读摘要、读仓库 README 或准备组会，每轮最多六步。仅支持已接入的本地合成计算，不会运行任意仓库代码。固定案例保留用于比较。</p>${ !p ? "<label>项目名称（可选）<input name=\"title\" maxlength=\"120\" placeholder=\"留空时使用 idea 开头\"></label>" : "" }${ p ? `<p>${ p.execution.mode === "research" ? backendLabel(p.execution.backend) + "逐步研究" : real ? backendLabel(p.execution.backend) + "与固定工具" : "固定程序流程演示" }；执行器在项目创建时选择。</p>` : `<label>执行器<select name="mode"><option value="simulation">流程演示，不调用模型</option><option value="real_case">固定合成计算</option><option value="research">逐步研究</option></select></label>${backendSelect()}` }<label ${p?.execution.mode === "research" ? "hidden" : ""}>本轮计算输入<select name="scenario">${ scenarioOptions(p?.scenario, real) }</select></label>${ !p ? "<div class=\"form-grid\"><label>项目后台模型请求总上限<input type=\"number\" name=\"api_budget\" value=\"12\" min=\"0\" max=\"100\" required></label></div><label>项目公开HTTP请求总上限<input type=\"number\" name=\"source_budget\" value=\"24\" min=\"0\" max=\"24\" required></label><p class=\"muted\">研究模式每步2次模型请求、每轮最多6步；固定案例每轮通常6次请求。后台请求上限包含失败尝试；组会问答不设次数上限。模型请求不重试；公开连接仅在勾选允许时有限重试。Codex 按 CLI 启动计数，内部可能有多个模型 turn；这不是 token 或人民币预算。</p>" : "" }</details>`;
}
function inputsSummary(b) {
  const w = b.work_time;
  return `<dl><dt>Idea</dt><dd>${ esc(b.idea) }</dd><dt>资源</dt><dd>${ esc(b.resources) || "未补充" }</dd><dt>权限</dt><dd>${ [
    b.permissions.model_calls ? "模型调用" : null,
    b.permissions.local_compute ? "已接入本地计算" : null,
    b.permissions.public_research ? "公开论文与仓库查询" : null,
    b.permissions.retry_public_reads ? "连接失败后最多重试两次（每次计入）" : null
  ].filter(Boolean).join("、") || "未授权执行" }</dd><dt>本轮研究预算</dt><dd>${w.duration_minutes === undefined ? "旧版每日时段已停用；下一轮默认120分钟，可重新选择" : `最多${esc(w.duration_minutes)}分钟，确认后计时`}</dd><dt>额外要求</dt><dd>${ esc(b.requirements) || "未补充" }</dd></dl>`;
}
function report(artifacts, simulation, research = false, operations = []) {
  if (research || artifacts.some(a => a.body.kind === "research")) return researchReport(artifacts, operations);
  const by = Object.fromEntries(artifacts.map(a => [
      a.role,
      a
    ])), computed = by.executor?.body, review = by.reviewer?.body;
  let result = "尚无计算结果，暂时不能判断。";
  if (computed) {
    if (simulation)
      result = computed.metrics.mse < computed.baseline.mse ? "拟合直线比总猜平均值更贴近这五个数据点。但这是拿拟合用的数据评分，尚不知道它对新数据的表现。" : "本轮拟合直线没有比总猜平均值更贴近这五个数据点，需要查看误差和输入。";
    else {
      const r = computed.results;
      result = `已经保存 ${ r.length } 次重复的测试结果。${ r.every(x => x.metrics.linear.mse < x.metrics.baseline.mse) ? "每次重复中，拟合直线的平方误差都低于只猜均值。" : "结果方向不完全一致，需要继续检查。" }这些观察只适用于当前合成数据。`;
    }
  }
  const numbers = computed && !simulation ? `<details><summary>查看具体数值（越小越接近测试标签）</summary><div class="table-scroll"><table><thead><tr><th>重复</th><th>直线平方误差</th><th>均值平方误差</th><th>直线绝对误差</th></tr></thead><tbody>${ computed.results.map(r => `<tr><td>${ r.seed }</td><td>${ r.metrics.linear.mse.toFixed(3) }</td><td>${ r.metrics.baseline.mse.toFixed(3) }</td><td>${ r.metrics.linear.mae.toFixed(3) }</td></tr>`).join("") }</tbody></table></div></details>` : computed ? `<details><summary>查看具体数值（演示数据）</summary><p>这五个点上的平均平方误差：拟合直线 ${ computed.metrics.mse.toFixed(3) }，只猜平均值 ${ computed.baseline.mse.toFixed(3) }。越小表示整体偏差越小；这不是新数据上的成绩。</p></details>` : "";
  return `<section class="panel report"><h2>本轮报告</h2><p class="muted">摘要由程序依据已保存结果整理；角色原始报告与证据可在下方展开。</p><h3>做了什么</h3><p>${ by.researcher ? "准备输入" + (computed ? "、完成计算" : "") + (review ? "，并独立复算" : "") + "，过程和数据已保存。" : "尚未完成输入准备。" }${ simulation ? "当前使用固定程序演示。" : "角色使用已选模型后台，工具只处理合成计算。" }</p><h3>发现什么</h3><p>${ esc(result) }</p>${ numbers }<h3>还有什么没做</h3><p>${ review ? review.verified ? "数值已独立核对一致，但报告文字仍需审查。" : "数值核对存在不一致，需要检查原始证据。" : "独立核验尚未完成。" } 尚未探索论文或仓库，也没有根据这个 idea 自动编写新实验。</p><h3>接下来怎么做</h3><p>是否认可这些有限结果？下一轮的目标、资源、权限、本轮工作时长或额外要求是否需要调整？</p><details><summary>审查角色原始报告与证据（${ artifacts.length } 份）</summary>${ artifacts.map(a => {
    const b = a.body, spec = b.parameters;
    return `<article class="evidence"><h3>${ esc(roles[a.role]) }</h3>${ spec ? `<p class="muted">工具实际输入：${ spec.test_outlier_fraction === 0 ? "干净测试标签" : "测试标签约一成异常" }，${ spec.seeds.length } 次重复。</p>` : "" }<p>${ esc(b.summary) }</p>${ b.report?.limitations ? `<ul>${ b.report.limitations.map(x => `<li>${ esc(x) }</li>`).join("") }</ul>` : `<p class="muted">${ esc(b.limitation) }</p>` }<a href="/api/evidence/${ esc(a.id) }" target="_blank" rel="noopener">打开原始证据</a></article>`;
  }).join("") || "<p>尚无产物</p>" }</details></section>`;
}

const researchActions = {search_papers: "检索论文摘要", read_abstract: "读取论文摘要", search_repositories: "搜索公开仓库", inspect_repository: "检查仓库 README", synthetic_regression: "运行自有合成基准", prepare_meeting: "整理研究进展"};
function evidenceLink(ref, label) {
  const path = ref.startsWith("operation:") ? "/api/tool-operations/" + ref.slice(10) : "/api/evidence/" + ref;
  return `<a href="${esc(path)}" target="_blank" rel="noopener">${esc(label)} ↗</a>`;
}
function concreteFindings(report) {
  const findings = report?.findings || [];
  if (!findings.length) return "";
  return `<ul>${findings.map(item => `<li><p>${esc(item.finding)}</p><p class="muted">${esc(item.verification)}</p>${(item.evidence_refs || []).map((ref,i) => evidenceLink(ref,`查看依据 ${i+1}`)).join(" · ")}</li>`).join("")}</ul>`;
}

function artifactDetails(a, p) {
  if (a.body.kind !== "research") return report(p.artifacts.filter(x => x.version === a.version), p.execution.mode === "simulation");
  const b=a.body, r=b.report || {};
  return `<section class="readable-report"><p class="prose">${esc(b.summary || r.summary)}</p>${concreteFindings(r)}<h3>还有哪些没确认</h3><ul>${(r.limitations || [b.limitation || "尚未独立核验。"]).map(x=>`<li>${esc(x)}</li>`).join("")}</ul>${r.next_step ? `<h3>建议接下来做什么</h3><p class="prose">${esc(r.next_step)}</p>` : ""}<h3>依据</h3>${(r.evidence_refs || []).map((ref,i)=>evidenceLink(ref,`记录 ${i+1}`)).join(" · ") || '<p class="muted">报告未提供引用。</p>'}${(b.result?.sources || []).length ? `<ul>${b.result.sources.map(s=>`<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a><p class="muted">${esc(s.verification)}</p></li>`).join("")}</ul>` : ""}<details><summary>这一步怎么做的</summary><p class="prose">${esc(b.plan)}</p><p class="prose">${esc(b.reason)}</p><p>工具：${esc(researchActions[b.action] || b.action)}；返回状态：${esc(b.result?.status || "未知")}。</p>${b.result?.error ? `<p class="prose">${esc(b.result.error)}</p>` : ""}</details><p>${evidenceLink(a.id,"原始报告与数据")}</p></section>`;
}

function researchReport(artifacts, operations) {
  const latest = artifacts.at(-1)?.body;
  const orphaned = operations.filter(o => o.body.kind === "research" && !artifacts.some(a => a.task_id === o.task_id));
  const partial = orphaned.length ? `<p>另有 ${orphaned.length} 步已保存工具结果，但模型报告尚未完成或未通过检查。</p><ul>${orphaned.map(o => `<li>${esc(researchActions[o.body.action])} · ${esc(o.body.result.status)}：<a href="/api/tool-operations/${esc(o.id)}" target="_blank" rel="noopener">审查已保存工具证据</a></li>`).join("")}</ul>` : "";
  const sources = artifacts.flatMap(a => a.body.result?.sources || []);
  const reused = new Set((latest?.result?.meeting_evidence?.items || []).filter(item => item.version < artifacts.at(-1)?.version).flatMap(item => (item.result.sources || []).map(source => source.id))).size;
  return `<section class="panel report"><h2>本轮报告</h2><p class="muted">以下是模型报告，来源和工具状态可以核对；报告文字仍需审查。</p><h3>做了什么</h3>${partial}<p>${ artifacts.length ? `已保存 ${artifacts.length} 个研究步骤，本轮读取 ${sources.length} 条资料记录。${reused ? `另复用前轮 ${reused} 条已保存资料。` : ""}` : "后台尚未保存研究步骤。" }</p><h3>发现什么</h3>${concreteFindings(latest?.report) || `<p>${esc(latest?.summary || "还没有可审查的结果。")}</p>`}<h3>还有什么没做</h3><ul>${ (latest?.report?.limitations || ["尚未执行上游仓库代码，也没有完成论文实验复现。"]).map(x => `<li>${esc(x)}</li>`).join("") }</ul><h3>接下来怎么做</h3><p>${ esc(latest?.report?.next_step || "等待资料整理后，再确定下一轮目标与执行条件。") }</p><details><summary>逐步报告与原始证据（${artifacts.length} 份）</summary>${artifacts.map((a,i) => {const b=a.body;return `<article class="evidence"><h3>第 ${i+1} 步：${esc(researchActions[b.action] || b.action)}</h3><p>${esc(b.summary)}</p><p class="muted">实际工具状态：${esc(b.result?.status)}；参数：${esc(b.value || "无")}。</p><p>本步规划：${esc(b.plan)}</p><p>原因：${esc(b.reason)}</p><ul>${(b.result?.sources || []).map(x => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>：${esc(x.verification)}</li>`).join("")}</ul>${b.result?.error ? `<p>${esc(b.result.error)}</p>` : ""}<a href="/api/evidence/${esc(a.id)}" target="_blank" rel="noopener">打开原始证据</a></article>`;}).join("")}</details></section>`;
}

function requestDetails(p) {
  const real = p.execution.mode !== "simulation", rs = p.model_requests, known = rs.filter(r => r.usage && Number.isFinite(r.usage.total_tokens));
  return `<details><summary>执行状态、额度与调用明细</summary>${p.execution.backend === "codex_cli" && real ? `<p>模型后台：${esc(backendLabel(p.execution.backend))}。以下请求次数按 CLI 启动计数，内部模型 turn 未设硬上限；token 为 CLI 返回的用量。平台工具受原权限限制。</p>` : ""}<p>本轮时间预算：最多${p.round_time.duration_minutes}分钟，截止${esc(when(p.round_time.deadline_at))}。这是投入上限，不是完成量。</p><p>本轮已保存 ${p.artifacts.filter(a => a.version === p.version).length} 份报告、${p.tool_operations.filter(o => p.tasks.some(t => t.id === o.task_id && t.version === p.version)).length} 份工具结果；失败 ${p.tasks.filter(t => t.version === p.version && t.status === "failed").length} 个步骤。</p><p>角色任务已用 ${ p.used }/${ p.budget }；问答已用 ${ p.qa_used } 次（不限次数）。${ real ? `后台真实请求 ${ rs.filter(r => r.category === "background").length }/${ p.execution.api_budget }；公开资料请求 ${(p.source_requests || []).length}/${p.execution.source_budget ?? 24}；组会真实请求 ${ rs.filter(r => r.category === "qa").length } 次（不限次数）。已知 ${ known.reduce((n, r) => n + r.usage.total_tokens, 0) } tokens；${ rs.length - known.length } 次用量未知。人民币费用未知，没有 token 硬上限。` : "角色与问答为固定程序，不调用模型。" }</p><ul>${ p.tasks.map(t => `<li>第 ${ t.version } 轮 · ${ esc(roles[t.role] || t.role.replace("research_step_", "研究步骤 ")) } · ${ esc(states[t.status]) }${ t.error ? `：${ esc(t.error) }` : "" }</li>`).join("") }</ul>${ real ? `<h3>实际模型请求</h3><ul>${ rs.map(r => `<li><a href="/api/model-requests/${ esc(r.id) }" target="_blank" rel="noopener">${ esc(r.phase) } · ${ esc(r.status) }</a></li>`).join("") }</ul><h3>公开来源请求</h3><ul>${(p.source_requests || []).map(r => `<li><a href="/api/source-requests/${esc(r.id)}" target="_blank" rel="noopener">${esc(r.url)} · ${esc(r.status)} · HTTP ${r.http_status ?? "未知"} · ${esc(r.transport || "原记录")} · 第 ${r.attempt_number ?? 1} 次尝试</a></li>`).join("") || "<li>无公开来源请求</li>"}</ul><h3>独立保存的工具结果</h3><ul>${ p.tool_operations.map(o => `<li><a href="/api/tool-operations/${ esc(o.id) }" target="_blank" rel="noopener">${ esc(o.body.tool || researchActions[o.body.action] || o.body.action) }</a></li>`).join("") || "<li>早期工具结果保存在角色证据内。</li>" }</ul>` : "" }</details>`;
}

function bubble(key, speaker, body, user = false, time = null, foot = "", pending = false) {
  const role = user ? "me" : speaker.includes("计算") || speaker.includes("实验") ? "compute" : speaker.includes("复算") || speaker.includes("复核") ? "review" : speaker.includes("研究") || speaker.includes("准备输入") ? "research" : "host";
  const names = {me: "你", compute: "实验员", review: "复核员", research: "研究员", host: "协调助手"};
  return `<article class="chat-message ${user ? "user-message" : "lab-message"} role-${role} ${pending ? "pending-reply" : ""}" data-key="${esc(key)}"><div class="message-column"><div class="message-meta" title="${esc(speaker)}${time ? ` · ${esc(when(time))}` : ""}"><span class="role-dot" aria-hidden="true"></span>${names[role]}</div><div class="message-body">${body}</div>${foot ? `<div class="message-foot">${foot}</div>` : ""}</div></article>`;
}
function attachment(kind, id, label) {
  return `<button class="attachment" data-attachment="${kind}" data-id="${esc(id)}"><span class="attachment-icon" aria-hidden="true">▤</span><span>${esc(label)}<small>报告与记录</small></span><span aria-hidden="true">›</span></button>`;
}
function statusText(p) {
  const ts = p.tasks.filter(t => t.version === p.version);
  if (ts.some(t => t.status === "running")) return p.paused || p.round_time?.expired ? "正在保存当前步骤" : "正在工作";
  if (p.paused) return "已暂停 · 随时聊聊";
  if (p.group_proposal && !p.group_proposal.approved) return "有个安排想和你确认";
  if (p.round_time?.expired) return "本次投入已结束 · 可以继续聊";
  if (p.used >= p.budget) return "任务额度已用完 · 可以继续聊";
  if (p.work_blocker) return !p.current_inputs.body.permissions.model_calls && p.execution.mode !== "simulation" ? "等你选择可用工具" : "暂未启动 · 查看进展";
  if (ts.some(t => t.status === "failed")) return "有一步没完成 · 记录已保存";
  if (ts.length && ts.every(t => t.status === "completed" || t.status === "cancelled")) return "已有结果 · 随时聊聊";
  return "工作已排队";
}
function shortText(value, length = 180) {
  const text = String(value || "");
  return text.length > length ? text.slice(0, length) + "…" : text;
}
function permissionSummary(brief) {
  const labels={model_calls:"调用模型",public_research:"查公开论文与仓库",local_compute:"运行已接入的合成计算",retry_public_reads:"有限重试公开查询"};
  return Object.entries(labels).filter(([key])=>brief.permissions[key]).map(([,label])=>label).join("、") || "暂不允许调用模型或工具";
}
function proposalCard(p) {
  const proposal=p.group_proposal, b=proposal.brief;
  const waiting=sending.has(p.id) || pendingSends.has(p.id) || p.group_messages.some(m=>m.status==="processing");
  const requiredTool=p.execution?.mode === "simulation" ? "local_compute" : "model_calls";
  const missing=!b.permissions[requiredTool];
  return `<section class="decision-card" aria-label="待确认的工作安排"><span class="card-eyebrow">${proposal.approved ? "已同意 · 等当前步骤保存后交接" : "协调助手 · 想和你确认"}</span><h3>接下来这样做，可以吗？</h3><p class="prose">${esc(b.idea)}</p><dl><dt>投入上限</dt><dd>${b.work_time.duration_minutes} 分钟${proposal.reset_clock ? "，安排生效时开始计时" : "，沿用原截止时间"}</dd><dt>可以使用</dt><dd>${esc(permissionSummary(b))}</dd>${b.resources ? `<dt>可用资源</dt><dd>${esc(b.resources)}</dd>` : ""}</dl><p class="card-caption">任务与请求总额度继续沿用。已有成果和讨论会保留。</p>${missing ? `<p class="card-caption">还没有允许${requiredTool==="model_calls" ? "调用模型" : "本地计算"}，同意后也暂不会启动工作。<button class="inline-action" data-open-tools>调整工具 ›</button>${p.execution?.mode!=="simulation" ? '<button class="inline-action" data-open-demo>另开程序演示群 ›</button>' : ""}</p>` : ""}${!proposal.approved ? `<div class="card-actions"><button class="primary" data-approve-proposal="${esc(proposal.message_id)}" ${waiting ? "disabled" : ""}>同意这个安排</button><button data-edit-proposal>我想改一下</button></div>` : ""}</section>`;
}
function nextAction(p) {
  if(p.group_proposal) return `<article class="current-guide" data-key="proposal-${esc(p.group_proposal.message_id)}">${proposalCard(p)}</article>`;
  const permissions=p.current_inputs.body.permissions;
  const needsTools=p.execution.mode === "simulation" ? !permissions.local_compute : !permissions.model_calls;
  if(p.used===0 && needsTools && !p.paused)
    return `<article class="current-guide" data-key="start-guide"><section class="decision-card start-card"><span class="card-eyebrow">协调助手</span><h3>想法记下了。让大家开始？</h3><p>先选可以使用的工具和投入时长。我们会把安排发到群里，等你点头后再做。</p><div class="card-actions"><button class="primary" data-open-tools>选择可用工具</button><button data-draft="先聊聊这个想法，我还没有决定执行。">先聊聊想法</button>${p.execution?.mode!=="simulation" ? '<button data-open-demo>另开程序演示群</button>' : ""}</div><p class="card-caption">当前还未执行。${p.execution.mode === "simulation" ? "这是固定程序演示，不调用模型。" : "模型权限开启前，只能记录条件和安排。"}</p></section></article>`;
  if(p.paused || p.round_time?.expired || p.used>=p.budget || p.work_blocker)
    return `<article class="current-guide" data-key="work-guide"><section class="work-notice"><span class="notice-dot" aria-hidden="true"></span><div><strong>${esc(statusText(p))}</strong><p>${esc(blockerText(p))}。${p.artifacts.length ? "已有报告可以继续看、继续讨论。" : "消息和工作安排都已保留。"}</p></div><button data-open-activity>查看原因 ›</button></section></article>`;
  return "";
}
function putDraft(value) {
  const text=document.querySelector("#chat-text"); if(!text)return;
  const combined=text.value ? text.value+"\n"+value : value;
  if(combined.length>4000) {announce("输入框已经写满，可以先发出草稿再补充。",true);return;}
  text.value=combined; saveDraft(currentProject || "new",combined); text.focus();
}
async function stopWork(p) {
  if(stopping.has(p.id)) return;
  stopping.add(p.id);
  const request=stopRequests.get(p.id) || {message:"先停一下",message_id:crypto.randomUUID()};
  stopRequests.set(p.id,request);
  const persist=()=>{try {sessionStorage.setItem("labcouncil-stop-pending",JSON.stringify([...stopRequests]));} catch (_) {}};
  persist();
  try {
    const latest=await api(`/api/projects/${p.id}`);
    if(!latest.group_messages.some(m=>m.id===request.message_id && m.status==="completed"))
      await api(`/api/projects/${p.id}/chat`,request);
    stopRequests.delete(p.id);persist();
    if(currentProject===p.id) {await refreshProject();announce("已暂停新工作。已经发出的请求可能仍会返回，原消息和结果会保留。");}
  } catch(error) {
    if(currentProject===p.id) {
      await refreshProject().catch(()=>{});
      if(projectData?.group_messages.some(m=>m.id===request.message_id && m.status==="completed")) {
        stopRequests.delete(p.id);persist();announce("暂停已确认，原消息和结果保留。");
      } else announce("暂停尚未确认。服务恢复后再点“先暂停工作”，会核对原请求，不重复建立任务。",true);
    }
  } finally {stopping.delete(p.id);}
}
async function openDemo(p) {
  if(demoOpening.has(p.id)) return;
  demoOpening.add(p.id);
  try {
  const ticket=navigation;
  const b={...p.current_inputs.body,permissions:{model_calls:false,local_compute:true,public_research:false,retry_public_reads:false}};
  const result=await api("/api/projects",{title:"程序演示 · "+p.title.slice(0,70),idea:b.idea,brief:b,mode:"simulation",backend:"codex_cli",budget:3,api_budget:0,source_budget:0});
  if(ticket===navigation) {await showProject(result.id);announce("另开了程序演示群：只做固定小实验，不调用模型；原研究群和草稿仍保留。");}
  else await sidebar();
  } finally {demoOpening.delete(p.id);}
}
async function postControl(p, message, expectedProposalId) {
  if(sending.has(p.id) || pendingSends.has(p.id) || p.group_messages.some(m=>m.status==="processing")) return;
  const send={message,message_id:crypto.randomUUID(),created:Date.now()/1000};
  if(expectedProposalId) send.expected_proposal_id=expectedProposalId;
  pendingSends.set(p.id,send);savePending();
  updateTranscript(projectData,meetingData,true);
  await sendChat(p.id,send);
}
function toolMessage(form) {
  const permissions={model_calls:"调用模型",public_research:"查询公开论文与仓库",local_compute:"本地计算"};
  return "本次工作条件：\n"+Object.entries(permissions).map(([key,label])=>(form.elements.namedItem(key).checked ? "允许" : "禁止")+label+"。").join("\n")+"\n投入"+form.elements.namedItem("minutes").value+"分钟。";
}
function openTools(p) {
  const b=p.group_proposal?.brief || p.current_inputs.body, sim=p.execution.mode==="simulation";
  const check=(key,title,description)=>`<label class="tool-choice"><input type="checkbox" name="${key}" ${b.permissions[key] ? "checked" : ""}><span><strong>${title}</strong><small>${description}</small></span></label>`;
  showSheet("大家可以做哪些事？",`<p class="muted">针对这个研究群选择。提交后先看安排，再决定执行。</p><form id="choose-tools">${check("model_calls","调用模型讨论与规划",sim ? "程序演示群不会实际调用模型。" : "使用 "+backendLabel(p.execution.backend)+"；会消耗对应账号用量。")}${check("public_research","查公开论文与仓库","已接入的公开资料查询；仍受现有请求额度限制。")}${check("local_compute","运行合成数据的小实验","仅限已接入的计算工具，尚不支持任意代码或 GPU 训练。")}<label class="time-choice">这次最多投入多久？<span><input name="minutes" type="number" min="1" max="10080" value="${b.work_time.duration_minutes}" required> 分钟</span></label><p class="muted">时长是投入上限，不保证产出量。任务和请求总额度不会自动增加。</p><button class="primary" type="submit">把条件发到群里</button></form>`);
  document.querySelector("#choose-tools").onsubmit=e=>action(e,async()=>{
    const text=toolMessage(e.currentTarget);
    await postControl(p,text);
    document.querySelector("#settings").close();
  });
}
function systemNote(key, text, control = "") {
  return `<article class="system-note" data-key="${esc(key)}"><p>${esc(text)}</p>${control}</article>`;
}
function answerBody(text) {
  // Keep the saved answer intact. Protocol IDs and repeated plans remain in full text.
  const preview=text.split("\n我理解的工作安排：")[0].replace(/\n证据：[A-Za-z0-9:_\-, ]+(?=\n|$)/g,"").trim();
  if (text.length <= 420 && preview === text) return `<p class="prose">${esc(text)}</p>`;
  return `<p class="prose">${esc(shortText(preview,300))}</p><details><summary>完整答复</summary><p class="prose">${esc(text)}</p></details>`;
}
function artifactMessage(a, p) {
  const b = a.body;
  const speaker = b.kind === "research" ? "研究员" : roles[a.role] || "协调助手";
  const raw = b.summary || "这一步的结果已经保存。";
  const summary = raw.length > 360 ? raw.slice(0,360) + "…（完整报告见附件）" : raw;
  const label = b.kind === "research" ? researchActions[b.action] || "研究记录" : a.role === "executor" ? "实验数据与原始报告" : a.role === "reviewer" ? "独立复算记录" : "本轮输入数据";
  return bubble(`artifact-${a.id}`, speaker, `<p class="prose">${esc(summary)}</p>${attachment("artifact", a.id, label)}`, false, a.created);
}
function transcript(p, meetings) {
  const entries = [];
  const add = (time, rank, html) => entries.push({time: time || p.created, rank, html});
  const chatVersions = new Set((p.events || []).filter(e => e.kind === "group_plan_applied").map(e => JSON.parse(e.body).version));
  for (const input of p.input_history.length ? p.input_history : [p.current_inputs]) {
    if (chatVersions.has(input.version)) continue;
    add(input.created, 0, `<div class="round-marker" data-key="round-${input.version}">${esc(new Date(input.created * 1000).toLocaleDateString("zh-CN"))}</div>`);
    add(input.created, 1, bubble(`input-${input.version}`, "你 · 已确认的本轮输入", `<p class="prose">${esc(input.body.idea)}</p>${attachment("inputs", input.version, "已记录的资源与权限")}`, true, input.created));
    add(input.created, 2, systemNote(`plan-${input.version}`, "工作安排已记录。", `<button data-attachment="plan" data-id="${input.version}">查看安排 ›</button>`));
  }
  for (const a of p.artifacts) add(a.created, 3, artifactMessage(a, p));
  for (const op of p.tool_operations || []) {
    if (p.artifacts.some(a => a.task_id === op.task_id)) continue;
    add(op.created, 3, bubble(`partial-${op.id}`, "LabCouncil · 已保存的工具结果", `<p>${esc(researchActions[op.body.action] || op.body.tool || "计算")}已留下结果，但本步报告尚未完成或未通过检查。</p><a href="/api/tool-operations/${esc(op.id)}" target="_blank" rel="noopener">审查工具证据 ↗</a>`));
  }
  for (const task of p.tasks.filter(t => t.status === "failed")) {
    add(task.finished || task.created, 4, bubble(`failure-${task.id}`, "LabCouncil · 任务失败", `<p>第 ${task.version} 轮的${esc(roles[task.role] || task.role.replace("research_step_", "研究步骤 "))}没有完成。已保存的其他证据仍可审查。</p>${attachment("failure", task.id, "失败记录")}`));
  }
  for (const event of p.events || []) {
    if (!["research_stopped", "round_time_expired", "group_plan_applied", "group_plan_stale", "execution_status_notice"].includes(event.kind)) continue;
    const data = typeof event.body === "string" ? JSON.parse(event.body) : event.body;
    const reason = event.kind === "group_plan_applied" ? "工作安排已保存。执行进展可以在活动里查看。" : String(data.reason || "记录已保存").replaceAll("等待组会", "可以继续讨论");
    add(event.created, 4, systemNote(`stopped-${event.id || event.created}`, reason, event.kind === "group_plan_applied" ? `<button data-attachment="inputs" data-id="${data.version}">查看完整安排 ›</button>` : '<button data-open-activity>查看活动 ›</button>'));
  }
  for (const m of meetings) {
    const s = m.snapshot, real = !s.simulation;
    if (!p.events.some(e => e.kind === "group_plan_applied" && JSON.parse(e.body).version === m.version + 1)) add(m.created, 5, bubble(`meeting-${m.id}`, "LabCouncil · 保存的讨论材料", `${attachment("meeting", m.id, `历史材料 · ${when(s.cutoff)}`)}`));
    (m.discussion || []).forEach((d, i) => {
      add(d.created, 6, bubble(`question-${m.id}-${i}`, `你 · 第 ${m.version} 轮组会`, `<p class="prose">${esc(d.question)}</p>`, true, d.created));
      add(d.created, 7, bubble(`answer-${m.id}-${i}`, real ? "研究员 · " + backendLabel(p.execution.backend) + " 依据本场快照答复" : "研究员 · 模板答复，程序演示", answerBody(d.answer), false, d.created, real ? "历史讨论 · 依据当场保存材料" : "程序演示 · 未调用模型"));
    });
    if (m.decision && !chatVersions.has(m.decision.to_version)) add(m.decision.created || m.created, 8, bubble(`decision-${m.id}`, "LabCouncil · 组会决定已保存", `<p>已确认第 ${m.decision.to_version} 轮方向：${esc(m.decision.instruction)}</p><p class="muted">此前输入、规划、报告与讨论继续保留。</p>`));
  }
  for (const m of p.group_messages || []) {
    add(m.created, 6, bubble(`group-user-${m.id}`, "你", `<p class="prose">${esc(m.user_text)}</p>`, true, m.created));
    const request=p.model_requests.find(r=>r.id===m.request_id);
    const origin=m.request_id ? `模型请求：${backendLabel(p.execution.backend)} · ${request?.elapsed === null || request?.elapsed === undefined ? "耗时未知" : request.elapsed.toFixed(2) + "秒"}` : p.execution.mode === "simulation" ? "程序演示 · 未调用模型" : "本机系统回执 · 未调用模型";
    const body = m.answer ? answerBody(m.answer) : `<p><span class="pending-dot" aria-hidden="true"></span>正在等待${m.request_id ? "模型" : "服务"}答复，已等待 ${Math.max(0,Math.floor(Date.now()/1000-m.created))} 秒</p>`;
    const foot = m.answer ? `${esc(origin)}${!m.request_id && p.execution.mode !== "simulation" ? " · 执行进展见活动" : ""}${m.request_id ? `<br><button class="evidence-link" data-attachment="chat-context" data-id="${esc(m.id)}">依据与调用记录 ›</button>` : ""}` : "消息已保存，答复尚未完成。";
    add(m.finished || m.created, 7, bubble(`group-answer-${m.id}`, m.speaker || "协调助手", body, false, m.finished, foot, !m.answer));
  }
  const pending = pendingSends.get(p.id);
  if (pending && !(p.group_messages || []).some(m => m.id === pending.message_id)) {
    add(pending.created, 6, bubble(`pending-user-${pending.message_id}`, "你", `<p class="prose">${esc(pending.message)}</p>`, true));
    if (!pending.error) add(pending.created, 7, bubble(`pending-answer-${pending.message_id}`, "协调助手", '<p><span class="pending-dot" aria-hidden="true"></span>正在发送，等待服务确认…</p>', false, null, "", true));
  }
  if(pending?.error) add(pending.created,8,systemNote(`pending-error-${pending.message_id}`,`没有确认发送结果：${pending.error}。可以继续发送原消息；已保存的不会重新处理。`,`<button data-retry-send ${sending.has(p.id) ? "disabled" : ""}>恢复这条消息 ›</button>`));
  return entries.sort((a, b) => a.time - b.time || a.rank - b.rank).map(e => e.html).join("")+nextAction(p);
}
function updateTranscript(p, meetings, forceBottom = false) {
  const html = transcript(p, meetings);
  if (html === transcriptSignature) return;
  const nearBottom = content.scrollHeight - content.scrollTop - content.clientHeight < 100;
  const root=content.querySelector("#transcript"), viewportTop=content.getBoundingClientRect().top;
  const anchor=[...root.children].find(el=>el.getBoundingClientRect().bottom>viewportTop);
  const offset=anchor?.getBoundingClientRect().top-viewportTop;
  const template=document.createElement("template"); template.innerHTML=html;
  const existing=new Map([...root.children].map(el=>[el.dataset.key,el]));
  let cursor=root.firstElementChild;
  for (const incoming of [...template.content.children]) {
    const markup=incoming.outerHTML, old=existing.get(incoming.dataset.key);
    let node=old;
    if(!old || entryMarkup.get(old)!==markup) {
      node=incoming;
      if(old) [...old.querySelectorAll("details")].forEach((d,i)=>{if(d.open && node.querySelectorAll("details")[i]) node.querySelectorAll("details")[i].open=true;});
      entryMarkup.set(node,markup);
      if(old) { old.replaceWith(node); if(cursor===old) cursor=node; }
    }
    if(node!==cursor) root.insertBefore(node,cursor);
    cursor=node.nextElementSibling;
    existing.delete(node.dataset.key);
  }
  for(const obsolete of existing.values()) obsolete.remove();
  transcriptSignature = html;
  if(forceBottom || nearBottom) content.scrollTop=content.scrollHeight;
  else if(anchor) {
    const same=[...root.children].find(el=>el.dataset.key===anchor.dataset.key);
    if(same) content.scrollTop+=same.getBoundingClientRect().top-viewportTop-offset;
  }
  updateJumpLink();
}
function updateJumpLink() {
  const button=document.querySelector("#jump-latest");
  if(button) button.hidden=!currentProject || content.scrollHeight-content.scrollTop-content.clientHeight<100;
}
function setComposer(force = false) {
  const area = document.querySelector("#compose-area"), p = projectData;
  const key = currentProject || "new";
  const waiting = sending.has(key) || pendingSends.has(key) || (p?.group_messages || []).some(m=>m.status==="processing");
  const hint = waiting ? "上一条消息正在核对，可以先写下一句" : "Enter 发送，Shift+Enter 换行";
  if (!force && area.dataset.context === key && area.querySelector("textarea")) {
    area.querySelector("#composer-help").textContent = hint;
    area.querySelector("button[type=submit]").disabled = waiting;
    return;
  }
  area.dataset.context = key;
  area.innerHTML = `<button id="jump-latest" class="jump-latest" type="button" hidden>回到最新消息 ↓</button><form id="composer"><button class="composer-plus" type="button" aria-label="补充资源或要求" aria-expanded="false" aria-controls="composer-menu">＋</button><div id="composer-menu" hidden><button type="button" data-add="资源：">补充资源</button><button type="button" data-add="额外要求：">补充要求</button><button type="button" data-open-activity>查看活动</button>${p ? '<button type="button" data-stop-work>先暂停工作</button>' : ""}</div><label class="sr-only" for="chat-text">群聊消息</label><textarea id="chat-text" rows="1" maxlength="4000" placeholder="${p ? "给研究群发消息…" : "你想研究什么？"}" aria-describedby="composer-help" required>${esc(questionDrafts.get(key) || "")}</textarea><button class="send-button" aria-label="发送" title="发送" type="submit" ${waiting ? "disabled" : ""}><span aria-hidden="true">↑</span></button></form><span id="composer-help" class="composer-hint">${hint}</span>`;
  area.querySelector("#jump-latest").onclick=()=>{content.scrollTop=content.scrollHeight;updateJumpLink();};
  updateJumpLink();
  const form = area.querySelector("form"), text = form.querySelector("textarea");
  const menu = form.querySelector("#composer-menu"), plus = form.querySelector(".composer-plus");
  plus.onclick = () => { menu.hidden = !menu.hidden; plus.setAttribute("aria-expanded", String(!menu.hidden)); };
  menu.onclick = e => {
    const add = e.target.closest("[data-add]");
    if (add) {
      const value=text.value+(text.value ? "\n" : "")+add.dataset.add;
      if(value.length>4000) announce("这条消息已写满，可以另发一条补充。",true);
      else {text.value=value;saveDraft(key,text.value);}
      text.focus();
    }
    if (e.target.closest("[data-open-activity]")) openProfile("activity");
    if (e.target.closest("[data-stop-work]")) stopWork(projectData).catch(e=>announce(e.message,true));
    menu.hidden = true; plus.setAttribute("aria-expanded", "false");
  };
  bindEnter(form, text);
  text.addEventListener("input", () => saveDraft(key, text.value));
  form.onsubmit = e => action(e, async () => {
    const value = text.value.trim();
    if (!value || sending.has(key) || pendingSends.has(key) || (projectData?.group_messages || []).some(m=>m.status==="processing")) return;
    if(p) {
      const send={message:value,message_id:crypto.randomUUID(),created:Date.now()/1000};
      pendingSends.set(p.id,send); savePending();
      saveDraft(key,""); text.value="";
      updateTranscript(projectData,meetingData,true);
      try { await sendChat(p.id,send); }
      catch(error) { if(currentProject===p.id) throw error; }
      return;
    }
    const ticket=navigation;
    sending.add(key); setComposer();
    try {
      if (!p) {
        const brief = {...defaultBrief(), idea:value, permissions:{model_calls:false,local_compute:false,public_research:false,retry_public_reads:false}};
        const result = await api("/api/projects", {title:setupSettings.title || value.slice(0,60), idea:value, brief,
          mode:setupSettings.mode || "research", backend:setupSettings.backend || "codex_cli",
          scenario:setupSettings.scenario || "clean", api_budget:Number(setupSettings.api_budget ?? 12), source_budget:Number(setupSettings.source_budget ?? 24)});
        if (ticket !== navigation) {
          if(questionDrafts.get(key)?.trim()===value) saveDraft(key,"");
          await sidebar(); return;
        }
        if (text.value.trim() === value) saveDraft(key,"");
        else { saveDraft(result.id,text.value); saveDraft(key,""); }
        await showProject(result.id);
        announce("群已建立。接下来选可用工具，或继续补充想法。");
        return;
      }
    } finally { sending.delete(key); setComposer(); }
  });
}
async function sendChat(id,send) {
  if(sending.has(id)) return;
  sending.add(id); delete send.error; savePending(); setComposer(); announce("");
  let confirmed=false;
  try {
    await api(`/api/projects/${id}/chat`,{message:send.message,message_id:send.message_id,...(send.expected_proposal_id ? {expected_proposal_id:send.expected_proposal_id} : {})});
    confirmed=true;
    pendingSends.delete(id); savePending();
    // Polling may already have shown the answer; do not pull the reader to the bottom.
    if(currentProject===id) await refreshProject();
  } catch(error) {
    if(confirmed) {
      if(currentProject===id) announce("消息和处理记录已保存，暂时没能刷新显示；稍后会再读取。",true);
      return;
    }
    send.error=error.message; pendingSends.set(id,send); savePending();
    if(currentProject===id) {
      await refreshProject().catch(()=>{});
      if(currentProject===id && projectData) updateTranscript(projectData,meetingData);
    }
    if(!pendingSends.has(id)) return;
    throw error;
  } finally {
    sending.delete(id); setComposer();
    if(currentProject===id && projectData) updateTranscript(projectData,meetingData);
  }
}
function bindEnter(form, text) {
  text.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
}
function closeProfile() {
  const focusedInside=document.querySelector("#agent-panel").contains(document.activeElement);
  document.querySelector("#agent-panel").hidden = true;
  document.querySelector("#open-profile").setAttribute("aria-expanded","false");
  syncBackdrop();
  if(focusedInside) (profileReturnFocus?.isConnected ? profileReturnFocus : document.querySelector("#open-profile")).focus();
}
function closeProjects() {
  const focusedInside=document.querySelector("#sidebar").contains(document.activeElement);
  document.querySelector(".layout").classList.remove("projects-open");
  document.querySelector("#toggle-projects").setAttribute("aria-expanded","false");
  syncBackdrop();
  if(focusedInside) document.querySelector("#toggle-projects").focus();
}
function syncBackdrop() {
  const panel=document.querySelector("#agent-panel"), narrow=window.innerWidth<=850;
  const open=!panel.hidden || document.querySelector(".layout").classList.contains("projects-open");
  document.querySelector("#drawer-backdrop").hidden=!open;
  document.querySelector("main").inert=narrow && open;
  for(const el of [panel,document.querySelector("#sidebar")]) {
    if(narrow && open) { el.setAttribute("role","dialog"); el.setAttribute("aria-modal","true"); }
    else { el.removeAttribute("role");el.removeAttribute("aria-modal"); }
  }
}
function openProfile(tab = "activity") {
  const wasClosed=document.querySelector("#agent-panel").hidden;
  if(wasClosed) profileReturnFocus=document.activeElement;
  profileTab = tab;
  document.querySelector("#agent-panel").hidden = false;
  document.querySelector("#open-profile").setAttribute("aria-expanded","true");
  if (window.innerWidth <= 850) closeProjects();
  renderProfile(); syncBackdrop();
  if(wasClosed) document.querySelector(`[data-profile-tab="${profileTab}"]`).focus();
}
function taskLabel(t, p) {
  const artifact = p.artifacts.find(a => a.task_id === t.id);
  const op = (p.tool_operations || []).find(o => o.task_id === t.id);
  return researchActions[artifact?.body.action || op?.body.action] || roles[t.role] || "研究步骤 " + t.role.replace("research_step_", "");
}
function activityRow(t, p) {
  const artifact = p.artifacts.find(a => a.task_id === t.id);
  const op = (p.tool_operations || []).find(o => o.task_id === t.id);
  const sub = t.status === "running" ? "实际步骤已启动，等待保存结果" : t.status === "queued" ? "等待启动" : t.status === "cancelled" ? "未执行，原安排已保留" : t.status === "failed" ? shortText(t.error || "没有完成，失败记录已保存",60) : shortText(artifact?.body.summary || op?.body.result?.status || "结果已保存",60);
  const icons = {researcher:"⌕",executor:"▥",reviewer:"✓"};
  return `<button class="activity-row ${esc(t.status)}" data-task="${esc(t.id)}"><span class="activity-icon" aria-hidden="true">${icons[t.role] || "⌕"}</span><span class="activity-copy"><strong>${esc(taskLabel(t,p))}</strong><small class="activity-date">${esc(when(t.finished || t.started || t.created))} · 安排 ${t.version}</small><small>${esc(sub)}</small></span><span class="activity-status">${esc(t.status === "cancelled" ? "未执行" : states[t.status])}</span></button>`;
}
function blockerText(p) {
  const reasons=[];
  if (p.paused) reasons.push("已暂停启动新任务");
  if (p.round_time?.expired) reasons.push("投入时间已到");
  if (p.used>=p.budget) reasons.push("任务额度已用完");
  if (p.work_blocker && !p.round_time?.expired) reasons.push(p.work_blocker.replaceAll("等待组会调整", "可以在聊天里补充").replaceAll("等待组会审查", "已有结果仍可审查"));
  return reasons.join("；");
}
function activityView(p) {
  const active=p.tasks.filter(t=>t.status==="running"), queued=p.tasks.filter(t=>t.status==="queued" && t.version===p.version);
  const history=p.tasks.filter(t=>!["running","queued"].includes(t.status) || t.version!==p.version).sort((a,b)=>(b.finished || b.started || b.created)-(a.finished || a.started || a.created));
  const proposal=p.group_proposal;
  const section=(label,items,empty)=>`<h3 class="section-label">${label}</h3>${items.map(t=>activityRow(t,p)).join("") || `<p class="profile-empty">${empty}</p>`}`;
  return `<p class="profile-project">${esc(p.title)}</p><p class="profile-status">${esc(blockerText(p) || statusText(p))}</p>${proposal ? `<h3 class="section-label">${proposal.approved ? "等待交接" : "等你决定"}</h3><button class="activity-row" data-proposal><span class="activity-icon" aria-hidden="true">◇</span><span class="activity-copy"><strong>新的工作安排</strong><small>${esc(shortText(proposal.brief.idea,85))}</small></span><span class="activity-status">${proposal.approved ? "已同意" : "待讨论"}</span></button>` : ""}${section("正在进行",active,"当前没有正在执行的步骤。")}${queued.length ? section("等待中",queued,"") : ""}${p.meeting_at ? `<h3 class="section-label">已安排</h3><button class="activity-row" data-schedule><span class="activity-icon" aria-hidden="true">◷</span><span class="activity-copy"><strong>定时整理讨论材料</strong><small>${esc(when(p.meeting_at))}</small></span></button>` : ""}${section("过往活动",history,"有了结果，会留在这里。")}`;
}
function contextView(p) {
  const b=p.current_inputs.body;
  const reports=[...p.artifacts].sort((a,b)=>b.created-a.created).map(a=>attachment("artifact",a.id,`${taskLabel(p.tasks.find(t=>t.id===a.task_id) || {id:a.task_id,role:a.role},p)} · 安排 ${a.version} · ${when(a.created)}`)).join("");
  return `<section class="context-section"><h3>已保存的成果 · ${p.artifacts.length} 份</h3>${reports || '<p class="profile-empty">还没有报告。完成后会出现在这里，也会发到群里。</p>'}</section><section class="context-section"><h3>正在做什么</h3><p>${esc(b.idea)}</p></section><section class="context-section"><h3>可用资源</h3><p>${esc(b.resources || "还没有补充，可以直接在聊天里说。")}</p></section><section class="context-section"><h3>你的要求</h3><p>${esc(b.requirements || "还没有额外要求。")}</p></section><section class="context-section"><h3>工作安排</h3><p>${esc(p.current_inputs.plan.granularity)}</p><ol>${p.current_inputs.plan.steps.map(s=>`<li>${esc(s.replaceAll("等待组会","等你反馈"))}</li>`).join("")}</ol></section><p class="muted">这里来自已保存的项目记录。旧输入、完整报告和失败记录继续保留；每条答复使用的上下文仍可单独查看。</p>`;
}
function settingsView(p) {
  const permissions=p.current_inputs.body.permissions;
  return `<p class="muted badge">${p.execution.mode === "simulation" ? "本地模拟原型 · 不调用模型" : backendLabel(p.execution.backend)}</p><button type="button" id="profile-tools">选择可用工具与时长</button><h3 class="section-label">工具与权限</h3><div class="tool-row"><span>模型调用</span><span>${permissions.model_calls ? "已允许" : "未授权"}</span></div><div class="tool-row"><span>公开论文与仓库查询</span><span>${permissions.public_research ? "已允许" : "未授权"}</span></div><div class="tool-row"><span>已接入的本地合成计算</span><span>${permissions.local_compute ? "已允许" : "未授权"}</span></div><p class="muted">需要改变权限时，在聊天里明确说明。任意代码执行、云电脑、语音和应用连接尚未接入。</p><h3 class="section-label">后台工作</h3><p class="muted">${esc(blockerText(p) || statusText(p))}。暂停会阻止新任务启动，当前步骤仍可保存结果。</p><button type="button" class="pause-action" id="profile-pause">${p.paused ? "恢复后台工作" : "暂停后台工作"}</button><details><summary>投入与定时设置</summary><form id="configure"><label>项目任务总上限<input name="budget" type="number" min="0" max="100" value="${p.budget}" required></label><label>定时整理材料<input name="meeting_at" type="datetime-local" value="${p.meeting_at ? esc(new Date(p.meeting_at*1000-new Date().getTimezoneOffset()*60000).toISOString().slice(0,16)) : ""}"></label><button type="submit">保存</button></form></details>${requestDetails(p)}`;
}
function renderProfile() {
  const panel=document.querySelector("#agent-panel");
  if (panel.hidden) return;
  document.querySelectorAll("[data-profile-tab]").forEach(b=>{const selected=b.dataset.profileTab===profileTab; b.setAttribute("aria-selected",String(selected));b.tabIndex=selected ? 0 : -1;});
  const body=document.querySelector("#profile-body");
  body.setAttribute("aria-labelledby","tab-"+profileTab);
  const p=projectData;
  if (!p) { body.innerHTML='<p class="profile-empty">先发一个想法，创建你的研究群。</p><button id="configure-new">选择模型与执行方式</button><p class="muted">新研究群默认使用 Codex CLI，模型和工具权限初始关闭。</p>'; document.querySelector("#configure-new").onclick=()=>document.querySelector("#new-settings").click();return; }
  const html=profileTab==="activity" ? activityView(p) : profileTab==="context" ? contextView(p) : settingsView(p);
  const signature=p.id+"|"+profileTab+"|"+html;
  if(profileSignature===signature)return;
  profileSignature=signature;
  const scrollTop=body.scrollTop;
  body.innerHTML=html;
  body.scrollTop=scrollTop;
  body.onclick=e=>{
    const t=e.target.closest("[data-task]"); if(t) showTask(t.dataset.task);
    const a=e.target.closest("[data-attachment]");if(a) showAttachment(a.dataset.attachment,a.dataset.id);
    if(e.target.closest("[data-proposal]")) showSheet("待讨论的工作安排",`${inputsSummary(p.group_proposal.brief)}<p class="muted">${p.group_proposal.approved ? "已同意，等待当前步骤保存结果后交接。" : "可以在聊天里修改，或者说‘按这个做’。"}</p>`);
    if(e.target.closest("[data-schedule]")) openProfile("settings");
  };
  const tools=body.querySelector("#profile-tools");
  if(tools)tools.onclick=()=>openTools(projectData);
  const pause=body.querySelector("#profile-pause");
  if(pause) pause.onclick=e=>action(e,async()=>{await api(`/api/projects/${p.id}/configure`,{paused:!p.paused,budget:p.budget,meeting_at:p.meeting_at});await refreshProject();renderProfile();announce(p.paused ? "已解除暂停；启动前仍检查时间、权限和额度。" : "已暂停新任务，当前步骤会保存结果。");});
  const form=body.querySelector("#configure");
  if(form)form.onsubmit=e=>action(e,async()=>{const f=new FormData(form);await api(`/api/projects/${p.id}/configure`,{paused:!!p.paused,budget:Number(f.get("budget")),meeting_at:f.get("meeting_at") ? new Date(f.get("meeting_at")).getTime()/1000 : null});await refreshProject();renderProfile();announce("设置已保存。");});
}
function showTask(id) {
  const p=projectData, t=p.tasks.find(t=>t.id===id); if(!t)return;
  const artifact=p.artifacts.find(a=>a.task_id===id), op=p.tool_operations.find(o=>o.task_id===id);
  const calls=p.model_requests.filter(r=>r.task_id===id);
  showSheet(taskLabel(t,p),`<p class="muted">${esc(t.status==="cancelled" ? "未执行" : states[t.status])} · ${esc(when(t.finished || t.started || t.created))} · 安排 ${t.version}</p>${t.error ? `<p class="prose">${esc(t.error)}</p>` : ""}${artifact ? artifactDetails(artifact,p) : `<p>${t.status==="running" ? "步骤已启动，报告尚未保存。" : t.status==="queued" ? "任务已排队，尚未执行。" : "这一步没有完成报告。"}</p>`}${op ? `<p><a href="/api/tool-operations/${esc(op.id)}" target="_blank" rel="noopener">已保存的工具结果 ↗</a></p>` : ""}${calls.length ? `<details><summary>模型调用记录（${calls.length} 次）</summary>${calls.map(r=>`<p><a href="/api/model-requests/${esc(r.id)}" target="_blank" rel="noopener">${esc(r.phase)} · ${esc(r.status)} · ${r.elapsed == null ? "耗时未知" : r.elapsed.toFixed(2)+"秒"} ↗</a></p>`).join("")}</details>` : ""}`);
}
function showSheet(title, body) {
  document.querySelector("#settings-title").textContent = title;
  document.querySelector("#settings-body").innerHTML = body;
  if (!document.querySelector("#settings").open) document.querySelector("#settings").showModal();
}
function showAttachment(kind, id) {
  const p = projectData;
  if (kind === "inputs" || kind === "plan") {
    const input = p.input_history.find(x => String(x.version) === String(id)) || p.current_inputs;
    showSheet(kind === "inputs" ? `第 ${id} 轮工作条件` : `第 ${id} 轮工作安排`, kind === "inputs" ? inputsSummary(input.body) : `<p>${esc(input.plan.granularity)}</p><ol>${input.plan.steps.map(s => `<li>${esc(s)}</li>`).join("")}</ol><p class="muted">平台工作边界，具体 agent 决策保存在研究记录中。</p>`);
  } else if (kind === "artifact") {
    const a = p.artifacts.find(x => x.id === id); if (!a) return;
    showSheet("报告与证据", `<p class="muted">${esc(when(a.created))} · 安排 ${a.version}</p>${artifactDetails(a,p)}`);
  } else if (kind === "chat-context") {
    const m = p.group_messages.find(x => x.id === id); if (!m) return;
    showSheet("这条答复的依据", `<p class="muted">消息到达时保存：${esc(when(m.context.cutoff))}。后续进展会在新的答复中使用；旧答复不改写。</p>${m.context.evidence.map(e => `<p>${esc(e.summary)}</p><a href="${e.id.startsWith("operation:") ? "/api/tool-operations/" + esc(e.id.slice(10)) : "/api/evidence/" + esc(e.id)}" target="_blank" rel="noopener">原始证据 ↗</a>`).join("") || "<p>当时还没有研究证据，答复只讨论状态或工作安排。</p>"}<p><a href="/api/model-requests/${esc(m.request_id)}" target="_blank" rel="noopener">模型调用记录 ↗</a></p>`);
  } else if (kind === "meeting") {
    const m = meetingData.find(x => x.id === id); if (!m) return;
    const s = m.snapshot;
    showSheet(`第 ${m.version} 轮组会材料`, `<p class="muted">材料截止 ${esc(when(s.cutoff))}，本场报告保持固定。</p>${report(s.artifacts, s.simulation, p.execution.mode === "research", s.tool_operations || [])}`);
  } else if (kind === "failure") {
    const t = p.tasks.find(x => x.id === id); if (t) showSheet("任务失败记录", `<p class="prose">${esc(t.error)}</p>`);
  }
}
async function refreshProject(forceBottom = false) {
  if (!currentProject || refreshing) return;
  refreshing = true;
  const id = currentProject, ticket = navigation;
  try {
    const p = await api(`/api/projects/${id}`);
    const meetings = await Promise.all(p.meetings.map(m => api(`/api/meetings/${m.id}`)));
    if (ticket !== navigation || id !== currentProject) return;
    const oldVersion=projectData?.version;
    projectData = p; meetingData = meetings;
    const pending=pendingSends.get(id), saved=p.group_messages.find(m=>m.id===pending?.message_id);
    if(saved && saved.status!=="processing") {
      pendingSends.delete(id); savePending();
      if(pending.error) announce("已找回原消息和处理记录。");
    }
    document.querySelector("#project-title").textContent = p.title;
    document.querySelector("#work-status").textContent = (p.execution.mode === "simulation" ? "程序演示 · " : "") + statusText(p);
    document.querySelector("#work-status").title=p.execution.mode === "simulation" ? "固定程序演示，不调用模型" : backendLabel(p.execution.backend);
    modeLabel(p.execution.mode !== "simulation", p.execution.mode === "research", p.execution.backend);
    updateTranscript(p, meetings, forceBottom);
    setComposer();
    if (profileTab !== "settings") renderProfile();
    if (oldVersion && oldVersion !== p.version) await sidebar();
  } finally { refreshing = false; }
}
async function showProject(id) {
  navigation++;
  currentProject = id; transcriptSignature = "";
  profileSignature="";
  closeProfile();
  projectData = null; meetingData = [];
  content.innerHTML = '<div id="transcript" class="transcript"></div><div id="setup-slot" class="transcript"></div>';
  document.querySelector("#compose-area").innerHTML = "";
  document.querySelector("#compose-area").dataset.context = "";
  document.querySelector("#project-actions").innerHTML = '<button id="open-results" class="header-action" aria-label="查看已保存的成果">成果</button><button id="open-settings" class="header-action" aria-label="查看进展">进展</button>';
  document.querySelector("#project-title").textContent = "正在读取项目…";
  announce("");
  document.querySelector("#work-status").textContent = "正在读取保存的报告与讨论…";
  content.onclick = e => {
    const file = e.target.closest("[data-attachment]");
    if (file) showAttachment(file.dataset.attachment, file.dataset.id);
    if (e.target.closest("[data-open-activity]")) openProfile("activity");
    if (e.target.closest("[data-stop-work]")) stopWork(projectData).catch(e=>announce(e.message,true));
    if(e.target.closest("[data-open-tools]")) openTools(projectData);
    if(e.target.closest("[data-open-demo]")) action(e,()=>openDemo(projectData));
    const draft=e.target.closest("[data-draft]");if(draft)putDraft(draft.dataset.draft);
    if(e.target.closest("[data-edit-proposal]")) putDraft("我想修改刚才的安排：");
    const approve=e.target.closest("[data-approve-proposal]");
    if(approve) {
      const p=projectData;
      postControl(p,"按这个做",approve.dataset.approveProposal).catch(error=>{if(currentProject===p.id)announce(error.message,true);});
    }
    if (e.target.closest("[data-retry-send]")) {
      const id=currentProject, send=pendingSends.get(id);
      if(send) sendChat(id,send).catch(error=>{if(currentProject===id) announce(error.message,true);});
    }
  };
  document.querySelector("#open-settings").onclick = () => openSettings();
  document.querySelector("#open-results").onclick = () => openProfile("context");
  // A previous project's in-flight refresh must finish before this navigation loads.
  while (refreshing) await new Promise(resolve => setTimeout(resolve, 30));
  if (id !== currentProject) return;
  await refreshProject(true);
  try { localStorage.setItem("labcouncil-project", id); } catch (_) { /* Local storage can be disabled. */ }
  closeProjects();
  await sidebar();
}
function openSettings() {
  openProfile("activity");
}
async function newConversation() {
  navigation++;
  currentProject = null; projectData = null; meetingData = [];
  try { localStorage.setItem("labcouncil-project","new"); } catch (_) { /* Optional preference. */ }
  profileSignature="";
  closeProfile();
  content.onclick = e=>{const sample=e.target.closest("[data-draft]");if(sample)putDraft(sample.dataset.draft);};
  document.querySelector("#project-title").textContent = "新的研究群";
  document.querySelector("#work-status").textContent = "";
  document.querySelector("#project-actions").innerHTML = '<button id="new-settings" aria-label="群聊设置">···</button>';
  document.querySelector("#new-settings").onclick = () => {
    showSheet("群聊设置", `<form id="new-executor">${executorSettings()}<button type="submit">保存</button></form>`);
    const form=document.querySelector("#new-executor"); form.querySelector("details").open=true;
    form.elements.namedItem("mode").value=setupSettings.mode || "research";
    form.elements.namedItem("backend").value=setupSettings.backend || "codex_cli";
    form.onsubmit=e=>action(e,async()=>{setupSettings=Object.fromEntries(new FormData(form));modeLabel(setupSettings.mode !== "simulation", setupSettings.mode === "research", setupSettings.backend);document.querySelector("#settings").close();});
  };
  modeLabel((setupSettings.mode || "research") !== "simulation", (setupSettings.mode || "research") === "research", setupSettings.backend || "codex_cli");
  announce("");
  content.innerHTML = `<div id="transcript" class="transcript"><section class="welcome"><span class="dot-character" aria-hidden="true"><i></i><i></i></span><span class="welcome-eyebrow">你的研究小组</span><h2>一个想法，就能开始。</h2><p>不必先写一份完整计划。聊聊你想弄清什么，<br>大家会留下安排、进展和依据，你随时可以改主意。</p><div class="team-roster" aria-label="小组分工"><span>协调</span><span>研究</span><span>实验</span><span>复核</span></div><div class="starter-list"><button data-draft="我想研究一个方向："><span>查一查</span><small>了解论文和已有工作</small><b aria-hidden="true">↗</b></button><button data-draft="我有一个假设，想先验证："><span>验证一下</span><small>从可核对的小实验开始</small><b aria-hidden="true">↗</b></button><button data-draft="我想和大家一起打磨这个想法："><span>一起打磨</span><small>还没想清楚也可以聊</small><b aria-hidden="true">↗</b></button></div><p class="welcome-foot">点一个开头，或直接在下面写。消息发送后才会建群。</p></section></div><div id="setup-slot" class="transcript"></div>`;
  setComposer(true);
  await sidebar();
  closeProjects();
  document.querySelector("#chat-text").focus();
}
document.querySelector("#group-search").addEventListener("input", filterGroups);
document.querySelector("#new-project").onclick = () => newConversation().catch(e => announce(e.message, true));
document.querySelector("#close-settings").onclick = () => document.querySelector("#settings").close();
document.querySelector("#toggle-projects").onclick = e => {
  if (window.innerWidth <= 850) closeProfile();
  const open = document.querySelector(".layout").classList.toggle("projects-open");
  e.currentTarget.setAttribute("aria-expanded", String(open));
  syncBackdrop();
  if(open) document.querySelector("#group-search").focus();
};
document.querySelector("#close-projects").onclick=closeProjects;
document.querySelector("#open-profile").onclick=()=>document.querySelector("#agent-panel").hidden ? openProfile() : closeProfile();
document.querySelector("#close-profile").onclick=closeProfile;
document.querySelector("#drawer-backdrop").onclick=()=>{closeProjects();closeProfile();};
document.querySelectorAll("[data-profile-tab]").forEach(b=>{
  b.onclick=()=>openProfile(b.dataset.profileTab);
  b.onkeydown=e=>{
    const keys=["ArrowLeft","ArrowRight","Home","End"];if(!keys.includes(e.key))return;e.preventDefault();
    const tabs=[...document.querySelectorAll("[data-profile-tab]")], index=tabs.indexOf(b);
    const next=e.key==="Home" ? 0 : e.key==="End" ? tabs.length-1 : (index+(e.key==="ArrowRight" ? 1 : -1)+tabs.length)%tabs.length;
    tabs[next].click();tabs[next].focus();
  };
});
document.addEventListener("keydown",e=>{if(e.key==="Escape" && !document.querySelector("#settings").open){closeProjects();closeProfile();const menu=document.querySelector("#composer-menu");if(menu)menu.hidden=true;document.querySelector(".composer-plus")?.setAttribute("aria-expanded","false");}});
document.addEventListener("keydown",e=>{
  if(e.key!=="Tab" || window.innerWidth>850 || document.querySelector("#settings").open) return;
  const drawer=!document.querySelector("#agent-panel").hidden ? document.querySelector("#agent-panel") : document.querySelector(".layout").classList.contains("projects-open") ? document.querySelector("#sidebar") : null;
  if(!drawer) return;
  const controls=[...drawer.querySelectorAll('button,a,input,select,textarea,summary,[tabindex]')].filter(el=>!el.disabled && el.tabIndex>=0 && el.getClientRects().length);
  const first=controls[0],last=controls.at(-1);
  if(e.shiftKey && document.activeElement===first) {e.preventDefault();last.focus();}
  else if(!e.shiftKey && document.activeElement===last) {e.preventDefault();first.focus();}
});
content.addEventListener("scroll",updateJumpLink,{passive:true});
window.addEventListener("resize",syncBackdrop);
if (location.protocol === "file:") {
  document.querySelector("#new-project").disabled = true;
  announce("请通过本地服务地址打开，HTML 文件预览不能保存项目。", true);
} else (async () => {
  try {
    const ps = await sidebar();
    let saved; try { saved = localStorage.getItem("labcouncil-project"); } catch (_) { /* Optional preference. */ }
    if (ps.length && saved !== "new") await showProject(ps.find(p => p.id === saved)?.id || ps[0].id);
    else await newConversation();
  } catch (e) { announce(`连接本地服务失败：${e.message}`, true); }
})();
setInterval(async () => {
  if (!currentProject || refreshing || document.querySelector("#settings").open) return;
  try { await refreshProject(); } catch (e) { announce(e.message, true); }
}, 4000);
