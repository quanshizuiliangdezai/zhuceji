$ErrorActionPreference = 'SilentlyContinue'
$root = "C:\Users\13370\zhuceji"
Set-Location $root

Write-Host "==> Killing anything on port 8092"
$procs = (Get-NetTCPConnection -LocalPort 8092 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
foreach ($pid_ in $procs) {
    Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue
    Write-Host ("    killed old PID " + $pid_)
}

Write-Host "==> Killing stale web.server processes"
Get-Process -Name pythonw -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*web.server*" } | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    Write-Host ("    killed web.server PID " + $_.Id)
}

Start-Sleep -Seconds 2

$py = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { Write-Host "ERROR: pythonw not found at $py"; exit 1 }

Write-Host "==> Starting web.server (pythonw, hidden)..."
Start-Process -FilePath $py -ArgumentList "-m","web.server" `
    -RedirectStandardOutput (Join-Path $root "_web_start.log") `
    -RedirectStandardError (Join-Path $root "_web_start.err") `
    -WindowStyle Hidden

Start-Sleep -Seconds 7

if (Get-NetTCPConnection -LocalPort 8092 -ErrorAction SilentlyContinue) {
    Write-Host ""
    Write-Host "[OK] 8092 is LISTENING. Open http://127.0.0.1:8092 (press Ctrl+F5)"
} else {
    Write-Host ""
    Write-Host "[FAIL] 8092 not listening - startup failed. Error log below:"
    Get-Content (Join-Path $root "_web_start.err") -Tail 30
}
Write-Host ""
Write-Host "--- _web_start.log (tail) ---"
Get-Content (Join-Path $root "_web_start.log") -Tail 15
