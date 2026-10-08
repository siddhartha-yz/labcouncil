# 第一次用 LabCouncil：菜鸟测评 v1

先看 [CASEBOOK.md](CASEBOOK.md)：48个场景写的是用户会怎样说、怎样点，以及怎样才算帮到了他。无需读JSON。

不是熟练用户换几个错别字。包括不知道目标、没资料、怕扣钱、口语暂停/反悔、不懂结果、断连、刷新，以及正常数据→坏数据的两轮真实工作。工具选择只用可见中文按钮；用户不需要知道权限口令、实验种子或证据编号。

- [PROTOCOL.md](PROTOCOL.md)：范围、评分、冻结与公开测评借鉴。
- [AUDIT-NOTE.md](AUDIT-NOTE.md)：首轮审查发现的评分遗漏与保守补充。
- cases.json / browser-cases.json：40条HTTP对话状态场景、8条实际界面任务。
- manifest.json：题目与运行脚本的冻结哈希。与运行副本一起核查，不能悄悄改题重写基线。

评分器控制测试：

```sh
python3 -m unittest discover -s evaluations/novice-v1 -p 'test_*.py' -v
```

默认只运行本机控制路径，8条真实模型场景保留为未测：

```sh
python3 evaluations/novice-v1/run.py --output workspaces/novice-v1/my-control-run
```

显式运行真实模型路径（现有Codex登录，最多28次CLI启动）：

```sh
python3 evaluations/novice-v1/run.py --output workspaces/novice-v1/my-live-run --live
```

数据库、请求与答复、截图、审查材料和数值结果都放在已忽略的workspaces中。运行目录必须是新目录。没有模型成功替身，没有自动切模型或丢掉失败。浏览器任务需另走真实界面并留观察记录；不能用API成绩代替。report.py读取逐条宿主审查和界面记录，未测不自动通过。它的叙述模板针对本次首轮基线；后续测评须重新核对和重写结论，不能把这轮失败原因、固定示例或数值直接套给另一轮。

一次合成测试不等于真实新用户测评，也没有做开放论文/仓库复现。本版是能复用、能暴露失败的首轮基线。

后续修复与同题完整复测见 [2026-10-09记录](../../docs/NOVICE-ITERATION-2026-10-09.md)。后续报告用 `iteration_report.py --run 新运行目录 --browser 新浏览器记录目录 --baseline 原基线目录`，需要另外逐条审查并提供 reviews.json；它不会自动按模型自评通过。
