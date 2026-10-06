"use strict";
const content = document.querySelector("#content"), message = document.querySelector("#message");
let currentProject = null, currentMeeting = null, page = "project", navigation = 0;
const drafts = new Map();
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
  cancelled: "已被新一轮替代"
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
    public_research: false
  },
  work_time: {
    all_day: false,
    start: "09:00",
    end: "18:00",
    timezone: "Asia/Shanghai"
  }
});
function announce(text, error = false) {
  message.textContent = text;
  message.className = error ? "error" : "";
}
function modeLabel(real) {
  document.querySelector(".badge").textContent = real ? "真实 Flash · 固定计算案例" : "流程演示 · 不调用模型";
  document.querySelector("footer").textContent = "项目输入、规划、证据和组会决定按轮次保存。当前执行器限于固定计算案例，尚未接入自动文献研究。";
}
function pipeline(step) {
  return `<ol class="pipeline" aria-label="项目流程">${ [
    "设定本轮",
    "后台工作与报告",
    "开组会"
  ].map((s, i) => `<li ${ step === i + 1 ? "aria-current=\"step\"" : "" }>${ i + 1 }. ${ s }</li>`).join("") }</ol>`;
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
  }
}
async function sidebar() {
  const r = await api("/api/projects");
  document.querySelector("#projects").innerHTML = r.projects.map(p => `<button class="project-link ${ p.id === currentProject ? "active" : "" }" data-project="${ esc(p.id) }">${ esc(p.title) }<small>第 ${ p.version } 轮</small></button>`).join("") || "<p class=\"muted\">还没有项目</p>";
  document.querySelectorAll("[data-project]").forEach(b => b.addEventListener("click", () => showProject(b.dataset.project).catch(e => announce(e.message, true))));
  return r.projects;
}
function briefFields(b) {
  const w = b.work_time;
  return `<label>Idea：这一轮想解决什么？<textarea name="idea" maxlength="4000" required placeholder="写清楚你想知道什么、希望得到什么结果">${ esc(b.idea) }</textarea></label><label>可调用资源<textarea name="resources" maxlength="4000" placeholder="例如：可用模型和调用额度、本机算力、已有数据、论文或仓库地址。不要填写密钥。">${ esc(b.resources) }</textarea></label><fieldset><legend>权限：允许 agent 做什么？</legend><label class="check"><input type="checkbox" name="model_calls" ${ b.permissions.model_calls ? "checked" : "" }>调用已配置的模型（可能产生费用）</label><label class="check"><input type="checkbox" name="local_compute" ${ b.permissions.local_compute ? "checked" : "" }>运行已接入的本地计算工具</label><label class="check"><input type="checkbox" name="public_research" ${ b.permissions.public_research ? "checked" : "" }>查询公开论文与仓库（尚未接入）</label><p class="muted">这些勾选不授权任意 shell、安装依赖、公开发布或访问其他私人文件。</p></fieldset><fieldset><legend>工作时间：每天什么时段可以工作？</legend><div class="form-grid"><label>每天开始<input name="start" type="time" value="${ esc(w.start) }" required></label><label>每天结束<input name="end" type="time" value="${ esc(w.end) }" required></label></div><label>时区<input name="timezone" value="${ esc(w.timezone) }" required></label><label class="check"><input name="all_day" type="checkbox" ${ w.all_day ? "checked" : "" }>全天可工作</label><p class="muted">支持跨午夜。时段外不启动新任务，已开始的短任务可收尾保存；你可随时开组会。</p></fieldset><label>额外要求<textarea name="requirements" maxlength="4000" placeholder="例如：先复现再采用；保留失败记录；报告用大白话；不要重复已有实验。">${ esc(b.requirements) }</textarea></label>`;
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
      public_research: f.has("public_research")
    },
    work_time: {
      all_day: f.has("all_day"),
      start: f.get("start"),
      end: f.get("end"),
      timezone: f.get("timezone")
    }
  };
}
function scenarioOptions(s = "clean", real = false) {
  return `<option value="clean" ${ s === "clean" ? "selected" : "" }>${ real ? "干净测试数据，一次重复" : "平稳数据" }</option><option value="outlier" ${ s === "outlier" ? "selected" : "" }>${ real ? "测试标签约一成异常，三次重复" : "含异常点" }</option>`;
}
function executorSettings(p = null) {
  const real = p?.execution.mode === "real_case";
  return `<details><summary>当前执行器与实验设置</summary><p class="muted">完整研究执行器仍在开发。当前只执行预先定义的数据准备、计算与复算，不能把任意 idea 自动实现成实验。资源文字与公开研究权限会保存，但尚不接入新的机器、文件或检索工具。</p>${ !p ? "<label>项目名称（可选）<input name=\"title\" maxlength=\"120\" placeholder=\"留空时使用 idea 开头\"></label>" : "" }${ p ? `<p>${ real ? "真实 Flash 与固定工具" : "固定程序流程演示" }；执行器在项目创建时选择。</p>` : `<label>执行器<select name="mode"><option value="simulation">流程演示，不调用模型</option><option value="real_case">真实 Flash，固定合成计算</option></select></label>` }<label>本轮计算输入<select name="scenario">${ scenarioOptions(p?.scenario, real) }</select></label>${ !p ? "<div class=\"form-grid\"><label>项目后台模型请求总上限<input type=\"number\" name=\"api_budget\" value=\"12\" min=\"0\" max=\"100\" required></label><label>项目组会模型请求总上限<input type=\"number\" name=\"qa_api_budget\" value=\"1\" min=\"0\" max=\"100\" required></label></div><p class=\"muted\">真实案例每轮通常6次请求；上限包含失败尝试，不自动重试。不是 token 或人民币预算。</p>" : "" }</details>`;
}
async function setup(p = null, m = null) {
  navigation++;
  page = "inputs";
  currentProject = p?.id || null;
  currentMeeting = m?.id || null;
  const saved = m ? drafts.get(m.id) || m.draft : null;
  let b = saved?.brief || p?.current_inputs.body || defaultBrief();
  if (saved && !saved.brief)
    b = {
      ...b,
      idea: saved.instruction
    };
  const real = p?.execution.mode === "real_case";
  modeLabel(real);
  content.innerHTML = `${ pipeline(1) }<h1>${ m ? `设定第 ${ m.version + 1 } 轮` : "设定第一轮" }</h1><p>${ m ? "同一个项目继续。原有目标、规划、实验、报告与组会决定都会保留。" : "给出目标和工作边界，再让后台开始工作。" }</p><form id="inputs" class="panel">${ briefFields(b) }${ executorSettings(saved ? {
    ...p,
    scenario: saved.scenario
  } : p) }<div class="actions">${ m ? "<button id=\"save-inputs\" type=\"button\">保存草稿</button>" : "" }<button class="primary" type="submit">${ m ? "确认本轮输入，继续后台工作" : "确认输入，开始后台工作" }</button>${ m ? "<button id=\"back-meeting\" type=\"button\">返回组会</button>" : "" }</div><p id="draft-status" class="muted">${ saved ? `草稿版本 ${ saved.revision }。保存不会启动新任务。` : m ? "尚未保存。确认后才进入下一轮。" : "默认只演示流程；真实模型调用需要选择执行器并明确授权。" }</p></form>`;
  const form = document.querySelector("#inputs");
  if (!p) {
    form.querySelector("[name=mode]").addEventListener("change", e => {
      const yes = e.target.value === "real_case";
      form.querySelector("[name=scenario]").innerHTML = scenarioOptions("clean", yes);
      modeLabel(yes);
    });
  }
  form.addEventListener("submit", e => action(e, async () => {
    const brief = readBrief(form), f = new FormData(form);
    if (m) {
      await api(`/api/meetings/${ m.id }/confirm`, {
        expected_version: m.version,
        instruction: brief.idea,
        scenario: f.get("scenario"),
        brief
      });
      announce("已确认下一轮。此前上下文仍保留，后台会按权限和每日时段启动。");
      await showProject(p.id);
    } else {
      const r = await api("/api/projects", {
        title: f.get("title") || brief.idea.slice(0, 40),
        idea: brief.idea,
        brief,
        mode: f.get("mode"),
        scenario: f.get("scenario"),
        budget: 9,
        qa_budget: 6,
        api_budget: Number(f.get("api_budget")),
        qa_api_budget: Number(f.get("qa_api_budget"))
      });
      announce("输入已保存。后台按当前权限、工作时段和执行器处理。");
      await showProject(r.id);
    }
  }));
  if (m) {
    document.querySelector("#back-meeting").addEventListener("click", () => showMeeting(m.id));
    document.querySelector("#save-inputs").addEventListener("click", e => action(e, async () => {
      const brief = readBrief(form), f = new FormData(form);
      const r = await api(`/api/meetings/${ m.id }/draft`, {
        expected_revision: (drafts.get(m.id) || saved)?.revision || 0,
        instruction: brief.idea,
        scenario: f.get("scenario"),
        brief
      });
      drafts.set(m.id, r);
      document.querySelector("#draft-status").textContent = `草稿已保存 · 版本 ${ r.revision }，没有启动新任务。`;
      announce("五项输入已保存为草稿。");
    }));
    form.addEventListener("input", () => {
      drafts.set(m.id, {
        brief: readBrief(form),
        scenario: new FormData(form).get("scenario"),
        revision: (drafts.get(m.id) || saved)?.revision || 0
      });
      document.querySelector("#draft-status").textContent = "内容已修改，尚未保存；原有项目不会被覆盖。";
    });
  }
  await sidebar();
}
function inputsSummary(b) {
  const w = b.work_time;
  return `<dl><dt>Idea</dt><dd>${ esc(b.idea) }</dd><dt>资源</dt><dd>${ esc(b.resources) || "未补充" }</dd><dt>权限</dt><dd>${ [
    b.permissions.model_calls ? "模型调用" : null,
    b.permissions.local_compute ? "已接入本地计算" : null,
    b.permissions.public_research ? "公开论文与仓库查询（未接入）" : null
  ].filter(Boolean).join("、") || "未授权执行" }</dd><dt>每日时间</dt><dd>${ w.all_day ? "全天" : `${ esc(w.start) }–${ esc(w.end) }` } · ${ esc(w.timezone) }</dd><dt>额外要求</dt><dd>${ esc(b.requirements) || "未补充" }</dd></dl>`;
}
function report(artifacts, simulation) {
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
  return `<section class="panel report"><h2>本轮报告</h2><p class="muted">摘要由程序依据已保存结果整理；角色原始报告与证据可在下方展开。</p><h3>做了什么</h3><p>${ by.researcher ? "准备输入" + (computed ? "、完成计算" : "") + (review ? "，并独立复算" : "") + "，过程和数据已保存。" : "尚未完成输入准备。" }${ simulation ? "当前使用固定程序演示。" : "角色使用真实 Flash，工具只处理合成计算。" }</p><h3>发现什么</h3><p>${ esc(result) }</p>${ numbers }<h3>还有什么没做</h3><p>${ review ? review.verified ? "数值已独立核对一致，但报告文字仍需审查。" : "数值核对存在不一致，需要检查原始证据。" : "独立核验尚未完成。" } 尚未探索论文或仓库，也没有根据这个 idea 自动编写新实验。</p><h3>组会需要决定什么</h3><p>是否认可这些有限结果？下一轮的目标、资源、权限、每日时段或额外要求是否需要调整？</p><details><summary>审查角色原始报告与证据（${ artifacts.length } 份）</summary>${ artifacts.map(a => {
    const b = a.body, spec = b.parameters;
    return `<article class="evidence"><h3>${ esc(roles[a.role]) }</h3>${ spec ? `<p class="muted">工具实际输入：${ spec.test_outlier_fraction === 0 ? "干净测试标签" : "测试标签约一成异常" }，${ spec.seeds.length } 次重复。</p>` : "" }<p>${ esc(b.summary) }</p>${ b.report?.limitations ? `<ul>${ b.report.limitations.map(x => `<li>${ esc(x) }</li>`).join("") }</ul>` : `<p class="muted">${ esc(b.limitation) }</p>` }<a href="/api/evidence/${ esc(a.id) }" target="_blank" rel="noopener">打开原始证据</a></article>`;
  }).join("") || "<p>尚无产物</p>" }</details></section>`;
}
function requestDetails(p) {
  const real = p.execution.mode === "real_case", rs = p.model_requests, known = rs.filter(r => r.usage && Number.isFinite(r.usage.total_tokens));
  return `<details><summary>执行状态、额度与调用明细</summary><p>角色任务已用 ${ p.used }/${ p.budget }；问答已用 ${ p.qa_used }/${ p.qa_budget }。${ real ? `后台真实请求 ${ rs.filter(r => r.category === "background").length }/${ p.execution.api_budget }；组会真实请求 ${ rs.filter(r => r.category === "qa").length }/${ p.execution.qa_api_budget }。已知 ${ known.reduce((n, r) => n + r.usage.total_tokens, 0) } tokens；${ rs.length - known.length } 次用量未知。人民币费用未知，没有 token 硬上限。` : "角色与问答为固定程序，不调用模型。" }</p><ul>${ p.tasks.map(t => `<li>第 ${ t.version } 轮 · ${ esc(roles[t.role]) } · ${ esc(states[t.status]) }${ t.error ? `：${ esc(t.error) }` : "" }</li>`).join("") }</ul>${ real ? `<h3>实际模型请求</h3><ul>${ rs.map(r => `<li><a href="/api/model-requests/${ esc(r.id) }" target="_blank" rel="noopener">${ esc(r.phase) } · ${ esc(r.status) }</a></li>`).join("") }</ul><h3>独立保存的工具结果</h3><ul>${ p.tool_operations.map(o => `<li><a href="/api/tool-operations/${ esc(o.id) }" target="_blank" rel="noopener">${ esc(o.body.tool) }</a></li>`).join("") || "<li>早期工具结果保存在角色证据内。</li>" }</ul>` : "" }</details>`;
}
async function showProject(id) {
  const ticket = ++navigation;
  page = "project";
  currentProject = id;
  currentMeeting = null;
  const p = await api(`/api/projects/${ id }`);
  if (ticket !== navigation)
    return;
  const real = p.execution.mode === "real_case", b = p.current_inputs.body, tasks = p.tasks.filter(t => t.version === p.version), artifacts = p.artifacts.filter(a => a.version === p.version), done = tasks.every(t => t.status === "completed");
  modeLabel(real);
  let status = done ? "本轮工作完成，等待你开组会" : tasks.some(t => t.status === "failed") ? "本轮有任务失败，等待你审查" : p.paused ? "后台已暂停" : p.work_blocker || "后台按当前计划工作";
  if (!done && p.used >= p.budget && !tasks.some(t => t.status === "running"))
    status = "任务额度已用完，等待你审查";
  content.innerHTML = `${ pipeline(2) }<h1>第 ${ p.version } 轮：工作与报告</h1><p class="muted">${ esc(status) }</p><p class="direction">${ esc(b.idea.slice(0, 240)) }${ b.idea.length > 240 ? "…（完整目标见本轮输入）" : "" }</p><div class="actions"><button class="primary" id="open-meeting">开组会，审查本轮报告</button><button id="refresh">刷新进度</button></div><details><summary>本轮输入：资源、权限、每日时间与要求</summary>${ inputsSummary(b) }${ p.current_inputs.legacy ? "<p class=\"muted\">旧案例没有保存五项输入，显示兼容默认值；历史证据没有修改。</p>" : "" }</details><details><summary>本轮规划与进度 · ${ tasks.filter(t => t.status === "completed").length }/3 项完成</summary><p>${ esc(p.current_inputs.plan.granularity) }</p><ol class="plan">${ p.current_inputs.plan.steps.map((s, i) => `<li>${ esc(s) } <span class="muted">${ esc(states[tasks[i]?.status] || "等待") }</span></li>`).join("") }</ol><p class="muted">当前计划由固定执行器生成。按资源和时间自主规划、自动探索论文／仓库及持续研究 loop 仍待接入。</p></details>${ report(artifacts, !real) }<details><summary>项目历史：原有输入、规划与组会决定</summary><p class="muted">新一轮接着同一个项目工作，不会清空旧证据。历史组会材料固定为当时版本。</p>${ p.input_history.map(i => `<details><summary>第 ${ i.version } 轮输入与规划</summary>${ inputsSummary(i.body) }<ol>${ i.plan.steps.map(s => `<li>${ esc(s) }</li>`).join("") }</ol></details>`).join("") }<div class="history">${ p.meetings.map(m => `<div class="history-item"><span>第 ${ m.version } 轮组会 · ${ m.status === "closed" ? "已确认下一轮" : "待审查" }</span><button data-meeting="${ esc(m.id) }">查看组会</button></div>`).join("") || "<p>尚未开组会</p>" }</div></details>${ requestDetails(p) }<details><summary>暂停、角色额度与定时准备材料</summary><form id="configure" class="panel"><div class="form-grid"><label>项目角色任务总上限<input name="budget" type="number" min="0" max="100" value="${ p.budget }" required></label><label>项目问答总上限<input name="qa_budget" type="number" min="0" max="100" value="${ p.qa_budget }" required></label></div><label>后台状态<select name="paused"><option value="false" ${ !p.paused ? "selected" : "" }>继续</option><option value="true" ${ p.paused ? "selected" : "" }>暂停新任务</option></select></label><label>下次准备组会材料时间（浏览器本机时区）<input name="meeting_at" type="datetime-local"><span class="muted">留空取消定时安排。每日工作时段在组会后的本轮输入中调整。</span></label><button type="submit">保存设置</button></form></details>`;
  document.querySelector("#open-meeting").addEventListener("click", e => action(e, async () => {
    const m = await api(`/api/projects/${ id }/meeting`, {});
    await showMeeting(m.id);
  }));
  document.querySelector("#refresh").addEventListener("click", () => showProject(id).catch(e => announce(e.message, true)));
  content.querySelectorAll("[data-meeting]").forEach(x => x.addEventListener("click", () => showMeeting(x.dataset.meeting).catch(e => announce(e.message, true))));
  document.querySelector("#configure").addEventListener("submit", e => action(e, async () => {
    const f = new FormData(e.currentTarget);
    await api(`/api/projects/${ id }/configure`, {
      paused: f.get("paused") === "true",
      budget: Number(f.get("budget")),
      qa_budget: Number(f.get("qa_budget")),
      meeting_at: f.get("meeting_at") ? new Date(f.get("meeting_at")).getTime() / 1000 : null
    });
    announce("设置已保存。");
    await showProject(id);
  }));
  await sidebar();
}
async function showMeeting(id) {
  const ticket = ++navigation;
  page = "meeting";
  currentMeeting = id;
  const m = await api(`/api/meetings/${ id }`);
  if (ticket !== navigation)
    return;
  currentProject = m.project_id;
  const s = m.snapshot, real = !s.simulation;
  modeLabel(real);
  const p = await api(`/api/projects/${ m.project_id }`);
  if (ticket !== navigation)
    return;
  const exhausted = real && p.model_requests.filter(r => r.category === "qa").length >= p.execution.qa_api_budget || p.qa_used >= p.qa_budget || real && !p.current_inputs.body.permissions.model_calls;
  content.innerHTML = `${ pipeline(3) }<h1>第 ${ m.version } 轮组会</h1><p class="muted">材料截止 ${ when(s.cutoff) } · ${ m.status === "closed" ? "已确认下一轮" : "等待审查" }。${ s.tasks.some(t => t.status !== "completed") ? "开会时有任务尚未完成，本场材料不完整。" : "本轮报告已固定保存。" }</p><button id="back-project">返回项目</button>${ report(s.artifacts, s.simulation) }<section class="panel"><h2>追问与审查意见</h2><p class="muted">${ real ? "真实 Flash 依据本场快照回答。" : "当前为模板问答演示。" }讨论不会自动改变下一轮计划。</p>${ m.discussion.map(d => `<div class="conversation"><strong>问题</strong><p>${ esc(d.question) }</p><strong>${ real ? "Flash 答复" : "模拟答复" }</strong><p>${ esc(d.answer) }</p></div>`).join("") }${ m.status !== "closed" ? `<form id="ask"><label>你想追问什么？<textarea name="question" maxlength="1000" required ${ exhausted ? "disabled" : "" }></textarea></label><button type="submit" ${ exhausted ? "disabled" : "" }>保存追问并查看答复</button>${ exhausted ? "<p class=\"muted\">问答额度已用完或模型调用未授权。仍可审查证据并设定下一轮输入。</p>" : "" }</form>` : "" }</section>${ m.decision ? `<section class="panel"><h2>已确认的下一轮</h2><p>${ esc(m.decision.instruction) }</p><p>第 ${ m.decision.to_version } 轮；旧报告、规划与决定仍保留。</p><details><summary>查看确认后的五项输入</summary>${ inputsSummary(m.next_inputs.body) }</details></section>` : `<section class="panel"><h2>审查后，重新设定下一轮</h2><p>带着这个项目的上下文，调整 idea、资源、权限、每日工作时间和额外要求。只有确认后，后台才开始新一轮。</p><button class="primary" id="next-inputs">调整下一轮输入</button></section>` }<details><summary>本场组会对应的输入与规划</summary>${ inputsSummary(m.inputs.body) }<ol>${ m.inputs.plan.steps.map(x => `<li>${ esc(x) }</li>`).join("") }</ol></details>`;
  document.querySelector("#back-project").addEventListener("click", () => showProject(m.project_id));
  document.querySelector("#next-inputs")?.addEventListener("click", () => setup({
    ...p,
    current_inputs: m.inputs
  }, m));
  document.querySelector("#ask")?.addEventListener("submit", e => action(e, async () => {
    if (real)
      announce("正在依据固定快照回答，本次计入真实问答请求。");
    await api(`/api/meetings/${ id }/ask`, { question: new FormData(e.currentTarget).get("question") });
    await showMeeting(id);
    announce("追问已保存；下一轮输入仍需你确认。");
  }));
  await sidebar();
}
document.querySelector("#new-project").addEventListener("click", () => setup().catch(e => announce(e.message, true)));
if (location.protocol === "file:") {
  document.querySelector("#new-project").disabled = true;
  announce("请通过本地服务地址打开，HTML文件预览不能保存项目。", true);
} else
  (async () => {
    try {
      const ps = await sidebar();
      if (ps.length)
        await showProject(ps[0].id);
      else
        await setup();
    } catch (e) {
      announce(`连接本地服务失败：${ e.message }`, true);
    }
  })();
setInterval(async () => {
  if (page !== "project" || !currentProject || document.activeElement?.matches("input,textarea,select") || [...document.querySelectorAll("details[open]")].some(d => d.getClientRects().length))
    return;
  try {
    await showProject(currentProject);
  } catch (e) {
    announce(e.message, true);
  }
}, 4000);
