# 逐步研究与组会循环：实际验收

日期：2026-10-06。预注册在第一次请求之前保存，修正与网络诊断范围逐项记录。所有确认都由Codex执行，属于工程fixture，不是用户科研评审。

## 用户能直接看到的变化

前端仍只有“设定本轮→后台工作与报告→开组会”。新建时可选真实Flash逐步研究，五项输入按轮次继承；公开查询和模型调用需要明确权限。本地计算可不授权。每天固定时段仍限制新任务启动，组会可在时段外进行。

后台每次让agent选择一个已接入的动作，工具状态先独立保存，再生成大白话报告；完成后事务内安排下一步。每轮最多六步，不是反复派固定三个角色。达到请求/任务上限、模型明确准备组会或出现重复操作时停止。精确相同操作跨轮去重；失败和未知读取不偷偷重发。

可用工具为arXiv摘要/检索、GitHub搜索/固定commit README、自有OLS合成基准、整理组会。没有任意代码执行、GPU训练或上游论文实验复现。报告失败时仍保留工具记录，新的组会快照可收录这些独立证据。来源有时间、URL、尝试状态、响应内容哈希；全文响应留在本地SQLite。

## 真实运行结果

项目 `035225388d064221b90d1e05c4fb6d28`，数据库 `workspaces/pipeline-preview/state.sqlite3`，界面 [8965](http://127.0.0.1:8965/)。

| 检查 | 结果 |
| --- | --- |
| 模型实际请求 | 后台 11/12；组会 1/1 |
| usage | 已知 12346 tokens；1 次未知；人民币费用未知 |
| 公开查询 | 4 次尝试；0 次成功 |
| 持久化 | 6 tasks、4 reports、5 独立tool记录 |
| 上下文循环 | 4 版输入、4 场快照、3 次工程确认、1 次真实追问 |
| 自动重试 | 0；每task attempts均1 |
| 重启 | 请求数/输入/证据不变，claim无待处理任务 |

第一轮：第一条Flash请求HTTP400，未查询来源。代码检查发现JSON提示缺失，违反供应商JSON模式要求。旧适配器未保存HTTP错误body，不能从这个body证明具体原因；已修复缺失提示并增加发送前检查及脱敏错误body保存。原失败保留，未重置额度。

第二轮：真实agent先申请论文摘要2602.08990，连接错误后选择独立GitHub检索。两次公开查询均无可用HTTP响应。第二份模型报告给出五条limitations，违反当时四条限制，任务停止；工具记录与原模型响应仍在。随后放宽为最多八条限制，并给规划上下文传入失败task和准确HTTP工具状态。

第三轮：申请InternScience/InternAgent检查，连接失败，工具记录明确URLError/SSLEOFError；agent下一步自行选择prepare_meeting，未假装拿到论文或代码。

第四轮：在剩余原额度内检查独立候选InternScience/scp，仍连接失败；完整一步结束后只剩一个后台请求，平台不再安排需要两请求的下一步。真实追问明确没有README、没有执行代码、没有复现，并将连接失败与科研结论分开。

模型文字仍有错误：第二轮plan混淆“第一轮模型HTTP400”与“论文查询连接错误”，还称本步“不消耗模型调用”；这些原文已记录，平台实际账本没有据此改计数。后续规划增加实际失败字段，不能因此声称所有语义错误已解决。

## 网络诊断与局部结果

按单独预注册进行了3次根路径诊断：Python HEAD、curl HEAD、同一资料适配器GET，均HTTP200；curl证书验证0。随后前台独立组件检查最多3请求，实际用了2：SCP元信息HTTP200，commit读取TLS失败。零模型请求，与后台项目分开保存。修正工具以保留已成功取得的部分元信息后，仅重新解析缓存，零新增HTTP，保留repository_metadata条目。

这些结果不能证明后台网络已修复，也不能声称已读固定commit README。原文查询仍不稳定，唯一根因尚未确认；未降低证书验证。独立诊断不是后台隐藏重试，统计与原项目4次来源尝试分开。

## 验证范围与剩余工作

Python3.11与3.14各53项测试通过，JavaScript语法检查通过。测试覆盖步骤动态派发、六步/模型/公开HTTP额度、权限拒绝、旧租约/版本隔离、跨轮去重、失败后独立工具保留与快照追问、缓存/哈希、固定commit README解析、禁止任意URL和跳转、部分元信息、过大上下文节选；全部使用离线fixture或本机HTTP，不冒充真实科研效果。

实际GUI已经走过新建、失败组会、继承/修改输入、确认、真实报告与追问；正常停止重启验收不代表长周期守护/崩溃稳定性全部通过。最终提示节选、部分来源保留和孤立工具快照分支主要由离线测试覆盖，未增加后台真实模型请求复验所有分支。

第2步仍未全部完成：优先解决公开资料连接稳定性，再接一个明确授权的隔离复现实验，保存代码/环境/输入/结果/独立核验。任意科研idea实现、长时GPU实验、模型按需读取全项目记忆、人民币/token硬预算、多日稳定性都未验收。原有上海Lab、VirtualLab、freephdlabor及其他候选继续保留在WORKLIST，不因这次工程验收改变采用结论。

## 可复查记录

- [预注册](PROTOCOL.md)、[首次修正](REPAIR.md)、[第二次修正](REPAIR-02.md)、[连接诊断协议](NETWORK-PROTOCOL.md)
- [实际账本与报告摘要](run-summary.json)、[首次失败](attempt-01-summary.json)、[第二轮原模型响应](attempt-02-summary.json)
- [前台组件](source-component.json)、[缓存重解析](source-component-reparse.json)、[重启检查](restart-check.json)
- [离线账本审计脚本](audit_saved_run.py)、[Python3.11](tests-python311.txt)、[Python3.14](tests-python314.txt)
- [研究报告截图](research-project.png)、[组会截图](research-meeting.png)

公开导出省略完整上游内容，artifact哈希对应原始完整body；模型原始响应和工具完整结果在本地忽略的数据库，可通过本机原始证据入口审查。

实现接口依据：[arXiv API手册](https://info.arxiv.org/help/api/user-manual.html)、[arXiv访问间隔要求](https://info.arxiv.org/help/api/tou.html)、[GitHub公开搜索](https://docs.github.com/en/rest/search/search)、[GitHub仓库内容接口](https://docs.github.com/en/rest/repos/contents)、[DeepSeek JSON模式](https://api-docs.deepseek.com/guides/json_mode/)。这些文档说明接口约束，不为本平台科研效果背书。
