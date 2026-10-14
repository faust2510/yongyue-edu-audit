#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 回归探针：/student/profile 在「邮箱为空的学生」上会不会 500。

缺陷（2026-10-02 空态审计实测，本机 edu19 克隆）：
  custom_addons/edu_portal/views/batch1.xml 的 edu_profile 模板写了
      t-out="info[email] or user.email or 空串"
  而 /student/profile 的 values 里**没有** user 这个键（controllers/batch1.py 的 student_profile），
  平时靠 or 短路侥幸不炸：学生邮箱非空 ⇒ 不求值；
  邮箱为空（**刚建号、还没填资料的新生就是这个状态**）⇒ KeyError: user ⇒ 整页 500。
  实测复现：新建空账号 empty@local → GET /student/profile = HTTP 500，
  docker logs 里的 traceback 指向 template_edu_portal_edu_profile 的 KeyError: user。

判据（可反向证伪）：HTTP 状态码 == --expect（默认 200）；且响应体里出现 --must-contain（默认「学生档案」），
  防止「200 但其实是错误页」混过去。两者任一不满足 ⇒ exit 1。

用法（本地）：
  /opt/homebrew/bin/python3 docs/audit/empty-states/probe_profile_500.py \
      --login empty@local --password demo123
用法（生产，需要**真实账号**；本执行者没有该口令，见 report.md §7）：
  /opt/homebrew/bin/python3 docs/audit/empty-states/probe_profile_500.py \
      --base https://edu.example.org --db edu19 --login <学生登录名> --password <口令> --expect 200
"""
import argparse
import sys

import requests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8069")
    ap.add_argument("--db", default="edu19")
    ap.add_argument("--login", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--path", default="/student/profile")
    ap.add_argument("--expect", type=int, default=200)
    ap.add_argument("--must-contain", default="学生档案")
    args = ap.parse_args()

    s = requests.Session()
    s.trust_env = False          # 本机有系统代理，本地/生产请求都别走它
    try:
        r = s.post(args.base + "/web/session/authenticate",
                   json={"jsonrpc": "2.0",
                         "params": {"db": args.db, "login": args.login,
                                    "password": args.password}}, timeout=30)
        uid = (r.json().get("result") or {}).get("uid")
    except Exception as e:
        print("ENV：认证请求失败：%s" % e)
        return 2
    if not uid:
        print("FAIL：登录失败（login=%s db=%s）—— 口令不对或账号不存在" % (args.login, args.db))
        return 2
    try:
        g = s.get(args.base + args.path, timeout=30)
    except Exception as e:
        print("ENV：%s 请求失败：%s" % (args.path, e))
        return 2
    body = g.text or ""
    hit = args.must_contain in body
    ok = (g.status_code == args.expect) and (hit or not args.must_contain)
    print("base=%s db=%s login=%s uid=%s path=%s"
          % (args.base, args.db, args.login, uid, args.path))
    print("HTTP %s（期望 %s）｜ 响应体 %d 字节 ｜ 含「%s」=%s ｜ 是 500 错误页=%s"
          % (g.status_code, args.expect, len(body), args.must_contain, hit,
             "500: Internal Server Error" in body or "重置模板" in body))
    print("结论：%s" % ("PASS（页面正常渲染）" if ok else "FAIL（与期望不符 ⇒ 探针报红）"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())