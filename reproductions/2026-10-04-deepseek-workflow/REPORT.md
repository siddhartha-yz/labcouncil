# DeepSeek Flash 两轮工具工作流记录

日期：2026-10-04（Asia/Shanghai）。这是 LabCouncil 自有脚本的受控功能验证；**不是上游框架或论文的复现，也没有实际人类组会。** 两个模型角色使用同一个 `deepseek-flash`，关闭 thinking，固定工具和合成数据。

## 结果

经过显式记录的策略修订、验收实现修正和一次网络重试，两轮工作流完成：执行实验 → 证据报告 → 工具复核 → 固定评审输入 → 新进程加载状态 → 新实验和报告 → 复核。再次提交完成命令没有新增调用。

原始自主工具选择设置没有通过：Reviewer 在没有调用验证工具时返回 `verified=true`。后续采用强制工具前置的设置；不能把它的通过解释为原始设置通过，更不能据此认为模型自述的“已验证”可信。

协议和历次修订：[PROTOCOL.md](PROTOCOL.md)。源码版本：

| 版本 | commit | 改变 |
| --- | --- | --- |
| 原始 | 49e56dd | 预注册，真实请求之前提交 |
| 修订 2 | 5bbb33d | 强制工具前置，失败请求计入累计预算 |
| 修订 3 | 64b8357 | 允许准确的已登记历史引用，离线复核原始报告 |
| 修订 4 | f0f77cd | 超时后显式重试报告，仍受累计预算限制 |

记录中的脚本 SHA256 对应相应版本，不以当前文件哈希替换历史值。恢复只验证指定阶段边界和已知失败情形，未实现任意位置崩溃恢复。

## 所有尝试与失败

首次启动在读取配置时发现 `.env` 仍为 Pro，协议要求 Flash，因此退出码 2，没有 API 请求或实验产物；更正配置后才运行以下尝试。

| 目录 | 新 API 请求数 | 观察 | 结论 |
| --- | --- | --- | --- |
| [run-01](runs/run-01/state.json) | 3 | Executor 工具和报告通过；Reviewer 跳过工具声称 verified=true | 原始设置失败，拦截有效 |
| [run-02](runs/run-02/state.json) | 6 | 第一轮两角色通过；新进程执行第二轮正确参数；报告准确区分新旧证据，却被仅接受单个 ID 的校验拒绝 | 验收实现误拒，原始响应保留 |
| [run-03](runs/run-03/state.json) | 2 | 离线重新验收第二轮报告；验证工具通过；生成 Reviewer 报告请求 45 秒网络超时 | 网络失败，未知服务端是否已生成 |
| [run-04](runs/run-04/state.json) | 1 | 复用已完成工具的消息重发报告；报告通过 | 修订后的流程完成 |

run-03/04 是前一目录的显式恢复副本，累计计数和 events 包含继承历史；**不能把四份累计状态或相同 events 再次相加**。run-04 的 `failure_message` 字段保留自复制的失败 checkpoint，表示历史失败；最终状态以 `status=completed` 为准，具体历史见事件记录。

原始模型内容、工具参数和响应保存在各目录的 events.jsonl；CSV、实验 JSON、哈希和报告一并保存。认证头、key、账户信息未保存。复制之前检查了所有配置中的 API key 均未出现在公开材料中。

## 评审输入是否改变工具行为

| 项目 | 第一轮 | 第二轮 |
| --- | --- | --- |
| task_version | 1 | 2 |
| seeds | 7 | 7、19、31 |
| 测试标签异常值 | 0% | 10%，幅度 10 |
| 指标 | MSE | MSE、MAE、median absolute error |
| 实验证据 | experiment-0001 | experiment-0002，新文件 |

以上均为实际模型工具参数及本地执行结果，不是仅修改计划文字。额外比较 seed=7 的两份 CSV，确认训练行与测试 x 保持相同，恰有 10/100 个测试标签改变，幅度均为 10；见 [integrity-summary.json](integrity-summary.json)。

两轮报告中的全部 seed/metric 数字与原始结果一致，验证工具另用原始矩公式拟合并从 CSV 重算指标、检查哈希。第一轮 seed=7 测试 MSE：线性回归 0.1704689586，均值基线 12.8883584996。第二轮 seed=7 MSE：线性回归 10.1556704190，均值基线 23.9518945987；其他 seed 和指标见 [第二轮报告](runs/run-04/round-2-executor.json) 和 CSV。

工具参数被严格限制为预注册设置，首个工具调用被程序强制。因此，这不是自由设计实验的能力检查。

## 检查、用量与解释边界

- 9 项离线完整性与停止检查通过：重算、CSV 篡改、指标篡改、编造数值、旧任务版本、合法历史/非法引用、预算耗尽、已完成任务不重复派发、累计尝试预算。
- 真实执行完成后，再次运行 continue：`already_completed`，新增 API 0 / 工具 0。
- 客户端请求尝试总数 12；11 次取得成功响应，1 次网络超时。收到响应的 usage 合计输入 9,940、输出 2,070、总计 12,010 token；见 [usage-summary.json](usage-summary.json)。超时请求不能视为零费用，未查询余额或确认结算费用。
- 两个模型角色不能提供独立科学判断。确定性工具给出本例的数值验收，模型的文字结论仍需人工检查。

人工阅读还发现两项限制：Executor 第二轮对不同指标“差距大小”的表述混合了 MSE 与绝对误差的尺度，不宜直接跨指标比较；第二轮 Reviewer 没有看到第一轮 Reviewer 历史，只能对本轮验证材料发言，不能替平台断言第一轮从未验证。这些语义问题没有被数值验收自动发现，原文保持不变。

不能从三组 seed、合成数据、固定工具和注入的测试意见推出科研质量提升或多 agent 优势。文献检索、自由编程、GPU、定时组会和真实交互尚未验证。

## 复跑

从仓库根目录运行，配置本地 `.env`，使用新的输出目录；每次运行可能产生 API 费用。

```bash
python3 -m unittest discover -s reproductions -p 'test_deepseek_workflow.py' -v
python3 reproductions/check_deepseek_workflow.py first --output-dir logs/my-workflow
python3 reproductions/check_deepseek_workflow.py continue --output-dir logs/my-workflow
python3 reproductions/check_deepseek_workflow.py continue --output-dir logs/my-workflow
```

正常复跑采用当前修订后的策略，不能视为重跑原始自主工具选择条件。原始条件需 checkout `49e56dd`。复现本次异常路径时，可参考协议和源代码中的 `reassess` / `retry-report`；仅支持记录中指定的失败情形，不能自动处理其他错误。

## 后续采用决定

尚未采用任何上游框架。这一轮支持把固定工具、产物哈希、数值核验、版本化评审输入和有限恢复继续作为原型组件研究；不支持采信模型自行声明的验证状态。下一步需要运行固定版本的上游最小示例，再建立真正由用户评审、确认决定的界面；科研效果另做多任务对照。
