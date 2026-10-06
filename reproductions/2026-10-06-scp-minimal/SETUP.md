# 从公开仓库重新准备 SCP 检查

以下是环境准备步骤，不是新的作者科研结果复现。需要 Python 3.12；本次实际版本3.12.14。原环境完整 freeze 保留不改，下面的 portable requirements 仅去掉了本机 SCP 安装路径，其他版本不变。

在 LabCouncil 仓库根目录执行；源码目录已存在时先核对版本，不重复 clone 或覆盖：

```bash
mkdir -p workspaces/upstreams
git clone https://github.com/InternScience/scp.git workspaces/upstreams/scp
git -C workspaces/upstreams/scp checkout --detach cea5398564032aea65a78e246d06c30ae945e03f
python3.12 -m venv workspaces/scp-env
workspaces/scp-env/bin/python -m pip install -r reproductions/2026-10-06-scp-minimal/requirements-replay.txt
workspaces/scp-env/bin/python -m pip install --no-deps workspaces/upstreams/scp
```

安装失败要另存输出，不能自动放宽版本再沿用相同结果。具体包在其他系统上的可安装性未验证。

选择一个全新目录复跑，不用 key，也不向云端注册：

```bash
timeout -k 3s 20s workspaces/scp-env/bin/python reproductions/check_scp_minimal.py --output-dir logs/my-scp-check
timeout -k 3s 20s workspaces/scp-env/bin/python reproductions/check_scp_http.py --output-dir logs/my-scp-check
```

HTTP 使用本机23495端口；避免与其他实例同时运行。需要允许本地进程/线程及回环通信。失败时保存完整输出和执行环境，不把本次已记录的受限环境超时直接推广为 SDK 故障。

2026-10-06追加：新输出目录参数已在既有隔离环境实际复跑，stdio和HTTP检查均通过，输出留在忽略的 `logs/scp-replay-20261006-final/`；原公开尝试未覆盖。这里的全新环境安装步骤尚未另外运行，不声称新机器安装通过。
