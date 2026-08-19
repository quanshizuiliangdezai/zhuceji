# -*- coding: utf-8 -*-
"""临时验证脚本：用面板内部函数查远端账号 capacity 真实值（跑完即删）"""
import sys, json
sys.path.insert(0, r"C:\Users\13370\zhuceji")
sys.path.insert(0, r"C:\Users\13370\zhuceji\web")

from web import server as S

S.engine.load_config()
cfg = S._sub2api_cfg()
print("cfg base_url:", cfg["base_url"], "| email:", cfg["email"], "| capacity cfg:", cfg.get("capacity"))

token = S._sub2api_login(cfg)
print("login OK, token len:", len(token))

remote = S._sub2api_list_grok(token, cfg["base_url"])
print("remote total:", len(remote))

from collections import Counter
caps = Counter(a.get("capacity") for a in remote)
print("capacity distribution:", dict(caps))

# 取前3个样本，看完整字段里有没有 capacity
for a in remote[:3]:
    print("sample:", json.dumps({k: a.get(k) for k in ("id","name","capacity","group_ids")}, ensure_ascii=False))

# 挑一个 capacity 还是 1 的账号，手动 PUT capacity=30，看响应
target = next((a for a in remote if int(a.get("capacity") or 0) != 30), None)
if target:
    aid = target["id"]
    s, b = S._http_json("PUT", cfg["base_url"] + "/api/v1/admin/accounts/%d" % aid,
                        token=token, body={"group_ids": [int(cfg["group_id"])], "capacity": 30})
    print("manual PUT acc %d -> HTTP %s: %s" % (aid, s, b[:200]))
