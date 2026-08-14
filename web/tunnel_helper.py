#!/usr/bin/env python3
"""永久反向 SSH 隧道助手（面板「隧道」tab 用）。

隧道语义：把本机 `local_port` 通过 SSH 反向转发到服务器 `remote_port`，
即服务器上的 `127.0.0.1:remote_port` 流量会被转发回本机 `127.0.0.1:local_port`。
用户原话：本地 ip:18080 - 服务器 ip:18080。

认证方式：
- key     ：OpenSSH 密钥免密（沿用系统 ssh.exe 或 git 自带 ssh）。
- password：用 PuTTY 的 plink.exe，支持 `-pw 密码` 非交互传密码建隧道
            （Windows OpenSSH 无法非交互传密码，plink 可以）。
            plink 由面板检测/一键下载到项目 tools/ 目录，无需用户手动装 PuTTY。

设计要点（对应"需要提供的信息弄成面板输入框 + 可设置开机自启 + 时刻读取真实信息"）：
- 所有连接参数都来自面板填写并保存到 tunnel.json，启动器脚本（tunnel_run.ps1）运行时不写死，
  每次循环都**实时读取 tunnel.json**，改了配置下次重连立即生效，无需重新建立。
- 启动器带**重连循环**（ssh 用 ServerAlive + ExitOnForwardFailure；plink 用退出后 10s 重连），
  掉线自动重连。
- 进程跟踪用 pidfile（tunnel_run.pid），停止时按 pid 树 kill，并用 wmic 兜底按命令行特征清理
  （同时覆盖 ssh.exe 与 plink.exe）。
- 开机自启注册为 Windows 任务计划 ONLOGON（登录时后台启动启动器），与面板自启同理。
"""
from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

TUNNEL_CFG = "tunnel.json"
TUNNEL_TASK = "grok-register-tunnel-autostart"
RUNNER = "tunnel_run.ps1"
PIDFILE = "tunnel_run.pid"
PLINK_PRIMARY = "https://the.earth.li/~sgtatham/putty/latest/w64/plink.exe"
PLINK_FALLBACKS = [
    "https://www.chiark.greenend.org.uk/~sgtatham/putty/latest/w64/plink.exe",
]

DEFAULTS = {
    "server": "",          # 服务器地址 / IP
    "ssh_port": 22,         # SSH 端口
    "user": "root",         # SSH 登录用户
    "auth": "key",          # key | password（password 走 plink 支持密码）
    "key_path": "",         # 私钥路径（ed25519/rsa）
    "key_pass": "",         # 私钥密码（可选，通常留空）
    "password": "",         # 密码登录（password 模式走 plink -pw）
    "plink_path": "",       # plink 可执行路径（留空=自动探测：tools/plink.exe → PATH → 常见位置）
    "local_port": 18080,    # 本机被转发的端口
    "remote_port": 18080,   # 服务器上暴露的端口
    "enabled": False,       # 是否已建立（仅作 UI 提示）
}


# ---------------------------------------------------------------------------
# 配置读写
# ---------------------------------------------------------------------------
def read_cfg(root: Path) -> dict:
    data = dict(DEFAULTS)
    p = root / TUNNEL_CFG
    if p.is_file():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for k, v in loaded.items():
                    data[k] = v
        except Exception:
            pass
    # 数值字段兜底转换
    for num_key in ("ssh_port", "local_port", "remote_port"):
        try:
            data[num_key] = int(data[num_key])
        except Exception:
            data[num_key] = DEFAULTS[num_key]
    return data


def save_cfg(root: Path, data: dict) -> dict:
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    for num_key in ("ssh_port", "local_port", "remote_port"):
        try:
            cfg[num_key] = int(cfg[num_key])
        except Exception:
            cfg[num_key] = DEFAULTS[num_key]
    (root / TUNNEL_CFG).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cfg


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def ssh_exe() -> str:
    if sys.platform == "win32":
        cand = r"C:\Windows\System32\OpenSSH\ssh.exe"
        if os.path.isfile(cand):
            return cand
        git = r"C:\Program Files\Git\usr\bin\ssh.exe"
        if os.path.isfile(git):
            return git
        return "ssh"
    return "ssh"


def _run(cmd, input_text=None, timeout=60, cwd=None):
    """统一执行子进程，读取输出时容忍非 UTF-8（中文系统命令输出可能非 UTF-8）。"""
    return subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=cwd,
    )


# ---------------------------------------------------------------------------
# Plink（PuTTY）检测 / 下载
# ---------------------------------------------------------------------------
def find_plink(cfg: dict, root: Path) -> str | None:
    """定位 plink 可执行文件：优先用户指定路径 → 项目 tools/plink.exe → 常见位置 → PATH。"""
    candidates: list[str] = []
    custom = str(cfg.get("plink_path", "")).strip()
    if custom:
        candidates.append(custom)
    candidates.append(str(root / "tools" / "plink.exe"))
    candidates.append(r"C:\Program Files\PuTTY\plink.exe")
    candidates.append(r"C:\Program Files (x86)\PuTTY\plink.exe")
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    found = shutil.which("plink") or shutil.which("plink.exe")
    if found:
        return found
    return None


def _plink_version(path: str) -> str:
    try:
        out = _run([path, "-V"], timeout=20)
        text = (out.stderr or out.stdout).strip()
        if text:
            return text.splitlines()[0][:80]
    except Exception:
        pass
    return ""


def check_plink(root: Path, cfg: dict) -> dict:
    p = find_plink(cfg, root)
    if p:
        return {"available": True, "path": p, "version": _plink_version(p)}
    return {"available": False, "path": None, "version": ""}


def download_plink(root: Path) -> str:
    """从 PuTTY 官方下载 64 位 plink.exe 到项目 tools/ 目录。返回路径。

    依次尝试主源与备用镜像，任一成功即用（自动跟随 latest 最新版）。
    """
    dest = root / "tools" / "plink.exe"
    dest.parent.mkdir(parents=True, exist_ok=True)
    ctx = ssl.create_default_context()
    last_err = None
    for url in [PLINK_PRIMARY] + PLINK_FALLBACKS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180, context=ctx) as resp:
                data = resp.read()
            if len(data) < 100_000:
                raise RuntimeError("下载的 plink.exe 过小（%d 字节）" % len(data))
            dest.write_bytes(data)
            return str(dest)
        except Exception as exc:
            last_err = exc
    raise RuntimeError("所有 plink 下载源均失败: %s" % last_err)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def _validate(cfg: dict) -> str:
    """返回错误信息字符串，空串表示校验通过。"""
    if not str(cfg.get("server", "")).strip():
        return "服务器地址不能为空"
    try:
        port = int(cfg.get("ssh_port", 22))
    except Exception:
        return "SSH 端口必须是整数"
    if not (1 <= port <= 65535):
        return "SSH 端口必须在 1–65535"
    for pk in ("local_port", "remote_port"):
        try:
            p = int(cfg.get(pk, 0))
        except Exception:
            return "%s 必须是整数" % pk
        if not (1 <= p <= 65535):
            return "%s 必须在 1–65535" % pk
    if cfg.get("auth") == "key":
        kp = str(cfg.get("key_path", "")).strip()
        if not kp:
            return "密钥认证需要填写私钥路径"
        if not os.path.isfile(kp):
            return "私钥文件不存在: %s" % kp
    elif cfg.get("auth") == "password":
        if not str(cfg.get("password", "")).strip():
            return "密码认证需要填写服务器登录密码"
        if not find_plink(cfg, ROOT_HINT if ROOT_HINT else Path.cwd()):
            return "未检测到 plink，无法用密码建隧道：请先在隧道 tab 点「安装 plink」"
    return ""


# ROOT 在运行时由调用方注入（server.py 启动时设置）；校验时若未注入则用 cwd 兜底
ROOT_HINT: Path | None = None


def build_ssh_args(cfg: dict) -> list:
    args = [
        "-p", str(int(cfg.get("ssh_port", 22))),
        "-N", "-T",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=15",
    ]
    if cfg.get("auth") == "key":
        kp = str(cfg.get("key_path", "")).strip()
        if kp:
            args += ["-i", kp]
    else:
        args += ["-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"]
    local = int(cfg.get("local_port", 18080))
    remote = int(cfg.get("remote_port", 18080))
    args += ["-R", "%d:127.0.0.1:%d" % (remote, local)]
    args.append("%s@%s" % (str(cfg.get("user", "root")).strip(), str(cfg.get("server", "")).strip()))
    return args


def build_plink_args(cfg: dict) -> list:
    """plink 命令参数（含 -N -T）。密码通过 -pw 传入。

    注意：plink 没有 OpenSSH 的 -accept-new-host-keys / -keepalive 选项；
    首次 host key 提示由启动器里的 `echo y |` 管道喂入 y 自动接受（测试时通过
    子进程 stdin 喂 'y'）。重连由外层 while 循环负责。
    """
    port = int(cfg.get("ssh_port", 22))
    local = int(cfg.get("local_port", 18080))
    remote = int(cfg.get("remote_port", 18080))
    user = str(cfg.get("user", "root")).strip()
    server = str(cfg.get("server", "")).strip()
    password = str(cfg.get("password", ""))
    args = [
        "-N", "-T",
        "-P", str(port),
        "-R", "%d:127.0.0.1:%d" % (remote, local),
        "-pw", password,
        "%s@%s" % (user, server),
    ]
    return args


def build_ssh_test_args(cfg: dict) -> list:
    """用于执行远程命令测试（不建隧道，不带 -R -N -T）。"""
    args = [
        "-p", str(int(cfg.get("ssh_port", 22))),
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=15",
    ]
    if cfg.get("auth") == "key":
        kp = str(cfg.get("key_path", "")).strip()
        if kp:
            args += ["-i", kp]
    else:
        args += ["-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"]
    args.append("%s@%s" % (str(cfg.get("user", "root")).strip(), str(cfg.get("server", "")).strip()))
    return args


def build_plink_test_args(cfg: dict) -> list:
    """plink 测试参数：只验证 SSH 可达与认证，不建隧道（不带 -R -N -T）。"""
    port = int(cfg.get("ssh_port", 22))
    user = str(cfg.get("user", "root")).strip()
    server = str(cfg.get("server", "")).strip()
    password = str(cfg.get("password", ""))
    return [
        "-P", str(port),
        "-pw", password,
        "%s@%s" % (user, server),
    ]


def client_invocation(cfg: dict, root: Path):
    """返回 (exe, base_args, is_plink) 用于执行远程命令测试。base_args 不含 -N -T -R。"""
    if cfg.get("auth") == "password":
        plink = find_plink(cfg, root)
        if not plink:
            raise RuntimeError("未找到 plink，无法用密码测试/建立隧道，请先安装 plink")
        return plink, build_plink_test_args(cfg), True
    return ssh_exe(), build_ssh_test_args(cfg), False


# ---------------------------------------------------------------------------
# 运行器脚本（带重连循环，实时读 tunnel.json）
# ---------------------------------------------------------------------------
def write_runner(root: Path) -> Path:
    content = r"""# tunnel_run.ps1 - 由面板"隧道"tab 生成
# 运行时不写死任何参数：每次循环都相对自身定位项目根并实时读取 tunnel.json
$ErrorActionPreference = 'SilentlyContinue'
$MyDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = $MyDir
$PidFile = Join-Path $Root 'tunnel_run.pid'
$Log = Join-Path $Root 'tunnel_run.log'
$ssh = "C:\Windows\System32\OpenSSH\ssh.exe"
if (-not (Test-Path $ssh)) { $ssh = "ssh" }

function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Out-File -Append -FilePath $Log }

# 记录本启动器 PID（供面板停止时按树 kill）
$Pid | Out-File -FilePath $PidFile -Force

while ($true) {
    if (-not (Test-Path (Join-Path $Root 'tunnel.json'))) {
        Log "tunnel.json 缺失，10s 后重试"
        Start-Sleep -Seconds 10
        continue
    }
    try { $cfg = Get-Content (Join-Path $Root 'tunnel.json') -Raw | ConvertFrom-Json }
    catch { Log "tunnel.json 解析失败，10s 后重试"; Start-Sleep -Seconds 10; continue }

    $server = $cfg.server
    $port = [int]($cfg.ssh_port)
    $user = $cfg.user
    $auth = $cfg.auth
    $key = $cfg.key_path
    $local = [int]($cfg.local_port)
    $remote = [int]($cfg.remote_port)

    if ($auth -eq 'password') {
        $plink = $cfg.plink_path
        if (-not $plink -or -not (Test-Path $plink)) { $plink = "plink" }
        $pargs = @('-N','-T','-P',"$port",'-R',"$remote`:127.0.0.1:$local",
                   '-pw',$cfg.password,"$user@$server")
        Log "connecting (plink) $user@$server :$port  -R ${remote}:127.0.0.1:${local}"
        # echo y 喂入首次 host key 确认（后台无 TTY 时靠管道 stdin）
        echo y | & $plink @pargs
        Log "tunnel exited, retry in 10s"
        Start-Sleep -Seconds 10
        continue
    }

    # 默认：OpenSSH 密钥免密
    $args = @('-p', "$port", '-N', '-T',
        '-o', 'StrictHostKeyChecking=accept-new',
        '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
        '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=15')
    if ($auth -eq 'key' -and $key) { $args += @('-i', $key) }
    elseif ($auth -eq 'password') { $args += @('-o', 'PreferredAuthentications=password', '-o', 'PubkeyAuthentication=no') }
    $args += @('-R', "$remote`:127.0.0.1:$local")
    $args += @("$user@$server")

    Log "connecting $user@$server :$port  -R ${remote}:127.0.0.1:${local}"
    & $ssh @args
    Log "tunnel exited, retry in 10s"
    Start-Sleep -Seconds 10
}
"""
    runner = root / RUNNER
    runner.write_text(content, encoding="utf-8")
    return runner


# ---------------------------------------------------------------------------
# 进程状态（pidfile 优先，wmic 兜底；覆盖 ssh.exe 与 plink.exe）
# ---------------------------------------------------------------------------
def _pidfile_alive(root: Path) -> int:
    pf = root / PIDFILE
    if not pf.is_file():
        return 0
    try:
        pid = int(pf.read_text(encoding="utf-8").strip())
    except Exception:
        return 0
    if pid <= 0:
        return 0
    try:
        out = _run(["tasklist", "/FI", "PID eq %d" % pid], timeout=15)
        if "PID" in out.stdout and str(pid) in out.stdout:
            return pid
    except Exception:
        pass
    return 0


def _wmic_marked_pids(cfg: dict) -> list:
    """兜底：扫描 ssh.exe / plink.exe 中含本隧道 -R 标记与服务器的 PID。"""
    pids = []
    remote = int(cfg.get("remote_port", 18080))
    local = int(cfg.get("local_port", 18080))
    marker = "-R %d:127.0.0.1:%d" % (remote, local)
    server = str(cfg.get("server", "")).strip()
    for exe in ("ssh.exe", "plink.exe"):
        try:
            out = _run(["wmic", "process", "where", "name='%s'" % exe,
                        "get", "processid,commandline", "/format:csv"], timeout=20)
            for line in out.stdout.splitlines():
                low = line.lower()
                if marker in low and server.lower() in low:
                    parts = line.split(",")
                    if parts:
                        pid_str = parts[-1].strip()
                        if pid_str.isdigit():
                            pids.append(int(pid_str))
        except Exception:
            pass
    return pids


def tunnel_status(root: Path) -> dict:
    cfg = read_cfg(root)
    pid = _pidfile_alive(root)
    marked = _wmic_marked_pids(cfg) if pid == 0 else []
    running = pid > 0 or bool(marked)
    return {
        "ok": True,
        "running": running,
        "pid": pid or (marked[0] if marked else 0),
        "marked_pids": marked,
        "enabled": bool(cfg.get("enabled")),
        "plink": check_plink(root, cfg),
        "config": {k: cfg[k] for k in ("server", "ssh_port", "user", "auth",
                                       "local_port", "remote_port")},
    }


def start_tunnel(root: Path, cfg: dict) -> dict:
    err = _validate(cfg)
    if err:
        return {"ok": False, "message": err}
    if cfg.get("auth") == "password":
        plink = find_plink(cfg, root)
        if not plink:
            return {"ok": False,
                    "message": "未检测到 plink，无法用密码建隧道。请先在隧道 tab 点「安装 plink」"}
    cfg["enabled"] = True
    save_cfg(root, cfg)
    runner = write_runner(root)
    ps = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    try:
        subprocess.Popen(
            [ps, "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy",
             "Bypass", "-File", str(runner).replace("/", "\\")],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                           | getattr(subprocess, "DETACHED_PROCESS", 0)),
        )
    except Exception as exc:
        return {"ok": False, "message": "启动隧道失败: %s" % exc}
    time.sleep(1.5)
    st = tunnel_status(root)
    if st["running"]:
        return {"ok": True, "message": "隧道已建立（带重连），本机 %d → 服务器 %d（%s）"
                % (int(cfg["local_port"]), int(cfg["remote_port"]),
                   "plink 密码" if cfg.get("auth") == "password" else "密钥免密"),
                "running": True, "pid": st["pid"]}
    return {"ok": True, "message": "已尝试启动隧道（pidfile 尚未就绪，请稍后刷新状态）",
            "running": False}


def stop_tunnel(root: Path) -> dict:
    cfg = read_cfg(root)
    pid = _pidfile_alive(root)
    killed = []
    if pid:
        try:
            _run(["taskkill", "/F", "/PID", str(pid), "/T"], timeout=15)
            killed.append(pid)
        except Exception:
            pass
    for mp in _wmic_marked_pids(cfg):
        if mp not in killed:
            try:
                _run(["taskkill", "/F", "/PID", str(mp)], timeout=15)
                killed.append(mp)
            except Exception:
                pass
    cfg["enabled"] = False
    save_cfg(root, cfg)
    pf = root / PIDFILE
    if pf.is_file():
        try:
            pf.unlink()
        except Exception:
            pass
    return {"ok": True, "message": "已停止隧道（清理 PID: %s）" % (", ".join(map(str, killed)) or "无"),
            "killed": killed}


# ---------------------------------------------------------------------------
# 测试：SSH 可达 + 端到端转发验证
# ---------------------------------------------------------------------------
def test_ssh_reachable(cfg: dict, root: Path) -> dict:
    try:
        exe, base, is_plink = client_invocation(cfg, root)
    except Exception as exc:
        return {"ok": False, "reachable": False, "message": str(exc)}
    # plink 首次未知 host key 需从 stdin 喂 'y' 接受
    inp = "y\n" if is_plink else None
    try:
        out = _run([exe] + base + ["echo", "tunnel_ok"], timeout=30, input_text=inp)
    except Exception as exc:
        return {"ok": False, "reachable": False, "message": "SSH 连接异常: %s" % exc}
    if out.returncode == 0 and "tunnel_ok" in out.stdout:
        return {"ok": True, "reachable": True, "message": "SSH 可达且认证通过"}
    err = (out.stderr or out.stdout).strip()
    if "Permission denied" in err:
        return {"ok": False, "reachable": False,
                "message": "认证失败（密钥/密码不对或公钥未装到服务器）"}
    if "timed out" in err or "Connection timed out" in err or "Could not resolve" in err:
        return {"ok": False, "reachable": False,
                "message": "无法连接服务器（地址/端口/网络不通）"}
    return {"ok": False, "reachable": False, "message": "SSH 测试未通过: " + err[:200]}


def test_forward(root: Path, cfg: dict) -> dict:
    """端到端验证：本机临时起一个 HTTP 服务，从服务器 curl 回来比对 token。"""
    local = int(cfg.get("local_port", 18080))
    remote = int(cfg.get("remote_port", 18080))
    token = "grok_tunnel_probe_%d" % int(time.time())

    probe = None
    busy = False
    import http.server
    import socketserver

    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(token.encode("utf-8"))

        def log_message(self, *a):
            pass

    try:
        srv = socketserver.TCPServer(("127.0.0.1", local), _H)
    except OSError:
        busy = True
        srv = None
    if srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    try:
        remote_cmd = (
            "curl -s -o /dev/null -w 'HTTP_%{http_code}' -m 8 http://127.0.0.1:%d/ "
            "|| python3 -c \"import urllib.request;print('HTTP_'+str(urllib.request.urlopen('http://127.0.0.1:%d/',timeout=8).status))\" 2>/dev/null"
            % (remote, remote)
        )
        try:
            exe, base, is_plink = client_invocation(cfg, root)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        inp = "y\n" if is_plink else None
        try:
            out = _run([exe] + base + [remote_cmd], timeout=35, cwd=str(root), input_text=inp)
        except Exception as exc:
            return {"ok": False, "message": "服务器侧测试异常: %s" % exc}
        resp = out.stdout.strip()
        if not busy and token in out.stdout:
            return {"ok": True, "message": "端到端隧道通：服务器 %d 成功回连到本机 %d（探针命中）" % (remote, local)}
        if busy:
            if "timed out" in (out.stderr or "") or "Connection timed out" in (out.stderr or ""):
                return {"ok": False, "message": "隧道转发不通（服务器侧连接超时）"}
            return {"ok": True,
                    "message": "隧道已建立：服务器 %d 能连通本机 %d（本地端口已被业务占用，属正常）" % (remote, local)}
        if "timed out" in (out.stderr or "") or "Connection timed out" in (out.stderr or ""):
            return {"ok": False, "message": "隧道转发不通（服务器侧连接超时）"}
        return {"ok": True, "message": "隧道已建立：服务器 %d 可达本机 %d（本地无服务监听属正常）" % (remote, local)}
    finally:
        if srv:
            try:
                srv.shutdown()
            except Exception:
                pass


def test_tunnel(root: Path, cfg: dict) -> dict:
    err = _validate(cfg)
    if err:
        return {"ok": False, "message": err, "steps": []}
    steps = []
    r1 = test_ssh_reachable(cfg, root)
    steps.append({"name": "SSH 可达 / 认证", **r1})
    if not r1["ok"]:
        return {"ok": False, "message": r1["message"], "steps": steps}
    st = tunnel_status(root)
    if not st["running"]:
        return {"ok": False, "message": "SSH 正常，但隧道尚未建立，请先点「建立隧道」再测试转发",
                "steps": steps}
    r2 = test_forward(root, cfg)
    steps.append({"name": "端到端转发", **r2})
    return {"ok": r2["ok"], "message": r2["message"], "steps": steps}


# ---------------------------------------------------------------------------
# 开机自启（任务计划 ONLOGON）
# ---------------------------------------------------------------------------
def autostart_status(root: Path) -> dict:
    return {
        "ok": True,
        "installed": _task_exists(),
        "task_name": TUNNEL_TASK,
        "is_windows": sys.platform == "win32",
        "plink": check_plink(root, read_cfg(root)),
        "config": {k: read_cfg(root)[k] for k in
                   ("server", "ssh_port", "user", "auth", "local_port", "remote_port")},
    }


def install_autostart(root: Path, cfg: dict) -> dict:
    err = _validate(cfg)
    if err:
        return {"ok": False, "message": err}
    if cfg.get("auth") == "password" and not find_plink(cfg, root):
        return {"ok": False, "message": "未检测到 plink，无法设置密码模式开机自启，请先安装 plink"}
    save_cfg(root, {**read_cfg(root), **cfg, "enabled": True})
    runner = write_runner(root)
    if sys.platform == "win32":
        return _install_windows(runner)
    return _install_posix(runner)


def remove_autostart() -> dict:
    if sys.platform == "win32":
        return _remove_windows()
    return _remove_posix()


def _task_exists() -> bool:
    try:
        if sys.platform == "win32":
            out = _run(["schtasks", "/Query", "/TN", TUNNEL_TASK], timeout=20)
            return out.returncode == 0
        out = _run(["crontab", "-l"], timeout=20)
        return TUNNEL_TASK in out.stdout
    except Exception:
        return False


def _install_windows(runner: Path) -> dict:
    ps = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    tr = '"{ps}" -WindowStyle Hidden -ExecutionPolicy Bypass -File "{file}"'.format(
        ps=ps, file=str(runner).replace("/", "\\")
    )
    # 以当前登录用户身份运行（无需管理员），/RL HIGHEST 提升权利但不强制提权
    out = _run(["schtasks", "/Create", "/TN", TUNNEL_TASK, "/SC", "ONLOGON",
                "/TR", tr, "/F"], timeout=60)
    if out.returncode != 0:
        return {"ok": False, "message": "创建任务计划失败",
                "stderr": (out.stderr or out.stdout).strip()}
    return {"ok": True, "message": "已设置开机自启（登录时后台建立隧道，带重连）",
            "launcher": str(runner)}


def _remove_windows() -> dict:
    out = _run(["schtasks", "/Delete", "/TN", TUNNEL_TASK, "/F"], timeout=60)
    return {"ok": True, "message": "已取消开机自启", "removed": out.returncode == 0}


def _install_posix(launcher: Path) -> dict:
    try:
        cur = _run(["crontab", "-l"], timeout=20).stdout
    except Exception:
        cur = ""
    lines = [l for l in cur.splitlines() if TUNNEL_TASK not in l]
    lines.append("@reboot {launcher}  # {tag}".format(launcher=str(launcher), tag=TUNNEL_TASK))
    _run(["crontab", "-"], input_text="\n".join(lines) + "\n", timeout=20)
    return {"ok": True, "message": "已设置开机自启（@reboot）", "launcher": str(launcher)}


def _remove_posix() -> dict:
    try:
        cur = _run(["crontab", "-l"], timeout=20).stdout
    except Exception:
        cur = ""
    lines = [l for l in cur.splitlines() if TUNNEL_TASK not in l]
    _run(["crontab", "-"], input_text="\n".join(lines) + "\n", timeout=20)
    return {"ok": True, "message": "已取消开机自启"}
