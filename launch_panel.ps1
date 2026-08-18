<#
  grok-register panel launcher (silent).
  Invoked by the startup shortcut (.lnk) so the panel starts on boot
  without any visible window. No vbs, no console flash.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

# Read port/host from server.json (default 8092 / 127.0.0.1)
$port = 8092
$hostAddr = "127.0.0.1"
try {
    $cfg = Get-Content (Join-Path $root "server.json") -Encoding utf8 -ErrorAction SilentlyContinue | ConvertFrom-Json
    if ($cfg.port -and ($cfg.port -is [int])) { $port = $cfg.port }
    if ($cfg.host) { $hostAddr = $cfg.host }
} catch {}

# Skip if already listening (avoid duplicate instance)
if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    exit 0
}

# Locate pythonw (prefer venv pythonw, then venv python)
$candidates = @(
    (Join-Path $root ".venv\Scripts\pythonw.exe"),
    (Join-Path $root ".venv\Scripts\python.exe")
)
$py = $null
foreach ($c in $candidates) { if (Test-Path $c) { $py = $c; break } }
if (-not $py) { exit 1 }

Start-Process -FilePath $py -ArgumentList "-m","web.server","--host",$hostAddr,"--port",$port `
    -WorkingDirectory $root `
    -RedirectStandardOutput (Join-Path $root "_web_start.log") `
    -RedirectStandardError (Join-Path $root "_web_start.err") `
    -WindowStyle Hidden
