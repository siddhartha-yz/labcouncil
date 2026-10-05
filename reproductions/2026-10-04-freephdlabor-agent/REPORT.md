# freephdlabor 实际基础 agent 验证

记录整理：2026-10-05（Asia/Shanghai）；协议与实验开始于 2026-10-04。[预注册与追加条件](PROTOCOL.md)。固定上游 [9102d18](https://github.com/ltjed/freephdlabor/tree/9102d18a161037294d3d963b2799351aa724c58b)，smolagents 1.20.0，Python 3.12.14，真实 DeepSeek Flash。

**采用决定：暂不直接作为 LabCouncil 的持续运行后端。** TCP 干预影响下一轮工具行为的有限检查通过；保存/恢复存在类型和状态缺失，断开输入会阻塞，同任务重发不会阻止重复计算。没有复现完整 ManagerAgent 或论文科研结果。

## 实际路径和改变条件

使用原 BaseResearchAgent、WorkspacePythonExecutor、setup_user_input_socket、make_user_input_step_callback、save_memory 和 resume_memory。namespace package 仅避开无关专用 agent 的 eager imports，不替换这些实现；全部上游 Python 哈希运行前后一致。模型由真实 OpenAIServerModel 连接官方 DeepSeek 接口。未运行官方完整 launcher；Python、模型、SDK 均与原环境条件有差异，规划关闭，主要行为检查关闭自动压缩，备份试验另使用原 ContextMonitoringCallback。

工具是固定数据上的实际 MSE 计算，限定 linear / baseline 两个输入，无任意路径、shell 或外部检索。TCP 输入是明确的测试夹具，不是人工组会。每项行为仅一次，不重试到成功。

## 结果与判定

| 检查 | 观察 | 判定边界 |
| --- | --- | --- |
| 无输入 | 第二次工具仍为 linear，MSE 0 | 有限行为通过 |
| 修改当前任务 | 原 TCP callback 追加 UserInstructionStep，第二次工具改为 baseline，MSE 8 | 有限行为通过 |
| 新任务 | callback 追加 TaskStep，第二次工具改为 baseline | 有限行为通过；agent.task 仍为旧任务，不能称完整任务切换 |
| 取消输入 | 第二次工具仍为 linear | 有限行为通过 |
| TCP 输入中途断开 | 两行已到达队列、socket 已断开；callback 开始后 8 秒子进程超时 | 阻塞被观察到；没有自动取消或断开恢复 |
| 正常保存、独立进程恢复 | 步骤数量保留；修改类型变成 TaskStep；agent.task=None；checkpoint_value=37 丢失 | 不是完整状态恢复 |
| 恢复后完整序列化 | get_full_steps 报 AttributeError：dict 没有 .dict；源码 Timing 等留作 dict | 未通过；不能正常再次导出完整记忆 |
| 恢复后消息构造与续跑 | write_memory_to_messages 可用；两次续跑均各三次真实请求完成 | 不能把序列化失败误说成完全不能调用模型 |
| 保存后异常退出 | callback 中 save 后 exit 73；恢复主记忆只有原 TaskStep，当前 ActionStep 缺失 | 动作边界检查点不完整；不是保存中断 / SIGKILL 测试 |
| 原增量备份 | crash callback 前原监控保存了一条真实 ActionStep；resume_memory 仍只加载 TaskStep | 备份存在，但本入口未自动使用它恢复动作 |
| 重发原任务 reset=False | 正常完成后的两项计算再次执行；异常退出后已执行 linear 也再次执行 | 本入口无相同任务/实验去重；提示明确重发原任务，不能据此估计任意恢复提示的重复概率 |

初次完整序列化与消息检查共用一个 try，遇到前者异常就未检查后者。[run-02](run-02/) 分开复查纠正了这个验收实现问题，没有更改原 failed 证据。恢复后的 Timing 为 dict 是首次 .dict 错误来源；ToolCall、TokenUsage 等也未完整恢复为原类型。暂未触发模型上下文压缩或检查 PlanningStep 的跨进程恢复，规划在本协议中关闭。

`save_memory` 源码以 w 打开文件且捕获异常，未提供原子提交；本次未在写入中途杀进程，因此截断文件恢复仍未验证。原自动备份的 load_full_conversation 返回数据，不等于 launcher 自动恢复整个执行环境。

## 原始证据和调用计数

[run-01](run-01/)：四项正常运行各三次、保存后退出一次，共 13 次真实响应；随后每项在新进程离线恢复。目录保存原请求、响应、MSE、序列化状态、stdout/stderr、原记忆文件和当时 runner.py。

[run-02](run-02/)：先复制初次目录，不覆盖原件；正常任务与 crash 续跑各三次，增量备份 crash 一次，另有零模型请求的复查和真实 TCP 断开测试。共新增 7 次。复制的原 API 事件不重复计费统计。

[usage-summary.json](usage-summary.json)：20 次请求、20 次收到响应；输入 45,592、输出 1,194、合计 46,786 token。原 LoggingLiteLLMModel 用 prompt_tokens 等属性读取 smolagents TokenUsage，日志显示 0；真实 provider usage 已另保存，不能用上游零值声称免费。金额未核对账户账单。

工具文件写入使用宿主 Python，模型代码用原 smolagents 限制解释器；没有以 fake model 或手动追加正确结果证明 agent 听从指令。

复跑（先克隆并 checkout 上述完整 commit，安装 run-01/provenance.json 的实际依赖，选择不存在的输出目录，填写被忽略的 .env）：

```bash
python reproductions/check_freephdlabor_agent.py --upstream /path/to/pinned/freephdlabor --output /path/to/new/run-01
python reproductions/check_freephdlabor_recovery.py --upstream /path/to/pinned/freephdlabor --initial /path/to/new/run-01 --output /path/to/new/run-02
```

固定小样本只支持这些被测条件。后续可以借鉴步骤边界干预、共享工作区和增量日志；若集成，需要独立实现带类型的检查点、原子保存、任务版本与幂等工具 ID、断开/超时处理。没有证据支持目前直接承诺长期无人值守、精确恢复或科研效果提升。

## 原核心与完整 pip 环境复查

[历史版本报告](../2026-10-04-source-mapping/REPORT.md) 补充最初源码、Python3.11.10和448项作者pip清单的安装/零请求复查；恢复变量缺失与完整序列化错误仍出现。新增真实 PlanningStep 测试保留计划原文但未恢复执行变量；2次Flash请求、1525 token，与本目录20次统计分开。原 launcher 帮助入口已启动，但指定 deepseek-flash 在原参数列表被拒绝。源码未为迎合这些结果而修改。
