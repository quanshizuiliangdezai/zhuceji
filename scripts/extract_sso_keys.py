#!/usr/bin/env python3
"""从 grok-register 生成的 CPA 凭证中提取 Grok Web SSO Key(access_token)。

用法:
    .venv\Scripts\python.exe scripts\extract_sso_keys.py

输出到控制台，复制 SSO Key 后粘贴到 sub2api 的「SSO Cookie 导入」框。
"""
import json
import glob
import os
import sys

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pattern = os.path.join(base_dir, "cpa_auths", "xai-*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        print("未找到 cpa_auths/xai-*.json 文件", file=sys.stderr)
        sys.exit(1)

    for p in files:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        email = data.get("email", "")
        token = data.get("access_token", "")
        print(f"文件: {os.path.basename(p)}")
        print(f"邮箱: {email}")
        print("SSO Key (access_token) - 完整复制下面这一整行:")
        print(token)
        print("---")

if __name__ == "__main__":
    main()
