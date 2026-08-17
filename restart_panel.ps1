$ErrorActionPreference = 'Stop'
$root = "C:\Users\13370\zhuceji"
Set-Location $root

Write-Host "==> 1. stop all processes on port 8092" -ForegroundColor Cyan
Get-NetTCPConnection -LocalPort 8092 -ErrorAction SilentlyContinue | ForEach-Object {
    try { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } catch {}
}

Write-Host "==> 2. stop web.server / tunnel_runner python processes" -ForegroundColor Cyan
Get-Process -Name python, pythonw -ErrorAction SilentlyContinue | Where-Object {
    ($_.CommandLine -like "*web.server*") -or ($_.CommandLine -like "*tunnel_runner*")
} | ForEach-Object {
    try { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue } catch {}
}

Start-Sleep -Seconds 3

Write-Host "==> 3. find usable Python (venv first, fallback system)" -ForegroundColor Cyan
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

Write-Host "==> 4. start web.server (hidden window)" -ForegroundColor Cyan
Start-Process -FilePath $py -ArgumentList "-m", "web.server" `
    -WorkingDirectory $root `
    -RedirectStandardOutput (Join-Path $root "_web_start.log") `
    -RedirectStandardError (Join-Path $root "_web_start.err") `
    -WindowStyle Hidden

Start-Sleep -Seconds 6

if (Get-NetTCPConnection -LocalPort 8092 -ErrorAction SilentlyContinue) {
    Write-Host ""
    Write-Host "[OK] 8092 is listening, open http://127.0.0.1:8092 (press Ctrl+F5 to hard refresh)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[FAIL] 8092 failed to start, error log:" -ForegroundColor Red
    Get-Content (Join-Path $root "_web_start.err") -Tail 30
}
Write-Host ""
Write-Host "--- _web_start.log (tail) ---" -ForegroundColor Cyan
Get-Content (Join-Path $root "_web_start.log") -Tail 15 -ErrorAction SilentlyContinue
