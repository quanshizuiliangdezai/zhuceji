<# =============================================================================
# zhuceji (grok-register) 一键部署脚本 (Windows PowerShell) — 健壮版
#
# 改进点:
#   - 自动定位“真实 Python”，跳过 Microsoft Store 桩 (AppInstallerPythonRedirector)
#     以及本机 agent 托管的内部 python，优先使用用户安装的 Python。
#   - 启动 WebUI 时使用虚拟环境自身的 python.exe，不依赖 PATH。
#   - 后台启动采用“脱离会话”的方式，关闭终端后服务继续运行。
#
# 用法:
#   powershell -ExecutionPolicy Bypass -File deploy.ps1
#   $env:PORT=8080; powershell -ExecutionPolicy Bypass -File deploy.ps1
#   $env:HOST="0.0.0.0"; powershell -ExecutionPolicy Bypass -File deploy.ps1
#   powershell -ExecutionPolicy Bypass -File deploy.ps1 update
# ============================================================================= #>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

# ---- 1. 选择 Python (健壮版) ----
function Find-RealPython {
  $candidates = [System.Collections.Generic.List[string]]::new()

  # (a) py 启动器 (只列用户安装的 Python, 不含 agent 托管版)
  if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
      $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
      if ($exe -and (Test-Path $exe)) { $candidates.Add($exe) }
    } catch { }
  }

  # (b) 扫描常见安装目录
  $scanRoots = @(
    Join-Path $env:LOCALAPPDATA "Programs\Python",
    "C:\Python*",
    "C:\Program Files\Python*",
    "C:\Program Files (x86)\Python*"
  )
  foreach ($r in $scanRoots) {
    if (Test-Path $r) {
      Get-ChildItem $r -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $pe = Join-Path $_.FullName "python.exe"
        if (Test-Path $pe) { $candidates.Add($pe) }
      }
    }
  }

  # (c) PATH 中的 python / python3, 排除 Store 桩与 agent 托管版
  foreach ($cmd in @("python", "python3")) {
    $p = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($p) {
      $src = $p.Source
      if ($src -like "*\Microsoft\WindowsApps\*") { continue }  # 跳过 Store 桩, 其余 (含 agent 托管版) 作为兜底
      $candidates.Add($src)
    }
  }

  # 去重, 返回第一个能正常运行的
  $seen = @{}
  foreach ($c in $candidates) {
    if ($seen.ContainsKey($c)) { continue }
    $seen[$c] = $true
    try {
      $ver = & $c -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
      if ($ver) { return @{ Exe = $c; Ver = $ver } }
    } catch { }
  }
  return $null
}

$PyInfo = Find-RealPython
if (-not $PyInfo) {
  Write-Error "未找到可用的 Python。请先安装 Python 3.9+ (https://python.org)，并在 Windows 设置中关闭 Microsoft Store 的 python 执行别名。"
  exit 1
}
$PY = $PyInfo.Exe
$PYVER = $PyInfo.Ver
Write-Host "[*] 使用 Python $PYVER ($PY)"

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
  if (-not (Test-Path (Join-Path .venv "Scripts/Activate.ps1"))) {
    Write-Error "虚拟环境创建失败, 请检查 Python 是否完整安装 (需含 venv 组件)"
    exit 1
  }
}

$Activate = Join-Path .venv "Scripts/Activate.ps1"
if (-not (Test-Path $Activate)) {
  Write-Error "虚拟环境激活脚本缺失: $Activate (请删除 .venv 后重试)"
  exit 1
}
. $Activate

# ---- 3. 依赖 ----
Write-Host "[2/4] 安装 / 更新依赖 ..."
python -m pip install --upgrade pip -q
python -m pip install -r requirements-web.txt

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
  $Conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($Conns) {
    $Conns | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
  }
} catch { Write-Host "    (端口检测跳过: $_)" }

# ---- 6. 后台启动 (脱离会话, 关闭终端后仍运行) ----
$LogPath = Join-Path $Root "web-deploy.log"
$ErrLog  = Join-Path $Root "web-deploy.err"
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { $VenvPy = "python" }

try {
  Start-Process -FilePath $VenvPy -ArgumentList @("-m", "web.server", "--host", $HostAddr, "--port", $Port) `
    -WindowStyle Hidden -RedirectStandardOutput $LogPath -RedirectStandardError $ErrLog -PassThru | Out-Null
} catch {
  # 无图形会话时回退到附加到当前会话
  Start-Process -FilePath $VenvPy -ArgumentList @("-m", "web.server", "--host", $HostAddr, "--port", $Port) `
    -NoNewWindow -RedirectStandardOutput $LogPath -RedirectStandardError $ErrLog -PassThru | Out-Null
}
Start-Sleep -Seconds 4

# 验证是否起来
$Up = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($Up) {
  Write-Host "[OK] 已启动, 监听 $HostAddr`:$Port"
  Write-Host "     访问: http://$HostAddr`:$Port"
  Write-Host "     日志: web-deploy.log"
} else {
  Write-Host "[失败] 未在端口 $Port 监听到服务, 请查看日志:"
  if (Test-Path $LogPath) { Get-Content $LogPath -Tail 20 }
  if (Test-Path $ErrLog)  { Get-Content $ErrLog  -Tail 20 }
  exit 1
}
