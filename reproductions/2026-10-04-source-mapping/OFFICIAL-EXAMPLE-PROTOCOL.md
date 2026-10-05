# Virtual Lab 1.1.0 官方 notebook 最小阶段

预注册：2026-10-05。固定 2a3654b67729972b7e2a8145adad4ec06f0164af，pyproject / __about__ 显示1.1.0。该 commit 是论文发表前最后公开的时间候选，并非已经与 Zenodo 存档逐字比较后的唯一论文 commit。

直接执行上游 nanobody_design/run_nanobody_design.ipynb 的代码 cells 0、2、3、4，即官方团队成员选择、五次并行讨论与一次合并。不重写议程或减少 num_iterations；不继续生物设计/代码生成/计算/湿实验阶段。唯一模型改变是原 PI 的 gpt-4o-2024-08-06 改为 deepseek-flash；保存目录由 cwd 指向本次新目录。保留原温度0.8/0.2；每请求1024输出上限、45秒超时、0重试，总上限6次。连接适配仅记录真实 SDK 请求和回复，保持线程调用和原 meeting 代码。

验收：五份原 discussion JSON/Markdown 与 merge 文件存在、读入五条原摘要；每个回应非空，merge 摘要不捏造已实施实验；source hashes前后不变；原 cells 的hash与执行输入保存。失败不重试到成功；输出截断计失败。此例只选择角色，不验证之后的完整 nanobody 工作流或科学结果。

## 初次未调用 API 的连接适配失败与复查

原 1.1.0 使用 client.beta.assistants / threads / runs，而先前被测1.2.0使用 chat.completions。首次连接适配仅提供 chat，五个线程的 AttributeError 被原 concurrent.futures.wait 忽略，合并阶段再次抛 AttributeError，共零次 provider 请求；这次不能算作 DeepSeek 或上游模型失败。

追加诊断在原 SDK client 上保留真实 beta 接口，记录实际 assistants.create HTTP；不模拟服务端 threads/runs，不把 Chat Completions 改写成假 Assistants。执行同样 cells，捕获 wait 返回的 futures 异常供审计。最多六次 API（五次并发 create 与一次合并阶段 create），不自动重试。若 DeepSeek 接口返回404，记录为当前供应商与原服务路径不兼容，不判定原 OpenAI 模型论文错误。任何创建成功则在请求层停止后续未预算的 threads/runs，不将意外兼容计作通过。
