#!/usr/bin/env python3
"""登录落地页对比：目标站 vs 本地，逐账号真实登录，记录最终URL+截图。
输出 shots/cmp/<side>_<account>.png + shots/cmp/report.md

凭据（t81 收口）—— 两侧的纪律**不同**，别混：
· local（本库）：唯一声明点 LOCAL_CRED_DEFAULTS，可用
  EDU_<KEY>_LOGIN / EDU_<KEY>_PASSWORD（KEY ∈ STU|FAC|PAR|BO|ADMIN）覆盖。
  旧值 ("admin","admin") 在本库**失效**（实测 AccessDenied），已改为 demo123。
· target（外部对照站）：**不给任何默认口令** —— 那是别人的系统，写死的演示口令
  （student@openeducat.com/student 一类）无从核验，且正是"失效凭据 + 静默继续"的同族
  形态。必须显式提供 CMP_TARGET_<KEY>_LOGIN / CMP_TARGET_<KEY>_PASSWORD；
  读不到就把该账号显式登记为**未验证**（不再当"对照成功"）。
· 口令不出现在任何输出里（打印/报告只出现登录名）。

用法：python3 scripts/cmp_landing.py [账号名 …]
退出码：0 = 每一行都已**登录验证**；1 = 明确提供的凭据被拒（登录失败）；
        2 = 有行未验证（target 侧未配置凭据，或站点不可达）；
        1 优先于 2（"发现失败"优先于"这次没看成"）。
"""
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
OUT = ROOT / "shots" / "cmp"
OUT.mkdir(parents=True, exist_ok=True)

TARGET_BASE = os.environ.get("CMP_TARGET_BASE", "https://target-site.example")
LOCAL_BASE = os.environ.get("CMP_LOCAL_BASE", "http://localhost:8069")

# ---- 凭据（t81）----
LOCAL_CRED_DEFAULTS = {
    "student":    ("STU", "stu@local", "demo123"),
    "faculty":    ("FAC", "faculty@local", "demo123"),
    "parent":     ("PAR", "parent@local", "demo123"),
    "backoffice": ("BO", "backoffice@local", "demo123"),
    "admin":      ("ADMIN", "admin", "demo123"),   # 本库口令；生产用 EDU_ADMIN_PASSWORD 覆盖
}
ACCOUNTS = list(LOCAL_CRED_DEFAULTS)


def local_cred(name):
    key, login, pwd = LOCAL_CRED_DEFAULTS[name]
    return (os.environ.get("EDU_%s_LOGIN" % key, login),
            os.environ.get("EDU_%s_PASSWORD" % key, pwd))


def target_cred(name):
    """外部对照站凭据：**只从环境变量读，没有默认值**。

    返回 (login, pwd) 或 (None, None)（= 未配置 ⇒ 该行未验证）。
    """
    key = LOCAL_CRED_DEFAULTS[name][0]
    login = os.environ.get("CMP_TARGET_%s_LOGIN" % key)
    pwd = os.environ.get("CMP_TARGET_%s_PASSWORD" % key)
    if not login or not pwd:
        return None, None
    return login, pwd


# 登录成功的判据：会话里真有 uid（本地/目标站都是 Odoo 家族；目标站若不同族，
# 该探针会返回 0 ⇒ 记"未验证"而不是记 OK —— 宁可说"没看成"，也不假 OK）。
SESSION_PROBE = """async () => {
  try {
    const r = await fetch('/web/session/get_session_info', {method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})});
    const j = await r.json();
    return (j.result || {}).uid || 0;
  } catch (e) { return 0; }
}"""


def login_and_shoot(pw, side, base, user, pwd, name):
    """返回 (url_final, status, note)；status ∈ verified | rejected | error。

    · verified：会话里有 uid ⇒ 这一行**真的对照上了**；
    · rejected：凭据被拒（登录后仍无 uid）⇒ 明确失败，退出码 1；
    · error：站点不可达/选择器失败等 ⇒ "没看成"，退出码 2（不是"失败结论"）。
    """
    browser = pw.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                              locale="zh-CN", ignore_https_errors=True)
    page = ctx.new_page()
    url_final, err, status = "?", "", "error"
    try:
        page.goto(base + "/web/login", timeout=45000, wait_until="load")
        page.wait_for_timeout(1200)
        # 若已有会话会直接跳走；检测是否在登录页
        if page.locator("#login").count() == 0:
            page.goto(base + "/web/login?redirect=%2Fweb%2Flogin", timeout=45000)
            page.wait_for_timeout(800)
        page.fill("#login", user)
        page.fill("#password", pwd)
        page.locator(".oe_login_form button[type=submit], form[action='/web/login'] button[type=submit]").first.click()
        # 后端 web client 用 websocket 轮询，networkidle 可能永不触发 → load + 定长等待
        try:
            page.wait_for_load_state("load", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(7000)  # 等 OWL 应用渲染
        url_final = page.url
        uid = page.evaluate(SESSION_PROBE)
        status = "verified" if uid else "rejected"
        # 登录失败也把"落点"截下来（否则只能靠人猜），但**备注里写明未验证**
        shot = OUT / f"{side}_{name}.png"
        page.screenshot(path=str(shot), full_page=False)
        note = ("OK（已验证 uid=%s）" % uid) if uid else \
               ("FAIL 凭据被拒：登录后会话无 uid（落在 %s）→ 该行**不得**当作对照成功"
                % url_final)
        print(f"[{side}:{name}] URL={url_final} {note}")
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, str(e)[:130])
        print(f"[{side}:{name}] ERROR {err}")
        try:
            page.screenshot(path=str(OUT / f"{side}_{name}_ERR.png"))
        except Exception:
            pass
        note = "未验证：运行失败（站点不可达/页面结构不符）—— " + err
    browser.close()
    return url_final, status, note


def main():
    only = set(sys.argv[1:]) or None
    report = ["| 账号 | 端 | 登录后最终 URL | 截图 | 备注 |", "|---|---|---|---|---|"]
    verified_rows, rejected, unverified = [], [], []
    with sync_playwright() as pw:
        for name in ACCOUNTS:
            if only and name not in only:
                continue
            tgt = target_cred(name)
            attempts = [("target", TARGET_BASE, tgt)]
            attempts.append(("local", LOCAL_BASE, local_cred(name)))
            for side, base, cred in attempts:
                if not cred[0] or not cred[1]:
                    note = ("未验证：target 侧未配置凭据 —— 需要 CMP_TARGET_%s_LOGIN / "
                            "_PASSWORD；**没有默认口令**（别人的系统不写死我们的口令）"
                            % LOCAL_CRED_DEFAULTS[name][0])
                    print(f"[{side}:{name}] {note}")
                    report.append(f"| {name} | {side} | - | - | {note} |")
                    unverified.append("%s/%s" % (side, name))
                    continue
                url, status, note = login_and_shoot(pw, side, base, cred[0],
                                                    cred[1], name)
                report.append(f"| {name} | {side} | {url} | shots/cmp/{side}_{name}.png "
                              f"| {note.replace('|', '/')} |")
                if status == "rejected":
                    rejected.append("%s/%s" % (side, name))
                elif status == "error":
                    unverified.append("%s/%s" % (side, name))
                else:
                    verified_rows.append("%s/%s" % (side, name))
                time.sleep(0.5)
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print("\n== 对照结论：已验证 %d 行（%s）/ 凭据被拒 %d 行（%s）/ 未验证 %d 行（%s）=="
          % (len(verified_rows), ", ".join(verified_rows) or "-",
             len(rejected), ", ".join(rejected) or "-",
             len(unverified), ", ".join(unverified) or "-"))
    if rejected:
        return 1
    if unverified:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
