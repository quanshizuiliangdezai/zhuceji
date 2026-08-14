#!/usr/bin/env python3
"""外部重启助手：等待旧进程释放端口后启动新的 web.server 进程。"""
from __future__ import annotations

import argparse
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

    cmd = [
        args.python, "-m", "web.server",
        "--host", args.host,
        "--port", str(args.port),
        "--workers", str(args.workers),
    ]
    creationflags = (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
    )
    subprocess.Popen(
        cmd,
        cwd=args.cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )


if __name__ == "__main__":
    main()
