# -*- coding: utf-8 -*-
"""临时验证2：PUT 后回读账号24 的 capacity + 看完整字段"""
import sys, json
sys.path.insert(0, r"C:\Users\13370\zhuceji")
sys.path.insert(0, r"C:\Users\13370\zhuceji\web")

from web import server as S
S.engine.load_config()
cfg = S._sub2api_cfg()
token = S._sub2api_login(cfg)

# 1) GET 单个账号看完整字段
s, b = S._http_json("GET", cfg["base_url"] + "/api/v1/admin/accounts/24", token=token)
print("GET acc 24 -> HTTP", s)
d = json.loads(b).get("data", {})
print("capacity:", d.get("capacity"), "| concurrency:", d.get("concurrency"), "| rate_multiplier:", d.get("rate_multiplier"), "| priority:", d.get("priority"))
print("ALL KEYS:", sorted(d.keys()))
