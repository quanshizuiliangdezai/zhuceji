$ErrorActionPreference = 'Stop'
$root = "C:\Users\13370\zhuceji"
Set-Location $root

# 0. 拉取最新代码（best-effort，失败也继续用当前代码）
Write-Host "==> 0. git pull latest (feat/sub2api-discover)" -ForegroundColor Cyan
try {
    $gpLog = Join-Path $root "restart_panel_gitpull.log"
    & git pull origin feat/sub2api-discover 2>&1 | Out-File -FilePath $gpLog -Encoding utf8
    Write-Host "    git pull 完成（详情见 restart_panel_gitpull.log）" -ForegroundColor Gray
} catch {
    Write-Host ("    (git pull 失败，继续使用当前代码: " + $_.Exception.Message + ")") -ForegroundColor Yellow
}

# 1. 探测正在监听的面板端口（在杀进程之前）
Write-Host "==> 1. detect running panel ports" -ForegroundColor Cyan
$runningPorts = @()
try {
    $procs = Get-Process -Name python, pythonw -ErrorAction SilentlyContinue | Where-Object {
        ($_.CommandLine -like "*web.server*") -or ($_.CommandLine -like "*tunnel_runner*")
    }
    foreach ($p in $procs) {
        Get-NetTCPConnection -OwningProcess $p.Id -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
            if ($runningPorts -notcontains $_.LocalPort) { $runningPorts += $_.LocalPort }
        }
    }
} catch {}
if ($runningPorts.Count -gt 0) {
    Write-Host ("    检测到监听端口: " + ($runningPorts -join ", ")) -ForegroundColor Green
} else {
    Write-Host "    未发现正在运行的面板" -ForegroundColor Gray
}

# 2. 杀掉所有 web.server / tunnel_runner 进程
Write-Host "==> 2. stop web.server / tunnel_runner processes" -ForegroundColor Cyan
Get-Process -Name python, pythonw -ErrorAction SilentlyContinue | Where-Object {
    ($_.CommandLine -like "*web.server*") -or ($_.CommandLine -like "*tunnel_runner*")
} | ForEach-Object {
    try { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue } catch {}
}
Start-Sleep -Seconds 3

# 3. 决定目标端口：一律以 server.json 为准（默认 8092），与配置保持一致，消除双端口混乱
$cfgPort = 8092
try {
    $cfg = Get-Content (Join-Path $root "server.json") -Encoding utf8 -ErrorAction SilentlyContinue | ConvertFrom-Json
    if ($cfg.port -and ($cfg.port -is [int])) { $cfgPort = $cfg.port }
} catch {}
$targetPort = $cfgPort
Write-Host ("    目标端口(取自 server.json): " + $targetPort) -ForegroundColor Green

# 4. 找可用的 Python（优先 venv 的 pythonw，再系统 Python）
Write-Host "==> 3. find usable Python (venv pythonw first)" -ForegroundColor Cyan
$candidates = @(
    (Join-Path $root ".venv\Scripts\pythonw.exe"),
    (Join-Path $root ".venv\Scripts\python.exe"),
    "C:\Users\13370\AppData\Local\Programs\Python\Python312\pythonw.exe",
    "C:\Users\13370\AppData\Local\Programs\Python\Python312\python.exe"
)
$py = $null
foreach ($c in $candidates) {
    if (Test-Path $c) { $py = $c; break }
}
if (-not $py) {
    Write-Host "[ERROR] cannot find Python" -ForegroundColor Red
    exit 1
}
Write-Host ("    using: " + $py) -ForegroundColor Green

# 5. 无窗口启动面板
Write-Host "==> 4. start web.server (hidden window)" -ForegroundColor Cyan
Start-Process -FilePath $py -ArgumentList "-m", "web.server", "--port", $targetPort `
    -WorkingDirectory $root `
    -RedirectStandardOutput (Join-Path $root "_web_start.log") `
    -RedirectStandardError (Join-Path $root "_web_start.err") `
    -WindowStyle Hidden

Start-Sleep -Seconds 6

$resultLog = Join-Path $root "restart_panel_result.log"
if (Get-NetTCPConnection -LocalPort $targetPort -ErrorAction SilentlyContinue) {
    $msg = ("[OK] " + $targetPort + " is listening. 请浏览器打开 http://127.0.0.1:" + $targetPort + " 并按 Ctrl+F5 强刷。")
    Write-Host ""
    Write-Host $msg -ForegroundColor Green
    $msg | Out-File -FilePath $resultLog -Encoding utf8
} else {
    $errTail = (Get-Content (Join-Path $root "_web_start.err") -Tail 30 -ErrorAction SilentlyContinue) -join "`n"
    $msg = ("[FAIL] " + $targetPort + " 启动失败，请看 " + (Join-Path $root "_web_start.err") + "`n" + $errTail)
    Write-Host ""
    Write-Host $msg -ForegroundColor Red
    $msg | Out-File -FilePath $resultLog -Encoding utf8
}
Write-Host ""
Write-Host "--- _web_start.log (tail) ---" -ForegroundColor Cyan
Get-Content (Join-Path $root "_web_start.log") -Tail 15 -ErrorAction SilentlyContinue
