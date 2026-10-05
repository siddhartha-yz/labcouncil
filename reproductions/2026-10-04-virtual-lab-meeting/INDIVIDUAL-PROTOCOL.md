# 一对一会议和来源质疑传递

预注册：2026-10-04。上游、SDK、模型及预算条件沿用团队会议记录。使用真实 individual 入口，num_rounds=1（研究员、Scientific Critic、研究员共三次响应），随后只从落盘 JSON load_summaries，在下一场 individual num_rounds=0（一次响应）中读取总结。共四次 API，不允许外部工具。

指定来源是此前真实实验 JSON 的路径和 SHA256；固定来源质疑 SOURCE_CRITIQUE_SEED7：仅 seed=7 的 clean-data MSE 不能证明跨种子、outlier 或全面科研表现，不能称计划为已执行。不是人类组会或额外实验。保持原 Markdown 总结格式，避免此前 JSON 与上游模板冲突。

验收：来源 ID、限制和待执行多种子计划必须进入研究员最终回复和下次总结；原 MSE 不变；最终总结与落盘最后回复一致；下一轮输入严格来自磁盘总结；原 Scientific Critic 的角色描述不变、模型改为 Flash；全部源码哈希保持不变。另由 Codex 做逐句语义检查（不冒充用户人工评审），不仅检查关键词。
