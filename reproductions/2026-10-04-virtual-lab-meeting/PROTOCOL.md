# Virtual Lab 最小团队会议：改变模型条件的验证

日期：2026-10-04（Asia/Shanghai）。固定上游 commit `8a3a4fd9ccc0cd297bd523751e03bc9527c91832`，对应源码版本 1.2.0。尚未确定该版本与论文实验代码的对应关系。

## 范围与条件变化

调用真实上游 `Agent`、`run_meeting`、保存会议和读取摘要函数，不重写会议编排。原始源文件不修改。运行时用记录型 client factory 替换 `run_meeting` 模块的 `OpenAI()` 连接入口，使用 DeepSeek 官方兼容接口；响应是实际 SDK/API 返回对象。

所有角色显式设为 `deepseek-flash`，关闭 thinking，temperature=0，单次输出上限 768 token，超时 45 秒，SDK max_retries=0。角色、问题和预算均为本次验证设置，不复用纳米抗体实验。仅安装被测运行路径需要的 openai、tiktoken、requests、tqdm，记录实际依赖；不声称完整复用上游安装或论文环境。

源码的 cl100k_base token 估算和 GPT 价格表不适用于 DeepSeek 结算；保留其输出但单独保存实际 API usage，不把未知价格当作零费用。源码 hash 在运行前后比较。

## 两场最小会议

每场三个角色：Principal Investigator、Experimentalist、Methodologist；`num_rounds=1`，预期 PI 初始、两个成员发言、PI 总结，共四次 API 请求。PubMed 搜索关闭。

第一场：提供已落盘的干净合成数据 seed=7 的 MSE 证据，讨论单次结果的边界和后续验证计划。不得宣称已经执行其他实验。要求最终总结为 JSON，包含证据 ID、观察到的两个 MSE、局限和下一步。

第二場：通过上游 load_summaries 从第一场 JSON 读取总结，加入新的议程和预设评审决定 `TEST_REVIEW_MAE_3SEEDS`，要求下一步计划使用 seeds 7/19/31 和 mse/mae/median_absolute_error；同时明确这是尚待执行的计划。该决定是测试输入，不代表用户实际组会确认。

## 通过标准

1. 两场均运行真实上游编排，实际请求数各为 4；三个角色均有非空回应，PI 两次发言。
2. 上游保存的 JSON 与 Markdown 存在，返回 summary 与最后一条会议消息一致；第二场输入实际包含读取的第一场 summary。
3. 两场最终 JSON 引用证据准确，观察 MSE 与提供的实际证据一致（绝对或相对误差不超过 1e-4），包含非空局限和下一步。
4. 第二场总结包含测试决定 ID、指定 seeds 与 metrics，不声称已执行第二场新增实验。
5. 源码文件哈希前后一致；调用经过脱敏记录，保存模型、响应、usage、错误和真实耗时。

最多 8 次 API 请求，无自动重试或模型回退，失败即停止并保留材料。第二场预算只在第一场通过后执行。

这是上游会议函数的功能验证，不检验代码执行、干预 callback、后台恢复、实验质量、多 agent 优势或论文纳米抗体结论。模型和任务条件变化必须随结果一起记录。

## 修订 2：适配上游的 Markdown 总结格式

原始协议和脚本固定于 commit `c60317b`。第一场四次请求全部返回，上游保存了会议，但纯 JSON 验收失败：最后摘要包含 Markdown 章节和单个 JSON 代码块。源码 `team_meeting_team_lead_final_prompt` 在 agenda_rules 后要求固定 Markdown summary_structure，与本次“仅 JSON”规则冲突。

修订后保留原摘要文本，接受纯 JSON 或其中唯一的 json 代码块；无块、多个块或结构不合法则失败。数值、证据、局限、计划和实验未执行标记仍验证。原始严格 JSON 条件仍记为未通过，不将本次问题简单归为模型能力失败。

从新目录复制第一场记录，离线重新验收单个 JSON 块，再通过原始 load_summaries 读取完整文本运行第二场，不重发第一场请求。累计最多 8 次，已使用 4 次，第二场最多剩余 4 次。上游源码仍不修改；此为适配层输出合同改变，在新请求前提交。

## 修订 3：支持正文末尾的单个 JSON 对象，仅离线复核

修订 2 固定于 commit `073a9db`。第二场四次发言和保存均完成，总结的 seeds、metrics、决定 ID 和观察数值正确，但 JSON 置于 Markdown 正文末尾，没有代码围栏，被解析器拒绝。累计已使用 8 次请求，不再发请求。

扩展适配合同：接受纯 JSON、唯一的 json 代码块，或正文末尾唯一的可解码 JSON 对象。无合法对象、多个候选对象、尾部对象后还有正文则拒绝。保留原始输出和失败状态，只在独立 assessment.json 中离线复核两场语义字段和原有功能标准，不重写 metadata 的历史 failed 状态。

这证明的是修订合同下已有会议输出可用；原始“仅 JSON”与修订 2 的代码围栏要求仍未通过。此格式适配不涉及改变上游源码或新增模型证据。
