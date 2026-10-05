# 上海 AI Lab 的平台对 LabCouncil 有什么用

检查日期：2026-10-05。

**有用，值得加入候选。先试 InternAgentS 工作台，再考虑接入 InternAgent 的实验循环。现有证据还不足以直接替换 LabCouncil。**

你记得的应当是「书生·端砚 / Intern-Discovery」。它把科研助手、模型、数据、工具和计算资源放到一个平台里。下面几个名字有关联，但对应的产品与源码不能混为一谈。

## 四个东西分别干什么

| 名字 | 对我们有什么用 | 本轮确认到哪里 |
| --- | --- | --- |
| [书生·端砚 / Intern-Discovery](https://discovery-home.intern-ai.org.cn/tabs/home/index.html?embedded=1&v=20260827-home143) | 可体验已有科研产品，参考报告、文件和证据入口的呈现方式 | 检查公开产品页；未登录、未执行任务，也未确认整个平台可自部署 |
| [InternAgent 1.5](https://github.com/InternScience/InternAgent) | 可以作为“查资料、想方案、跑实验、记结果”的执行模块候选 | 下载固定版本、检查源码和配置、运行一个原恢复函数边界检查；未跑完整科研流程 |
| [InternAgentS](https://internagents.github.io/)，其项目页链接到 [OpenClaudeScience](https://github.com/qzzqzzb/OpenClaudeScience) | 最贴近个人研究工作台：聊天、项目文件、产物预览、工具审批、SSH 计算任务 | 下载固定版本、检查模型配置和续跑实现、运行一个原续跑函数边界检查；未启动 UI |
| [SCP](https://github.com/InternScience/scp) | 接入领域数据库、计算工具和实验设施，减少逐个写适配器的工作 | 检查公开仓库说明、手册、包配置与论文；未验证 Hub 或具体工具可用性 |

另有组织下的 [InternScience/InternAgents](https://github.com/InternScience/InternAgents)，本次浏览的默认 `guidedtour` 分支主要提供用户手册网站。没有据此确认它和上述 OpenClaudeScience 源码的版本对应关系。

## 对个人云组会最有价值的是哪部分

InternAgentS 已有我们迟早需要的界面：项目、对话、文件和运行状态在一起，工具操作可审批，远程计算有独立任务记录。源码有 DeepSeek 配置别名，也允许指定 OpenAI-compatible 接口和模型名。对我们的 Flash 是**可配置接入候选**，不是已经证明完整兼容：本轮没有实际模型请求。后续应显式使用我们已验证的模型 ID，避免沿用上游旧示例。

InternAgent 1.5 的价值在实验过程。它有循环轮数、候选方案、实验后记录与历史检索，也有 `--resume`。主模型适配器允许自定义 base URL 和模型名，但实验执行是另一层：默认调用 Claude Code，其他选项包括 OpenHands、iFlow。只配置 DeepSeek key，不等于所有环节都会改用 DeepSeek。

因此，值得评估的组合是：**用工作台展示文件和审批，用科研执行模块做有限实验，由 LabCouncil 保存组会决定、控制下一轮任务与验收结果。** 这是设计判断，还没有做集成。

本轮检查的入口没有确认到完整的“固定时间汇报 → 多角色现场问答 → 用户确认决定 → 后台按决定继续”的组会功能。工具审批只是其中一部分。不能把有审批界面就当作有组会系统。

## 两个实际运行的小检查

先写 [检查范围](PROTOCOL.md)，再运行 [脚本](../check_shanghai_boundaries.py)。记录在 [boundary-results.json](boundary-results.json)。从固定源码 AST 提取原函数体，未改上游代码、未导入完整框架、未安装依赖、未读取密钥、未调用模型。

1. **部分完成不一定能正确恢复。** InternAgent 在缺少总报告时扫描目录。我们构造一轮两个候选，其中只有一个候选的 `run_0` 有 `final_info.json`，原函数仍报告已完成 1 轮；所有结果文件都没有时报告 0 轮。说明这个恢复判断粒度不足以证明这一轮的全部实验完成，需要完整故障测试确认会不会漏跑或重复跑。
2. **预算展示不等于预算自动停止。** InternAgentS 的原续跑判断函数只看目标状态和自动续跑次数。在 active、次数未到上限、已用 token 等于预算的输入下仍返回继续；complete 或次数到上限时返回停止。它有自动目标续跑代码，但这个函数没有预算停止条件。不能由此断言所有部署都会超支，也不能把它当作我们需要的硬预算控制。

这些是**局部函数行为**，不是工作台稳定性测试，更不是论文科研结果复现。没有验证浏览器关闭、后台进程重启、审批后重连、真实模型计费、GPU、SSH 或 SCP 服务。

## 论文有结果，但不能照搬成绩

[InternAgent 1.5 技术报告](https://arxiv.org/abs/2602.08990) 于 2026-02-09 提交；[SCP 论文](https://arxiv.org/abs/2512.24189) 于 2025-12-30 提交。本轮查到的是 arXiv 技术报告/预印本，没有确认同行评审录用记录或独立复现。

InternAgent 论文提供推理基准、算法任务和跨学科实验结果，并有记忆模块比较。值得研究；但其中较高的推理成绩使用 Gemini-3-pro 与 o4-mini 等模型，不能换成 DeepSeek Flash 后沿用分数。科研案例的设备、数据和专家参与条件也不能默认在个人笔记本上重现。官方机构身份证明来源，不保证每项结论可靠。

## 本地条件与下一步

工作台和调用云端模型本身不需要在 5070 Ti 上加载论文里的大模型。源码启动路径要求 Python 3.11+、Node/npm 和三个本地服务；现有 Linux 笔记本值得做最小启动试验。具体实验是否够用，要按数据和模型判断，本轮没有 GPU 验证。端砚公开产品页目前标注 Linux 客户端尚待推出；这和 InternAgentS 源码启动是两件事。

下一轮最小验收建议：只给 InternAgentS 一个小项目和 DeepSeek Flash，生成一份能复算的结果；要求工具审批，刷新浏览器并重启服务，确认待审批任务和产物仍在；人为耗尽小预算，确认真正停下来。报告第一页只写“做了什么、发现什么、哪里不确定、下一步要你决定什么”。通过以后，再尝试把 InternAgent 的 AutoDebug 小任务封装成一个受预算约束的任务。SCP 等实际需要领域工具时再接。

## 固定版本与源码入口

- InternAgent：`fa8c3eedfa9751d3752ea6eb49220b303ac2397d`，提交日期 2026-07-29。根许可证 Apache-2.0。
- InternAgentS：`4a5f2ab2879ebd4f806155c796e247da94bb1625`，提交日期 2026-07-06。根许可证 MIT；不据此推断所有附带 skills 和依赖都同许可证。
- [InternAgent 恢复实现](https://github.com/InternScience/InternAgent/blob/fa8c3eedfa9751d3752ea6eb49220b303ac2397d/launch_discovery.py#L439)、[默认配置](https://github.com/InternScience/InternAgent/blob/fa8c3eedfa9751d3752ea6eb49220b303ac2397d/config/default_config.yaml)、[模型适配](https://github.com/InternScience/InternAgent/blob/fa8c3eedfa9751d3752ea6eb49220b303ac2397d/internagent/mas/models/openai_model.py)、[实验后端说明](https://github.com/InternScience/InternAgent/blob/fa8c3eedfa9751d3752ea6eb49220b303ac2397d/docs/openrouter.md)。
- [InternAgentS 模型配置与续跑](https://github.com/qzzqzzb/OpenClaudeScience/blob/4a5f2ab2879ebd4f806155c796e247da94bb1625/internagents/agent_graph.py#L1299)、[前端断开时继续选项](https://github.com/qzzqzzb/OpenClaudeScience/blob/4a5f2ab2879ebd4f806155c796e247da94bb1625/ui/src/app/hooks/useChat.ts#L1564)、[项目包依赖](https://github.com/qzzqzzb/OpenClaudeScience/blob/4a5f2ab2879ebd4f806155c796e247da94bb1625/pyproject.toml)。前端选项不代表我们已测试过后台恢复。
- [上海 AI Lab 2026-02-11 官方发布](https://www.shlab.org.cn/news/5444231) 将 InternAgent 1.5 解释为 Intern-Discovery 的核心技术之一。端砚产品页、SCP 和手册仓库为本次网页快照检查，未固定为源码实验版本。

源码克隆位于被忽略的 `workspaces/upstreams/`；[source-manifest.json](source-manifest.json) 保存本轮主要核查文件的哈希与固定版本链接。下载初期发生 DNS/TLS 错误，重试后两个源码仓库均成功取得，检查时工作树干净。
