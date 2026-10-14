#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""页内链接可达性门禁：模板里**渲染出来的按钮/链接**指向的路由，到底存不存在。

## 为什么需要它（2026-10-02 立，因一起真实缺陷）

现有 check_nav_reachable.py 的输入是**活的导航树（website.menu）** —— 它只覆盖「导航栏里的链接」。
而 `views/*.xml` **页内**的按钮/链接（如「导出 CSV」）不在 website.menu 里，**没有任何门禁看着**。

实证（本门禁立起来的原因）：
  · `custom_addons/edu_portal/views/batch3.xml` 的「导出 CSV」按钮指向 `/my/time_off/export`；
  · 控制器里 `my_time_off_export()` **实现完整、却丢了 @http.route 装饰器** ⇒ 从未注册成路由；
  · 实测 `GET /my/time_off/export` → **404**（而 `/my/time_off` → 200）⇒ 用户点下去就是 404 页。
  · 发现途径：符号级死代码扫描（「有实现但全仓没人按名字调用」正是「装饰器丢了」的指纹）。

## 判据（只判一种，避免误报）

**只把 404 判为缺陷**：404 = 路由根本不存在，无歧义。
403 / 303 / 302 / 200 一律不算（角色权限、流程跳转、需要参数都可能产生它们，属正常）。
含动态段的路径（`<int:x>`、`{{ }}`、`${}`）与静态资源（/web/、/static/、外链）一律跳过 —— 探不了就不探，
**不假装探过**。

退出码：0=无 404 ｜ 1=发现 404 ｜ 2=环境未就绪（站点不通 / 登录失败）——**2 不是通过**。

玩法：
    python3 scripts/check_inpage_links.py               # 默认本地栈 + backoffice 身份
    python3 scripts/check_inpage_links.py --logins student,faculty,backoffice
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import glob
import io
import http.cookiejar

BASE = "http://localhost:8069"
DB = "edu19"
LOGINS = {"student": ("stu@local", "demo123"),
          "faculty": ("faculty@local", "demo123"),
          "backoffice": ("backoffice@local", "demo123")}
SKIP_PREFIX = ("/web/", "/static/", "/website/", "/odoo/", "/longpolling",
               "/edu_portal/static", "/edu_brand/static", "/edu_life/static",
               # ⚠ 2026-10-02 实测加入：`/mail/` 是 **Odoo 核心**路由（不是本仓的页面），
               #   且它要求参数。裸探 `/mail/unfollow`（来自 edu_brand/views/odoo_debrand.xml:35,48
               #   的退订链接，参数运行时才拼上）会让核心抛
               #   `TypeError: MailController.mail_action_unfollow() missing 4 required positional
               #   arguments` ⇒ **每次跑本门禁都在日志里留 11 条 ERROR**，
               #   而 tests/smoke/E_quiz_cross.py 的 B8「日志巡检」正是读这些记录 ⇒
               #   门禁自己把别人的 smoke 弄红。（本门禁的目的就是「别制造假红」。）
               #   ⇒ 本门禁只查**本仓页面**的路由；核心路由不探。
               "/mail/")


def extract_paths(patterns):
    """从模板里抽内部路径（只取**字面量**形式，动态的一律跳过）。"""
    found = {}
    rx = [
        re.compile(r'href="/?(/[A-Za-z0-9_\-./]*)"'),
        re.compile(r"href='/(/[A-Za-z0-9_\-./]*)'"),
        re.compile(r'action="/?(/[A-Za-z0-9_\-./]*)"'),
        re.compile(r"t-attf-href=\"'?(/[A-Za-z0-9_\-./]*)"),
        re.compile(r"t-att-href=[^/]{0,3}(/[A-Za-z0-9_\-./]*)"),
    ]
    for p in patterns:
        for i, line in enumerate(io.open(p, encoding="utf-8", errors="replace"), 1):
            if "t-att-href" in line and "'" not in line.split("t-att-href")[1][:12]:
                continue
            for r in rx:
                for m in r.finditer(line):
                    path = m.group(1)
                    found.setdefault(path, []).append("%s:%d" % (p.split("custom_addons/")[-1], i))
    # ⚠ 2026-10-02 补 `t-att-href="'/path' + 变量"` 这种**字符串拼接**形式（用 [^/]{0,3} 跳过引号，
    #   免得在模式里写引号）。第一版**没有**这条 ⇒ 本门禁立起来要抓的那个缺陷
    #   （views/batch3.xml:638 的 `t-att-href="'/my/time_off/export?filterby=' + filterby + ..."`）
    #   **根本不在候选集里**：我把刚补的装饰器拿掉再造 404，门禁**仍然报绿**。
    #   ⇒ 教训：新门禁必须用**它要抓的那个真实缺陷**做反向注入，随便造一个 red 不算数。
    return found


def probe(session, base, path):
    req = urllib.request.Request(base + path, method="GET")
    try:
        with session.open(req, timeout=25) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--logins", default="backoffice")
    a = ap.parse_args()

    paths = extract_paths(sorted(glob.glob("custom_addons/*/views/*.xml")))
    cand = [p for p in paths
            if not p.startswith(SKIP_PREFIX)
            and not any(ch in p for ch in "{}$<>#")
            and not p.endswith("/")
            and len(p) > 1]
    # ⚠ 2026-10-02 实测教训：第一版只跳了 `{{ }}`，**漏了 QWeb 的 `#{ }`**，于是把
    #   `t-attf-href="/assess/fill/#{task.id}"` 截成 `/assess/fill/` 拿去探 ⇒ **20 条假 404**。
    #   ⇒ 现在凡含 `{ } $ < > #` 的路径一律不探；再加一条「以 `/` 结尾也不探」
    #     （本仓真实路由没有尾斜杠，截断产物才会留这个尾巴）。
    #   教训本身值得记：**新门禁第一版报出来的东西，先证伪再相信** —— 20 条里 20 条是假的。
    cand.sort()
    print("模板里抽到字面量内部路径 %d 条（去重后）；跳过静态/动态 %d 条"
          % (len(cand), len(paths) - len(cand)))

    bad = []
    tried = 0
    for role in a.logins.split(","):
        role = role.strip()
        if role not in LOGINS:
            print("SKIP 未知身份 %s" % role)
            continue
        user, pwd = LOGINS[role]
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        body = json.dumps({"jsonrpc": "2.0", "method": "call",
                           "params": {"db": a.db, "login": user, "password": pwd}}).encode()
        req = urllib.request.Request(a.base + "/web/session/authenticate", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with op.open(req, timeout=25) as r:
                ok = b"\"uid\"" in r.read()
        except Exception as e:
            print("SKIP-ENV：登录失败（%s）—— 这不是通过" % e)
            return 2
        if not ok:
            print("SKIP-ENV：身份 %s 登录被拒 —— 这不是通过" % role)
            return 2
        for p in cand:
            code = probe(op, a.base, p)
            tried += 1
            if code == 404:
                bad.append((p, role, paths[p][:2]))

    print("实探 %d 次（%d 条路径 × %d 身份）" % (tried, len(cand), len(a.logins.split(","))))
    if not cand:
        print("SKIP-ENV：一条可探路径都没有 —— 这不是通过")
        return 2
    if bad:
        print("")
        print("发现 %d 条 **404**（路由不存在）：" % len(bad))
        for p, role, where in bad:
            print("  404  %-44s [%s]  出现在 %s" % (p, role, ", ".join(where)))
        print("")
        print("RESULT=FAIL（404 %d 条）" % len(bad))
        return 1
    print("RESULT=OK（0 条 404）")
    return 0


if __name__ == "__main__":
    sys.exit(main())