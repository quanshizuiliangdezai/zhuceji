# =============================================================================
# zhuceji (grok-register) 一键安装 + 部署脚本 (Windows PowerShell)
#
# 用法（任意目录，需要 git 和 powershell）:
#   powershell -ExecutionPolicy Bypass -Command "iex (irm https://raw.githubusercontent.com/quanshizuiliangdezai/zhuceji/main/install.ps1)"
#
# 自定义端口 / 监听地址:
#   $env:PORT=8080; $env:HOST="0.0.0.0"; powershell -ExecutionPolicy Bypass -Command "iex (irm ...)"
#
# 脚本逻辑:
#   1. 检测当前目录是否已是仓库根（存在 deploy.ps1）
#   2. 若不是，则 git clone 到 .\zhuceji
#   3. 调用仓库内的 deploy.ps1 完成 venv/依赖/配置/启动
# =============================================================================
$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/quanshizuiliangdezai/zhuceji.git"
$InstallDir = if ($env:INSTALL_DIR) { $env:INSTALL_DIR } else { "zhuceji" }
$Branch = if ($env:BRANCH) { $env:BRANCH } else { "feat/sub2api-discover" }

function Run-Deploy {
  param($Root)
  Write-Host "[*] 调用 deploy.ps1 完成部署 ..."
  & powershell -ExecutionPolicy Bypass -File "$Root\deploy.ps1"
  exit $LASTEXITCODE
}

if (Test-Path "deploy.ps1") {
  Write-Host "[*] 检测到当前目录已是仓库根，直接执行 deploy.ps1 ..."
  Run-Deploy -Root (Get-Location).Path
}

if (Test-Path $InstallDir) {
  Write-Host "[*] 目录 $InstallDir 已存在，切换到 $Branch 并更新 ..."
  Set-Location $InstallDir
  if (Test-Path .git) {
    git fetch origin $Branch 2>$null
    git checkout $Branch 2>$null
    git pull --ff-only 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "    (git pull 失败，继续使用当前代码)" }
  }
} else {
  Write-Host "[*] 克隆仓库 $Branch 分支到 .\$InstallDir ..."
  git clone --branch $Branch $RepoUrl $InstallDir
  Set-Location $InstallDir
}

Run-Deploy -Root (Get-Location).Path
