# DeepSeek API 最小连通测试

日期：2026-10-04（Asia/Shanghai）。范围：认证、API 连通和固定文本输出。**没有运行多 agent、工具调用、会议、恢复或科研效果实验。**

## 预先规定

- 接口：`https://api.deepseek.com/chat/completions`。
- 模型：从本地 `DEEPSEEK_MODEL` 读取，此次为 `deepseek-v4-pro`。
- 输入：`Reply with exactly LABCOUNCIL_OK. Do not include any other text.`
- 关闭 thinking；`max_tokens=128`、`temperature=0`、`stream=false`。
- 单次请求超时 45 秒，不自动重试，不自动切换模型。
- 通过标准：HTTP 成功、`finish_reason=stop`，去除首尾空白后输出准确等于 `LABCOUNCIL_OK`。
- key 仅用于认证头；记录不包含认证头、key、交互 ID 或账户信息。凭据文件作为数据解析，不执行其中的命令。

官方参考：[首次调用](https://api-docs.deepseek.com/)、[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)。

## 实际运行与结果

脚本：[check_deepseek_connectivity.py](../check_deepseek_connectivity.py)。Python 3.14.4，仅使用标准库，无额外 SDK 依赖。运行在允许联网的执行环境；此前 Gemini 检查已确认默认沙箱存在网络解析限制。

```bash
python3 reproductions/check_deepseek_connectivity.py --output logs/deepseek-connectivity-attempt-01.json
```

| 指标 | 实际结果 |
| --- | --- |
| 客户端请求尝试 | 1 次，无重试 |
| HTTP / 退出码 | 200 / 0 |
| 请求模型 / 返回模型 | deepseek-v4-pro / deepseek-v4-pro |
| finish_reason | stop |
| 输出 | LABCOUNCIL_OK |
| 客户端耗时 | 0.964 秒 |
| 输入 / 输出 / 总 token | 20 / 5 / 25 |
| 缓存命中输入 token | 0 |

脱敏记录：[attempt-01.json](attempt-01.json)。包含时间、请求参数、选取的响应字段、usage 和脚本 SHA256，没有保存完整认证请求或完整响应对象。未查询余额，也未将 token 数换算为已结算费用。

## 结论与限制

本地配置可读取，当前账户能成功调用 `deepseek-v4-pro`。此次关闭 thinking 以检查连通，因此也没有验证推理模式。

该结果不证明科研评审质量、工具调用正确性、长任务可靠性或持续运行额度，也不是上游论文的复现。与此前 Gemini 的单次耗时不能构成模型性能比较：接口、tokenizer 和生成设置不同，且样本数均为 1。

## 默认模型更正与 Flash 检查

初始将 Pro 设为默认，未先比较当前版本，选择依据不足。用户指出版本差异后，核对官方模型表：`deepseek-flash` 当前对应 DeepSeek-V4.1-Flash，`deepseek-v4-pro` 对应 DeepSeek-V4-Pro-0813；旧名称 `deepseek-v4-flash` 仍被接受，但官方建议使用 `deepseek-flash`。[官方模型表](https://api-docs.deepseek.com/quick_start/pricing/)

后续验证按用户选择使用 `deepseek-flash`；本地配置、公开配置模板和脚本缺省值均已更正。之前的 Pro 记录保留为实际历史结果。其脚本 SHA256 对应仓库 commit `0189a1e` 中的脚本，不能用更正后的脚本哈希替代。

采用相同固定输入和生成设置重跑一次，无重试：

```bash
python3 reproductions/check_deepseek_connectivity.py --output logs/deepseek-flash-connectivity-attempt-01.json
```

结果：HTTP 200、退出码 0、返回模型 `deepseek-flash`、`finish_reason=stop`、输出 `LABCOUNCIL_OK`；耗时 0.411 秒，输入 20 / 输出 5 / 总计 25 token。脱敏记录见 [flash-attempt-01.json](flash-attempt-01.json)。这是 Flash 连通证据，不能由两个单次固定文本请求判断模型的科研能力高低。

下一步应执行有明确验收标准的工具任务、生成证据报告、接收人的修改意见，再验证下一轮行为，另行记录失败、耗时和用量。

复跑时填写本地 `.env` 的 `DEEPSEEK_API_KEY` 和 `DEEPSEEK_MODEL`，选择新的输出文件名。每次运行发送一次可能计费的 API 请求。结果仅代表本次观察，后续权限、额度和模型行为可能变化。
