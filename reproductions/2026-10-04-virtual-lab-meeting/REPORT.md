# Virtual Lab 上游会议函数检查

日期：2026-10-04（Asia/Shanghai）。固定上游 commit `8a3a4fd9ccc0cd297bd523751e03bc9527c91832`，源码版本 1.2.0。[上游固定版本](https://github.com/zou-group/virtual-lab/tree/8a3a4fd9ccc0cd297bd523751e03bc9527c91832)

**结论：真实上游会议编排、摘要保存和后续会议读入摘要得到有限功能证据。原始严格 JSON 输出条件失败；在显式修订的格式合同下，已有两场输出经离线复核通过。** 模型替换为 DeepSeek Flash、任务替换为合成回归证据讨论；不是论文科研结果复现。

## 实际使用了什么

- 原始 `Agent`、`run_meeting`、`save_meeting`、`load_summaries`；上游源文件哈希运行前后一致。
- 运行时替换连接构造入口，将真实 SDK 请求发到 DeepSeek 官方接口，返回真实 SDK 响应。没有模拟模型回答或重新实现上游会议编排。
- 每场 PI 初始、Experimentalist、Methodologist、PI 总结，四次回应；共两场、8 次请求，无模型请求重试。
- PubMed 搜索关闭，没有执行新的实验。讨论的第一轮 MSE 来源是已保存的真实本地合成实验，第二场新的 seeds/metrics 是尚待执行的计划。
- 评审决定 `TEST_REVIEW_MAE_3SEEDS` 是预设测试输入，`human_confirmed=false`；没有假设用户在线或把模型推荐当作用户同意。

协议及修订：[PROTOCOL.md](PROTOCOL.md)。原始验证脚本对应 commit `c60317b`，单个代码块适配对应 `073a9db`；最终脚本另支持唯一的末尾 JSON 对象。

## 失败与重新验收

| 条件 / 记录 | 实际结果 | 判定 |
| --- | --- | --- |
| 原始纯 JSON， [run-01/metadata.json](runs/run-01/metadata.json) | 第一场四次发言完成；返回 Markdown 章节和 JSON 代码块 | 原始格式条件失败，会议编排与保存已观察到 |
| 单代码块适配，[run-02/metadata.json](runs/run-02/metadata.json) | 第一场离线复核通过；第二场四次发言完成，JSON 直接置于正文末尾 | 代码围栏条件失败，原始状态保留 |
| 纯 JSON / 单代码块 / 唯一末尾对象，[assessment.json](runs/run-02/assessment.json) | 离线复核已有两场输出，数值、引用、计划字段和保存文件符合要求 | 修订格式合同下通过；新增 API 0 |

上游 `team_meeting_team_lead_final_prompt` 在 agenda_rules 后再次要求固定 Markdown 结构，与最初设定的“仅 JSON”规则冲突。它不是通用结构化决策输出接口。不能因原始格式验收失败，直接归因于模型科学能力；也不能删除失败、声称第一次就成功。

最终解析器拒绝无合法对象、多个候选对象或末尾对象之后还有正文的歧义输出。7 项格式边界离线检查通过。原始会议正文、原始 metadata 与重新验收结果分别保存，没有把 failed 改成 passed。

## 功能逐项证据

两场均有 PI 两次、两个成员各一次非空回应。上游保存的 Markdown 包含 JSON 讨论文件的每条原始消息。第二场 inputs.json 的 summaries 与第一场最后一条消息一致，并检查它实际进入第二场 SDK 请求。

两场汇总均保留 `experiment-0001` 的 MSE：线性回归 0.17046895861013783，均值基线 12.888358499556563，包含局限、下一步，以及 `new_experiments_executed=false`。

第二场总结的 `planned_seeds=[7,19,31]`、`planned_metrics=[mse,mae,median_absolute_error]`、`decision_ids=[TEST_REVIEW_MAE_3SEEDS]` 与输入一致。两个成员同时质疑改变 seeds 与 metrics 的解释边界，PI 保留了这些局限。该会议只输出计划，没有执行下一轮实验；此前自有工作流测试另验证了工具执行。

第一场模型生成了 `decision-0001` 作为建议 ID，没有人类确认。因此任何原型都必须把它当作未批准的草稿，不能直接调度为已确认决定。本检查未验证研究建议是否最佳、多角色是否增加科学价值。

## 环境、用量与复跑

Python 3.12.14。被测运行路径使用 openai 3.24.0、tiktoken 0.14.0、requests 2.34.2、tqdm 4.70.1；完整实际版本见 [requirements-observed.txt](requirements-observed.txt)。没有安装 notebook 或 typed-argument-parser，不声称完整官方环境复现。

```bash
uv venv /tmp/labcouncil-virtual-lab-venv-20261004 --python /tmp/labcouncil-repro-venv-20261004/bin/python --cache-dir /tmp/labcouncil-uv-cache
uv pip install --python /tmp/labcouncil-virtual-lab-venv-20261004/bin/python --cache-dir /tmp/labcouncil-uv-cache openai tiktoken requests tqdm
```

安装经历一次网络重试，随后成功；不属于模型运行失败。真实调用共 8 次，输入 9,976、输出 1,778、合计 11,754 token。上游 cl100k_base 估算与这些 API usage 不同；上游价格表不知道 DeepSeek，会输出 warning。未换算或确认结算费用。

本次两次运行命令：

```bash
/tmp/labcouncil-virtual-lab-venv-20261004/bin/python reproductions/check_virtual_lab_meeting.py --upstream /tmp/labcouncil-virtual-lab-20261004 --evidence reproductions/2026-10-04-deepseek-workflow/runs/run-04/artifacts/experiment-0001/experiment.json --output-dir logs/virtual-lab-meeting-01
/tmp/labcouncil-virtual-lab-venv-20261004/bin/python reproductions/check_virtual_lab_meeting.py --upstream /tmp/labcouncil-virtual-lab-20261004 --evidence reproductions/2026-10-04-deepseek-workflow/runs/run-04/artifacts/experiment-0001/experiment.json --output-dir logs/virtual-lab-meeting-02 --resume-first logs/virtual-lab-meeting-01
```

第二次继承第一场 4 次请求，新增第二场 4 次，不能再把两份累计 API 数相加。API 事件保存完整模型内容、请求消息、usage 和耗时，认证头、key 和账户信息不保存。

复跑正常路径时克隆上游、checkout 固定 commit，使用记录的依赖，填写本地 `.env`，选择新输出目录；当前脚本采用修订后的格式合同。两场最多 8 次可能计费的请求，超时或字段不符即停止。首次 cl100k_base 缓存需要网络下载；本次缓存位置为 `/tmp/labcouncil-tiktoken-cache`。

## 采用决定

**暂不将 Virtual Lab 直接选为平台运行后端。** 当前证据支持借鉴或适配其会议角色提示、顺序发言和会议文件保存；不支持用会议文字自动产生已确认决定，更不能替代任务调度、工具验证、预算、持久化 worker 或恢复机制。

后续原型可以基于已经验证的独立工具和证据组件建立真实用户评审入口。若集成上游会议，须独立实现结构化决策校验与人类确认，并保留格式失败。论文对应版本、原论文模型条件和科研结果仍未复现。

## 一对一会议补充（整理于 2026-10-05）

[INDIVIDUAL-PROTOCOL.md](INDIVIDUAL-PROTOCOL.md) 在新增请求前固定来源质疑和条件。[individual-01](runs/individual-01/) 使用原 individual 入口、研究员 → Scientific Critic → 研究员三次响应，再从真实磁盘 load_summaries 开下一场一次响应。原 Critic 角色文本保持不变，仅模型改为 Flash。四次真实请求输入 2,759、输出 1,009、总 3,768 token；源码未改变。

`SOURCE_CRITIQUE_SEED7`、原始 MSE、仅单 seed clean-data 的限制，以及未执行的 seeds 7/19/31 计划均进入两次总结。来源为此前真实 experiment.json 路径和 SHA256。输入和保存总结逐项一致。不是用户真实评审，也没有执行新实验。

**语义复核发现方法问题：研究员和 Critic 把 seed=7 的 baseline MSE 12.888358499556563 固定为后续所有 seed 的比较基线，最终和下一轮总结均沿用了它。** 原工具实际基线是在各 seed 的训练集拟合均值、对该 seed 对应测试集重新评价；不同 seed / outlier 条件应匹配数据重新计算，不能拿一个旧测试分数作为普适对照。机械验收通过仅证明来源传递，不能证明计划正确。该建议保持未批准；没有修正原回复或把它用于后续实验。正确对照须在后续实验协议显式规定。

这进一步支持现有暂不直接采用决定：多角色自检未阻止一个具体方法错误。观察不足以证明多 agent 普遍不如单 agent，仍需等预算重复对照。
