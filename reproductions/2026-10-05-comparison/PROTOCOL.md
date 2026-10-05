# 等预算受控工作流比较

预注册日期：2026-10-05，Asia/Shanghai。这是 R4 改变条件的工程/证据质量比较，不是任何论文结果复现，不使用上游虚拟实验室替代完整研究系统。

两个计算任务：T1 clean test labels（outlier_fraction=0），T2 10% test-label outliers ±10（训练集不变）。复用已独立校验的回归工具：各 seed 40 train / 100 test，OLS vs 对应 train mean，每个 seed 重新计算两个模型在同一 test 上的指标。种子可选 7/19/31，指标可选 mse/mae/median_absolute_error。两次独立 API 重复，不同条件数据和工具完全相同。温度 0.3；服务器随机性不可控，n=2 只用于发现问题，不做统计优越性声明。

三组：single（一个 agent 执行、检查、修订）；multi（executor 初稿→独立 reviewer→executor 修订，无人类反馈）；human（executor 初稿→真实用户组会意见→独立 reviewer→executor 修订）。每组每任务每重复最多六次 API、每次 1024 output tokens / 45 秒 / 0 自动重试，最多六个 seed 计算单位、两次新实验、两次 evidence verification；12 个运行合计最多72 API。实际使用量和人类时间另计，不把额外人力归因为多 agent 因果效果。

先用两次请求产生 seed=7 / mse 初稿：第一次强制调用真实工具，第二次生成 JSON 报告。single 剩余四次用于同一角色自查；multi/human reviewer 两次（允许核查工具），executor 两次（允许再实验）。保留阶段上下文和角色差异，它是受控流程差异，不要求每个角色各拿同等六次。

报告 schema：evidence_refs、observations(seed/metric/linear/baseline)、conclusion、limitations、verification_refs。关键判定提前固定：数值在1e-4绝对/相对容差内，来源真实；覆盖三个 seed 和三个指标；匹配 baseline；声称核验须有真实 verify 事件。输出非法、耗尽预算、网络失败、工具拒绝全部计入分母，不更换样本或重试到成功。记录每项是否达成，而非只报一个总分。Codex 可做语义复核但不充当 human 组。

human 组在初稿后保存检查点，等待用户真实反馈和自报评审时间；未经反馈不启动后半程。意见原文记录其适用任务，不能把 Codex 预设质疑标记为 human。所有实验保留 CSV、hash、参数、逐请求输入输出、错误、usage和原始报告。相同规格的重复工具请求返回原 evidence，另记 duplicate_request，不能悄悄重算。所有组使用同样去重机制。

## 初稿和无人工组完成后的评分名称澄清

初版 verification_claim_supported 实际要求所有引用证据核验完，导致诚实返回空 verification_refs 也标 false。为避免误称虚构，保留初版 runner 和 state，不改原记录。离线复评分别输出 verification_claim_supported（声称的 ID 均确实核验；空声明不会被判虚构）和 all_report_evidence_verified（所有报告证据实际核验）。人类组续跑使用修订评分；模型请求、工具、预算、语义验收条件未改。不重新运行已有模型样本。

## 用户实际反馈后的时间记录

用户选择“认可当前有限结论，按 agent 自己的方案继续”，对耗时问题回复“这阅读材料都不说人话。” 原文保存，不解释成新的实验指令；只增加易懂中文报告要求。耗时记为 unknown/null，不能当零分钟或用界面等待时长代替。放宽反馈文件的时间字段接收 null，以保留真实意见并继续已授权工作；因此无法做包含人工时间的完整成本效率结论。没有重新询问或替用户编造分钟数。
