# SCP：小工具的发现和调用通过，云端资源未验证

日期：2026-10-06，Asia/Shanghai。官方 [InternScience/scp](https://github.com/InternScience/scp/tree/cea5398564032aea65a78e246d06c30ae945e03f) 固定 commit `cea5398564032aea65a78e246d06c30ae945e03f`。协议见 [PROTOCOL.md](PROTOCOL.md)。

SCP 的原始 SDK 可以把自有 Python 函数注册成工具，由独立客户端发现并调用。这个能力对以后接入实验工具有参考价值。**这里没有验证云端 Hub、官方科学工具库、权限体系或论文科研结果。**

## 我们实际检查了什么

工具为自有 `mean_squared_error`，输入 5 个固定点。主机用另一种写法核对：只猜平均值的 MSE 为 8，正确预测的 MSE 为 0。没有调用模型、没有读取 API key、没有向云端注册。

| 原始路径 | 结果 | 限制 |
| --- | --- | --- |
| FastMCP + stdio_client + ClientSession，独立子进程 | 初始化、工具发现、正确调用通过；长度错误、类型错误、未知工具返回错误；之后再次正确调用通过 | 自有数学函数，不是官方科学资源 |
| SciLabServer + SciLabClient，实际回环 HTTP | 工具发现、正确调用和错误后的调用通过 | 原 `run_http` 忽略 host 参数绑定全接口，因此用原 `flask_app.run(host='127.0.0.1')` 启动；未修改源码、未调用注册方法 |

HTTP 的非法长度和未知工具返回 500，错误正文为 Flask 页面，没有稳定的结构化工具错误；stdio 路径则返回 `isError`。没有验证认证、并发、重试、取消或副作用去重。

## 最初失败怎样解释

第一次在受限执行环境中 stdio 初始化无回应，外层 30 秒后终止。第二次加 5 秒响应超时，进入原始 `shared/session.py` 的错误分支，却抛出 `NameError: McpError is not defined`；文件导入的是 `ScpError`。这处错误分支缺陷仍成立，但不是正常工具调用失败的充分依据。

随后在第二个隔离环境固定较早的 AnyIO / Pydantic / settings，受限环境仍失败。更换为允许正常进程通信的执行环境后：同一新依赖环境、同一源码，在带 strace 的检查和不带 strace 的控制检查中都通过。记录支持**受限执行环境影响了最初初始化**这一推断；未定位到具体限制机制，不能声称早期依赖修复了问题，也不把初始超时作为正常调用能力失败的证据。

`trace-attempt/stdio-result.json` 和 `unrestricted-control/stdio-result.json` 保存通过的全部响应；`stdio-wire-excerpt.txt` 是同一成功检查的协议读写节选。原失败、兼容依赖尝试及一次错误解析 Python symlink 导致缺包的自有 wire probe 都保留。后者是测试脚本错误，不是 SCP 导入故障。

## 可重复范围与采用判断

原环境 Python 3.12.14；通过的版本包括 AnyIO 4.15.1、Pydantic 2.13.5、pydantic-settings 2.15.0，完整清单见 `environment-freeze.txt`。这是当前解析的依赖，不是作者论文环境。较早依赖另存 `compat-environment-freeze.txt`，不覆盖通过环境。

复跑需要本地固定源码与隔离安装，使用 `--output-dir logs/my-scp-check` 或记录参数，避免覆盖已有尝试：

```bash
timeout -k 3s 20s workspaces/scp-env/bin/python reproductions/check_scp_minimal.py --output-dir logs/my-scp-check
timeout -k 3s 30s workspaces/scp-env/bin/python reproductions/check_scp_http.py --output-dir logs/my-scp-check
```

新机器环境准备步骤见 [SETUP.md](SETUP.md)，原 freeze 中的本机路径保持原样另存，提供去掉该行的 portable requirements。

当前保留为可选工具协议候选，不为 M1 模拟平台增加整套依赖。真正接入科学资源时，仍要对选中的每个工具核对输入输出、授权、超时、费用与恢复。Hub 代码还包含 Redis、对象存储及权限服务等路径，这次未运行，云端账号与工具可用性未知。README 许可徽标写 Apache 2.0，根 LICENSE 和 pyproject 写 MIT；实际集成前按所需文件再核对许可，不只看徽标。
