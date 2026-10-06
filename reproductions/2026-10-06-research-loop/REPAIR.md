# 首次请求失败后的修正

真实首次请求返回HTTP400，消耗后台额度1/12；没有执行来源查询。原供应商适配器没有保存HTTP错误body，无法从本次错误body证明具体原因。请求检查发现research-plan提示缺少JSON字样，违反DeepSeek官方JSON模式要求（https://api-docs.deepseek.com/guides/json_mode/）。这是一项已确认的请求构造缺陷，修正提示并增加发送前检查；不把推断写成供应商返回的原话。

增加脱敏且有大小上限的HTTP错误body持久化。旧失败task不重置、不重跑。下一次通过Codex工程fixture组会确认同项目新轮，再使用剩余原额度；不增加12/1上限。

此修正与下一轮启动均在再次请求之前记录。
