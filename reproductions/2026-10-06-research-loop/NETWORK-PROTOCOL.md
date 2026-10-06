# 连接诊断预注册

第三轮来源连接错误已记录异常类URLError，原因类SSLEOFError，发生在TLS握手，未得到HTTP状态。该轮已自行停止，不重发原工具操作。

接下来单独运行最多两次公开GitHub首页HEAD连接诊断，分别使用当前Python标准库和系统curl。只诊断TLS/传输，目标https://api.github.com/，不读取原失败查询、不调用模型、不修改项目额度。记录HTTP状态或异常类型，不降低证书验证和TLS安全要求。

两次HEAD诊断均HTTP200，curl证书验证结果0。为了区分接口工具本身与后台进程网络，再追加且仅追加一次公开根路径GET，直接调用同一个NoRedirect资料适配器，目标仍为https://api.github.com/；不是原失败查询的重试。结果单独保存。

## 前台资料适配器独立验收

第四轮后台仍连接失败，项目后台调用现为11/12；不再追加真实后台模型步骤。为比较进程环境，单独用同一公开资料适配器执行一次InternScience/scp检查，运行于前台审批后的命令环境。隔离数据库workspaces/research-source-check/state.sqlite3；最多3次公开HTTP请求（元信息、commit、README），每端点只尝试一次；0次模型请求。该手动组件复查会再次请求后台失败过的元信息URL，明确作为网络诊断，不是后台隐藏重试，也不计为原项目研究成果。完整source/tool记录在独立数据库，公开导出状态、commit、哈希。即使成功也不能推断后台网络已修复。
