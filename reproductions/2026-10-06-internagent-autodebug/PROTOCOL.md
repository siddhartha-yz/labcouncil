# InternAgent 1.5：最小 AutoDebug 检查

预先写入：2026-10-06（Asia/Shanghai）。固定源码 `fa8c3eedfa9751d3752ea6eb49220b303ac2397d`。

1. 用已有 Python 3.11.10 / PyTorch 环境运行原始 `tasks/AutoDebug/code/experiment.py` 的字节相同副本，不修改模型、数据、训练轮数或随机种子。限制 CPU 线程，60 秒外层超时，执行两次，各自保存输出和结果。示例没有固定 PyTorch 随机种子；两次运行是重复尝试，不是两组预设 seed。
2. 保存环境版本、原始文件哈希和实际训练时间；检查结果文件是否有限数值。作者描述的 30 秒训练上限单独判断。此步骤运行的是作者提供的基线，**没有 agent 改进实验**。
3. 在清除所有模型密钥、关闭 dotenv 自动读取的环境中运行原始 `launch_discovery.py --help`，记录最早失败。核对原始实验后端需要的 CLI/库以及超时设置。只做有边界的依赖诊断，不安装整个跨学科依赖清单。
4. 若仅有 DeepSeek key 无法运行原始实验后端，明确记录未完成完整发现循环，不用替代 agent 或伪造 CLI 充当原版成功。

不验证论文科研结果、模型效果或一般自主研究能力。上游示例中的既有经验文本与未经指定种子的随机初始化是限制；不将本地基线输出与作者不同机器的预存结果直接做效果排名。

## 后续增补（基线与入口预检之后）

DeepSeek [官方 Anthropic 兼容说明](https://api-docs.deepseek.com/guides/anthropic_api/)和 [Claude Code 配置说明](https://api-docs.deepseek.com/guides/coding_agents/)支持用同一 DeepSeek key 配置 Claude Code。因此不能仅凭本机尚未安装 CLI，就断言 DeepSeek key 无法运行这个后端。

在项目内隔离安装官方 CLI；如运行，真实 key 仅由本地主机代理持有，CLI 收到占位凭据。代理只转发 Messages / token count 路径，固定 Flash、禁用 thinking，输出上限 512，最多 4 次模型请求，保留 usage。用原始 ClaudeCodeRunner 执行一个不调用工具的短文本任务，外层超时 60 秒。单独记录直接 CLI 与原 runner 的差异；不把后端接口检查当作完整发现循环或 AutoDebug 改进成功。
