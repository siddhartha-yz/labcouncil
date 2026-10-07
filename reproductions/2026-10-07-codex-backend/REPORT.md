# Codex CLI 后台接入验收

2026-10-07。结论：现有 LabCouncil 的逐步研究和组会循环已经实际通过 Codex CLI 调用 `gpt-6.1-sol / high` 跑通。没有另建框架，也没有把原项目数据改成新模型。此次是合成小任务工程验收，不能代表真实论文复现、科研能力提升或优于 Flash。

## 实际运行

本机 CLI `0.159.0`，`codex login status` 为 ChatGPT 登录。每次通过参数固定 `--model gpt-6.1-sol` 和 `--config 'model_reasoning_effort="high"'`，没有降级逻辑或全局配置修改；登录信息没有放进仓库或提示。CLI JSONL 事件未返回可独立核验的服务端模型标识，本文的型号证据是明确启动参数，不能冒充服务端模型证明。

成功项目 ID：`4ca753ec3cc242a3b38030d0b84a4c64`。完整输入、规划、工具结果、报告、请求和用量见 [result.json](result.json)。

| 项目 | 实际结果 |
| --- | --- |
| 初始输入 | idea、CPU资源与调用额度、权限、全天每日时段、报告要求 |
| 第一轮 | Codex 选择 clean 合成计算，再整理组会，共2步/4次CLI |
| 组会追问 | 1次实际Codex答复，引用第一轮固定证据 |
| 第二轮 | 验收脚本确认新方向；Codex选择outlier计算，再整理组会，2步/4次CLI |
| 跨轮上下文 | 第二轮引用第一轮 operation，没有重复执行clean |
| 任务与报告 | 4项任务完成、4份报告、4份独立工具记录 |
| 模型后端 | 9次CLI启动；后台8次、组会1次；约141.52秒 |
| CLI用量 | 9次均返回usage；input+output合计101572 tokens，包含缓存输入；不是收费或账户限额的等价换算 |
| 公开HTTP | 0次；这次未检索论文/仓库 |
| 重启 | 正常服务重启后，任务、输入、决定、报告、快照和9次调用记录不变 |

“开组会”和下一轮确认由验收脚本执行，不是用户阅读后的科研评审，不能计为人工耗时。CLI一次启动可含内部模型turn，9次启动不等于9次API请求。

## 有限实验结果与人工检查

第一轮只有seed=7、40个训练点和100个测试点。直线模型MAE约0.313，均值基线约3.091；MSE约0.170和12.888。

第二轮是一个受控工具操作，内部计算seed=7/19/31三次重复，10%测试标签加入异常；训练数据未污染。MAE范围分别约1.247—1.283和3.572—3.867。第二轮报告说明无异常对照只测seed=7，没有三种子配对比较，也没有真实数据或论文复现。

验收后重新从保存的数据独立复算指标，并核对4份artifact与4份operation的SHA256，全部一致，见 [verification.json](verification.json)。报告引用通过只意味着能定位保存证据，不保证每句话正确。第二轮逐步简报的“误差升至”包含不同种子的范围；最终报告保留了未做配对比较这一限制，不能据此得出一般鲁棒性结论。

## 首次失败也保留

第一次项目 `c6576df342a84cc3961a726371344b76` 在一次CLI调用后被平台判失败。CLI exit=0，返回usage=10612 tokens；事件含启动诊断 `item.type=error` 和最终 `agent_message`。最初适配器把任何非agent_message/reasoning item当作执行工具，误判为 `unexpected_cli_tool`。

修正为允许启动诊断item，同时仍拒绝真正的工具item；新增专门回归测试。未自动重发旧任务，修复后另建成功项目。原错误、请求和用量见 [attempt-01.json](attempt-01.json)。全部两次项目合计10次CLI启动、已知112184 tokens；成功项目与失败尝试分开记录。

## 界面与自动检查

群聊布局保留，只增加模型后台选择和准确标识。浏览器完成新群五项输入，选择research/Codex但关闭模型权限后，实际保存backend=`codex_cli`、model=`gpt-6.1-sol`、effort=`high`，worker没有启动CLI，任务单位和调用记录均为0。该界面fixture ID：`6472e89761e64ea0a7bebe26f7ed95a7`。

检查840px桌面和425px窄屏，页面无横向溢出；组会附件可读并能打开原工具证据。界面截图：[组会](meeting.jpg)、[权限阻止启动](permission-blocked.jpg)。原8965预览先备份数据库、确认无运行任务，再升级已知网页/worker；新CLI验收使用独立9065数据库，不覆盖原有项目。

```bash
python3 -m unittest discover -s tests -q
# 81 tests passed, including 12 new subprocess/CLI tests and 1 new HTTP backend test
python3 -m unittest discover -s reproductions -p test_score_comparison.py -v
# 5 score tests passed
node --check labcouncil/static/app.js
git diff --check
```

单元测试用可执行fixture程序，不访问真实模型；真实CLI结果由上述独立验收产生。检查涵盖精确参数、JSON参数映射、权限、预算预占、非零退出、无效输出、超时终止、worker死亡终止、意外工具事件、启动诊断、旧数据库迁移和跨轮继承。research模式实际验收通过；Codex固定合成案例路径尚未单独跑真实三角色模型验收。

## 接入边界与后续

Codex承担规划、工具参数和报告推理，平台承担允许的公开读取与受控合成计算。CLI采用ephemeral/read-only，关闭自身shell、浏览器、apps、插件、hooks和子agent，不允许自动扩展工具权限。read-only不是完整读文件隔离；本次没有引入任意仓库执行工作区。

背景模型后端额度按CLI启动预占；失败/未知占额度，无平台自动重试或模型替换；CLI内部连接恢复与模型turn不是平台计数覆盖的API硬预算。初版验收使用每次120秒超时；当前新worker的研究报告/组会答复默认为180秒，research租约600秒，规划和固定工具阶段仍为120秒。CLI父进程随worker死亡终止。SQLite保留项目上下文，独立CLI会话不靠`resume --last`继承记忆。

上海AI Lab候选、其他论文/仓库复现、公开benchmark和实际用户科研组会的原待办不变。这次实验不按原single/multi/human比较的同一条件运行，不加进66.7分比较，也不能把所有科研验收项目打勾。

参考接口：[官方非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)、[官方CLI命令](https://learn.chatgpt.com/docs/developer-commands?surface=cli)、[gpt-6.1-sol官方模型页](https://developers.openai.com/api/docs/models/gpt-6.1-sol)。本机实际CLI help与版本用于核对具体参数。

新增默认报告期限与任务租约余量回归后，当前82项平台测试、5项分数测试通过。
