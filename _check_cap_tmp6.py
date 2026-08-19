# -*- coding: utf-8 -*-
"""临时验证6：确认 concurrency 才是正确字段 —— 手动 PUT concurrency=30 看是否生效"""
import sys, json
sys.path.insert(0, r"C:\Users\13370\zhuceji")
sys.path.insert(0, r"C:\Users\13370\zhuceji\web")

from web import server as S
S.engine.load_config()
cfg = S._sub2api_cfg()
token = S._sub2api_login(cfg)
base = cfg["base_url"]

# 用 account 24 测试：先看当前 concurrency
s, b = S._http_json("GET", base + "/api/v1/admin/accounts/24", token=token)
d = json.loads(b).get("data", {})
print("BEFORE: concurrency =", d.get("concurrency"), "| capacity 键存在?", "capacity" in d)

# PUT concurrency=30
s, b = S._http_json("PUT", base + "/api/v1/admin/accounts/24",
                    token=token, body={"concurrency": 30})
print("PUT concurrency=30 -> HTTP", s)
if s == 200:
    r = json.loads(b).get("data", {})
    print("PUT 响应里的 concurrency =", r.get("concurrency"))

# 回读确认
s, b = S._http_json("GET", base + "/api/v1/admin/accounts/24", token=token)
d = json.loads(b).get("data", {})
print("AFTER: concurrency =", d.get("concurrency"))

# 恢复 concurrency=1 保持原状（不污染生产数据）
s, b = S._http_json("PUT", base + "/api/v1/admin/accounts/24",
                    token=token, body={"concurrency": 1})
d = json.loads(b).get("data", {}) if s == 200 else {}
print("RESTORE: concurrency =", d.get("concurrency"))
