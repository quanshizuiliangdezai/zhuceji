#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隧道长驻 runner：由面板 `start_tunnel` 派生，循环保持反向 SSH 隧道。"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# 项目根 = scripts/.. (本脚本位于 scripts/)
ROOT = Path(__file__).resolve().parent.parent
PIDFILE = ROOT / "tunnel_run.pid"
LOGFILE = ROOT / "tunnel_run.log"
CFGFILE = ROOT / "tunnel.json"
DIAGFILE = ROOT / "tunnel_run.diag.log"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        sys.stderr.write(f"log fail: {e}\n")
        sys.stderr.write(line + "\n")


def diag(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    try:
        with open(DIAGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def read_cfg() -> dict:
    if not CFGFILE.is_file():
        return {}
    try:
        raw = CFGFILE.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)
    except Exception as e:
        log(f"读取 tunnel.json 失败: {e}")
        return {}


def find_plink(cfg: dict) -> str:
    plink = cfg.get("plink_path", "")
    if plink and Path(plink).is_file():
        return plink
    cand = ROOT / "tools" / "plink.exe"
    if cand.is_file():
        return str(cand)
    return "plink"


def validate(cfg: dict) -> str:
    need = ("server", "ssh_port", "user", "auth", "local_port", "remote_port")
    for k in need:
        if not cfg.get(k):
            return f"缺少配置项: {k}"
    try:
        for k in ("ssh_port", "local_port", "remote_port"):
            v = int(cfg[k])
            if v <= 0 or v > 65535:
                return f"端口非法: {k}={v}"
    except Exception as e:
        return f"端口解析失败: {e}"
    if cfg.get("auth") == "password" and not cfg.get("password"):
        return "密码模式缺少 password"
    return ""


def build_ssh_args(cfg: dict):
    port = int(cfg["ssh_port"])
    local = int(cfg["local_port"])
    remote = int(cfg["remote_port"])
    user = cfg["user"]
    server = cfg["server"]
    args = [
        "-p", str(port), "-N", "-T",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=15",
        "-R", f"{remote}:127.0.0.1:{local}",
        f"{user}@{server}",
    ]
    if cfg.get("auth") == "key" and cfg.get("key_path"):
        args = ["-i", cfg["key_path"]] + args
    return "ssh", args


def build_plink_args(cfg: dict):
    port = int(cfg["ssh_port"])
    local = int(cfg["local_port"])
    remote = int(cfg["remote_port"])
    user = cfg["user"]
    server = cfg["server"]
    password = cfg.get("password", "")
    hostkey = cfg.get("hostkey", "")
    plink = find_plink(cfg)
    args = [plink, "-batch", "-N", "-T", "-P", str(port)]
    if hostkey:
        args += ["-hostkey", hostkey]
    args += [
        "-R", f"{remote}:127.0.0.1:{local}",
        "-pw", password,
        f"{user}@{server}",
    ]
    return plink, args


def main() -> None:
    diag(f"runner started PID={os.getpid()} ROOT={ROOT}")
    PIDFILE.write_text(str(os.getpid()), encoding="utf-8")

    while True:
        cfg = read_cfg()
        err = validate(cfg)
        if err:
            log(f"配置校验失败: {err}")
            diag(f"config invalid: {err}")
            time.sleep(10)
            continue

        if cfg.get("auth") == "password":
            exe, args = build_plink_args(cfg)
            log(f"connecting (plink) {cfg['user']}@{cfg['server']}:{cfg['ssh_port']} -R {cfg['remote_port']}:127.0.0.1:{cfg['local_port']}")
        else:
            exe, args = build_ssh_args(cfg)
            log(f"connecting (ssh) {cfg['user']}@{cfg['server']}:{cfg['ssh_port']} -R {cfg['remote_port']}:127.0.0.1:{cfg['local_port']}")

        diag(f"exec: {exe} {args}")
        # 隐藏 Windows 控制台黑框，避免 plink/ssh 弹出命令行窗口
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = None
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
        proc = subprocess.Popen(
            args,
            executable=exe if os.path.isfile(exe) else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        proc.wait()
        log(f"隧道进程退出，exit_code={proc.returncode}，10s 后重连")
        diag(f"tunnel exited code={proc.returncode}")
        time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        diag(f"runner crashed: {e}")
        log(f"runner crashed: {e}")
        raise
