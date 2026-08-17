#!/usr/bin/env python3
"""Local FastAPI control plane that reuses the existing registration engine."""
from __future__ import annotations

import collections
import datetime
import glob
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

import grok_register_ttk as engine

ROOT = Path(__file__).resolve().parent.parent
from web import tunnel_helper as _tunnel_helper
_tunnel_helper.ROOT_HINT = ROOT  # 让隧道助手校验时能正确定位 tools/plink.exe
INDEX_HTML = Path(__file__).resolve().parent / "index.html"
PROXY_POOL_JS = Path(__file__).resolve().parent / "proxy-pool.js"
PROXY_POOL_CSS = Path(__file__).resolve().parent / "proxy-pool.css"
CPA_DIR = ROOT / "cpa_auths"
SERVER_JSON = ROOT / "server.json"
GROK_SUBSCRIPTION_PROXY = "https://cli-chat-proxy.grok.com/v1"
LOG_LIMIT = 2000

app = FastAPI(title="grok-register WebUI", version="1.2")

_job_lock = threading.Lock()
_job_thread: Optional[threading.Thread] = None
_controller: Any = None
_job_state = {
    "running": False,
    "mode": "idle",
    "target": 0,
    "success": 0,
    "fail": 0,
    "pending": 0,
    "warnings": 0,
    "uncertain": 0,
    "cancelled": False,
    "started_at": None,
    "finished_at": None,
    "accounts_file": "",
    "error": "",
}

_log_lock = threading.Lock()
_log_seq = 0
_logs = collections.deque(maxlen=LOG_LIMIT)


def _append_log(message: str) -> None:
    global _log_seq
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), str(message))
    with _log_lock:
        _log_seq += 1
        _logs.append({"seq": _log_seq, "line": line})


def _state_snapshot() -> dict[str, Any]:
    with _job_lock:
        return dict(_job_state)


def _load_config_if_idle() -> dict[str, Any]:
    with _job_lock:
        if not _job_state["running"]:
            engine.load_config()
        return dict(engine.config)


def _new_accounts_file() -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return str(ROOT / ("accounts_%s.txt" % stamp))


def _update_progress(batch: Any) -> None:
    with _job_lock:
        _job_state["success"] = int(batch.success_count)
        _job_state["fail"] = int(batch.fail_count)
        _job_state["pending"] = int(batch.registered_unsaved_count)
        _job_state["warnings"] = int(batch.postprocess_warning_count)
        _job_state["uncertain"] = int(getattr(batch, "uncertain_count", 0) or 0)
        _job_state["cancelled"] = bool(batch.cancelled)


def _run_job(count: int, controller: Any, accounts_file: str) -> None:
    global _controller
    try:
        batch = engine.run_registration_common(
            count=count,
            log_callback=_append_log,
            cancel_callback=controller.should_stop,
            accounts_output_file=accounts_file,
            observer=lambda batch, _account, _output: _update_progress(batch),
        )
        _update_progress(batch)
    except Exception as exc:
        with _job_lock:
            _job_state["error"] = str(exc)
        _append_log("[!] WebUI 任务异常: %s" % exc)
    finally:
        with _job_lock:
            _job_state["running"] = False
            _job_state["mode"] = "idle"
            _job_state["finished_at"] = time.time()
            _job_state["cancelled"] = bool(
                _job_state["cancelled"] or controller.should_stop()
            )
            _controller = None
        _append_log("[*] WebUI 任务结束")


@app.get("/", include_in_schema=False)
def index():
    html = INDEX_HTML.read_text(encoding="utf-8")
    if PROXY_POOL_CSS.is_file():
        html = html.replace("</head>", '<link rel="stylesheet" href="/proxy-pool.css">\n</head>', 1)
    if PROXY_POOL_JS.is_file():
        html = html.replace("</body>", '<script src="/proxy-pool.js"></script>\n</body>', 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/proxy-pool.js", include_in_schema=False)
def proxy_pool_js():
    return FileResponse(PROXY_POOL_JS, media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.get("/proxy-pool.css", include_in_schema=False)
def proxy_pool_css():
    return FileResponse(PROXY_POOL_CSS, media_type="text/css", headers={"Cache-Control": "no-store"})


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/server/config")
def get_server_config():
    return {"ok": True, "config": _load_server_json()}


@app.put("/api/server/config")
async def put_server_config(request: Request):
    data = await request.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="服务器配置必须是 JSON 对象")
    current = _load_server_json()
    host = str(data.get("host", current["host"])).strip()
    try:
        port = int(data.get("port", current["port"]))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="端口必须是整数") from exc
    try:
        workers = max(1, int(data.get("workers", current["workers"])))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="workers 必须是整数") from exc
    if not host:
        raise HTTPException(status_code=400, detail="监听地址不能为空")
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail="端口必须在 1–65535 之间")
    updated = {"host": host, "port": port, "workers": workers}
    try:
        _save_server_json(updated)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="保存服务器配置失败: %s" % exc) from exc
    return {"ok": True, "config": updated}


@app.post("/api/server/restart")
def restart_server(background_tasks: BackgroundTasks):
    import subprocess
    import sys

    cfg = _load_server_json()
    helper = [sys.executable, "-m", "web.restart_helper",
              "--python", sys.executable,
              "--cwd", str(ROOT),
              "--host", cfg["host"],
              "--port", str(cfg["port"]),
              "--workers", str(cfg["workers"])]
    try:
        subprocess.Popen(
            helper,
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                           | getattr(subprocess, "DETACHED_PROCESS", 0)),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="启动重启助手失败: %s" % exc) from exc

    def _exit_after_delay():
        time.sleep(2)
        os._exit(0)

    background_tasks.add_task(_exit_after_delay)
    return {"ok": True, "message": "服务正在重启到 %s:%d" % (cfg["host"], cfg["port"])}


@app.get("/api/server/autostart")
def get_autostart_status():
    from web import autostart_helper as ah
    return ah.autostart_status(ROOT)


@app.post("/api/server/autostart/install")
def install_autostart():
    from web import autostart_helper as ah
    try:
        result = ah.install_task(ROOT)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="设置开机自启失败: %s" % exc) from exc
    return {"ok": result.get("ok", False), "message": result.get("message", ""), "detail": result}


@app.post("/api/server/autostart/remove")
def remove_autostart():
    from web import autostart_helper as ah
    try:
        result = ah.remove_task()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="取消开机自启失败: %s" % exc) from exc
    return {"ok": result.get("ok", False), "message": result.get("message", ""), "detail": result}


# ---------------------------------------------------------------------------
# 隧道（永久反向 SSH 隧道）API
# ---------------------------------------------------------------------------
@app.get("/api/tunnel/config")
def get_tunnel_config():
    from web import tunnel_helper as th
    cfg = th.read_cfg(ROOT)
    # 不原样回吐敏感字段，改为"是否已设置"标记
    return {
        "ok": True,
        "config": cfg,
        "key_pass_set": bool(cfg.get("key_pass")),
        "password_set": bool(cfg.get("password")),
        "status": th.tunnel_status(ROOT),
    }


@app.put("/api/tunnel/config")
def put_tunnel_config(payload: dict):
    from web import tunnel_helper as th
    existing = th.read_cfg(ROOT)
    new = dict(payload or {})
    # 密码/私钥密码留空则保留原有的（避免误清空）
    if not str(new.get("key_pass", "")).strip():
        new["key_pass"] = existing.get("key_pass", "")
    if not str(new.get("password", "")).strip():
        new["password"] = existing.get("password", "")
    cfg = th.save_cfg(ROOT, new)
    return {"ok": True, "config": cfg,
            "key_pass_set": bool(cfg.get("key_pass")),
            "password_set": bool(cfg.get("password"))}


@app.post("/api/tunnel/start")
def start_tunnel():
    from web import tunnel_helper as th
    cfg = th.read_cfg(ROOT)
    _append_log("[*] 收到建立隧道请求: %s@%s:%s" % (cfg.get("user"), cfg.get("server"), cfg.get("ssh_port")))
    try:
        result = th.start_tunnel(ROOT, cfg)
        _append_log("[*] 建立隧道结果: %s" % json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        _append_log("[!] 建立隧道失败: %s" % exc)
        raise HTTPException(status_code=500, detail="建立隧道失败: %s" % exc) from exc
    return result


@app.post("/api/tunnel/stop")
def stop_tunnel():
    from web import tunnel_helper as th
    _append_log("[*] 收到停止隧道请求")
    try:
        result = th.stop_tunnel(ROOT)
        _append_log("[*] 停止隧道结果: %s" % json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        _append_log("[!] 停止隧道失败: %s" % exc)
        raise HTTPException(status_code=500, detail="停止隧道失败: %s" % exc) from exc
    return result


@app.get("/api/tunnel/status")
def tunnel_status_api():
    from web import tunnel_helper as th
    return th.tunnel_status(ROOT)


@app.post("/api/tunnel/test")
def test_tunnel():
    from web import tunnel_helper as th
    cfg = th.read_cfg(ROOT)
    _append_log("[*] 收到隧道连通性测试: %s@%s:%s" % (cfg.get("user"), cfg.get("server"), cfg.get("ssh_port")))
    try:
        result = th.test_tunnel(ROOT, cfg)
        _append_log("[*] 隧道测试结果: %s" % json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        _append_log("[!] 隧道测试失败: %s" % exc)
        raise HTTPException(status_code=500, detail="隧道测试失败: %s" % exc) from exc
    return result


@app.get("/api/tunnel/autostart")
def get_tunnel_autostart():
    from web import tunnel_helper as th
    return th.autostart_status(ROOT)


@app.post("/api/tunnel/autostart/install")
def install_tunnel_autostart():
    from web import tunnel_helper as th
    cfg = th.read_cfg(ROOT)
    _append_log("[*] 收到设置隧道开机自启请求: %s@%s:%s" % (cfg.get("user"), cfg.get("server"), cfg.get("ssh_port")))
    try:
        result = th.install_autostart(ROOT, cfg)
    except Exception as exc:
        _append_log("[!] 设置隧道开机自启失败: %s" % exc)
        raise HTTPException(status_code=500, detail="设置隧道开机自启失败: %s" % exc) from exc
    if result.get("ok"):
        _append_log("[*] %s" % result.get("message"))
    else:
        _append_log("[!] 设置隧道开机自启失败: %s" % result.get("message"))
    return {"ok": result.get("ok", False), "message": result.get("message", ""), "detail": result}


@app.post("/api/tunnel/autostart/remove")
def remove_tunnel_autostart():
    from web import tunnel_helper as th
    _append_log("[*] 收到取消隧道开机自启请求")
    try:
        result = th.remove_autostart()
    except Exception as exc:
        _append_log("[!] 取消隧道开机自启失败: %s" % exc)
        raise HTTPException(status_code=500, detail="取消隧道开机自启失败: %s" % exc) from exc
    _append_log("[*] %s" % result.get("message"))
    return {"ok": result.get("ok", False), "message": result.get("message", ""), "detail": result}


@app.get("/api/tunnel/plink")
def tunnel_plink(action: str = ""):
    from web import tunnel_helper as th
    th.ROOT_HINT = ROOT
    if action == "download":
        try:
            path = th.download_plink(ROOT)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="下载 plink 失败: %s" % exc) from exc
        return {"ok": True, "path": path, "info": th.check_plink(ROOT, th.read_cfg(ROOT))}
    return {"ok": True, "info": th.check_plink(ROOT, th.read_cfg(ROOT))}


@app.get("/api/config")
def get_config():
    return {"ok": True, "config": _load_config_if_idle()}


@app.put("/api/config")
async def put_config(request: Request):
    updates = await request.json()
    if not isinstance(updates, dict):
        raise HTTPException(status_code=400, detail="配置更新必须是 JSON 对象")

    allowed = set(engine.DEFAULT_CONFIG)
    unknown = sorted(set(updates) - allowed)
    if unknown:
        raise HTTPException(status_code=400, detail="未知配置项: " + ", ".join(unknown))

    with _job_lock:
        if _job_state["running"]:
            raise HTTPException(status_code=409, detail="任务运行期间不能修改配置")
        engine.load_config()
        candidate = dict(engine.config)
        candidate.update(updates)
        try:
            validated = engine.validate_run_requirements(candidate)
        except engine.ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        engine.config.clear()
        engine.config.update(validated)
        engine.save_config()
        result = dict(engine.config)
    return {"ok": True, "config": result}


@app.get("/api/proxy-pool/status")
def proxy_pool_status():
    from proxy_pool import manager_snapshot
    cfg = _load_config_if_idle()
    return {"ok": True, **manager_snapshot(config=cfg)}


@app.post("/api/proxy-pool/reload")
def proxy_pool_reload():
    from proxy_pool import get_manager
    with _job_lock:
        if _job_state["running"]:
            raise HTTPException(status_code=409, detail="任务运行期间不能重新加载代理池")
        engine.load_config()
        try:
            cfg = engine.validate_config_structure(dict(engine.config))
            manager = get_manager(config=cfg, log=_append_log)
            snapshot = manager.reload_sources(force=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    _append_log("[*] 代理池已重新加载")
    return {"ok": True, **snapshot}


@app.post("/api/proxy-pool/test")
def proxy_pool_test():
    from proxy_pool import get_manager
    with _job_lock:
        if _job_state["running"]:
            raise HTTPException(status_code=409, detail="任务运行期间不能手动测试代理池")
        engine.load_config()
        try:
            cfg = engine.validate_config_structure(dict(engine.config))
            manager = get_manager(config=cfg, log=_append_log)
            manager.reload_sources(force=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    results = manager.probe_all(force=True)
    _append_log("[*] 代理池测试完成: %s 个节点" % len(results))
    return {"ok": True, "results": results, **manager.snapshot()}


@app.post("/api/proxy-pool/preflight")
def proxy_pool_preflight(node_id: str = Query(..., min_length=1)):
    from proxy_pool import get_manager
    with _job_lock:
        if _job_state["running"]:
            raise HTTPException(status_code=409, detail="任务运行期间不能执行注册路径预检")
        engine.load_config()
        try:
            cfg = engine.validate_config_structure(dict(engine.config))
            if not cfg.get("proxy_pool_preflight_enabled", True):
                raise HTTPException(status_code=409, detail="注册路径预检已在配置中关闭")
            manager = get_manager(config=cfg, log=_append_log)
            result = manager.preflight_node(node_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    _append_log("[*] 代理节点注册路径预检完成: %s" % node_id)
    return {"ok": True, "result": result, **manager.snapshot()}


@app.get("/api/status")
def status():
    return {"ok": True, **_state_snapshot()}


@app.get("/api/logs")
def logs(after: int = Query(default=0, ge=0)):
    with _log_lock:
        entries = [dict(item) for item in _logs if int(item["seq"]) > int(after)]
        latest = int(_log_seq)
    return {"ok": True, "latest": latest, "entries": entries}


def _load_server_json() -> dict[str, Any]:
    defaults = {"host": "127.0.0.1", "port": 8092, "workers": 1}
    if SERVER_JSON.is_file():
        try:
            data = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in defaults:
                    if k in data:
                        defaults[k] = data[k]
        except Exception:
            pass
    return defaults


def _save_server_json(data: dict[str, Any]) -> dict[str, Any]:
    clean = {
        "host": str(data.get("host", "127.0.0.1")).strip(),
        "port": int(data.get("port", 8092)),
        "workers": max(1, int(data.get("workers", 1))),
    }
    if not clean["host"]:
        clean["host"] = "127.0.0.1"
    SERVER_JSON.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    return clean


def _parse_expiry(value) -> Optional[datetime.datetime]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(int(value))
        except Exception:
            return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(text)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _is_expired(data: dict) -> bool:
    expiry = _parse_expiry(data.get("expired"))
    if expiry is None:
        expiry = _parse_expiry(data.get("expires_at"))
    if expiry is None:
        return False
    now = datetime.datetime.now(datetime.timezone.utc if expiry.tzinfo else None)
    return expiry <= now


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _sub2api_account_expiry(a: dict) -> Optional[datetime.datetime]:
    """返回账号最紧迫的过期时间（顶层 expires_at 或 credentials.expires_at）。"""
    for key in ("expires_at",):
        exp = _parse_expiry(a.get(key))
        if exp:
            return exp
    creds = a.get("credentials") or {}
    return _parse_expiry(creds.get("expires_at"))


def _sub2api_is_temporarily_blocked(a: dict, now: Optional[datetime.datetime] = None) -> bool:
    """是否处于临时不可调度窗口。"""
    now = now or _utc_now()
    for key in ("temp_unschedulable_until", "overload_until", "rate_limit_reset_at"):
        t = _parse_expiry(a.get(key))
        if t and now < t:
            return True
    return False


def _sub2api_is_available(a: dict, now: Optional[datetime.datetime] = None) -> bool:
    """sub2api 账号是否当前可用（status active、schedulable、未过期、未被临时封禁）。"""
    now = now or _utc_now()
    if (a.get("status") or "").lower() != "active":
        return False
    if a.get("schedulable") is False and not _sub2api_is_temporarily_blocked(a, now):
        return False
    exp = _sub2api_account_expiry(a)
    if exp and now >= exp:
        return False
    if _sub2api_is_temporarily_blocked(a, now):
        return False
    return True


def _sub2api_is_expired_for_purge(a: dict, now: Optional[datetime.datetime] = None) -> bool:
    """判断账号是否应从 sub2api 中删除。"""
    now = now or _utc_now()
    status = (a.get("status") or "").lower()
    if status in ("expired", "banned", "invalid", "disabled", "deleted"):
        return True
    if a.get("schedulable") is False and not _sub2api_is_temporarily_blocked(a, now):
        return True
    exp = _sub2api_account_expiry(a)
    if exp and now >= exp:
        return True
    return False


def _read_sso_accounts():
    accounts = []
    if CPA_DIR.is_dir():
        for p in sorted(glob.glob(str(CPA_DIR / "xai-*.json"))):
            try:
                data = json.loads(Path(p).read_text(encoding="utf-8"))
            except Exception:
                continue
            expired_iso = data.get("expired", "")
            if not expired_iso:
                expires_at = data.get("expires_at")
                if expires_at:
                    try:
                        expired_iso = datetime.datetime.fromtimestamp(int(expires_at)).isoformat()
                    except Exception:
                        pass
            account = {
                "file": os.path.basename(p),
                "email": data.get("email", ""),
                "base_url": data.get("base_url", ""),
                "access_token": data.get("access_token", ""),
                "refresh_token": data.get("refresh_token", ""),
                "token_type": data.get("token_type", ""),
                "expired": expired_iso,
                "type": data.get("type", ""),
            }
            if not _is_expired(account):
                accounts.append(account)
    return accounts


@app.get("/api/sso/accounts")
def sso_accounts():
    accounts = _read_sso_accounts()
    return {"ok": True, "count": len(accounts), "accounts": accounts}


@app.get("/api/sso/export-sub2api")
def sso_export_sub2api(email: Optional[str] = None):
    accounts = []
    concurrency = int(engine.config.get("sub2api_account_concurrency") or 1)
    for data in _read_sso_accounts():
        if email and data.get("email") != email:
            continue
        token = data.get("access_token", "")
        if not token:
            continue
        base_url = data.get("base_url") or GROK_SUBSCRIPTION_PROXY
        name = data.get("email") or data.get("file")
        credentials = {
            "access_token": token,
            "base_url": base_url,
            "model_mapping": {},
        }
        if data.get("refresh_token"):
            credentials["refresh_token"] = data["refresh_token"]
        if data.get("token_type"):
            credentials["token_type"] = data["token_type"]
        if data.get("expired"):
            credentials["expires_at"] = data["expired"]
        accounts.append({
            "name": name,
            "notes": "grok-register SSO token",
            "platform": "grok",
            "type": "oauth",
            "credentials": credentials,
            "extra": {},
            "concurrency": max(1, concurrency),
            "priority": 0,
            "rate_multiplier": 1,
            "auto_pause_on_expired": True,
        })
    if not accounts:
        raise HTTPException(
            status_code=404,
            detail="没有可用的 SSO 账号（cpa_auths/ 为空或无 access_token）",
        )
    return {
        "exported_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "proxies": [],
        "accounts": accounts,
    }


@app.post("/api/start")
def start():
    global _job_thread, _controller

    with _job_lock:
        if _job_state["running"]:
            raise HTTPException(status_code=409, detail="已有注册任务正在运行")

        engine.load_config()
        try:
            validated = engine.validate_run_requirements(dict(engine.config))
        except engine.ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        engine.config.clear()
        engine.config.update(validated)

        count = int(engine.config["register_count"])
        controller = engine.CliStopController()
        accounts_file = _new_accounts_file()

        _job_state.update({
            "running": True,
            "mode": "register",
            "target": count,
            "success": 0,
            "fail": 0,
            "pending": 0,
            "warnings": 0,
            "uncertain": 0,
            "cancelled": False,
            "started_at": time.time(),
            "finished_at": None,
            "accounts_file": accounts_file,
            "error": "",
        })
        _controller = controller
        thread = threading.Thread(
            target=_run_job,
            args=(count, controller, accounts_file),
            name="grok-register-web-job",
            daemon=True,
        )
        _job_thread = thread
        try:
            thread.start()
        except Exception:
            _job_state["running"] = False
            _job_state["finished_at"] = time.time()
            _controller = None
            _job_thread = None
            raise

    _append_log("[*] WebUI 启动注册任务，目标数量: %s" % count)
    return {"ok": True, "started": True, "target": count, "accounts_file": accounts_file}


@app.post("/api/stop")
def stop():
    with _job_lock:
        controller = _controller
        running = bool(_job_state["running"])
    if not running or controller is None:
        return {"ok": True, "stopped": False}
    controller.stop()
    _append_log("[!] WebUI 已发送停止请求")
    return {"ok": True, "stopped": True}


def main() -> None:
    import argparse
    import uvicorn

    defaults = _load_server_json()
    parser = argparse.ArgumentParser(description="grok-register WebUI 服务")
    parser.add_argument("--host", default=defaults.get("host", "127.0.0.1"), help="监听地址 (默认 127.0.0.1)")
    parser.add_argument("--port", type=int, default=defaults.get("port", 8092), help="监听端口 (默认 8092)")
    parser.add_argument("--workers", type=int, default=defaults.get("workers", 1), help="worker 数量 (默认 1)")
    args = parser.parse_args()
    uvicorn.run("web.server:app", host=args.host, port=args.port, workers=args.workers)


# ---------------------------------------------------------------------------
# sub2api 自动同步（账号池）
# ---------------------------------------------------------------------------
_SUB2API_KEYS = (
    "sub2api_base_url", "sub2api_email", "sub2api_password",
    "sub2api_group_id", "sub2api_auto_sync", "sub2api_sync_interval_sec",
    "sub2api_proxy_key", "sub2api_proxy_id", "sub2api_grok_model",
    "sub2api_target_available", "sub2api_max_register_batch",
    "sub2api_pool_check_interval_sec", "sub2api_account_concurrency",
)
_SUB2API_DEFAULT_PROXY_KEY = "http|127.0.0.1|10808||"


def _sub2api_cfg() -> dict:
    c = engine.config
    return {
        "base_url": (c.get("sub2api_base_url") or "").strip().rstrip("/"),
        "email": (c.get("sub2api_email") or "").strip(),
        "password": c.get("sub2api_password") or "",
        "group_id": int(c.get("sub2api_group_id") or 8),
        "auto_sync": bool(c.get("sub2api_auto_sync", False)),
        "interval": int(c.get("sub2api_sync_interval_sec") or 3600),
        "proxy_key": (c.get("sub2api_proxy_key") or _SUB2API_DEFAULT_PROXY_KEY).strip(),
        "proxy_id": int(c.get("sub2api_proxy_id") or 0),
        "model": (c.get("sub2api_grok_model") or "grok-4.6").strip(),
        "target_available": int(c.get("sub2api_target_available") or 0),
        "max_register_batch": max(1, int(c.get("sub2api_max_register_batch") or 5)),
        "pool_check_interval": max(60, int(c.get("sub2api_pool_check_interval_sec") or 300)),
        "concurrency": max(1, int(c.get("sub2api_account_concurrency") or 1)),
    }


def _http_json(method: str, url: str, token: Optional[str] = None, body: Any = None, timeout: int = 25):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def _sub2api_login(cfg: dict) -> str:
    s, b = _http_json("POST", cfg["base_url"] + "/api/v1/auth/login",
                      body={"email": cfg["email"], "password": cfg["password"]})
    if s != 200:
        raise RuntimeError("sub2api 登录失败 HTTP %s: %s" % (s, b[:160]))
    return json.loads(b)["data"]["access_token"]


def _sub2api_list_grok(token: str, base: str) -> list:
    # 必须翻页拉全，否则只拿到默认前 20 条，导致后续账号匹配不到被反复当作新账号导入（重复雪球）
    items = []
    page, page_size = 1, 200
    while True:
        url = base + "/api/v1/admin/accounts?platform=grok&page=%d&page_size=%d" % (page, page_size)
        s, b = _http_json("GET", url, token=token)
        if s != 200:
            raise RuntimeError("列出 grok 账号失败 HTTP %s: %s" % (s, b[:160]))
        data = json.loads(b).get("data", {})
        chunk = data.get("items", [])
        items.extend(chunk)
        total = data.get("total")
        if not chunk or (total is not None and len(items) >= total) or len(chunk) < page_size:
            break
        page += 1
    return items


def _sub2api_import_one(acc: dict, base: str, token: str, proxy_key: str,
                        proxy_id: int = 0, model: str = "grok-4.6", concurrency: int = 1):
    creds = {"access_token": acc["access_token"], "base_url": acc["base_url"] or GROK_SUBSCRIPTION_PROXY}
    if acc.get("refresh_token"):
        creds["refresh_token"] = acc["refresh_token"]
    if acc.get("token_type"):
        creds["token_type"] = acc["token_type"]
    if acc.get("expired"):
        creds["expires_at"] = acc["expired"]
    creds["model_mapping"] = {model: model}
    account_payload = {
        "name": acc["email"] or acc["file"],
        "notes": "grok-register SSO token",
        "platform": "grok", "type": "oauth",
        "credentials": creds,
        "proxy_key": proxy_key,
        "concurrency": max(1, int(concurrency or 1)), "priority": 1, "rate_multiplier": 1,
        "auto_pause_on_expired": True,
    }
    if proxy_id:
        account_payload["proxy_id"] = int(proxy_id)
    payload = {"accounts": [account_payload]}
    s, b = _http_json("POST", base + "/api/v1/admin/accounts/batch", token=token, body=payload)
    if s != 200:
        raise RuntimeError("导入账号失败 HTTP %s: %s" % (s, b[:160]))
    for r in json.loads(b).get("data", {}).get("results", []):
        if r.get("success"):
            return r.get("id")
    return None


def _sub2api_update_account(acc_id, group_id, base: str, token: str, proxy_id: int = 0):
    body = {"group_ids": [int(group_id)]}
    if proxy_id:
        body["proxy_id"] = int(proxy_id)
    _http_json("PUT", base + "/api/v1/admin/accounts/%d" % int(acc_id),
               token=token, body=body)


def _sub2api_set_model(acc_id, model: str, base: str, token: str):
    # PUT 为合并语义，仅补 model_mapping，不破坏已有 credentials
    _http_json("PUT", base + "/api/v1/admin/accounts/%d" % int(acc_id),
               token=token, body={"credentials": {"model_mapping": {model: model}}})


def _sub2api_delete(acc_id, base: str, token: str):
    _http_json("DELETE", base + "/api/v1/admin/accounts/%d" % int(acc_id), token=token)


def _sso_sync_once() -> dict:
    cfg = _sub2api_cfg()
    if not cfg["base_url"] or not cfg["email"] or not cfg["password"]:
        return {"ok": False, "reason": "sub2api 未配置（缺少地址/邮箱/密码）"}
    try:
        token = _sub2api_login(cfg)
        local = _read_sso_accounts()  # 已过滤过期
        remote = _sub2api_list_grok(token, cfg["base_url"])
        remote_by_name = {}
        for a in remote:
            remote_by_name.setdefault(a.get("name"), []).append(a)
        added = linked = modeled = 0
        for acc in local:
            name = acc["email"] or acc["file"]
            matched = remote_by_name.get(name)
            if matched:
                for a in matched:
                    _sub2api_update_account(a["id"], cfg["group_id"], cfg["base_url"], token, cfg["proxy_id"])
                    linked += 1
                    # 已存在但缺模型的，自动补上（合并 PUT，不动 token）
                    if not (a.get("credentials") or {}).get("model_mapping"):
                        _sub2api_set_model(a["id"], cfg["model"], cfg["base_url"], token)
                        modeled += 1
            else:
                new_id = _sub2api_import_one(acc, cfg["base_url"], token, cfg["proxy_key"],
                                             cfg["proxy_id"], cfg["model"], cfg.get("concurrency", 1))
                if new_id:
                    _sub2api_update_account(new_id, cfg["group_id"], cfg["base_url"], token, cfg["proxy_id"])
                    added += 1
                    # 回填匹配表，防止 local 万一有重复 email 时本轮后续再次新建
                    remote_by_name.setdefault(name, []).append({"id": new_id})
        deleted = 0
        now = _utc_now()
        for a in remote:
            if _sub2api_is_expired_for_purge(a, now):
                _sub2api_delete(a["id"], cfg["base_url"], token)
                deleted += 1
        available = sum(1 for a in remote if cfg["group_id"] in (a.get("group_ids") or []) and _sub2api_is_available(a, now))
        return {"ok": True, "added": added, "linked": linked, "modeled": modeled, "deleted": deleted,
                "local": len(local), "remote_total": len(remote), "available": available,
                "target": cfg["target_available"]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc)}


def _run_fill_job(need: int, controller: Any, accounts_file: str) -> None:
    global _controller
    try:
        _append_log("[*] 智能补充开始注册 %d 个账号" % need)
        batch = engine.run_registration_common(
            count=need,
            log_callback=_append_log,
            cancel_callback=controller.should_stop,
            accounts_output_file=accounts_file,
            observer=lambda batch, _account, _output: _update_progress(batch),
        )
        _update_progress(batch)
        _append_log("[*] 智能补充注册完成，成功 %d / 失败 %d" % (batch.success_count, batch.fail_count))
        _append_log("[*] 智能补充开始同步到 sub2api")
        res = _sso_sync_once()
        _append_log("[*] 智能补充同步结果: %s" % json.dumps(res, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        with _job_lock:
            _job_state["error"] = str(exc)
        _append_log("[!] 智能补充任务异常: %s" % exc)
    finally:
        with _job_lock:
            _job_state["running"] = False
            _job_state["mode"] = "idle"
            _job_state["finished_at"] = time.time()
            _job_state["cancelled"] = bool(
                _job_state["cancelled"] or controller.should_stop()
            )
            _controller = None
        _append_log("[*] 智能补充任务结束")


def _sub2api_fill_once() -> dict:
    global _controller
    cfg = _sub2api_cfg()
    if not cfg["target_available"]:
        return {"ok": True, "reason": "target_available=0，未启用智能补充"}
    if not cfg["base_url"] or not cfg["email"] or not cfg["password"]:
        return {"ok": False, "reason": "sub2api 未配置（缺少地址/邮箱/密码）"}

    sync_res = _sso_sync_once()
    if not sync_res.get("ok"):
        return sync_res

    available = int(sync_res.get("available", 0))
    target = cfg["target_available"]
    need = max(0, target - available)
    if need <= 0:
        return {"ok": True, "filled": 0, "available": available, "target": target,
                "reason": "已达目标，无需补充"}

    need = min(need, cfg["max_register_batch"])

    with _job_lock:
        if _job_state["running"]:
            return {"ok": True, "filled": 0, "available": available, "target": target,
                    "reason": "已有任务运行中，本次不补充"}
        engine.load_config()
        try:
            validated = engine.validate_run_requirements(dict(engine.config))
        except engine.ConfigError as exc:
            return {"ok": False, "reason": str(exc)}
        engine.config.clear()
        engine.config.update(validated)

        controller = engine.CliStopController()
        accounts_file = _new_accounts_file()
        _job_state.update({
            "running": True,
            "mode": "smart_fill",
            "target": need,
            "success": 0,
            "fail": 0,
            "pending": 0,
            "warnings": 0,
            "cancelled": False,
            "started_at": time.time(),
            "finished_at": None,
            "accounts_file": accounts_file,
            "error": "",
        })
        _controller = controller
        thread = threading.Thread(
            target=_run_fill_job,
            args=(need, controller, accounts_file),
            name="grok-register-smart-fill",
            daemon=True,
        )
        global _job_thread
        _job_thread = thread
        try:
            thread.start()
        except Exception:
            with _job_lock:
                _job_state["running"] = False
                _job_state["finished_at"] = time.time()
                _controller = None
                _job_thread = None
            raise
    return {"ok": True, "filled": need, "available": available, "target": target,
            "reason": "已启动智能补充"}


def _sub2api_pool_status() -> dict:
    cfg = _sub2api_cfg()
    if not cfg["base_url"] or not cfg["email"] or not cfg["password"]:
        return {"ok": False, "reason": "sub2api 未配置"}
    try:
        token = _sub2api_login(cfg)
        remote = _sub2api_list_grok(token, cfg["base_url"])
        now = _utc_now()
        group_id = cfg["group_id"]
        in_group = [a for a in remote if group_id in (a.get("group_ids") or [])]
        available = sum(1 for a in in_group if _sub2api_is_available(a, now))
        expired = sum(1 for a in in_group if _sub2api_is_expired_for_purge(a, now))
        return {
            "ok": True,
            "target": cfg["target_available"],
            "max_batch": cfg["max_register_batch"],
            "available": available,
            "total": len(in_group),
            "expired": expired,
            "gap": max(0, cfg["target_available"] - available),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc)}


def _proxy_key_from_proxy(p: dict) -> str:
    return "%s|%s|%s|%s|%s" % (
        p.get("protocol") or "http",
        p.get("host") or "",
        p.get("port") or "",
        p.get("username") or "",
        p.get("password") or "",
    )


def _sub2api_discover(base_url: str, email: str, password: str) -> dict:
    base = base_url.rstrip("/")
    token = _sub2api_login({"base_url": base, "email": email, "password": password})

    def get_items(ep: str) -> list:
        s, b = _http_json("GET", base + ep, token=token)
        if s != 200:
            raise RuntimeError("读取 %s 失败 HTTP %s: %s" % (ep, s, b[:160]))
        return json.loads(b).get("data", {}).get("items", [])

    groups = get_items("/api/v1/admin/groups")
    proxies = get_items("/api/v1/admin/proxies")
    channels = get_items("/api/v1/admin/channels")

    grok_groups = [g for g in groups if (g.get("platform") or "").lower() == "grok"]
    suggested_group = grok_groups[0] if grok_groups else (groups[0] if groups else None)
    group_id = suggested_group["id"] if suggested_group else None

    active_proxies = [p for p in proxies if (p.get("status") or "").lower() == "active"]
    if not active_proxies:
        active_proxies = proxies
    pref = [p for p in active_proxies if p.get("host") == "127.0.0.1" and str(p.get("port")) == "10808"]
    suggested_proxy = pref[0] if pref else (active_proxies[0] if active_proxies else None)
    proxy_key = _proxy_key_from_proxy(suggested_proxy) if suggested_proxy else _SUB2API_DEFAULT_PROXY_KEY
    proxy_id = suggested_proxy.get("id") if suggested_proxy else None

    models = []
    if group_id:
        for ch in channels:
            if group_id in (ch.get("group_ids") or []):
                for plat_map in (ch.get("model_mapping") or {}).values():
                    if isinstance(plat_map, dict):
                        models.extend(plat_map.keys())
    if not models:
        for ch in channels:
            mapping = ch.get("model_mapping") or {}
            for plat, plat_map in mapping.items():
                if isinstance(plat_map, dict) and "grok" in str(plat).lower():
                    models.extend(plat_map.keys())
    model = "grok-4.6" if "grok-4.6" in models else (models[0] if models else "grok-4.6")

    return {
        "ok": True,
        "groups": [{"id": g.get("id"), "name": g.get("name"), "platform": g.get("platform")} for g in groups],
        "proxies": [{"id": p.get("id"), "name": p.get("name"), "protocol": p.get("protocol"),
                     "host": p.get("host"), "port": p.get("port"), "status": p.get("status")} for p in proxies],
        "models": models,
        "suggested": {
            "group_id": group_id,
            "proxy_id": proxy_id,
            "proxy_key": proxy_key,
            "model": model,
        },
    }


@app.post("/api/sso/discover-sub2api")
async def discover_sub2api(request: Request):
    body = await request.json()
    base = (body.get("base_url") or "").strip()
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    if not base or not email:
        return {"ok": False, "reason": "sub2api 地址和邮箱不能为空"}
    # 前端保存后会清空密码框；若未填写，尝试用本地已保存的密码
    if not password:
        password = engine.config.get("sub2api_password") or ""
    if not password:
        return {"ok": False, "reason": "未填写密码且本地无已保存密码，请先填写或保存配置"}
    try:
        return _sub2api_discover(base, email, password)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc)}


@app.get("/api/sso/sub2api-config")
def get_sub2api_config():
    c = engine.config
    return {"ok": True, "config": {
        "sub2api_base_url": c.get("sub2api_base_url", ""),
        "sub2api_email": c.get("sub2api_email", ""),
        "sub2api_group_id": int(c.get("sub2api_group_id") or 8),
        "sub2api_proxy_key": c.get("sub2api_proxy_key", _SUB2API_DEFAULT_PROXY_KEY),
        "sub2api_proxy_id": int(c.get("sub2api_proxy_id") or 0),
        "sub2api_grok_model": c.get("sub2api_grok_model", "grok-4.6"),
        "sub2api_auto_sync": bool(c.get("sub2api_auto_sync", False)),
        "sub2api_sync_interval_sec": int(c.get("sub2api_sync_interval_sec") or 3600),
        "sub2api_target_available": int(c.get("sub2api_target_available") or 0),
        "sub2api_max_register_batch": int(c.get("sub2api_max_register_batch") or 5),
        "sub2api_pool_check_interval_sec": int(c.get("sub2api_pool_check_interval_sec") or 300),
        "sub2api_account_concurrency": max(1, int(c.get("sub2api_account_concurrency") or 1)),
        "password_set": bool(c.get("sub2api_password")),
    }}


@app.put("/api/sso/sub2api-config")
async def put_sub2api_config(request: Request):
    updates = await request.json()
    bad = set(updates) - set(_SUB2API_KEYS)
    if bad:
        raise HTTPException(status_code=400, detail="未知配置项: " + ", ".join(bad))
    int_keys = {
        "sub2api_group_id", "sub2api_sync_interval_sec",
        "sub2api_target_available", "sub2api_max_register_batch",
        "sub2api_pool_check_interval_sec", "sub2api_account_concurrency",
        "sub2api_proxy_id",
    }
    bool_keys = {"sub2api_auto_sync"}
    for k, v in updates.items():
        if k == "sub2api_password":
            if not v or v == "********":
                continue  # 不修改
            engine.config[k] = str(v)
        elif k in int_keys:
            engine.config[k] = int(v)
        elif k in bool_keys:
            engine.config[k] = bool(v)
        else:
            engine.config[k] = str(v)
    engine.save_config()
    return {"ok": True, "config": {k: engine.config.get(k) for k in _SUB2API_KEYS}}


@app.post("/api/sso/sync-sub2api")
def sync_sub2api():
    return _sso_sync_once()


@app.get("/api/sso/pool-status")
def pool_status():
    return _sub2api_pool_status()


@app.post("/api/sso/pool-fill")
def pool_fill():
    return _sub2api_fill_once()


# ---- 后台定时同步 ----
_sync_thread: Optional[threading.Thread] = None


def _sub2api_sync_loop():
    while True:
        cfg = _sub2api_cfg()
        interval = min(cfg["interval"], cfg["pool_check_interval"])
        time.sleep(max(60, interval))
        if not _sub2api_cfg()["auto_sync"]:
            continue
        try:
            if _sub2api_cfg()["target_available"]:
                res = _sub2api_fill_once()
                _append_log("[*] sub2api 智能池维护: %s" % json.dumps(res, ensure_ascii=False))
            else:
                res = _sso_sync_once()
                _append_log("[*] sub2api 定时同步完成: %s" % json.dumps(res, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            _append_log("[!] sub2api 定时同步异常: %s" % exc)


@app.on_event("startup")
def _startup_sub2api_sync():
    global _sync_thread
    try:
        engine.load_config()
    except Exception:
        pass
    if _sync_thread and _sync_thread.is_alive():
        return
    _sync_thread = threading.Thread(target=_sub2api_sync_loop, name="sub2api-sync", daemon=True)
    _sync_thread.start()
    _append_log("[*] sub2api 定时同步线程已启动")


if __name__ == "__main__":
    main()
