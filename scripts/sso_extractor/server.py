#!/usr/bin/env python3
"""Grok SSO 提取器 UI。

独立小工具，不修改 grok-register 上游代码。仅只读读取
``cpa_auths/*.json``（grok-register 注册产出的凭证），在网页上列出账号、
展示 access_token(SSO Key)，并提供两种导出方式：
  - 复制 SSO Key（手动粘贴到 sub2api 的 SSO Cookie 导入框）
  - 生成 sub2api「批量创建账号」JSON（直存 Grok OAuth token，不经过 x.ai）

启动:
    .venv\\Scripts\\python.exe scripts\\sso_extractor\\server.py
默认监听 http://127.0.0.1:8093
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent  # scripts/sso_extractor -> scripts -> project root
CPA_DIR = PROJECT_ROOT / "cpa_auths"
INDEX_HTML = HERE / "index.html"

# sub2api 的 Grok OAuth 默认上游（SSO token 可直接当 Bearer 使用）
GROK_SUBSCRIPTION_PROXY = "https://cli-chat-proxy.grok.com/v1"

app = FastAPI(title="Grok SSO 提取器", version="1.1")


@app.get("/", include_in_schema=False)
def index():
    if not INDEX_HTML.is_file():
        raise HTTPException(status_code=500, detail="index.html 未找到")
    return FileResponse(INDEX_HTML, headers={"Cache-Control": "no-store"})


def _read_accounts():
    accounts = []
    if CPA_DIR.is_dir():
        for p in sorted(glob.glob(str(CPA_DIR / "xai-*.json"))):
            try:
                data = json.loads(Path(p).read_text(encoding="utf-8"))
            except Exception:
                continue
            # grok-register 不同版本字段名不同：有的用 ISO 字符串 'expired'，有的用 Unix 秒 'expires_at'
            expired_iso = data.get("expired", "")
            if not expired_iso:
                expires_at = data.get("expires_at")
                if expires_at:
                    try:
                        expired_iso = datetime.fromtimestamp(int(expires_at)).isoformat()
                    except Exception:
                        pass
            accounts.append({
                "file": os.path.basename(p),
                "email": data.get("email", ""),
                "base_url": data.get("base_url", ""),
                "access_token": data.get("access_token", ""),
                "refresh_token": data.get("refresh_token", ""),
                "token_type": data.get("token_type", ""),
                "expired": expired_iso,
                "type": data.get("type", ""),
            })
    return accounts


@app.get("/api/accounts", include_in_schema=False)
def list_accounts():
    """读取 cpa_auths/*.json，返回账号列表（仅本地读取，不外发）。"""
    accounts = _read_accounts()
    return {"ok": True, "count": len(accounts), "accounts": accounts}


@app.get("/api/export-sub2api", include_in_schema=False)
def export_sub2api(email: str = None):
    """生成 sub2api「批量创建账号」导入 JSON（Grok OAuth，直存 token，不经过 x.ai）。

    sub2api 的批量创建端点（POST /api/v1/admin/accounts/batch）直接持久化
    credentials，不会触发 x.ai token 交换/SSO 转换，因此可用 SSO token 直接当
    access_token，base_url 用 cli-chat-proxy.grok.com/v1（grok 网页版上游）。

    返回格式严格对齐 sub2api 官方导出：
        {"exported_at": "...", "proxies": [], "accounts": [...]}
    """
    accounts = []
    for data in _read_accounts():
        if email and data.get("email") != email:
            continue
        token = data.get("access_token", "")
        if not token:
            continue
        base_url = data.get("base_url") or GROK_SUBSCRIPTION_PROXY
        name = data.get("email") or data.get("file")
        # sub2api 的 Grok OAuth 账号需要 refresh_token 才能自动刷新，
        # 否则点「同步上游模型/测试连接」会报 "grok oauth refresh token is missing"。
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
            "concurrency": 1,
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
        "exported_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "proxies": [],
        "accounts": accounts,
    }


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8093, workers=1)


if __name__ == "__main__":
    main()
