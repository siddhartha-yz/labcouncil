# 研究与开源参考

整理日期：2026-10-04。资料经过网页、论文及部分源码检查；已做有限 callback 检查、真实自有工具工作流和改变模型条件的上游会议函数验证，尚未独立复现论文科研结果。下文区分作者报告的结果和 LabCouncil 的设计判断。模型、依赖和运行条件应在集成前重新核对。

## Virtual Lab：组会机制

- 仓库：[zou-group/virtual-lab](https://github.com/zou-group/virtual-lab)
- 论文：[The Virtual Lab of AI agents designs new SARS-CoV-2 nanobodies, Nature 2025](https://doi.org/10.1038/s41586-025-09442-9)

人类设置议程，PI agent、科学专家和批评角色开展团队会议及一对一讨论。作者报告将 ESM、AlphaFold-Multimer 和 Rosetta 组合为计算流程，设计 92 个纳米抗体候选并进行了实验验证；这不表示 92 个候选全部获得成功结果。

借鉴：议程驱动讨论、角色分工、会议总结。局限：特定任务的科学结果不能直接证明跨学科、长期无人监督工作的可靠性。

## freephdlabor：持续研究与人工干预

- 仓库：[ltjed/freephdlabor](https://github.com/ltjed/freephdlabor)
- 论文：[Build Your Personalized Research Group: A Multiagent Framework for Continual and Interactive Science Automation](https://arxiv.org/abs/2510.15624)
- 已检查源码：[launch_multiagent.py](https://github.com/ltjed/freephdlabor/blob/main/launch_multiagent.py)、[callback_tools.py](https://github.com/ltjed/freephdlabor/blob/main/freephdlabor/interaction/callback_tools.py)

ManagerAgent 调度专业角色，使用共享工作区、上下文压缩和持久化状态。已检查的 callback 实现在步骤边界读取终端干预，把修改或新任务写入记忆后继续。启动脚本支持重用已有工作区。

借鉴：证据文件引用、持续任务、工作恢复和人工指令注入。局限：论文主要提供架构及实现；“24/7”是设计定位，不能替代长期运行的效果和故障恢复验证。终端交互需要进一步包装成会议流程。

## Agent Laboratory：人工反馈的实证参考

- 仓库：[SamuelSchmidgall/AgentLaboratory](https://github.com/SamuelSchmidgall/AgentLaboratory)
- 论文：[Agent Laboratory: Using LLM Agents as Research Assistants](https://arxiv.org/abs/2501.04227)
- 结果章节：[论文 v1 第 4 节](https://arxiv.org/html/2501.04227v1#S4)

流程包含文献、实验和报告，支持阶段性的 co-pilot 反馈。论文 v1 报告：外部评审的总体评分由自动模式的 3.8/10 提高到有人参与的 4.38/10，但贡献性改善很小。自动评审总体评分约 6.1/10，高于人类评审的约 3.8/10。

借鉴：比较人工反馈的实际价值，使用人工与可复现结果评价系统。局限：早期模型、小规模评估与主观评分，不能直接预测本平台在新领域的表现。

## Google Co-Scientist：假设的生成、审查和演化

- 论文：[Accelerating scientific discovery with Co-Scientist, Nature 2026](https://www.nature.com/articles/s41586-026-10644-y)
- 预印本：[arXiv:2502.18864](https://arxiv.org/abs/2502.18864)
- 后续工作：[Accelerating Scientific Research with Gemini in the Real-World, 2026-08 预印本](https://arxiv.org/abs/2608.26701)

多 agent 生成、反思、排名、演化研究假设，并接收科学家的自然语言指导。Nature 论文报告了生物医学场景中的验证，包括药物候选的体外实验。其 Code availability 明确说明完整源码未公开；第三方同名复现不等于官方实现。

借鉴：保存候选假设、反对意见与筛选理由。局限：大型系统的计算条件与个人平台不同；自动排名不能代替实证检验。

## AI Scientist-v2：实验搜索与自动执行

- 仓库：[SakanaAI/AI-Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2)
- 论文：[The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via Agentic Tree Search](https://arxiv.org/abs/2504.08066)

使用实验管理和树搜索迭代代码、实验、结果分析和论文。作者报告提交到 ICLR workshop 的三篇自动稿件中，一篇达到录用标准。这里的 workshop 结果不代表主会录用，也不能作为稳定成功率估计。

借鉴：实验分支、失败保留、代码与结果关联。局限：以自动产出论文为中心的流程，需要调整成由人工会议决定方向的研究过程。

## autoresearch：小而明确的实验循环

- 仓库：[karpathy/autoresearch](https://github.com/karpathy/autoresearch)

agent 修改训练代码，按固定五分钟训练预算执行，用验证指标决定保留或回退，再开始下一轮。人类通过 program.md 指导工作。

借鉴：有限改动范围、固定计算预算、可检查指标与回退。局限：特定单 GPU 训练设置下的工程示例，不能直接泛化为完整虚拟研究组。

## 独立评估：自动报告可能掩盖实验问题

- 论文：[Evaluating Sakana's AI Scientist: Bold Claims, Mixed Results, and a Promising Future?](https://arxiv.org/abs/2502.14297)

该研究评估早期 AI Scientist，报告 42% 的实验因代码错误失败，还发现新颖性误判、支撑不足和虚构数值。结果适用于其被测版本与实验设置，不能直接归因于 v2 或后来模型。

借鉴：结论与原始证据关联、独立复现、保留失败分母，不以报告篇数或 agent 自评分衡量研究成功。

## 本项目的候选验证顺序

新增上海 AI Lab 候选：[书生·端砚 / Intern-Discovery](https://discovery-home.intern-ai.org.cn/tabs/home/index.html?embedded=1&v=20260827-home143)、[InternAgent 1.5 源码](https://github.com/InternScience/InternAgent) 与[技术报告](https://arxiv.org/abs/2602.08990)、[InternAgentS 工作台源码](https://github.com/qzzqzzb/OpenClaudeScience)、[SCP 源码](https://github.com/InternScience/scp) 与[论文](https://arxiv.org/abs/2512.24189)。[2026-10-05 检查记录](../reproductions/2026-10-05-shanghai-lab/REPORT.md) 区分云端产品、工作台、执行框架与工具协议，并保留两项零 API 的原函数边界检查。InternAgentS 优先做最小启动和审批恢复验收；其余按实际任务需要评估。本轮不是论文结果复现。

1. 固定 Virtual Lab 版本，运行最小真实会议，检查讨论与产物。
2. 固定 freephdlabor 版本，验证干预、记忆保存、重启恢复与失败处理。
3. 在明确指标的任务上验证 autoresearch 式实验循环，并保留基线和全部失败。
4. 复杂实验再评估 AI Scientist-v2 的搜索机制，核对原论文条件。
5. 使用人工参与的比较实验，验证 LabCouncil 是否真正有用。

以上是候选验证顺序，尚未承诺采用任何仓库。遵循 [复现与采用规则](REPRODUCTION.md)，通过相应验证后再作集成决定。

## 当前证据状态

| 对象 | 已有材料 | 本项目尚未完成的验证 | 当前采用决定 |
| --- | --- | --- | --- |
| Virtual Lab | 出版方资料、官方仓库和固定 commit；[两场真实会议函数验证与格式失败](../reproductions/2026-10-04-virtual-lab-meeting/REPORT.md) | 论文版本对应、原论文模型条件、计算与湿实验结果复现、完整后端需求 | 暂不直接作为平台后端；会议机制可作参考 |
| freephdlabor | 预印本、官方仓库、固定 commit、源码检查、有限的 callback 行为检查 | 完整环境、真实模型行为、异常恢复、长期运行和科研效果 | 未决定 |
| Agent Laboratory | 论文结果章节与官方仓库说明 | 本地运行、反馈效果与评分结果复现 | 未决定 |
| Google Co-Scientist | 出版方论文与闭源说明；后续预印本 | 官方系统的独立运行与结果复现 | 不作为可直接集成的开源后端 |
| AI Scientist-v2 | 预印本与官方仓库说明 | 实验代码运行、论文结果与外部评审结果复现 | 未决定 |
| autoresearch | 官方仓库说明 | 原版训练环境、实验循环和性能验证 | 未决定 |

出版信息提供来源线索，不是科研结论的保证。这里没有确认全部论文的勘误／撤稿状态，没有把 arXiv 收录作为同行评审证明，也没有确认所有统计比较的因果有效性。首次本地记录见 [REPORT.md](../reproductions/2026-10-04-initial-audit/REPORT.md)。

## 2026-10-05 补充本地证据

[历史版本审计](../reproductions/2026-10-04-source-mapping/REPORT.md)、[真实 TCP / 恢复检查](../reproductions/2026-10-04-freephdlabor-agent/REPORT.md) 与[12次等预算流程比较](../reproductions/2026-10-05-comparison/REPORT.md) 均保留原始输入、失败和限制。Virtual Lab 旧版 Assistants 接口与新版有实质差异；freephdlabor 原公开恢复实现未完整还原执行状态。多角色完成更多指标，但未核验新增证据；这些发现改变采用判断，不证明普遍优越或普遍失败。

## 2026-10-06 InternAgentS 实际试用

[固定源码试用记录](../reproductions/2026-10-06-internagents-runtime/REPORT.md)：原最新依赖启动失败，固定 DeepAgents 0.5.7 后服务启动；8 次 DeepSeek Flash 请求确认小计算及普通退出恢复，同时发现连续审批转发异常和预算未计量/停止。直接 runtime 路径完成不算整套工作台通过；真实浏览器交互与论文结果仍未验证。暂不直接采用。
