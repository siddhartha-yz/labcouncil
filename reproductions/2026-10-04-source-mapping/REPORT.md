# 论文与代码版本核对、原入口检查

整理日期：2026-10-05，Asia/Shanghai。这里补充论文版本、源码条件和失败入口，避免把当前主分支的成功套到旧论文。

## Virtual Lab

[Nature 正式页面](https://www.nature.com/articles/s41586-025-09442-9) 显示发表日期2025-07-29、正式版本记录2025-09-03；页面明确提供同行评审信息。代码/讨论存档引用 [Zenodo 15320491](https://doi.org/10.5281/zenodo.15320491)，计算结果与 ELISA 数据另引用 [15331308](https://doi.org/10.5281/zenodo.15331308)。期刊身份是来源信息，不能代替本地验收。

官方 GitHub API 返回发表日前最后候选 commit [2a3654b](https://github.com/zou-group/virtual-lab/tree/2a3654b67729972b7e2a8145adad4ec06f0164af)，日期2025-05-27。实际 checkout 后 __about__ 为1.1.0、默认模型为 gpt-4o-2024-08-06。保存 [版本文件哈希](checked-out-version.json)、API 元数据及相关源码片段。仓库 tags 接口返回空列表，未据此虚构一个 v1.1.0 tag。

这个版本的 run_meeting 使用 **Assistants / threads / runs**；我们此前被测 [1.2.0](../2026-10-04-virtual-lab-meeting/REPORT.md) 使用 **Chat Completions**。这是实质接口差异，不能只把模型名替换就声称原版运行成功。

按[追加预注册](OFFICIAL-EXAMPLE-PROTOCOL.md)，执行官方 notebook cells 0/2/3/4（五次团队选择讨论与一次合并），未执行之后的设计计算或湿实验：

- [official-example-01](official-example-01/metadata.json)：初次适配只提供 chat，原 beta 访问失败；共0次服务请求。我们自己的适配假设错误，不是上游科研失败。原 notebook 只 wait futures、不读异常，继续到零份摘要后在合并阶段再次报错。
- [official-example-02](official-example-02/metadata.json)：保持真实 SDK beta 接口，六次向 DeepSeek POST /assistants 均返回404；原线程异常独立记录。没有模拟 Assistants 服务，也没有生成模型答案。因此是当前模型供应商/接口下原入口不兼容，不能说原 OpenAI 条件下论文错误。
- 两次运行上游 src 哈希前后一致。openai 1.60.2 / Python3.12.14 的完整实际依赖见 metadata；SDK 超时45秒、重试0。没有完整安装 notebook 或纳米抗体依赖，直接执行 notebook 已读取的代码 cells。

Zenodo API 的两次读取均 TLS 失败，网页也无法正常取得元数据；失败分别保存，未覆盖。**尚未将时间候选与论文冻结存档按 hash 对齐。** 不把“最后一个发表前 commit”冒充明确标注的论文 commit，也不把发布时间附近的代码当作原实验计算条件全部确认。纳米抗体计算与湿实验结论仍未复现，首轮协议已明确排除湿实验。

## freephdlabor

[arXiv 版本页](https://arxiv.org/abs/2510.15624) 当前列出v1、提交于2025-10-17 13:13:32 UTC；预印本页面不是同行评审证明。[论文基础设施章节](https://arxiv.org/html/2510.15624v1) 提出跨会话持久化与继续研究的主张，作为可检验对象登记，不预先相信“24/7”能正常恢复。

[官方历史 API 记录](source-details-01/freephdlabor-commit-history.json) 返回26个公开 commit，最早为 [e95ce84](https://github.com/ltjed/freephdlabor/tree/e95ce84ffbf9c4c234e616cdf20b3854ea0273b5)、2025-10-20；论文提交时间之前的查询在一次成功请求中返回空列表。最初公开实现晚于论文三天，不能确认更早的作者实验代码。

两次历史文件读取的成功与 TLS 失败都保留。[最初 BaseResearchAgent](historical-files-01/freephdlabor-initial-base.json) 和[最初 callback](historical-files-02/freephdlabor-initial-callback.json) 的整文件 SHA256，与这次实际测试的9102d18版本相同：

- base：6fb5a654c6f027b7613b053075411abec58d189f82638cafc4311bd7b2d7b027
- callback：09b85650a21d0bbc9e03c60467084c3002891faa8f79e871e3a71cb28de40ba6

这支持把被测实现的问题追溯到最初公开代码；并不能把改变后的模型/依赖条件测试直接标成原论文科研结果复现。

[最初环境](environment-manifest.json) 声明 Python3.11.10、smolagents1.20.0、openai1.60.2、pydantic2.11.7，以及448项 pip 和一组 conda 系统依赖。另用最初源码和上述核心库版本、Python3.11.16做离线读取已有真实运行记忆（Python补丁版本不同，其余依赖未完全冻结）：

- [core-01](freephdlabor-core-01/preflight-failure.json)：离线助手不必要地创建 TCP socket，被本地 sandbox 拒绝；0请求，保留为检查脚本环境问题。
- [core-02](freephdlabor-core-02/assessment.json)：移除该无关 socket，使用原 BaseResearchAgent 直接 resume。消息构造仍可用；完整序列化仍报 dict 无 .dict；task 为 None，执行变量缺失。模型请求0次。
- 原 launcher --help 在这个核心环境因缺少 phoenix 失败；[原 stderr](freephdlabor-core-02/launcher-stderr.txt)。它在解析参数前导入 tracing。为避免读取真实密钥和启用调试导出，子进程环境清空了模型 key、dotenv 加载禁用、tracing endpoint 仅 loopback。这是明确改变的零请求环境预检，不能当完整 launcher 复现。

完整 pip 清单另外执行 uv dry-run，459个总依赖解析成功；日志见 environment-resolve-stdout/stderr。随后为核对原入口建立 Python3.11.10 隔离环境，安装作者 pip 清单，安装结果另记。没有复刻 conda 的全部系统库，也没有运行持续 ManagerAgent 的整套科研流程；不能因基础 agent 测试通过就宣称完整系统可运行。

## 采用边界

两份来源都提供可用机制参考，但当前条件下暂不直接采用为平台后端。新的1.2会议功能、旧1.1入口不兼容、freephdlabor 基础恢复负结果分别登记。原论文任务、模型、预算与实验数据不完全相同，因此结果层 R3 保持未复现；这些记录只支持首轮功能检查和工程采用判断。

## 完整 pip 安装与最后的入口检查

448项作者 pip 依赖在独立 **Python3.11.10** 环境安装成功（459个解析后的包，日志记录11分35秒准备、5.79秒安装）。没有替换系统 Python，conda 系统库和 GPU driver 不同条件仍明确记录。

[author-01](freephdlabor-author-01/assessment.json) 因 Phoenix 默认写 ~/.phoenix 触发文件沙箱限制；[author-02](freephdlabor-author-02/assessment.json) 将 Phoenix 指向工作区后，crawl4ai 默认写 ~/.crawl4ai 再次触发同类限制。这些是运行环境限制，不是算法失败。

[author-03](freephdlabor-author-03/assessment.json) 使用库支持的缓存目录配置并允许普通缓存初始化后，原 launcher --help 退出0；[原帮助输出](freephdlabor-author-03/original-help.txt) 保存。随后 [author-04](freephdlabor-author-04/assessment.json) 以 --model deepseek-flash 调用原入口，在参数验证阶段退出2：[原错误](freephdlabor-author-04/original-err)。固定版本支持的模型列表没有这个名称。没有偷换成 Pro 或将旧别名当成用户指定条件；没有请求模型。

在这四个完整 pip 环境复查中，恢复消息仍可构造，完整序列化错误和 task / 执行变量缺失均重复出现，不能归结为先前使用Python3.12或新版SDK造成。实际 Python、全部包版本在各 assessment 保存；完整科研循环和原模型任务未运行。

另外，[planning-01](planning-01/assessment.json) 启用原基础 agent 的规划，2次真实Flash请求（输入968、输出557、总1525 token）生成 PlanningStep，计划文字在独立进程恢复后完全一致。任务字段和执行变量仍缺失，完整序列化仍失败。该成功项补齐先前关闭规划的范围，不把“计划文字还在”扩大成整个执行现场恢复。

Zenodo官方导出及DataCite注册元数据的替代读取也遇到TLS失败，另存 archive-alternatives-01；冻结存档hash映射继续记为未知。最终采用判断基于实际被测公开版本，不能冒充原论文科研结果复现。
