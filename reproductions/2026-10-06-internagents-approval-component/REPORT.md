# 连续审批：简单补丁不够，持久化调用结果的候选方案局部通过

2026-10-06。承接[实际服务失败](../2026-10-06-internagents-runtime/REPORT.md)。上游仍固定 `4a5f2ab2879ebd4f806155c796e247da94bb1625`，工作树未修改。**这次是局部故障诊断，不是完整工作台修复验收。**

一句话解释：第一次批准已经让执行端前进了；第二次批准时，协调端却可能从头再发第一次批准。只把错误捕获改掉，会使程序看起来跑完，却丢失你的第二次决定。

## 怎么检查的

从固定源文件用 AST 提取原 `_resume_remote_runtime`、原审批值解析和原配置清理函数，放入真实 LangGraph 1.2.13 StateGraph 与 MemorySaver。错误文案和 goal accounting 两个辅助函数用明确标注的 fixture；它们不在本次范围内。

分别使用无状态返回值 fixture、有状态严格 fixture，以及**另一个带独立检查点的实际本地 LangGraph 图**模拟执行端。后者先等待读取审批，再等待写入审批，记录收到的两个值。它不是原 RemoteGraph HTTP 服务，不调用 DeepAgents、真实工具、模型或网络；没有加载 `.env`，关闭 tracing。

这是逐步诊断，测试范围在每步发现问题后扩展，不声称全部提前预注册。可复跑：

```bash
timeout -k 3s 20s workspaces/upstreams/internagents/.venv/bin/python \
  reproductions/check_internagents_approval_component.py \
  --output-dir logs/approval-component-new
```

依赖之前隔离安装的原试验环境。使用新输出目录；脚本拒绝覆盖。记录包含源码字节 SHA256、依赖版本、实际图输出、远端调用顺序和检查点最终值。原辅助函数外的替代明确写在脚本里，不称为原服务运行。

## 两个候选方案的差别

| 代码 | 观察 | 判断 |
| --- | --- | --- |
| 原函数 | 第二次等待审批的 GraphInterrupt 被包装成 RuntimeError | 重现原服务失败的局部机制 |
| 把 interrupt 移出 try/except | 无状态 fixture 看似完成；有状态 fixture 收到重复第一次批准而失败 | 不能采用；无状态测试不足以代表会前进的执行端 |
| 同一简单补丁 + 独立检查点图 | 收到 `approve-first, approve-first`；操作者第二次给的 `approve-second` 或 `deny-second` 被丢失 | 看起来完成不代表正确传递决定 |
| 用公开 `langgraph.func.task` 保存每次远端调用结果，同时将 interrupt 放在捕获之外 | 收到 `approve-first, approve-second`，每次只调用一次；否决检查收到 `approve-first, deny-second` | 本局部暂停/恢复路径通过，值得进一步整套服务复验 |

否决 fixture 只检查字符串是否正确转发，不运行真实工具，也没有验证上游工具拒绝执行的语义。候选仍保留真实远端 OSError 的失败处理，不吞掉普通运行错误。

LangGraph [官方中断说明](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/interrupts.mdx)指出：恢复会从节点开头重新执行，宽泛捕获会拦截中断。公开 [task API](https://reference.langchain.com/python/langgraph/func/)提供任务结果持久化接口。本次方案没有修改 SDK、没有 monkey patch，也没有绕过真实服务失败去改其状态。

## 过程与原始输出

- `attempt-01`：6项诊断检查；还没有有状态执行端，不能用这个通过结论证明补丁正确。
- `attempt-02`：加入有状态 fixture，记录重发问题。
- `attempt-03`：加入独立实际检查点图，确认第二次值丢失。受限执行环境初次运行无响应，操作者终止，退出143；随后同代码在允许本地线程通信的环境0.46秒完成。具体限制未定位，单独记录，不归咎上游。
- `attempt-04`：加入任务缓存候选，12项诊断检查通过。
- `attempt-05`：加入第二次否决输入，14项诊断检查通过；其中多项是在确认原版/简单补丁的负结果，并非宣布那些版本可用。

补丁存档：[简单候选](attempt-05/candidate.patch)、[任务缓存候选](attempt-05/durable-candidate.patch)。它们只公开为诊断候选，没有应用到原上游，没有接入 LabCouncil。原失败保持失败。

## 尚未验证与下一步

MemorySaver 只保留本进程内检查点，不能证明进程重启恢复。完整协调/执行 HTTP 服务、原 UI、真实模型与工具、取消语义、并发、预算计量都未在这里复验。远端已经执行、协调端尚未保存结果时发生崩溃，仍有重复风险；需要稳定操作 ID 和执行端查询/去重，不能从任务缓存推断外部副作用严格只执行一次。

下一步在独立上游副本应用候选，经过原服务路径验证连续批准与否决，检查操作 ID、真实用量和崩溃窗口后，再决定采用。原有环境、预算与报告问题也继续保留在 [WORKLIST](../../docs/WORKLIST.md)。
