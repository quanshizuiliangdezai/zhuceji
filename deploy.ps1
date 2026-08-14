<# =============================================================================
# zhuceji (grok-register) 一键部署脚本 (Windows PowerShell)
#
# 用法 (在仓库根目录的 PowerShell 中执行):
#   powershell -ExecutionPolicy Bypass -File deploy.ps1
#   $env:PORT=8080; powershell -ExecutionPolicy Bypass -File deploy.ps1   # 自定义端口
#   $env:HOST="0.0.0.0"; powershell -ExecutionPolicy Bypass -File deploy.ps1
#   powershell -ExecutionPolicy Bypass -File deploy.ps1 update            # 部署前先 git pull
#
# 做了什么:
#   1. 选择 python (优先 python3, 否则 python)
#   2. 创建 .venv 虚拟环境 (已存在则跳过)
#   3. 安装 requirements-web.txt
#   4. 若不存在 config.json, 从 config.example.json 复制
#   5. 释放被占用的端口 (Stop-Process)
#   6. 后台启动 web.server, 日志写入 web-deploy.log
# ============================================================================= #>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

# ---- 1. 选择 Python ----
$PY = $null
if (Get-Command python3 -ErrorAction SilentlyContinue) { $PY = "python3" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $PY = "python" }
if (-not $PY) {
  Write-Error "未找到 Python, 请先安装 Python 3.9+"
  exit 1
}
$PYVER = & $PY -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "[*] 使用 Python $PYVER"

# ---- 可选: 更新代码 ----
if ($args.Count -gt 0 -and $args[0] -eq "update") {
  if (Test-Path .git) {
    Write-Host "[*] 更新代码 (git pull) ..."
    git pull --ff-only 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "    (git pull 失败, 继续用当前代码)" }
  }
}

# ---- 2. 虚拟环境 ----
if (-not (Test-Path .venv)) {
  Write-Host "[1/4] 创建虚拟环境 .venv ..."
  & $PY -m venv .venv
}

$Activate = Join-Path .venv "Scripts/Activate.ps1"
if (-not (Test-Path $Activate)) {
  Write-Error "虚拟环境激活脚本缺失: $Activate"
  exit 1
}
. $Activate

# ---- 3. 依赖 ----
Write-Host "[2/4] 安装 / 更新依赖 ..."
pip install --upgrade pip -q
pip install -r requirements-web.txt

# ---- 4. 配置 ----
if (-not (Test-Path config.json)) {
  if (Test-Path config.example.json) {
    Write-Host "[3/4] 复制示例配置 config.example.json -> config.json"
    Copy-Item config.example.json config.json
    Write-Host "      提示: 可直接在 WebUI 中填写配置, 或编辑 config.json"
  } else {
    Write-Host "[3/4] 未找到 config.example.json, 跳过配置复制"
  }
} else {
  Write-Host "[3/4] config.json 已存在, 跳过"
}

# ---- 5. 释放端口 ----
$Port = if ($env:PORT) { [int]$env:PORT } else { 8092 }
$HostAddr = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }
Write-Host "[4/4] 启动 WebUI (http://$HostAddr`:$Port) ..."
try {
  # 仅匹配 LISTENING 状态, 避免误杀作为客户端的进程 (如 chrome)
  $Conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($Conns) {
    $Conns | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
  }
} catch { Write-Host "    (端口检测跳过: $_)" }

# ---- 6. 后台启动 ----
$LogPath = Join-Path $Root "web-deploy.log"
Start-Process -FilePath "python" -ArgumentList @("-m","web.server","--host",$HostAddr,"--port",$Port) `
  -RedirectStandardOutput $LogPath -RedirectStandardError $LogPath -NoNewWindow -PassThru `
  | Out-Null
Start-Sleep -Seconds 3

# 验证是否起来
$Up = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($Up) {
  Write-Host "[OK] 已启动, 监听 $HostAddr`:$Port"
  Write-Host "     访问: http://$HostAddr`:$Port"
  Write-Host "     日志: web-deploy.log"
} else {
  Write-Host "[失败] 未在端口 $Port 监听到服务, 请查看 web-deploy.log:"
  if (Test-Path $LogPath) { Get-Content $LogPath -Tail 20 }
  exit 1
}
