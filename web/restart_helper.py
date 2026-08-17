#!/usr/bin/env python3
"""外部重启助手：等待旧进程释放端口后启动新的 web.server 进程。"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser(description="grok-register WebUI restart helper")
    parser.add_argument("--python", required=True, help="Python executable path")
    parser.add_argument("--cwd", required=True, help="working directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()

    time.sleep(args.delay)

    # 优先用 pythonw.exe（无窗口），避免闪控制台黑框
    py = args.python
    if py.endswith("python.exe"):
        pythonw = py[:-10] + "pythonw.exe"
        if os.path.isfile(pythonw):
            py = pythonw

    cmd = [
        py, "-m", "web.server",
        "--host", args.host,
        "--port", str(args.port),
        "--workers", str(args.workers),
    ]
    creationflags = (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
    # 关键：把新进程输出写入日志文件，避免静默死亡（之前用 DEVNULL 吞掉后，
    # 新进程启动失败时服务直接死透且没有任何可查的报错）。
    log_path = os.path.join(args.cwd, "_web_restart.log")
    log_f = open(log_path, "ab", buffering=0)
    log_f.write(("\n=== restart_helper 启动新进程 @ %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S")).encode("utf-8"))
    subprocess.Popen(
        cmd,
        cwd=args.cwd,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        close_fds=True,
        creationflags=creationflags,
        startupinfo=startupinfo,
    )


if __name__ == "__main__":
    main()
