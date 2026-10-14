#!/usr/bin/env python3
"""即时聊天冒烟项（补 360° 测试盲区）：公开页开关 + 匿名建会话。"""
import os
import urllib.request
import json

BASE = "http://localhost:8069"
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}))  # 绕过系统代理


def fetch(url, data=None):
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    return opener.open(req, timeout=30).read().decode()


html = fetch(BASE + "/campus/jobs?v=" + str(os.urandom(4).hex()))
ok_switch = "can_load_livechat: true" in html
print("PASS/FAIL 页面聊天开关:", "PASS" if ok_switch else "FAIL", flush=True)

payload = json.dumps({"jsonrpc": "2.0", "method": "call",
                      "params": {"channel_id": 2,
                                 "anonymous_name": "冒烟访客",
                                 "chatbot_script_id": 1, "persist": False},
                      "id": 1}).encode()
resp = json.loads(fetch(BASE + "/im_livechat/get_session", payload))
ok_session = bool(resp.get("result"))
print("PASS/FAIL 匿名建会话:", "PASS" if ok_session else "FAIL")
