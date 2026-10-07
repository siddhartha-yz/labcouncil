"use strict";
const content = document.querySelector("#content"), message = document.querySelector("#message");
let currentProject = null, navigation = 0;
let projectData = null, meetingData = [], refreshing = false, busy = false;
let transcriptSignature = "", setupSettings = {};
const questionDrafts = new Map();
let noticeTimer = null;
const pendingSends = new Map();

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
  document.querySelector(".badge").textContent = research ? backendLabel(backend) + " · 研究群" : real ? backendLabel(backend) + " · 实验群" : "程序演示群 · 不调用模型";
  document.querySelector("footer").textContent = "";
}
async function api(path, body) {
  const response = await fetch(path, body === undefined ? { cache: "no-store" } : {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-LabCouncil": "local"
    },
    body: JSON.stringify(body)
  });
  const result = await response.json();
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
  document.querySelector("#projects").innerHTML = r.projects.map(p => `<button class="project-link ${p.id === currentProject ? "active" : ""}" data-project="${esc(p.id)}"><span class="group-icon" aria-hidden="true">研</span><span class="project-copy"><strong>${esc(p.title)}</strong><small>第 ${p.version} 轮 · ${p.mode === "simulation" ? "程序演示" : p.backend === "codex_cli" ? "Codex" : "Flash"}</small></span></button>`).join("") || '<p class="empty-list">还没有研究群</p>';
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
  return `<section class="panel report"><h2>本轮报告</h2><p class="muted">摘要由程序依据已保存结果整理；角色原始报告与证据可在下方展开。</p><h3>做了什么</h3><p>${ by.researcher ? "准备输入" + (computed ? "、完成计算" : "") + (review ? "，并独立复算" : "") + "，过程和数据已保存。" : "尚未完成输入准备。" }${ simulation ? "当前使用固定程序演示。" : "角色使用已选模型后台，工具只处理合成计算。" }</p><h3>发现什么</h3><p>${ esc(result) }</p>${ numbers }<h3>还有什么没做</h3><p>${ review ? review.verified ? "数值已独立核对一致，但报告文字仍需审查。" : "数值核对存在不一致，需要检查原始证据。" : "独立核验尚未完成。" } 尚未探索论文或仓库，也没有根据这个 idea 自动编写新实验。</p><h3>组会需要决定什么</h3><p>是否认可这些有限结果？下一轮的目标、资源、权限、本轮工作时长或额外要求是否需要调整？</p><details><summary>审查角色原始报告与证据（${ artifacts.length } 份）</summary>${ artifacts.map(a => {
    const b = a.body, spec = b.parameters;
    return `<article class="evidence"><h3>${ esc(roles[a.role]) }</h3>${ spec ? `<p class="muted">工具实际输入：${ spec.test_outlier_fraction === 0 ? "干净测试标签" : "测试标签约一成异常" }，${ spec.seeds.length } 次重复。</p>` : "" }<p>${ esc(b.summary) }</p>${ b.report?.limitations ? `<ul>${ b.report.limitations.map(x => `<li>${ esc(x) }</li>`).join("") }</ul>` : `<p class="muted">${ esc(b.limitation) }</p>` }<a href="/api/evidence/${ esc(a.id) }" target="_blank" rel="noopener">打开原始证据</a></article>`;
  }).join("") || "<p>尚无产物</p>" }</details></section>`;
}

const researchActions = {search_papers: "检索论文摘要", read_abstract: "读取论文摘要", search_repositories: "搜索公开仓库", inspect_repository: "检查仓库 README", synthetic_regression: "运行自有合成基准", prepare_meeting: "整理组会材料"};
function concreteFindings(report) {
  const findings = report?.findings || [];
  if (!findings.length) return "";
  return `<ul>${findings.map(item => `<li><p>${esc(item.finding)}</p><p class="muted">${esc(item.verification)}</p>${(item.evidence_refs || []).map((ref,i) => ref.startsWith("operation:") ? `<a href="/api/tool-operations/${esc(ref.slice(10))}" target="_blank" rel="noopener">查看依据${i+1}</a>` : esc(ref)).join(" · ")}</li>`).join("")}</ul>`;
}

function researchReport(artifacts, operations) {
  const latest = artifacts.at(-1)?.body;
  const orphaned = operations.filter(o => o.body.kind === "research" && !artifacts.some(a => a.task_id === o.task_id));
  const partial = orphaned.length ? `<p>另有 ${orphaned.length} 步已保存工具结果，但模型报告尚未完成或未通过检查。</p><ul>${orphaned.map(o => `<li>${esc(researchActions[o.body.action])} · ${esc(o.body.result.status)}：<a href="/api/tool-operations/${esc(o.id)}" target="_blank" rel="noopener">审查已保存工具证据</a></li>`).join("")}</ul>` : "";
  const sources = artifacts.flatMap(a => a.body.result?.sources || []);
  const reused = new Set((latest?.result?.meeting_evidence?.items || []).filter(item => item.version < artifacts.at(-1)?.version).flatMap(item => (item.result.sources || []).map(source => source.id))).size;
  return `<section class="panel report"><h2>本轮报告</h2><p class="muted">以下是模型报告，来源和工具状态可以核对；报告文字仍需审查。</p><h3>做了什么</h3>${partial}<p>${ artifacts.length ? `已保存 ${artifacts.length} 个研究步骤，本轮读取 ${sources.length} 条资料记录。${reused ? `另复用前轮 ${reused} 条已保存资料。` : ""}` : "后台尚未保存研究步骤。" }</p><h3>发现什么</h3>${concreteFindings(latest?.report) || `<p>${esc(latest?.summary || "还没有可审查的结果。")}</p>`}<h3>还有什么没做</h3><ul>${ (latest?.report?.limitations || ["尚未执行上游仓库代码，也没有完成论文实验复现。"]).map(x => `<li>${esc(x)}</li>`).join("") }</ul><h3>组会需要决定什么</h3><p>${ esc(latest?.report?.next_step || "等待资料整理后，再确定下一轮目标与执行条件。") }</p><details><summary>逐步报告与原始证据（${artifacts.length} 份）</summary>${artifacts.map((a,i) => {const b=a.body;return `<article class="evidence"><h3>第 ${i+1} 步：${esc(researchActions[b.action] || b.action)}</h3><p>${esc(b.summary)}</p><p class="muted">实际工具状态：${esc(b.result?.status)}；参数：${esc(b.value || "无")}。</p><p>本步规划：${esc(b.plan)}</p><p>原因：${esc(b.reason)}</p><ul>${(b.result?.sources || []).map(x => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>：${esc(x.verification)}</li>`).join("")}</ul>${b.result?.error ? `<p>${esc(b.result.error)}</p>` : ""}<a href="/api/evidence/${esc(a.id)}" target="_blank" rel="noopener">打开原始证据</a></article>`;}).join("")}</details></section>`;
}

function requestDetails(p) {
  const real = p.execution.mode !== "simulation", rs = p.model_requests, known = rs.filter(r => r.usage && Number.isFinite(r.usage.total_tokens));
  return `<details><summary>执行状态、额度与调用明细</summary>${p.execution.backend === "codex_cli" && real ? `<p>模型后台：${esc(backendLabel(p.execution.backend))}。以下请求次数按 CLI 启动计数，内部模型 turn 未设硬上限；token 为 CLI 返回的用量。平台工具受原权限限制。</p>` : ""}<p>本轮时间预算：最多${p.round_time.duration_minutes}分钟，截止${esc(when(p.round_time.deadline_at))}。这是投入上限，不是完成量。</p><p>本轮已保存 ${p.artifacts.filter(a => a.version === p.version).length} 份报告、${p.tool_operations.filter(o => p.tasks.some(t => t.id === o.task_id && t.version === p.version)).length} 份工具结果；失败 ${p.tasks.filter(t => t.version === p.version && t.status === "failed").length} 个步骤。</p><p>角色任务已用 ${ p.used }/${ p.budget }；问答已用 ${ p.qa_used } 次（不限次数）。${ real ? `后台真实请求 ${ rs.filter(r => r.category === "background").length }/${ p.execution.api_budget }；公开资料请求 ${(p.source_requests || []).length}/${p.execution.source_budget ?? 24}；组会真实请求 ${ rs.filter(r => r.category === "qa").length } 次（不限次数）。已知 ${ known.reduce((n, r) => n + r.usage.total_tokens, 0) } tokens；${ rs.length - known.length } 次用量未知。人民币费用未知，没有 token 硬上限。` : "角色与问答为固定程序，不调用模型。" }</p><ul>${ p.tasks.map(t => `<li>第 ${ t.version } 轮 · ${ esc(roles[t.role] || t.role.replace("research_step_", "研究步骤 ")) } · ${ esc(states[t.status]) }${ t.error ? `：${ esc(t.error) }` : "" }</li>`).join("") }</ul>${ real ? `<h3>实际模型请求</h3><ul>${ rs.map(r => `<li><a href="/api/model-requests/${ esc(r.id) }" target="_blank" rel="noopener">${ esc(r.phase) } · ${ esc(r.status) }</a></li>`).join("") }</ul><h3>公开来源请求</h3><ul>${(p.source_requests || []).map(r => `<li><a href="/api/source-requests/${esc(r.id)}" target="_blank" rel="noopener">${esc(r.url)} · ${esc(r.status)} · HTTP ${r.http_status ?? "未知"} · ${esc(r.transport || "原记录")} · 第 ${r.attempt_number ?? 1} 次尝试</a></li>`).join("") || "<li>无公开来源请求</li>"}</ul><h3>独立保存的工具结果</h3><ul>${ p.tool_operations.map(o => `<li><a href="/api/tool-operations/${ esc(o.id) }" target="_blank" rel="noopener">${ esc(o.body.tool || researchActions[o.body.action] || o.body.action) }</a></li>`).join("") || "<li>早期工具结果保存在角色证据内。</li>" }</ul>` : "" }</details>`;
}

function bubble(key, speaker, body, user = false, time = null) {
  const role = user ? "me" : speaker.includes("计算") || speaker.includes("实验") ? "compute" : speaker.includes("复算") || speaker.includes("复核") ? "review" : speaker.includes("研究") || speaker.includes("准备输入") ? "research" : "host";
  const names = {me: "你", compute: "实验员", review: "复核员", research: "研究员", host: "协调助手"};
  const initials = {me: "我", compute: "算", review: "核", research: "研", host: "助"};
  return `<article class="chat-message ${user ? "user-message" : "lab-message"} role-${role}" data-key="${esc(key)}"><span class="avatar" aria-hidden="true">${initials[role]}</span><div class="message-column"><div class="message-meta" title="${esc(speaker)}${time ? ` · ${esc(when(time))}` : ""}">${names[role]}</div><div class="message-body">${body}</div></div></article>`;
}
function attachment(kind, id, label) {
  return `<button class="attachment" data-attachment="${kind}" data-id="${esc(id)}"><span class="attachment-icon" aria-hidden="true">▤</span><span>${esc(label)}<small>点击查看</small></span><span aria-hidden="true">›</span></button>`;
}
function statusText(p) {
  const ts = p.tasks.filter(t => t.version === p.version);
  if (ts.some(t => t.status === "running")) return p.round_time?.expired ? "本轮时长已到，正在保存当前步骤的结果" : `后台正在工作 · 剩余约${Math.ceil((p.round_time?.remaining_seconds ?? 0)/60)}分钟`;
  if (p.events.some(e => e.kind === "round_time_expired" && JSON.parse(e.body).version === p.version)) return "投入时间已到，可以讨论接下来怎么做";
  if (ts.some(t => t.status === "failed")) return "有步骤未完成，记录已保存，可以继续讨论";
  if (p.paused) return "后台已暂停启动新任务";
  if (ts.length && ts.every(t => t.status === "completed" || t.status === "cancelled")) return "当前工作已结束，随时聊进展或安排后续";
  if (p.used >= p.budget) return "任务额度已用完，可以审查已有结果";
  return p.work_blocker?.replaceAll("等待组会调整", "可以在群里补充安排").replaceAll("等待组会", "可以继续在群里讨论") || "后台按投入预算和当前权限安排工作";
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
    add(input.created, 0, `<div class="round-marker" data-key="round-${input.version}">第 ${input.version} 轮</div>`);
    add(input.created, 1, bubble(`input-${input.version}`, "你 · 已确认的本轮输入", `<p class="prose">${esc(input.body.idea)}</p>${attachment("inputs", input.version, "已记录的资源与权限")}`, true, input.created));
    add(input.created, 2, bubble(`plan-${input.version}`, "LabCouncil · 工作安排", `<p>${esc(input.plan.granularity)}</p>${attachment("plan", input.version, "工作安排")}`));
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
    if (!["research_stopped", "round_time_expired", "group_plan_applied", "group_plan_stale"].includes(event.kind)) continue;
    const data = typeof event.body === "string" ? JSON.parse(event.body) : event.body;
    add(event.created, 4, bubble(`stopped-${event.id || event.created}`, "LabCouncil · 本轮停止原因", `<p>${esc(data.reason)}</p>${event.kind === "group_plan_applied" ? attachment("inputs", data.version, "已记下的工作安排") : ""}`));
  }
  for (const m of meetings) {
    const s = m.snapshot, real = !s.simulation;
    if (!p.events.some(e => e.kind === "group_plan_applied" && JSON.parse(e.body).version === m.version + 1)) add(m.created, 5, bubble(`meeting-${m.id}`, "LabCouncil · 保存的讨论材料", `${attachment("meeting", m.id, `历史材料 · ${when(s.cutoff)}`)}`));
    (m.discussion || []).forEach((d, i) => {
      add(d.created, 6, bubble(`question-${m.id}-${i}`, `你 · 第 ${m.version} 轮组会`, `<p class="prose">${esc(d.question)}</p>`, true, d.created));
      add(d.created, 7, bubble(`answer-${m.id}-${i}`, real ? "研究员 · " + backendLabel(p.execution.backend) + " 依据本场快照答复" : "研究员 · 模板答复，程序演示", `<p class="prose">${esc(d.answer)}</p>`));
    });
    if (m.decision && !chatVersions.has(m.decision.to_version)) add(m.decision.created || m.created, 8, bubble(`decision-${m.id}`, "LabCouncil · 组会决定已保存", `<p>已确认第 ${m.decision.to_version} 轮方向：${esc(m.decision.instruction)}</p><p class="muted">此前输入、规划、报告与讨论继续保留。</p>`));
  }
  for (const m of p.group_messages || []) {
    add(m.created, 6, bubble(`group-user-${m.id}`, "你", `<p class="prose">${esc(m.user_text)}</p>`, true, m.created));
    add(m.finished || m.created, 7, bubble(`group-answer-${m.id}`, m.speaker,
      `<p class="prose">${esc(m.answer || "正在看你的消息…")}</p>${m.request_id ? attachment("chat-context", m.id, "这条答复的依据") : ""}`, false, m.finished));
  }
  return entries.sort((a, b) => a.time - b.time || a.rank - b.rank).map(e => e.html).join("");
}
function updateTranscript(p, meetings, forceBottom = false) {
  const html = transcript(p, meetings);
  if (html === transcriptSignature) return;
  const nearBottom = content.scrollHeight - content.scrollTop - content.clientHeight < 100;
  const top = content.scrollTop;
  const expanded = [...content.querySelectorAll("details[open]")].map(d => [d.closest("[data-key]")?.dataset.key, [...d.closest("[data-key]").querySelectorAll("details")].indexOf(d)]);
  content.querySelector("#transcript").innerHTML = html;
  for (const [key, index] of expanded) {
    const article = [...content.querySelectorAll("[data-key]")].find(a => a.dataset.key === key);
    if (article?.querySelectorAll("details")[index]) article.querySelectorAll("details")[index].open = true;
  }
  transcriptSignature = html;
  content.scrollTop = forceBottom || (nearBottom) ? content.scrollHeight : top;
}
function setComposer(force = false) {
  const area = document.querySelector("#compose-area"), p = projectData;
  const key = currentProject || "new";
  if (!force && area.dataset.context === key && area.querySelector("textarea")) {
    area.querySelector("#composer-help").textContent = busy ? "正在等待答复…" : "Enter 发送，Shift+Enter 换行";
    area.querySelector("textarea").disabled = busy;
    area.querySelector("button[type=submit]").disabled = busy;
    return;
  }
  area.dataset.context = key;
  area.innerHTML = `<form id="composer"><label class="sr-only" for="chat-text">群聊消息</label><textarea id="chat-text" rows="2" maxlength="4000" placeholder="${p ? "发消息，和大家讨论或安排工作…" : "先告诉大家，你想研究什么…"}" required ${busy ? "disabled" : ""}>${esc(questionDrafts.get(key) || "")}</textarea><div class="send-row"><span id="composer-help">Enter 发送，Shift+Enter 换行</span><button type="submit" ${busy ? "disabled" : ""}>发送</button></div></form>`;
  const form = area.querySelector("form"), text = form.querySelector("textarea");
  bindEnter(form, text);
  text.addEventListener("input", () => questionDrafts.set(key, text.value));
  form.onsubmit = e => action(e, async () => {
    const value = text.value.trim();
    if (!value || busy) return;
    busy = true; setComposer();
    try {
      if (!p) {
        const brief = {...defaultBrief(), idea:value, permissions:{model_calls:false,local_compute:false,public_research:false,retry_public_reads:false}};
        const result = await api("/api/projects", {title:setupSettings.title || value.slice(0,60), idea:value, brief,
          mode:setupSettings.mode || "research", backend:setupSettings.backend || "codex_cli",
          scenario:setupSettings.scenario || "clean", api_budget:Number(setupSettings.api_budget ?? 12), source_budget:Number(setupSettings.source_budget ?? 24)});
        questionDrafts.delete(key); await showProject(result.id);
        announce("群已建立。资源、权限和投入预算可以直接在聊天里补充。");
        return;
      }
      const saved = pendingSends.get(p.id);
      const send = saved?.message === value ? saved : {message:value,message_id:crypto.randomUUID()};
      pendingSends.set(p.id,send);
      await api(`/api/projects/${p.id}/chat`,send);
      pendingSends.delete(p.id); questionDrafts.delete(key); text.value="";
      if (currentProject === p.id) await refreshProject(true);
    } finally { busy=false; setComposer(); }
  });
}
function bindEnter(form, text) {
  text.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
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
    const b = a.body;
    showSheet("报告与证据", b.kind === "research" ? `${researchReport([a], [])}<a href="/api/evidence/${esc(id)}" target="_blank" rel="noopener">原始证据 ↗</a>` : report(p.artifacts.filter(x => x.version === a.version), p.execution.mode === "simulation"));
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
    document.querySelector("#project-title").textContent = p.title;
    document.querySelector("#work-status").textContent = statusText(p);
    modeLabel(p.execution.mode !== "simulation", p.execution.mode === "research", p.execution.backend);
    updateTranscript(p, meetings, forceBottom);
    setComposer();
    if (oldVersion && oldVersion !== p.version) await sidebar();
  } finally { refreshing = false; }
}
async function showProject(id) {
  navigation++;
  currentProject = id; transcriptSignature = "";
  projectData = null; meetingData = [];
  content.innerHTML = '<div id="transcript" class="transcript"></div><div id="setup-slot" class="transcript"></div>';
  document.querySelector("#compose-area").innerHTML = "";
  document.querySelector("#compose-area").dataset.context = "";
  document.querySelector("#project-actions").innerHTML = '<button id="open-settings" aria-label="群聊设置" title="群聊设置">···</button>';
  document.querySelector("#project-title").textContent = "正在读取项目…";
  announce("");
  document.querySelector("#work-status").textContent = "正在读取保存的报告与讨论…";
  content.onclick = e => {
    const file = e.target.closest("[data-attachment]");
    if (file) showAttachment(file.dataset.attachment, file.dataset.id);

  };
  document.querySelector("#open-settings").onclick = () => openSettings();
  // A previous project's in-flight refresh must finish before this navigation loads.
  while (refreshing) await new Promise(resolve => setTimeout(resolve, 30));
  if (id !== currentProject) return;
  await refreshProject(true);
  try { localStorage.setItem("labcouncil-project", id); } catch (_) { /* Local storage can be disabled. */ }
  document.querySelector("#sidebar").classList.remove("mobile-open");
  document.querySelector("#toggle-projects").setAttribute("aria-expanded", "false");
  await sidebar();
}
function openSettings() {
  const p = projectData;
  if (!p) return;
  const at = p.meeting_at ? new Date(p.meeting_at * 1000) : null;
  const local = at ? new Date(at.getTime() - at.getTimezoneOffset() * 60000).toISOString().slice(0,16) : "";
  document.querySelector("#settings-title").textContent = "群聊设置";
  document.querySelector("#settings-body").innerHTML = `<p class="muted">工作目标、资源和投入预算可以直接在群里商量。权限由你明确授权，工作安排经你同意后执行。这里保留后台消耗与暂停设置。</p><form id="configure"><div class="form-grid"><label>项目任务总上限<input name="budget" type="number" min="0" max="100" value="${p.budget}" required></label></div><label>后台状态<select name="paused"><option value="false" ${!p.paused ? "selected" : ""}>继续</option><option value="true" ${p.paused ? "selected" : ""}>暂停启动新任务</option></select></label><label>下次准备组会材料时间（本机时区）<input name="meeting_at" type="datetime-local" value="${local}"><span class="muted">留空取消定时安排。</span></label><button class="primary" type="submit">保存设置</button></form>${requestDetails(p)}`;
  document.querySelector("#configure").onsubmit = e => action(e, async () => {
    const f = new FormData(e.currentTarget);
    await api(`/api/projects/${p.id}/configure`, {paused: f.get("paused") === "true", budget: Number(f.get("budget")), meeting_at: f.get("meeting_at") ? new Date(f.get("meeting_at")).getTime()/1000 : null});
    document.querySelector("#settings").close();
    await refreshProject();
    announce("工作设置已保存。");
  });
  document.querySelector("#settings").showModal();
}
async function newConversation() {
  navigation++;
  currentProject = null; projectData = null; meetingData = [];
  content.onclick = null;
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
  content.innerHTML = `<div id="transcript" class="transcript"><div class="round-marker">新的研究群</div>${bubble("welcome", "协调助手", '<p>我们在这里一起做研究。</p><p>直接说你的 idea，或者交代想做的事情。资源、权限、投入上限和额外要求可以边聊边补充；有新的工作安排时，我会先复述，再按你的意见做。</p>')}</div><div id="setup-slot" class="transcript"></div>`;
  setComposer(true);
  await sidebar();
  document.querySelector("#sidebar").classList.remove("mobile-open");
  document.querySelector("#toggle-projects").setAttribute("aria-expanded", "false");
  document.querySelector("#chat-text").focus();
}
document.querySelector("#group-search").addEventListener("input", filterGroups);
document.querySelector("#new-project").onclick = () => newConversation().catch(e => announce(e.message, true));
document.querySelector("#close-settings").onclick = () => document.querySelector("#settings").close();
document.querySelector("#toggle-projects").onclick = e => {
  const open = document.querySelector("#sidebar").classList.toggle("mobile-open");
  e.currentTarget.setAttribute("aria-expanded", String(open));
};
if (location.protocol === "file:") {
  document.querySelector("#new-project").disabled = true;
  announce("请通过本地服务地址打开，HTML 文件预览不能保存项目。", true);
} else (async () => {
  try {
    const ps = await sidebar();
    let saved; try { saved = localStorage.getItem("labcouncil-project"); } catch (_) { /* Optional preference. */ }
    if (ps.length) await showProject(ps.find(p => p.id === saved)?.id || ps[0].id);
    else await newConversation();
  } catch (e) { announce(`连接本地服务失败：${e.message}`, true); }
})();
setInterval(async () => {
  if (!currentProject || busy || refreshing || document.querySelector("#settings").open) return;
  try { await refreshProject(); } catch (e) { announce(e.message, true); }
}, 4000);
