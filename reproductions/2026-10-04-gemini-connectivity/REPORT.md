# Gemini API 最小连通测试

日期：2026-10-04（Asia/Shanghai）。范围：认证、API 连通和固定文本输出。**没有运行多 agent、工具调用、会议、恢复或科研效果实验。**

## 预先规定

- 使用官方 REST Interactions API，模型 `gemini-3.8-flash`。
- 输入：`Reply with exactly LABCOUNCIL_OK. Do not include any other text.`
- `thinking_level=low`，`max_output_tokens=256`，`store=false`。
- 单次请求超时 45 秒，不自动重试，不自动切换模型。
- 通过标准：HTTP 成功、状态 `completed`，去除首尾空白后输出准确等于 `LABCOUNCIL_OK`。
- key 从本地 `.env` 读取，只用于认证头；不记录 key、认证头或交互 ID。凭据文件不作为脚本执行。

官方接口参考：[Getting started](https://ai.google.dev/gemini-api/docs/get-started)、[Thinking](https://ai.google.dev/gemini-api/docs/thinking)。

## 实际运行

解释器：Python 3.14.4；仅使用标准库，无额外 SDK 依赖。脚本：[check_gemini_connectivity.py](../check_gemini_connectivity.py)。

```bash
python3 reproductions/check_gemini_connectivity.py --output logs/gemini-connectivity-attempt-01.json
python3 reproductions/check_gemini_connectivity.py --output logs/gemini-connectivity-attempt-02.json
```

| 尝试 | 环境 | 结果 | 耗时 |
| --- | --- | --- | --- |
| 01 | 默认沙箱 | DNS 解析失败，URLError / gaierror；未取得 HTTP 响应 | 0.006 秒 |
| 02 | 允许联网的执行环境 | HTTP 200，状态 completed，输出 LABCOUNCIL_OK，退出码 0 | 1.646 秒 |

两次客户端请求尝试中，只有第二次取得了成功的模型响应。第一次是网络环境问题，没有证据表明发生了模型生成；没有将其计入模型质量失败。

接口返回的外层 usage：输入 17 token、输出 5 token、总计 22 token、thought 0 token。返回对象还包含底层调用的不同 token 计数，完整保存在 [attempt-02.json](attempt-02.json)，此处不将任何计数换算为已结算费用。

两份记录分别保存在 [attempt-01.json](attempt-01.json) 和 [attempt-02.json](attempt-02.json)。仅保存请求参数、公开测试输入、选取的响应字段和脱敏后的诊断。没有保存认证头、key 或账户信息。

## 结论与限制

本地配置可读取，当前账户能成功调用 `gemini-3.8-flash`。这一条固定文本请求不足以判断多 agent 表现、工具调用正确性、长任务可靠性、持续运行额度或科研评审质量，也不是任何上游论文的复现。

下一步应按复现规则测试最小真实工作流：执行有明确验收标准的工具任务、生成证据报告、接收人的修改意见，再验证下一轮行为。需要单独记录失败、耗时和 token 用量。

复跑时从 `.env.example` 创建本地 `.env`，填写自己的 key，并选择一个尚不存在的输出文件名。每次运行会发送一次可能计费的 API 请求。调用权限、额度和模型行为可能变化，当前结果仅代表此次观察。
