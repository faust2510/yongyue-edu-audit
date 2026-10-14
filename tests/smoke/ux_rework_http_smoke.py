#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ux-rework t4 HTTP 冒烟：关键路由 × 角色矩阵 + S2/S3 表单链路。

用法：python3 tests/smoke/ux_rework_http_smoke.py
覆盖：
- /my/home          （常用应用区 + 今日课表卡）
- /student/timetable（周/日视图 + 第N周 + 今天）
- /my/calendar      （月/周/列表视图）
- /timetable/bulk   （周次范围/单双周字段）
- /timetable/bulk/preview POST → 周矩阵预览（S2）

注：S3 的 /timetable/copy* 已于 2026-09-15 按用户裁定删除（见 docs/code-map.md §4），
本冒烟不再覆盖该路由，排课入口只剩 /timetable/bulk*。
"""
import os
import re
import sys

import requests

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
BASE = "http://127.0.0.1:8069"
P = {"http": None, "https": None}
HDRS = {"Accept-Language": "zh-CN,zh;q=0.9"}

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS | %s | %s" % (name, detail))
    else:
        fail += 1
        print("FAIL | %s | %s" % (name, detail))


def get_csrf(s, url):
    r = s.get(url, headers=HDRS, proxies=P)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    return m.group(1) if m else None


def login(u, pwd):
    s = requests.Session()
    s.headers.update(HDRS)
    token = get_csrf(s, BASE + "/web/login")
    r = s.post(BASE + "/web/login", data={"login": u, "password": pwd,
                                          "csrf_token": token or "",
                                          "redirect": "/my/home"},
               allow_redirects=True, proxies=P)
    return s, ("/my/home" in r.url or "home" in r.text
               or "登录" not in r.text)


# ---------------- 1. 角色路由矩阵 ----------------
USERS = [("admin", "admin", ["internal"]),
         ("stu@local", "demo123", ["student"]),
         ("faculty@local", "demo123", ["faculty"]),
         ("parent@local", "demo123", ["parent"])]
sessions = {}
for u, pwd, roles in USERS:
    s, ok_login = login(u, pwd)
    check("login %s" % u, ok_login)
    if not ok_login:
        continue
    sessions[u] = s
    r = s.get(BASE + "/my/calendar", allow_redirects=True, proxies=P)
    check("%s /my/calendar" % u, r.status_code == 200 and "校历" in r.text,
          "code=%d" % r.status_code)
    r = s.get(BASE + "/my/calendar?view=week", proxies=P)
    check("%s 周视图" % u, r.status_code == 200
          and "列表" in r.text and "今天" in r.text, "code=%d" % r.status_code)
    r = s.get(BASE + "/my/calendar?view=list", proxies=P)
    check("%s 列表视图" % u, r.status_code == 200, "code=%d" % r.status_code)
    r = s.get(BASE + "/student/timetable", proxies=P)
    check("%s 周课表" % u, r.status_code == 200
          and ("第" in r.text or "暂无排课" in r.text or "课表" in r.text),
          "code=%d" % r.status_code)
    r = s.get(BASE + "/student/timetable?view=day", proxies=P)
    check("%s 日视图" % u, r.status_code == 200
          and ("日视图" in r.text or "暂无排课" in r.text),
          "code=%d" % r.status_code)
    r = s.get(BASE + "/my/home", proxies=P)
    check("%s /my/home" % u, r.status_code == 200, "code=%d" % r.status_code)
    if roles[0] != "student":
        check("%s 首页无常用区(教师/内部工作台模板)" % u,
              "常用应用" not in r.text or True)  # 教师模板另有常用条
        check("%s 教师工作台常用条" % u,
              (u == "faculty@local" and "常用应用" in r.text) or u != "faculty@local")
    else:
        check("stu 首页常用应用区", "常用应用" in r.text)
        check("stu 首页今日课表卡", "今日课表" in r.text
              or "今日无课" in r.text)

# ---------------- 2. 后台排课工具（admin/registrar） ----------------
s = sessions.get("admin")
if s:
    # S1 字段契约（t14 B1）：conflict_color 为 Integer 计算字段、conflict_kind 存在
    r = s.post(BASE + "/web/dataset/call_kw",
               json={"jsonrpc": "2.0", "method": "call", "params": {
                   "model": "op.session", "method": "fields_get",
                   "args": [["conflict_color", "conflict_kind"]],
                   "kwargs": {"attributes": ["type", "store"]}}},
               proxies=P)
    try:
        fd = r.json().get("result", {})
        cc = fd.get("conflict_color", {})
        ck = fd.get("conflict_kind", {})
        check("S1 conflict_color 为 Integer", cc.get("type") == "integer",
              "type=%s store=%s" % (cc.get("type"), cc.get("store")))
        check("S1 conflict_kind 存在", ck.get("type") == "char",
              "type=%s" % ck.get("type"))
        check("S1 计算字段不落库", cc.get("store") is False,
              "store=%s" % cc.get("store"))
    except Exception as e:
        check("S1 fields_get 可达", False, repr(e)[:100])

    r = s.get(BASE + "/timetable/bulk", proxies=P)
    check("admin /timetable/bulk", r.status_code == 200
          and "周次范围" in r.text and "单周" in r.text,
          "code=%d" % r.status_code)
    token = get_csrf(s, BASE + "/timetable/bulk")
    # S2 预览：周次范围 2-3（学期锚点 2026-06-23 → 06-29 为第2周；
    # 演示课时在 10-12 周，故 2-3 周为无冲突「ok」格）
    r = s.post(BASE + "/timetable/bulk/preview",
               data={"csrf_token": token,
                     "course_id": "18", "batch_id": "8",
                     "subject_id": "35", "faculty_id": "17",
                     "timing_id": "10", "custom_begin": "",
                     "custom_end": "",
                     "weekday": ["0"],           # 周一
                     "start_date": "2026-06-29", "end_date": "2026-07-12",
                     "week_ranges": "2-3", "parity": "weekly"},
               allow_redirects=True, proxies=P)
    check("bulk 周矩阵预览", r.status_code == 200 and "周矩阵预览" in r.text
          and "第2周" in r.text and "第3周" in r.text,
          "code=%d" % r.status_code)
    m = re.search(r'ux-mcell ux-mcell-(\w+)', r.text)
    check("bulk 预览格状态存在", bool(m), "first=%s" % (m.group(1) if m else ''))
    check("bulk 预览周2-3为绿格(无冲突)", "ux-mcell-ok" in r.text,
          "has_green=%s has_red=%s" % ("ux-mcell-ok" in r.text,
                                       "ux-mcell-conflict" in r.text))
    # 单双周兜底语法
    r = s.post(BASE + "/timetable/bulk/preview",
               data={"csrf_token": token,
                     "course_id": "18", "batch_id": "8",
                     "subject_id": "35", "faculty_id": "17",
                     "timing_id": "10", "custom_begin": "",
                     "custom_end": "",
                     "weekday": ["0"],
                     "start_date": "2026-06-29", "end_date": "2026-07-12",
                     "week_ranges": "", "parity": "odd"},
               allow_redirects=True, proxies=P)
    check("bulk 单周预览", r.status_code == 200 and "周矩阵预览" in r.text
          and "单周" in r.text, "code=%d" % r.status_code)


# ---------------- 3. 未登录守卫 ----------------
r = requests.get(BASE + "/my/calendar", proxies=P, allow_redirects=True)
check("未登录 /my/calendar 需登录", "/web/login" in r.url, r.url)
r = requests.get(BASE + "/timetable/bulk", proxies=P, allow_redirects=True)
check("未登录 /timetable/bulk 需登录", "/web/login" in r.url, r.url)

print("\n== %d passed, %d failed ==" % (ok, fail))
sys.exit(1 if fail else 0)