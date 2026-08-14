# 一键部署

本项目提供**一条命令**完成「克隆仓库 → 建虚拟环境 → 装依赖 → 生成配置 → 启动 WebUI」的完整部署。

## 方式一（推荐）：一条命令从零部署

复制粘贴下面任意一条命令到终端运行即可：

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -Command "iex (irm https://raw.githubusercontent.com/quanshizuiliangdezai/zhuceji/main/install.ps1)"
```

### Linux / macOS / Windows Git Bash

```bash
curl -fsSL https://raw.githubusercontent.com/quanshizuiliangdezai/zhuceji/main/install.sh | bash
```

运行后访问：**http://127.0.0.1:8092**

## 方式二：仓库已克隆，用内置脚本部署

如果你已经把仓库 clone 下来了，在仓库根目录执行：

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File deploy.ps1
```

### Linux / macOS / Windows Git Bash

```bash
bash deploy.sh
```

脚本会自动：
1. 选择 `python3` / `python`
2. 创建 `.venv` 虚拟环境（已存在则跳过）
3. 安装 `requirements-web.txt`（含 WebUI 依赖 + 基础依赖）
4. 若不存在 `config.json`，从 `config.example.json` 复制一份
5. 释放被占用的 `8092` 端口
6. 后台启动 `web.server`，日志写入 `web-deploy.log`

启动后访问：**http://127.0.0.1:8092**

## 自定义端口 / 监听地址

```bash
# 端口 8080
PORT=8080 bash deploy.sh

# 允许局域网 / 外网访问 (监听所有网卡)
HOST=0.0.0.0 bash deploy.sh
```

PowerShell 版：

```powershell
$env:PORT=8080; powershell -ExecutionPolicy Bypass -File deploy.ps1
$env:HOST="0.0.0.0"; powershell -ExecutionPolicy Bypass -File deploy.ps1
```

## 更新已有部署

脚本支持 `update` 参数，部署前先 `git pull` 拉取最新代码：

```bash
bash deploy.sh update
# 或
powershell -ExecutionPolicy Bypass -File deploy.ps1 update
```

## 全新机器从头部署

```bash
git clone https://github.com/quanshizuiliangdezai/zhuceji.git
cd zhuceji
bash deploy.sh        # Linux/macOS/Git Bash
# 或
powershell -ExecutionPolicy Bypass -File deploy.ps1   # Windows
```

## 手动部署（等价步骤）

如果不用脚本，也可以手动执行以下等价命令：

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-web.txt
cp config.example.json config.json  # 可选, 也可在 WebUI 里填
python -m web.server --host 127.0.0.1 --port 8092
```

`web.server` 支持命令行参数：`--host`、`--port`、`--workers`。

## 验证

```bash
curl -s http://127.0.0.1:8092/api/status
# 期望返回 {"ok":true,...}
```

## 注意事项

- `config.json`、`cpa_auths/`、`accounts_*.txt` 等均在 `.gitignore` 中，不会随仓库提交，安全。
- 部署脚本只动 `.venv` 与本地进程，不影响 git 分支与远端同步。
- 若 8092 已被其他进程占用，脚本会自动释放（fuser/lsof 或 Stop-Process）。
