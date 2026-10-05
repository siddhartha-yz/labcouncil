# InternAgentS 实际试用结果

2026-10-06。**它能用 DeepSeek Flash 做小计算，普通停止重启也保留了状态；连续审批和预算控制没有过关。暂不整套采用。**

本轮固定源码 `4a5f2ab2879ebd4f806155c796e247da94bb1625`，上游工作树始终干净。使用原启动脚本、原协调服务和原执行服务，配置另放本地试验目录。先写 [验收范围](PROTOCOL.md)，再试运行。没有做论文科研实验，也没有真实用户组会。

## 哪些能用，哪些卡住

| 检查 | 结果 | 对 LabCouncil 的含义 |
| --- | --- | --- |
| 原版安装启动 | 最新解析依赖启动失败；固定 DeepAgents 0.5.7 后三个服务启动 | 需要固定兼容依赖，不能直接照 README 装最新版 |
| DeepSeek Flash 接入 | 8 次实际请求均返回 200 | 这个小任务的模型和工具调用路径可用 |
| 审批前正常停止再启动 | 同一 checkpoint、待审批请求都保留 | 普通退出恢复有实现；未证明突然断电或崩溃恢复 |
| 连续工具审批经协调服务转发 | 批准读取后，下一次写文件审批被包装为 RuntimeError | 用户界面背后的审批转发流程不能算通过 |
| 直接连接原执行服务 | 多次审批后实际完成计算和报告 | 执行模块可单独验证，不等于整套工作台通过 |
| 完成后正常停止再启动 | 执行服务会话内容、checkpoint、4 个产物哈希都一致 | 这条正常重启路径通过 |
| 目标 token 预算 | 预算 1 token，仍发出两次请求，已用字段始终为 0 | 预算值没有在本次运行中形成硬停止条件 |
| 网页交互 | HTTP 200；浏览器控制三次超时 | 未完成实际网页点击、审批卡片或刷新验收；超时不归因于框架 |

## 计算真的跑了吗

跑了。模型读到 CSV 后写了 [compute.py](artifacts/compute.py)，提出运行命令 `python3 compute.py`；操作者检查并通过原 runtime API 批准。工具记录返回退出码 0，磁盘上出现了 [result.json](artifacts/result.json)。

我们另从原 CSV 复算，没有执行模型生成的代码。5 个点恰好满足 y=2x+1，所以这个公式的平均平方误差为 0；始终预测数据均值 5，平均平方误差为 8。[独立检查](independent-verification.json)通过。这只说明在明确的合成任务上完成了读数据、执行代码、保存结果，不说明能自主研究真实课题。

原始 [report.md](artifacts/report.md) 保留了小样本、无测试集的限制，但把回归关系称为“线性可分”，术语不准确；去空白后 196 字符，末次答复却声称报告在 145 字以内。可读性和报告自查都未达到我们要求。这也说明只核验数值不够，不能默认报告里每句话都可靠。

## 连续审批为什么失败

第一次待审批包含目录列表和读取 CSV。重启后状态完整，批准后 runtime 实际执行了这两项操作，并产生了第二次审批：写入计算脚本。

在本轮依赖条件下，原协调服务的 `_resume_remote_runtime` 在 `try` 内遇到新的 `interrupt(...)`，其 `except Exception` 把正常的 GraphInterrupt 包装成 RuntimeError。协调线程 run 变成 error，仍保存上一份读取审批；独立 runtime 已停在新的写脚本审批。重启保留状态不等于审批状态能一直正确同步。

失败证据：[协调服务状态](states/proposed-compute.json)、[执行服务状态](states/runtime-after-resume-error.json)、[协调日志](logs/backend.log)、[固定源码](https://github.com/qzzqzzb/OpenClaudeScience/blob/4a5f2ab2879ebd4f806155c796e247da94bb1625/internagents/agent_graph.py#L1239)。没有给上游打补丁，也没有把失败改记成成功。

为了定位故障，后续绕过协调服务，直接用同一线程的原 runtime API 批准写脚本、运行、读取结果、写报告。这是诊断路径，不能拿它替代原工作台验收。

## 预算问题从函数检查变成了实际观察

另建一个合成验收线程，初始 goal 状态为 active，tokenBudget=1、tokensUsed=0，要求模型只回复、不调用工具或修改目标。用上游支持的环境变量将自动续跑限制为两轮。该状态是测试输入，不是人类真实研究目标。

两个实际请求消耗分别为 8769 和 8784 token（输入加输出）。最终状态仍 active、tokensUsed=0、goalContinuationTurns=2；服务因两轮上限结束，没有因 token 预算结束。[最终状态](states/budget-complete.json)与[请求用量](assessment.json)保留。不能将这个显示预算当作可靠的开销上限。

## 环境、花费和边界

- Python 3.12.14；UI 按 package-lock 执行 `npm ci --legacy-peer-deps --ignore-scripts`，安装 673 个包。
- 第一轮原 pyproject 解析出 DeepAgents 0.7.22，因其移除 backend factory 接口而启动失败，0 次模型请求。保留 [原失败](attempt-01-startup.log)和[依赖清单](attempt-01-dependencies.txt)。
- 第二轮仅将 DeepAgents 固定为上游声明的最低版本 0.5.7，其他依赖见 [清单](attempt-02-dependencies.txt)。这不是完整作者环境复现，也不能保证换成其他 SDK 组合会产生相同结果。
- 真实 key 只由本地代理持有，框架得到无效占位值；关闭外部 tracing、搜索、MCP、SCP 和 skills。未使用 SSH 或 GPU。
- 固定模型 `deepseek-flash`，thinking disabled，输出上限 1024；代理最多允许 12 次转发。本次小计算 6 次、预算检查 2 次，共 **8 次、73343 token**，其中输出 926。没有通过账单查询人民币费用。
- 代理请求上限是测试保护，不是上游预算能力。当前调用条件、正常退出恢复、单次小任务的结论不能推广到24小时无人值守运行。
- 公开状态与日志经过密钥模式检查、工作区前缀替换、ANSI/行尾空白清理；[清单](evidence-manifest.json)区分原始文件与公开文件哈希。产物保留原始字节。原始私有记录保存在忽略的 `workspaces/internagents-trial/`。
- 本次控制的浏览器页面没有成功读到可交互状态。只确认前端 HTTP 响应，不宣称界面验收通过。测试结束已停止自己启动的服务及代理。

## 采用决定

InternAgentS 仍值得参考文件工作台、模型接入和审批呈现，但本轮证据不足以把整套系统作为 LabCouncil 的现成后端。若继续候选验证，先处理兼容依赖、连续审批转发和实际 token 计量，再重新跑原协调服务路径以及真实浏览器交互。LabCouncil 的组会确认、任务去重、预算停止与证据验收仍需要明确实现。

运行脚本：[启动与受限代理](../internagents_trial_host.py)、[原服务会话操作](../check_internagents_session.py)。程序化审批是试验操作，未计作真实人工组会反馈。原源码中的版权内容随记录附 [MIT 许可证](UPSTREAM-LICENSE.txt)。
