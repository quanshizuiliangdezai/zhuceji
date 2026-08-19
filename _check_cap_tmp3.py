# -*- coding: utf-8 -*-
"""临时验证3：看 sub2api 文档/字段定义，确认 capacity vs concurrency"""
import sys, json
sys.path.insert(0, r"C:\Users\13370\zhuceji")
sys.path.insert(0, r"C:\Users\13370\zhuceji\web")

from web import server as S
S.engine.load_config()
cfg = S._sub2api_cfg()
token = S._sub2api_login(cfg)
base = cfg["base_url"]

# 1) 尝试拉 OpenAPI 文档
for path in ["/openapi.json", "/api/v1/openapi.json", "/docs", "/redoc"]:
    s, b = S._http_json("GET", base + path, token=token)
    print("GET", path, "-> HTTP", s, "len", len(b))
    if s == 200 and b.strip().startswith("{"):
        try:
            doc = json.loads(b)
            paths = doc.get("paths", {})
            # 找 accounts 相关 schema
            acc_schema = None
            for name, sch in (doc.get("components", {}).get("schemas", {}) or {}).items():
                if "account" in name.lower() and "update" not in name.lower() and "create" not in name.lower():
                    acc_schema = (name, sch)
                    break
            if acc_schema:
                print("ACCOUNT SCHEMA:", acc_schema[0], "->", json.dumps(acc_schema[1].get("properties", {}), ensure_ascii=False)[:800])
            break
        except Exception as e:
            print("  parse err:", e)
