# InternAgent 1.5：基线能跑，Flash 后端能连接，完整发现循环未验证

日期：2026-10-06，Asia/Shanghai。固定 [官方源码](https://github.com/InternScience/InternAgent/tree/fa8c3eedfa9751d3752ea6eb49220b303ac2397d)，完整协议见 [PROTOCOL.md](PROTOCOL.md)。

对 LabCouncil 有用的部分：作者的小回归示例可以作为实验执行接口的测试任务；原始 ClaudeCodeRunner 也能实际接上 DeepSeek Flash。**目前还不能把 InternAgent 整套当作已经跑通的研究后端。**

## 实际运行

- 原始 `experiment.py` 的字节相同副本执行两次，均成功。CPU 训练分别约 4.54 秒、2.51 秒，满足示例的 30 秒上限。
- 同样的数据切分下，MSE 分别为 238.685、260.390，R² 约 0.994。上游没有固定 PyTorch 初始化种子，两个结果有随机差异；不是两个预设 seed，也没有 agent 改进训练。
- 运行环境是已有 Python 3.11.10、PyTorch 2.5.1+cu124、scikit-learn 1.5.2、NumPy 1.26.4，实际 CUDA 不可用，所以跑 CPU。它不是作者完整依赖环境，不能据此判断用户 5070 Ti 的硬件性能。
- 原始 `launch_discovery.py --help` 最早在导入 `fastmcp` 时失败。跨学科完整 requirements 未安装，完整 idea-generation / experiment / report 循环未执行。任务目录也没有 README 泛称的 `launcher.sh`。

原始结果和 stdout 在本目录，文件哈希见 `baseline-manifest.json`。命令：`python3 reproductions/check_internagent_autodebug.py`，依赖固定源码和记录中的本地 Python 环境，拒绝覆盖已有尝试。

## 同一个 DeepSeek key 能不能供实验后端使用

能完成这里的**短文本连接测试**。DeepSeek [官方文档](https://api-docs.deepseek.com/guides/anthropic_api/)提供 Anthropic 格式端点；[CLI 配置文档](https://api-docs.deepseek.com/guides/coding_agents/)说明 Claude Code 的接法。原实验 runner 通过公开 `model` 参数指定 `deepseek-flash`，未修改上游文件。

项目内隔离安装 Claude Code 2.1.289。CLI 只收到占位凭据，真实 key 由本地代理持有；最多 4 次请求、输出上限 512、thinking 关闭、60 秒外层超时。

- 尝试 1：本地代理误拒绝带查询参数的 `/v1/messages?beta=true`，CLI 返回 400；没有转发模型请求。这是我们的测试代理缺陷，保留原失败，不归咎上游。
- 尝试 2：修正代理路径解析后，原始 runner 成功返回 `LABCOUNCIL_BACKEND_OK`。实际 1 次模型请求，响应声明 `deepseek-flash`；input 15,544 / output 8 tokens，未调用工具。
- 原 runner 用 stdout 表达结果，即使 CLI 失败也不会向调用者抛出非零退出异常；其 `subprocess.run` 未设超时。集成时需要外层退出、超时与预算检查，不能只看 Python 调用是否返回。

记录在 `backend-attempt-02/`；公开代理记录保留请求哈希、模型、用户短提示、工具名称、真实流式响应和 usage。CLI 的整段系统提示及工具描述仅保留在忽略的本地原始日志，公开记录明确说明删减，不声称公开文件等同完整原始请求。

这次后端没有编辑代码、运行改进实验或证明自主研究效果。完整发现入口的依赖问题仍保留；不把“缺少 CLI”扩写成“DeepSeek key 不兼容”，也不把短连接检查扩写成整套 InternAgent 成功。
