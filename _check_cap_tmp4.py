# -*- coding: utf-8 -*-
"""临时验证4：dump openapi 内容找 capacity/concurrency 字段定义"""
import sys, json
sys.path.insert(0, r"C:\Users\13370\zhuceji")
sys.path.insert(0, r"C:\Users\13370\zhuceji\web")

from web import server as S
S.engine.load_config()
cfg = S._sub2api_cfg()
token = S._sub2api_login(cfg)
base = cfg["base_url"]

s, b = S._http_json("GET", base + "/openapi.json", token=token)
doc = json.loads(b)
# 打印顶层结构
print("top keys:", list(doc.keys()))
paths = doc.get("paths", {})
print("paths:", list(paths.keys())[:30])
for p, methods in paths.items():
    if "account" in p.lower():
        print("PATH", p, "->", list(methods.keys()))
        for m, meta in methods.items():
            if m in ("put", "post", "patch"):
                body = meta.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
                ref = body.get("$ref", body)
                print("  ", m, "body:", json.dumps(ref, ensure_ascii=False)[:400])
comps = doc.get("components", {}).get("schemas", {})
print("schemas:", list(comps.keys())[:30])
for name, sch in comps.items():
    props = sch.get("properties", {})
    if any(k in props for k in ("capacity", "concurrency", "rate_multiplier")):
        print("SCHEMA", name, "->", json.dumps(props, ensure_ascii=False)[:600])
