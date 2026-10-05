# 这轮 agent 做了什么，下一轮怎么走

准备日期：2026-10-05。四份初稿均来自真实 DeepSeek Flash 的两次请求，每个任务重复两次；以下是摘要，不是替用户写好的评审意见。当时人工评审组已保存进度，等待你的意见。

用普通话说：我们让模型比较两种预测方法，一种从样本中学到直线规律，另一种总预测平均值。先看正常数据，再看掺入少量错误标签的数据。两次初步检查里，学习规律的方法误差更小，但只用了一个随机生成的数据样本，不能说明换一批数据也一定如此。

| 任务 | 已执行范围 | OLS test MSE | 对应均值基线 test MSE |
| --- | --- | --- | --- |
| clean | seed=7、mse | 0.17046895861013783 | 12.888358499556563 |
| outliers | seed=7、mse；仅 test 的 10% labels 加 ±10，训练数据不变 | 10.155670419036328 | 23.951894598705938 |

初稿都谨慎声明这是单 seed / 单指标的合成结果，没有声称一般科研价值；没有运行 seeds 19/31、mae、median_absolute_error 或独立证据核验。允许的后续工具支持上述范围，每个 seed 使用其训练均值作为基线，并在相同测试数据重新计算两个模型指标。每个运行至多六次模型请求，初稿已经使用两次。

## 看原始记录

- clean 第一次：[报告](runs/clean-human-1/draft-report.json)、[实验参数与结果](runs/clean-human-1/artifacts/evidence-1/experiment.json)、[原始 CSV](runs/clean-human-1/artifacts/evidence-1/seed-7.csv)。
- clean 第二次：[报告](runs/clean-human-2/draft-report.json)、[实验](runs/clean-human-2/artifacts/evidence-1/experiment.json)、[CSV](runs/clean-human-2/artifacts/evidence-1/seed-7.csv)。
- outliers 第一次：[报告](runs/outliers-human-1/draft-report.json)、[实验](runs/outliers-human-1/artifacts/evidence-1/experiment.json)、[CSV](runs/outliers-human-1/artifacts/evidence-1/seed-7.csv)。
- outliers 第二次：[报告](runs/outliers-human-2/draft-report.json)、[实验](runs/outliers-human-2/artifacts/evidence-1/experiment.json)、[CSV](runs/outliers-human-2/artifacts/evidence-1/seed-7.csv)。

请给两个任务的实际评审意见（可以共用同一条）：哪些结果可以保留、下一轮要补什么、结论边界如何限定。也请估计本次看材料和评审花费多少分钟。用户意见原文与时间另存，发给实际 reviewer / executor 后继续，Codex 不代替确认。

该比较只是受控小样本。真实组会增添了人类投入，不能把效果归因于多 agent 架构本身。

## 已收到你的意见

你认可当前有限结论，允许 agent 按自己的方案继续；同时要求材料说人话。后续报告改用易懂中文。评审用了多久未提供，记为未知。你的认可不被扩大解释为已证明系统科研能力。
