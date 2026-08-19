# -*- coding: utf-8 -*-
"""临时验证5：看 openapi 原始内容"""
import sys, json
sys.path.insert(0, r"C:\Users\13370\zhuceji")
sys.path.insert(0, r"C:\Users\13370\zhuceji\web")

from web import server as S
S.engine.load_config()
cfg = S._sub2api_cfg()
token = S._sub2api_login(cfg)
base = cfg["base_url"]

s, b = S._http_json("GET", base + "/openapi.json", token=token)
print("HTTP", s)
print("RAW:", b[:3000])
