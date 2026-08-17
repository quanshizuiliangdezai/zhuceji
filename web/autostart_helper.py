#!/usr/bin/env python3
"""开机自启助手：把面板注册为 Windows 任务计划（登录时后台启动）。

设计要点（对应需求"需要时刻读取我的真实信息"）：
- 本项目根目录、venv 解释器路径、监听 host/port 一律**不写死**；
- 启动器脚本（autostart_panel.ps1 / .sh）自带着项目里，运行时：
  1. 相对自身定位项目根；
  2. 实时读取 server.json 拿当前 host/port/workers（用户在面板改过立即生效）；
  3. 优先用项目内 .venv 解释器，缺失则回退系统 python；
  4. 端口已被占用则跳过（防重复启动）。
- 因此用户改了端口或重装到新路径，只要重新点一下面板按钮即可刷新任务。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "grok-register-panel-autostart"

_PS_LAUNCHER = r"""# autostart_panel.ps1 - 由面板"开机自启"按钮生成
# 运行时不写死路径/端口：每次执行都相对自身定位项目根，并实时读取 server.json
$ErrorActionPreference = 'SilentlyContinue'
$MyDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = $MyDir
$ServerJson = Join-Path $Root 'server.json'

# 实时读取真实监听配置（用户在面板改过也立即生效）
$host = '127.0.0.1'; $port = 8092; $workers = 1
if (Test-Path $ServerJson) {
    try {
        $cfg = Get-Content $ServerJson -Raw | ConvertFrom-Json
        if ($cfg.host) { $host = $cfg.host }
        if ($cfg.port) { $port = [int]$cfg.port }
        if ($cfg.workers) { $workers = [int]$cfg.workers }
    } catch {}
}

# 端口已占用则跳过（避免重复启动）
$occupied = netstat -ano | Select-String ":$port\b" | Select-String 'LISTENING'
if ($occupied) { exit 0 }

# 解析 venv pythonw（无窗口）；若缺失则回退 python/python3
$venvPy = Join-Path $Root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $venvPy)) { $venvPy = Join-Path $Root '.venv\Scripts\python.exe' }
if (-not (Test-Path $venvPy)) { $venvPy = 'python' }

# 后台、无窗口启动面板
Start-Process -FilePath $venvPy -ArgumentList '-m','web.server','--host',$host,'--port',$port,'--workers',$workers -WorkingDirectory $Root -WindowStyle Hidden
"""

_SH_LAUNCHER = r"""#!/usr/bin/env bash
# autostart_panel.sh - 由面板"开机自启"按钮生成（Linux/macOS）
# 运行时不写死路径/端口：相对自身定位项目根，实时读取 server.json
set -e
MYDIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$MYDIR"
SERVER_JSON="$ROOT/server.json"
HOST="127.0.0.1"; PORT=8092; WORKERS=1
if [ -f "$SERVER_JSON" ]; then
  VAL=$(grep -o '"host"[[:space:]]*:[[:space:]]*"[^"]*"' "$SERVER_JSON" | head -1 | sed 's/.*:"\(.*\)"/\1/')
  [ -n "$VAL" ] && HOST="$VAL"
  PVAL=$(grep -o '"port"[[:space:]]*:[[:space:]]*[0-9]*' "$SERVER_JSON" | head -1 | grep -o '[0-9]*$')
  [ -n "$PVAL" ] && PORT="$PVAL"
  WVAL=$(grep -o '"workers"[[:space:]]*:[[:space:]]*[0-9]*' "$SERVER_JSON" | head -1 | grep -o '[0-9]*$')
  [ -n "$WVAL" ] && WORKERS="$WVAL"
fi
if command -v ss >/dev/null 2>&1; then
  ss -ltn 2>/dev/null | grep -q ":$PORT " && exit 0
elif command -v lsof >/dev/null 2>&1; then
  lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && exit 0
fi
VENV_PY="$ROOT/.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
cd "$ROOT"
nohup "$VENV_PY" -m web.server --host "$HOST" --port "$PORT" --workers "$WORKERS" >/dev/null 2>&1 &
"""


def detect_venv_python(root: Path) -> str:
    venv = root / ".venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return str(venv)
    venv_sh = root / ".venv" / "bin" / "python"
    if venv_sh.is_file():
        return str(venv_sh)
    return sys.executable


def _read_server_json(root: Path) -> dict:
    defaults = {"host": "127.0.0.1", "port": 8092, "workers": 1}
    sj = root / "server.json"
    if sj.is_file():
        try:
            data = json.loads(sj.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in defaults:
                    if k in data:
                        defaults[k] = data[k]
        except Exception:
            pass
    return defaults


def write_launcher(root: Path) -> Path:
    """把启动器脚本写到项目根（运行时不写死路径/端口）。"""
    is_win = sys.platform == "win32"
    content = _PS_LAUNCHER if is_win else _SH_LAUNCHER
    launcher = root / ("autostart_panel.ps1" if is_win else "autostart_panel.sh")
    launcher.write_text(content, encoding="utf-8")
    if not is_win:
        try:
            os.chmod(launcher, 0o755)
        except Exception:
            pass
    return launcher


def autostart_status(root: Path) -> dict:
    info = _read_server_json(root)
    return {
        "ok": True,
        "installed": _task_exists(),
        "task_name": TASK_NAME,
        "is_windows": sys.platform == "win32",
        "info": {
            "project_root": str(root),
            "venv_python": detect_venv_python(root),
            "host": info.get("host", "127.0.0.1"),
            "port": int(info.get("port", 8092)),
            "workers": int(info.get("workers", 1)),
        },
    }


def install_task(root: Path) -> dict:
    launcher = write_launcher(root)
    if sys.platform == "win32":
        return _install_windows(launcher)
    return _install_posix(launcher)


def remove_task() -> dict:
    if sys.platform == "win32":
        return _remove_windows()
    return _remove_posix()


def _run(cmd, input_text=None, timeout=60):
    """统一执行子进程，读取输出时容忍非 UTF-8（避免中文系统 schtasks 输出解码崩溃）。"""
    return subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _task_exists() -> bool:
    try:
        if sys.platform == "win32":
            out = _run(["schtasks", "/Query", "/TN", TASK_NAME], timeout=20)
            return out.returncode == 0
        out = _run(["crontab", "-l"], timeout=20)
        return TASK_NAME in out.stdout
    except Exception:
        return False


def _install_windows(launcher: Path) -> dict:
    ps = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    tr = '"{ps}" -WindowStyle Hidden -ExecutionPolicy Bypass -File "{file}"'.format(
        ps=ps, file=str(launcher).replace("/", "\\")
    )
    out = _run(["schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON",
                "/TR", tr, "/F"], timeout=60)
    if out.returncode != 0:
        return {"ok": False, "message": "创建任务计划失败",
                "stderr": (out.stderr or out.stdout).strip()}
    return {"ok": True, "message": "已设置开机自启（登录时后台启动面板）",
            "launcher": str(launcher)}


def _remove_windows() -> dict:
    out = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], timeout=60)
    return {"ok": True, "message": "已取消开机自启", "removed": out.returncode == 0}


def _install_posix(launcher: Path) -> dict:
    try:
        cur = _run(["crontab", "-l"], timeout=20).stdout
    except Exception:
        cur = ""
    lines = [l for l in cur.splitlines() if TASK_NAME not in l]
    lines.append("@reboot {launcher}  # {tag}".format(launcher=str(launcher), tag=TASK_NAME))
    _run(["crontab", "-"], input_text="\n".join(lines) + "\n", timeout=20)
    return {"ok": True, "message": "已设置开机自启（@reboot）", "launcher": str(launcher)}


def _remove_posix() -> dict:
    try:
        cur = _run(["crontab", "-l"], timeout=20).stdout
    except Exception:
        cur = ""
    lines = [l for l in cur.splitlines() if TASK_NAME not in l]
    _run(["crontab", "-"], input_text="\n".join(lines) + "\n", timeout=20)
    return {"ok": True, "message": "已取消开机自启"}
