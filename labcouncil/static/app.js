"use strict";
const content = document.querySelector("#content"), message = document.querySelector("#message");
let currentProject = null, currentMeeting = null, navigation = 0;
let projectData = null, meetingData = [], editing = false, refreshing = false, busy = false;
let transcriptSignature = "", setupDraft = null, setupSettings = {};
const questionDrafts = new Map();
let wizard = null, noticeTimer = null;
const drafts = new Map();
const esc = x => String(x ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "\"": "&quot;",
  "'": "&#39;"
}[c]));
const roundDuration = b => b.work_time?.duration_minutes ?? 120;
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
  document.querySelector("footer").textContent = "讨论不会改变执行计划，下一轮需明确确认。";
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
    if (b.isConnected && b.closest("#composer") && !editing) setComposer();
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
function briefFields(b) {
  const minutes = roundDuration(b);
  return `<label>Idea：这一轮想解决什么？<textarea name="idea" maxlength="4000" required placeholder="写清楚你想知道什么、希望得到什么结果">${ esc(b.idea) }</textarea></label><label>可调用资源<textarea name="resources" maxlength="4000" placeholder="例如：可用模型和调用额度、本机算力、已有数据、论文或仓库地址。不要填写密钥。">${ esc(b.resources) }</textarea></label><fieldset><legend>权限：允许 agent 做什么？</legend><label class="check"><input type="checkbox" name="model_calls" ${ b.permissions.model_calls ? "checked" : "" }>调用已配置的模型（可能产生费用）</label><label class="check"><input type="checkbox" name="local_compute" ${ b.permissions.local_compute ? "checked" : "" }>运行已接入的本地计算工具</label><label class="check"><input type="checkbox" name="public_research" ${ b.permissions.public_research ? "checked" : "" }>查询公开论文与仓库</label><label class="check"><input type="checkbox" name="retry_public_reads" ${b.permissions.retry_public_reads ? "checked" : ""}>公开资料连接失败后，允许最多再试两次（每次留记录并计入额度）</label><p class="muted">这些勾选不授权任意 shell、安装依赖、公开发布或访问其他私人文件。</p></fieldset><fieldset><legend>本轮研究预算：最多工作多久？</legend><label>本轮工作时长（分钟）<input name="duration_minutes" type="number" min="1" max="10080" step="1" value="${esc(minutes)}" required></label><p class="muted">确认后开始计时，暂停和服务离线也计入。到时不启动新步骤，已启动的步骤可保存结果。任务完成或资源用完可以提前停止；时长不是完成量。</p></fieldset><label>额外要求<textarea name="requirements" maxlength="4000" placeholder="例如：先复现再采用；保留失败记录；报告用大白话；不要重复已有实验。">${ esc(b.requirements) }</textarea></label>`;
}
function readBrief(form) {
  const f = new FormData(form);
  return {
    idea: f.get("idea"),
    resources: f.get("resources"),
    requirements: f.get("requirements"),
    permissions: {
      model_calls: f.has("model_calls"),
      local_compute: f.has("local_compute"),
      public_research: f.has("public_research"),
      retry_public_reads: f.has("retry_public_reads")
    },
    work_time: { duration_minutes: Number(f.get("duration_minutes")) }
  };
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
  if (p.events.some(e => e.kind === "round_time_expired" && JSON.parse(e.body).version === p.version)) return "本轮工作时长已到，等待你开组会";
  if (ts.some(t => t.status === "failed")) return "本轮有任务失败，可以开组会审查已保存结果";
  if (p.paused) return "后台已暂停启动新任务";
  if (ts.length && ts.every(t => t.status === "completed" || t.status === "cancelled")) return "本轮工作已结束，可以开组会";
  if (p.used >= p.budget) return "任务额度已用完，可以审查已有结果";
  return p.work_blocker || "后台按本轮时间预算和当前权限安排工作";
}
function qaBlocker(p, m) {
  if (m?.status === "closed") return "这场组会已结束。点“开组会”回到当前轮次。";
  const real = p.execution.mode !== "simulation", s = m?.snapshot;
  if (!(s ? s.artifacts.length || (s.tool_operations || []).length : p.artifacts.some(a => a.version === p.version) || p.tool_operations.some(o => p.tasks.some(t => t.id === o.task_id && t.version === p.version)))) return s ? "本场固定材料还没有证据，可查看后续报告或调整下一轮。" : "还没有可讨论的证据，先等研究员保存结果。";
  if (real && !p.current_inputs.body.permissions.model_calls) return "未授权模型调用，可先查看报告或调整下一轮。";
  return null;
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
  for (const input of p.input_history.length ? p.input_history : [p.current_inputs]) {
    add(input.created, 0, `<div class="round-marker" data-key="round-${input.version}">第 ${input.version} 轮</div>`);
    add(input.created, 1, bubble(`input-${input.version}`, "你 · 已确认的本轮输入", `<p class="prose">${esc(input.body.idea)}</p>${attachment("inputs", input.version, "本轮工作条件")}`, true, input.created));
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
    if (!["research_stopped", "round_time_expired"].includes(event.kind)) continue;
    const data = typeof event.body === "string" ? JSON.parse(event.body) : event.body;
    add(event.created, 4, bubble(`stopped-${event.id || event.created}`, "LabCouncil · 本轮停止原因", `<p>第 ${data.version} 轮：${esc(data.reason)}</p>`));
  }
  for (const m of meetings) {
    const s = m.snapshot, real = !s.simulation;
    add(m.created, 5, bubble(`meeting-${m.id}`, `LabCouncil · 第 ${m.version} 轮组会`, `<p>本场材料截止 ${esc(when(s.cutoff))}。${s.tasks.some(t => t.status !== "completed") ? "当时有任务尚未完成，材料不完整。" : "已保存当时的报告。"} 后续结果不会自动加入本场。</p>${attachment("meeting", m.id, `第 ${m.version} 轮组会材料`)}<button class="small" data-meeting="${esc(m.id)}">${m.status === "closed" ? "回看这场组会" : "进入这场组会"}</button>${m.status !== "closed" ? '<p class="muted">开组会不会自动暂停后台；需要暂停时可在工作设置中调整。</p>' : ""}`));
    (m.discussion || []).forEach((d, i) => {
      add(d.created, 6, bubble(`question-${m.id}-${i}`, `你 · 第 ${m.version} 轮组会`, `<p class="prose">${esc(d.question)}</p>`, true, d.created));
      add(d.created, 7, bubble(`answer-${m.id}-${i}`, real ? "研究员 · " + backendLabel(p.execution.backend) + " 依据本场快照答复" : "研究员 · 模板答复，程序演示", `<p class="prose">${esc(d.answer)}</p>`));
    });
    if (m.decision) add(m.decision.created || m.created, 8, bubble(`decision-${m.id}`, "LabCouncil · 组会决定已保存", `<p>已确认第 ${m.decision.to_version} 轮方向：${esc(m.decision.instruction)}</p><p class="muted">此前输入、规划、报告与讨论继续保留。</p>`));
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
  content.scrollTop = forceBottom || (nearBottom && !editing) ? content.scrollHeight : top;
}
function selectedMeeting() { return meetingData.find(m => m.id === currentMeeting); }
function setComposer(force = false) {
  if (editing) { wizardComposer(); return; }
  const area = document.querySelector("#compose-area"), p = projectData, m = selectedMeeting();
  const blocker = p ? qaBlocker(p, m) : null;
  if (!force && area.dataset.context === `${currentProject}:${currentMeeting}`) {
    area.querySelector("#composer-help").textContent = busy ? "正在等待答复…" : blocker || "Enter 发送，Shift+Enter 换行";
    area.querySelector("textarea").disabled = Boolean(blocker) || busy;
    area.querySelector("button[type=submit]").disabled = Boolean(blocker) || busy;
    return;
  }
  const wasTyping = area.contains(document.activeElement) && document.activeElement.id === "chat-text";
  const selection = wasTyping ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
  area.dataset.context = `${currentProject}:${currentMeeting}`;
  const draftKey = currentProject || "new";
  area.innerHTML = `<div class="chat-tools">${p ? '<button id="composer-meeting">开组会</button><button id="next-inputs">下一轮方向</button><button id="conditions">工作条件</button>' : '<span>研究员、实验员、复核员和你一起工作</span>'}<span class="chat-context">${m?.status === "in_review" ? `第 ${m.version} 轮组会` : ""}</span></div><form id="composer"><label class="sr-only" for="chat-text">群聊消息</label><textarea id="chat-text" name="question" rows="2" maxlength="${p ? 1000 : 4000}" placeholder="${p ? "发消息，和大家讨论…" : "先告诉大家，你想研究什么…"}" required ${blocker || busy ? "disabled" : ""}>${esc(questionDrafts.get(draftKey) || "")}</textarea><div class="send-row"><span id="composer-help">${esc(blocker || "Enter 发送，Shift+Enter 换行")}</span><button type="submit" ${blocker || busy ? "disabled" : ""}>发送</button></div></form>`;
  const form = area.querySelector("form"), text = form.querySelector("textarea");
  bindEnter(form, text);
  if (wasTyping && !text.disabled) { text.focus(); text.setSelectionRange(...selection); }
  text.addEventListener("input", () => questionDrafts.set(draftKey, text.value));
  form.onsubmit = e => action(e, async () => {
    const value = text.value.trim();
    if (!value || busy) return;
    if (!p) {
      setupDraft = {...(setupDraft || defaultBrief()), idea: value};
      startWizard("resources");
      return;
    }
    if (qaBlocker(projectData, selectedMeeting())) return;
    busy = true; setComposer();
    try {
      let meeting = selectedMeeting();
      if (!meeting || meeting.status === "closed") {
        const result = await api(`/api/projects/${p.id}/meeting`, {});
        currentMeeting = result.id;
        meeting = await api(`/api/meetings/${result.id}`);
      }
      const blocked = qaBlocker(projectData, meeting);
      if (blocked) throw new Error(blocked);
      await api(`/api/meetings/${meeting.id}/ask`, {question: value});
      questionDrafts.delete(draftKey); text.value = "";
      if (currentProject === p.id) await refreshProject(true);
    } finally { busy = false; setComposer(); }
  });
  area.querySelector("#composer-meeting")?.addEventListener("click", e => action(e, () => openMeeting()));
  area.querySelector("#next-inputs")?.addEventListener("click", e => action(e, async () => { await ensureCurrentMeeting(); startWizard("idea"); }));
  area.querySelector("#conditions")?.addEventListener("click", () => showAttachment("inputs", p.version));
}
function bindEnter(form, text) {
  text.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
}
async function ensureCurrentMeeting() {
  if (busy) throw new Error("请等当前答复完成。");
  const m = selectedMeeting();
  if (m && m.status !== "closed" && m.version === projectData.version) return m;
  const result = await api(`/api/projects/${currentProject}/meeting`, {});
  currentMeeting = result.id;
  await refreshProject(true);
  return selectedMeeting();
}
async function openMeeting() {
  if (editing || busy) throw new Error("请先完成当前输入或等待答复。");
  await ensureCurrentMeeting();
  setComposer(true);
}
function startWizard(step) {
  const p = projectData, m = selectedMeeting();
  if (p && (!m || m.status === "closed" || m.version !== p.version)) return;
  const saved = m ? drafts.get(m.id) || m.draft : null;
  const brief = JSON.parse(JSON.stringify(saved?.brief || p?.current_inputs.body || setupDraft || defaultBrief()));
  brief.work_time = {duration_minutes: roundDuration(brief)};
  wizard = {p, m, brief, settings: {...setupSettings}, scenario: saved?.scenario || p?.scenario || "clean", revision: saved?.revision || 0, step: saved ? "review" : step, messages: []};
  editing = true;
  if (!p) content.querySelector("#transcript").innerHTML = bubble("initial-idea", "你", `<p class="prose">${esc(brief.idea)}</p>`, true);
  renderWizard();
}
const wizardPrompts = {
  idea: "下一轮想让大家解决什么？原有资料和讨论都会接着用。",
  resources: "你手头有哪些资源？例如本机算力、已有数据、可用模型，或者想研究的论文和仓库。不要发密钥。",
  permissions: "开始前，明确一下我们能做哪些事。权限和执行方式由你选择。",
  hours: "这一轮最多让大家工作多久？这是投入上限，完成任务或资源用完可提前停；到时等你开组会。",
  requirements: "还有其他要求吗？例如先复现再采用、保留失败记录，或者报告尽量简短。",
  review: "条件整理好了。你确认后，我们就按这些条件开始这一轮。"
};
function renderWizard() {
  if (!wizard) return;
  const w = wizard, b = w.brief;
  let controls = "";
  if (w.step === "permissions") controls = `<form id="permission-step"><label class="check"><input type="checkbox" name="model_calls" ${b.permissions.model_calls ? "checked" : ""}>调用已配置的模型</label><label class="check"><input type="checkbox" name="local_compute" ${b.permissions.local_compute ? "checked" : ""}>运行已接入的本地计算</label><label class="check"><input type="checkbox" name="public_research" ${b.permissions.public_research ? "checked" : ""}>查公开论文与仓库</label><label class="check"><input type="checkbox" name="retry_public_reads" ${b.permissions.retry_public_reads ? "checked" : ""}>公开连接失败后最多再试两次</label>${!w.p ? `<label>执行方式<select name="mode"><option value="simulation">程序演示 · 不调用模型</option><option value="research">逐步研究</option><option value="real_case">固定计算</option></select></label>${backendSelect()}` : ""}<button class="small" type="submit">按这些权限继续</button><button class="small" type="button" id="executor-options">执行设置</button></form>`;
  if (w.step === "hours") controls = `<form id="hours-step"><label>本轮工作时长（分钟）<input type="number" name="duration_minutes" min="1" max="10080" step="1" value="${esc(roundDuration(b))}" required></label><p class="muted">确认后计时；暂停和服务离线也计入。已启动步骤可收尾保存，不保证凑满时长。</p><button class="small" type="submit">按这个预算继续</button></form>`;
  if (w.step === "review") controls = `${inputsSummary(b)}<div class="actions"><button id="confirm-round" class="primary">${w.p ? "确认下一轮" : "开始工作"}</button>${w.p ? '<button id="save-wizard">保存草稿</button>' : ""}<button id="edit-conditions">调整条件</button></div><p class="muted">${w.p ? "草稿不会启动任务，确认后才进入下一轮。" : "当前执行：" + ((w.settings.mode || "simulation") === "simulation" ? "程序演示，不调用模型。" : backendLabel(w.settings.backend || "codex_cli") + "，使用本机登录的额度或对应 key。")}</p>`;
  const intro = w.messages.length ? w.messages.join("") : "";
  document.querySelector("#setup-slot").innerHTML = intro + bubble("wizard-prompt", "协调助手", `<p>${esc(wizardPrompts[w.step])}</p>${controls}`);
  const permissions = document.querySelector("#permission-step");
  if (permissions) {
    if (permissions.elements.namedItem("mode")) permissions.elements.namedItem("mode").value = w.settings.mode || "simulation";
    if (permissions.elements.namedItem("backend")) permissions.elements.namedItem("backend").value = w.settings.backend || "codex_cli";
    permissions.onsubmit = e => action(e, async () => {
      const f = new FormData(permissions);
      b.permissions = Object.fromEntries(["model_calls", "local_compute", "public_research", "retry_public_reads"].map(key => [key, f.has(key)]));
      if (f.has("mode")) w.settings.mode = f.get("mode");
      if (f.has("backend")) w.settings.backend = f.get("backend");
      advanceWizard(b.permissions.model_calls ? "已选择权限，允许模型调用。" : "已选择权限，不调用模型。", "hours");
    });
    document.querySelector("#executor-options").onclick = () => {
      const f = new FormData(permissions);
      b.permissions = Object.fromEntries(["model_calls", "local_compute", "public_research", "retry_public_reads"].map(key => [key, f.has(key)]));
      if (f.has("mode")) w.settings.mode = f.get("mode");
      if (f.has("backend")) w.settings.backend = f.get("backend");
      rememberWizard(); editExecutor();
    };
  }
  document.querySelector("#hours-step")?.addEventListener("submit", e => action(e, async () => {
    const f = new FormData(e.currentTarget);
    const minutes = Number(f.get("duration_minutes"));
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 10080) throw new Error("请输入1–10080分钟的整数。");
    b.work_time = {duration_minutes: minutes};
    advanceWizard(`本轮最多工作${minutes}分钟，之后等组会。`, "requirements");
  }));
  document.querySelector("#confirm-round")?.addEventListener("click", e => action(e, () => confirmWizard()));
  document.querySelector("#save-wizard")?.addEventListener("click", e => action(e, async () => {
    const result = await api(`/api/meetings/${w.m.id}/draft`, {expected_revision: w.revision, instruction: b.idea, scenario: w.scenario, brief: b});
    w.revision = result.revision; drafts.set(w.m.id, result);
    announce("草稿已保存，尚未启动下一轮。");
  }));
  document.querySelector("#edit-conditions")?.addEventListener("click", () => editConditions());
  wizardComposer();
  content.scrollTop = content.scrollHeight;
}
function advanceWizard(answer, next) {
  const w = wizard;
  w.messages.push(bubble(`guide-${w.messages.length}`, "协调助手", `<p>${esc(wizardPrompts[w.step])}</p>`));
  w.messages.push(bubble(`guide-${w.messages.length}`, "你", `<p class="prose">${esc(answer)}</p>`, true));
  w.step = next;
  rememberWizard(); renderWizard();
}
function rememberWizard() {
  const w = wizard;
  if (w.p) drafts.set(w.m.id, {brief: w.brief, scenario: w.scenario, revision: w.revision});
  else { setupDraft = w.brief; setupSettings = {...w.settings}; }
}
function wizardComposer() {
  if (!wizard) return;
  const area = document.querySelector("#compose-area"), w = wizard;
  const textStep = ["idea", "resources", "requirements", "review"].includes(w.step);
  const key = `wizard:${w.p?.id || "new"}:${w.step}`;
  if (area.dataset.context === key) return;
  area.dataset.context = key;
  area.innerHTML = `<div class="chat-tools"><button id="leave-wizard">${w.p ? "返回群聊" : "收起草稿"}</button>${["idea", "resources", "requirements"].includes(w.step) ? `<button id="skip-step">${w.step === "idea" ? "沿用原目标" : "沿用已有条件 / 跳过"}</button>` : ""}</div><form id="composer"><label class="sr-only" for="chat-text">群聊消息</label><textarea id="chat-text" rows="2" maxlength="4000" placeholder="${textStep ? (w.step === "review" ? "还想补充什么要求…" : "回复协调助手…") : "先在上方选择条件…"}" ${textStep ? "required" : "disabled"}></textarea><div class="send-row"><span id="composer-help">${w.step === "review" ? "点击上方按钮，确认后才开始工作" : "Enter 发送，Shift+Enter 换行"}</span><button type="submit" ${textStep ? "" : "disabled"}>发送</button></div></form>`;
  const form = area.querySelector("form"), text = form.querySelector("textarea"); bindEnter(form, text);
  form.onsubmit = e => action(e, async () => {
    const value = text.value.trim(); if (!value) return;
    if (w.step === "idea") { w.brief.idea = value; advanceWizard(value, "resources"); }
    else if (w.step === "resources") { w.brief.resources = value; advanceWizard(value, "permissions"); }
    else if (w.step === "requirements") { w.brief.requirements = value; advanceWizard(value, "review"); }
    else { w.brief.requirements = [w.brief.requirements, value].filter(Boolean).join("\n").slice(0,4000); text.value = ""; advanceWizard(value, "review"); }
  });
  area.querySelector("#skip-step")?.addEventListener("click", () => {
    const field = w.step === "idea" ? "idea" : w.step === "resources" ? "resources" : "requirements";
    advanceWizard(w.brief[field] || "暂不补充。", {idea: "resources", resources: "permissions", requirements: "review"}[w.step]);
  });
  area.querySelector("#leave-wizard").onclick = () => {
    rememberWizard(); wizard = null; editing = false;
    document.querySelector("#setup-slot").innerHTML = ""; setComposer(true);
  };
  if (textStep) text.focus();
}
async function confirmWizard() {
  const w = wizard, b = w.brief;
  let id = w.p?.id;
  if (w.p) {
    await api(`/api/meetings/${w.m.id}/confirm`, {expected_version: w.m.version, instruction: b.idea, scenario: w.scenario, brief: b});
    drafts.delete(w.m.id);
  } else {
    const result = await api("/api/projects", {title: w.settings.title || b.idea.slice(0,40), idea: b.idea, brief: b, mode: w.settings.mode || "simulation", backend: w.settings.backend || "codex_cli", scenario: w.scenario, budget: 9, api_budget: Number(w.settings.api_budget ?? 12), source_budget: Number(w.settings.source_budget ?? 24)});
    id = result.id; setupDraft = null; setupSettings = {}; questionDrafts.delete("new");
  }
  wizard = null; editing = false; await showProject(id);
}
function editConditions() {
  const w = wizard;
  showSheet("本轮工作条件", `<form id="condition-edit">${briefFields(w.brief)}<button class="primary" type="submit">保存条件，返回群聊</button></form>`);
  document.querySelector("#condition-edit").onsubmit = e => action(e, async () => {
    w.brief = readBrief(e.currentTarget); rememberWizard(); document.querySelector("#settings").close(); renderWizard();
  });
}
function editExecutor() {
  const w = wizard;
  showSheet("执行设置", `<form id="executor-edit">${executorSettings(w.p)}<button type="submit">保存设置</button></form>`);
  const form = document.querySelector("#executor-edit"); form.querySelector("details").open = true;
  for (const [key,value] of Object.entries(w.settings)) if (form.elements.namedItem(key)) form.elements.namedItem(key).value = value;
  form.elements.namedItem("scenario").value = w.scenario;
  form.onsubmit = e => action(e, async () => {
    const f = new FormData(form); w.scenario = f.get("scenario");
    for (const key of ["mode", "backend", "title", "api_budget", "source_budget"]) if (f.has(key)) w.settings[key] = f.get(key);
    rememberWizard(); document.querySelector("#settings").close(); renderWizard();
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
    projectData = p; meetingData = meetings;
    if (!currentMeeting) currentMeeting = meetings.filter(m => m.version === p.version && m.status !== "closed").at(-1)?.id || null;
    document.querySelector("#project-title").textContent = p.title;
    document.querySelector("#work-status").textContent = `第 ${p.version} 轮 · ${statusText(p)}`;
    modeLabel(p.execution.mode !== "simulation", p.execution.mode === "research", p.execution.backend);
    updateTranscript(p, meetings, forceBottom);
    setComposer();
  } finally { refreshing = false; }
}
async function showProject(id) {
  navigation++;
  currentProject = id; currentMeeting = null; editing = false; wizard = null; transcriptSignature = "";
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
    if (file) { showAttachment(file.dataset.attachment, file.dataset.id); return; }
    const button = e.target.closest("[data-meeting]");
    if (!button || editing || busy) return;
    currentMeeting = button.dataset.meeting;
    setComposer(true);
    document.querySelector("#chat-text")?.focus();
    announce(selectedMeeting()?.status === "closed" ? "这是已结束的组会。要继续项目，请开当前轮次的组会。" : "追问将依据这场组会的固定材料作答。");
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
  document.querySelector("#settings-body").innerHTML = `<p class="muted">本轮工作时长、资源与权限在组会后调整下一轮时修改。后台任务额度是整个项目累计上限；组会问答不设次数上限。</p><form id="configure"><div class="form-grid"><label>项目任务总上限<input name="budget" type="number" min="0" max="100" value="${p.budget}" required></label></div><label>后台状态<select name="paused"><option value="false" ${!p.paused ? "selected" : ""}>继续</option><option value="true" ${p.paused ? "selected" : ""}>暂停启动新任务</option></select></label><label>下次准备组会材料时间（本机时区）<input name="meeting_at" type="datetime-local" value="${local}"><span class="muted">留空取消定时安排。</span></label><button class="primary" type="submit">保存设置</button></form>${requestDetails(p)}`;
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
  currentProject = null; currentMeeting = null; projectData = null; meetingData = []; editing = false; wizard = null;
  content.onclick = null;
  document.querySelector("#project-title").textContent = "新的研究群";
  document.querySelector("#work-status").textContent = "";
  document.querySelector("#project-actions").innerHTML = "";
  modeLabel(false);
  announce("");
  content.innerHTML = `<div id="transcript" class="transcript"><div class="round-marker">新的研究群</div>${bubble("welcome", "协调助手", '<p>我们在这里一起做研究。</p><p>先说说你的 idea。接着我会问资源、权限、本轮工作时长和额外要求，确认后大家开始工作。</p>')}</div><div id="setup-slot" class="transcript"></div>`;
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
