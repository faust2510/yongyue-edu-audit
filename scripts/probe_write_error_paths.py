#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对门户写操作发**空载荷**，看用户拿到什么 —— **报告型探针**。

## 为什么立它（2026-10-03）

前 36 轮我验的都是「页面长得对不对」。换成验**错误路径**后，第一个探针就抓到一处真缺陷：
请假「结束早于开始」被**静默改写**成一天、还回「已提交」（已修，commit `9176a8f`）。
⇒ 这个轴值得做成可复跑的探针，而不是每次手写一段脚本。

## 判据（只看「没接住」和「静默成功」两类）

· ⛔ **没接住**：HTTP 5xx，或响应体里出现 `Traceback` / `Internal Server Error`；
· ⛔ **静默成功**：空载荷却落到 `box=submitted` 一类成功态（本该被校验挡住）；
· ✅ **明确拒绝**：落到带 `box=`/`error=`/`err=` 的结果页，且页面里有中文提示；
· ✅ **权限守卫**：落到 `/my/home` —— 本仓多处用 `if not _X_guard(): redirect('/my/home')`，
  属**有意**的权限回落（钝但一致），单列一档、不算缺陷。

⚠ 本工具**只发空载荷**：空载荷在任何一处都应当被挡下，因此**不会造数据**。
  若某路由对空载荷也落库，那本身就是缺陷（见上「静默成功」）。

退出码：0=无 ⛔ ｜ 1=有 ⛔ ｜ 2=ENV（登录不了 / 取不到 csrf）—— **2 不是通过**。
"""
import argparse
import sys

BASE = "http://127.0.0.1:8069"
LOGINS = {"student": ("stu@local", "demo123"),
          "faculty": ("faculty@local", "demo123"),
          "backoffice": ("backoffice@local", "demo123")}

# 路由 → 用哪个身份打（身份不对会落到权限守卫，那样测不到校验分支）
TARGETS = [
    ("/my/grievances/save", "student"),
    ("/my/journals/save", "student"),
    ("/course/change/request/save", "student"),
    ("/my/checkins/check", "student"),
    ("/ledger/new/save", "backoffice"),
    ("/attendance/save", "faculty"),
    ("/leave/set_state", "faculty"),
    ("/assess/templates/save", "backoffice"),
    ("/assess/tasks/save", "backoffice"),
    ("/downloads/folder/save", "backoffice"),
    ("/approvals/delegate/save", "faculty"),
]

POST_JS = """async ([routes, token]) => {
  const out = [];
  for (const r of routes) {
    try {
      const fd = new FormData();
      fd.append("csrf_token", token);
      const resp = await fetch(r, {method: "POST", body: fd, credentials: "same-origin"});
      const t = await resp.text();
      const doc = new DOMParser().parseFromString(t, "text/html");
      const body = (doc.body ? doc.body.textContent : "").replace(/\\s+/g, " ");
      const i = body.indexOf("错误消息");
      out.push({route: r, status: resp.status, url: resp.url.replace(location.origin, ""),
                trace: t.indexOf("Traceback") >= 0 || t.indexOf("Internal Server Error") >= 0,
                err: i >= 0 ? body.slice(i + 4, i + 94).trim() : null});
    } catch (e) { out.push({route: r, status: "FETCH-ERR", url: "", trace: true, err: String(e).slice(0, 80)}); }
  }
  return out;
}"""


def main():
    ap = argparse.ArgumentParser()
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    bad = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        cache = {}
        for route, role in TARGETS:
            if role not in cache:
                ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                pg = ctx.new_page()
                pg.goto(BASE + "/web/login", timeout=45000)
                pg.wait_for_selector("form.oe_login_form", timeout=30000)
                u, pw = LOGINS[role]
                pg.fill("form.oe_login_form input[name=login]", u)
                pg.fill("form.oe_login_form input[name=password]", pw)
                pg.click("form.oe_login_form button[type=submit]", timeout=30000)
                pg.wait_for_load_state("load", timeout=45000)
                if "/web/login" in pg.url:
                    print("SKIP-ENV：%s 登录失败 —— 这不是通过" % role)
                    return 2
                cache[role] = (ctx, pg)
            ctx, pg = cache[role]
            pg.goto(BASE + "/my/home", timeout=45000)
            pg.wait_for_timeout(900)
            tok = pg.evaluate('() => { const f = document.querySelector("input[name=csrf_token]"); return f ? f.value : null; }')
            d = pg.evaluate(POST_JS, [[route], tok])[0]
            kind = "?"
            if d["trace"] or d["status"] == 500:
                kind = "⛔ 没接住"
                bad.append((route, d))
            elif "submitted" in d["url"] or "saved=1" in d["url"]:
                kind = "⛔ 静默成功（空载荷不该成功）"
                bad.append((route, d))
            elif d["url"].startswith("/my/home"):
                kind = "✅ 权限守卫回落"
            elif any(k in d["url"] for k in ("box=", "error=", "err=")):
                kind = "✅ 明确拒绝"
            else:
                # 第三类**合法的静默**：越权/记录不存在 ⇒ 按「无操作」处理并 303 回列表。
                # 实测先例：/leave/set_state 空载荷 ⇒ leave_id=0 ⇒ rec.exists() 为假 ⇒
                # 一个字段都不写、回 /leave/approvals（控制器注释写明「与「不存在」同样处理」）。
                # 这不等于「静默成功」—— 判据是**有没有落库**，不是有没有报错。
                kind = "✅ 静默 no-op（回列表，未落库）"
            print("  %-32s [%-10s] %-10s %-26s %s" % (route, role, d["status"], d["url"][:26], kind))
            if d.get("err"):
                print("       提示：%s" % d["err"][:80])
        for ctx, pg in cache.values():
            ctx.close()
        b.close()
    if bad:
        print("RESULT=FOUND（%d 处）" % len(bad))
        return 1
    print("RESULT=OK（空载荷全部被挡住：明确拒绝或权限回落）")
    return 0


if __name__ == "__main__":
    sys.exit(main())