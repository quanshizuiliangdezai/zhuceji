$ErrorActionPreference = 'Stop'
$root = "C:\Users\13370\zhuceji"
Set-Location $root

# 0. 拉取最新代码（best-effort，失败也继续用当前代码）
Write-Host "==> 0. git pull latest (feat/sub2api-discover)" -ForegroundColor Cyan
try {
    $out = & git pull origin feat/sub2api-discover 2>&1
    $out | ForEach-Object { Write-Host ("    " + $_) }
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

# 3. 决定目标端口：优先用正在跑的端口，否则用 server.json，再否则 8092
$cfgPort = 8092
try {
    $cfg = Get-Content (Join-Path $root "server.json") -Encoding utf8 -ErrorAction SilentlyContinue | ConvertFrom-Json
    if ($cfg.port) { $cfgPort = $cfg.port }
} catch {}
$targetPort = if ($runningPorts.Count -gt 0) { $runningPorts[0] } else { $cfgPort }
Write-Host ("    目标端口: " + $targetPort) -ForegroundColor Green

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

if (Get-NetTCPConnection -LocalPort $targetPort -ErrorAction SilentlyContinue) {
    Write-Host ""
    Write-Host ("[OK] " + $targetPort + " is listening, open http://127.0.0.1:" + $targetPort + " (press Ctrl+F5 to hard refresh)") -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host ("[FAIL] " + $targetPort + " failed to start, error log:") -ForegroundColor Red
    Get-Content (Join-Path $root "_web_start.err") -Tail 30
}
Write-Host ""
Write-Host "--- _web_start.log (tail) ---" -ForegroundColor Cyan
Get-Content (Join-Path $root "_web_start.log") -Tail 15 -ErrorAction SilentlyContinue
