# 首次检查记录

日期：2026-10-04（Asia/Shanghai）。范围：来源固定、环境预检，以及有限的干预组件检查。**没有复现论文中的科研结果，也没有开展完整 agent 运行。**

## 固定的代码版本

| 对象 | commit | 源码日期 | 与论文版本的关系 |
| --- | --- | --- | --- |
| freephdlabor | `9102d18a161037294d3d963b2799351aa724c58b` | 2026-09-03 | 当前默认分支版本；尚未确定原论文实验使用的 commit |
| Virtual Lab | `8a3a4fd9ccc0cd297bd523751e03bc9527c91832` | 2025-12-30 | 当前默认分支版本；尚未确定原论文实验使用的 commit |

来源：[freephdlabor 固定版本](https://github.com/ltjed/freephdlabor/tree/9102d18a161037294d3d963b2799351aa724c58b)、[Virtual Lab 固定版本](https://github.com/zou-group/virtual-lab/tree/8a3a4fd9ccc0cd297bd523751e03bc9527c91832)。后续科研结果复现必须寻找论文对应版本，不能把运行新版本视为精确复现原论文。

## 环境预检

- 系统 `python3`：3.14.4；未安装 torch、openai、smolagents、litellm、pytest。
- 临时隔离环境由 uv 建立，实际解释器为 Python 3.12.14。
- 所检查的模型 API key 环境变量均未配置，只记录存在与否，没有读取或输出值。
- `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader` 退出码 9，提示无法连接 NVIDIA 驱动。不能据此判断物理 GPU 是否存在，但当前 GPU 可用性未通过检查。
- freephdlabor 官方 environment.yml 指定 Python 3.11.10、smolagents 1.20.0 和 torch 2.5.1；上述临时环境并非完整的官方环境。

## 实际命令及尝试

```bash
git clone --depth=1 https://github.com/ltjed/freephdlabor.git /tmp/labcouncil-freephdlabor-20261004
git clone --depth=1 https://github.com/zou-group/virtual-lab.git /tmp/labcouncil-virtual-lab-20261004
git -C /tmp/labcouncil-freephdlabor-20261004 rev-parse HEAD
git -C /tmp/labcouncil-virtual-lab-20261004 rev-parse HEAD
uv venv /tmp/labcouncil-repro-venv-20261004 --python python3
uv pip install --python /tmp/labcouncil-repro-venv-20261004/bin/python smolagents==1.20.0
```

下载源码和建立环境成功。第一次安装 smolagents 在下载官方 PyPI 元数据时，三次网络重试后失败，原始错误为 `tls handshake eof`。这是环境／网络失败，不是框架实验失败。

第二次安装成功，安装了 smolagents 1.20.0 及依赖。传递依赖使用本次解析到的版本，并非完整复用论文环境；实际版本保存于 [requirements-observed.txt](requirements-observed.txt)。记录版本时 uv freeze 因默认缓存目录只读失败，随后使用解释器的 importlib.metadata 成功导出，未改变运行环境。

## 干预组件检查的预先规定

脚本：[check_freephdlabor_intervention.py](../check_freephdlabor_intervention.py)。仅运行固定版本的 callback，使用真实 smolagents 记忆对象和队列输入；提供包含记忆的简单对象作为调用方，不构造完整研究 agent。没有模型请求、TCP 传输或科学实验。

| 输入 | 检查标准 |
| --- | --- |
| 无输入 | callback 返回，记忆不变 |
| 修改任务 | 一条用户修改加入记忆，可序列化为用户消息；下一次 callback 不重复追加 |
| 新任务 | 一条 TaskStep 加入记忆，内容匹配输入 |
| 取消 | callback 返回，记忆不变 |
| 输入未结束 | 在确定进入 callback 后观察是否持续等待；八秒后终止子进程 |

最后一项如果持续等待，只说明该函数在缺少完整输入时没有在八秒内返回。不能据此断言整个系统死锁；平台需要另行处理连接中断、超时与取消。

## 已执行的组件检查结果

```bash
/tmp/labcouncil-repro-venv-20261004/bin/python reproductions/check_freephdlabor_intervention.py \
  /tmp/labcouncil-freephdlabor-20261004 \
  --output reproductions/2026-10-04-initial-audit/intervention-results.json
```

主进程退出码：0。原始标准输出、标准错误、源码 SHA256、时间、依赖版本和各项状态保存在 [intervention-results.json](intervention-results.json)。

| 情况 | 实际结果 | 判断 |
| --- | --- | --- |
| 无输入 | 返回，记忆不变 | 该组件符合预期 |
| 修改任务 | UserInstructionStep 加入真实 AgentMemory，可生成用户消息；下一次调用不重复追加 | 该组件符合预期；尚未验证模型行为 |
| 新任务 | 内容匹配的 TaskStep 加入记忆 | 该组件符合预期；尚未验证任务执行 |
| 取消 | 返回，记忆不变 | 该组件符合预期 |
| 输入未结束 | 已进入 callback，八秒未返回，子进程被测试脚本终止 | 观察到等待；整体退出码 0 仅表示与预先规定的观察一致，不代表该情况满足产品要求 |

模型调用数：0。没有调用付费模型 API，没有训练实验。本记录提供的是有限的组件行为证据，不是整个系统或科研结论的独立复现。

复跑需要先 clone 上游并 checkout 上述固定 commit，再用隔离环境安装记录的依赖，执行相同脚本。当前临时 checkout 可能被系统清理，不是证据存储位置。

## 当前结论

尚未选用任何框架。来源审计、环境检查与有限的 callback 行为检查不足以验证论文结论。下一步需要分别完成最小真实会议、模型干预后的行为检查、恢复检查及科研效果比较。真实模型运行仍缺少配置，GPU 可用性检查仍未通过。
