#!/usr/bin/env python3
"""排课系统四角色真机截图：学生 / 教师 / 家长 / 管理员(门户+后台周课表)。
用法：EDU_ACTION_WEEK=<action_id> python3 scripts/shoot_timetable.py
输出：shots/local/timetable_<role>.png（1440 宽全页）

凭据（t81 收口）：只在 CRED_DEFAULTS **一处**声明，可用
EDU_<角色>_LOGIN / EDU_<角色>_PASSWORD（角色 ∈ STU|FAC|PAR|ADMIN）覆盖；
口令不出现在任何输出里（打印只出现登录名）。
退出码：0 = 四角色全部**已登录并出图**；1 = 有角色未验证/失败（绝不再"登录失败照样 OK"）。
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8069"
OUT = Path(__file__).parent.parent / "shots" / "local"
ACTION_WEEK = os.environ.get("EDU_ACTION_WEEK", "")

# ---- 凭据：**唯一声明点**（t81）----
# 口令只在这里出现，且**不打印**（打印只出现登录名）。admin 用 demo123：
# 旧值 ('admin','admin') 在本库是**失效凭据**（实测 AccessDenied）。旧版 login()
# 不校验结果 ⇒ 脚本照样打印 "OK admin -> …png" 且 exit 0，可产物是一张**登录页截图**
# （2026-09-28 实测，本文件 t81 收口）。同源事故见 scripts/check_odoo_trace.py t79。
CRED_DEFAULTS = [
    ("student", "STU", "stu@local", "demo123"),
    ("faculty", "FAC", "faculty@local", "demo123"),
    ("parent", "PAR", "parent@local", "demo123"),
    ("admin", "ADMIN", "admin", "demo123"),     # 生产/他库：EDU_ADMIN_PASSWORD 覆盖
]
ROLES = [(role, os.environ.get("EDU_%s_LOGIN" % key, login),
          os.environ.get("EDU_%s_PASSWORD" % key, pwd))
         for role, key, login, pwd in CRED_DEFAULTS]

# 登录成功的判据：会话里真有 uid。
# 不用"页面上还有没有密码框"这类 DOM 判据 —— 本库 /login 对已登录用户也会渲染
# 登录表单，DOM 判据会把"没登进去"读成"登进去了"（假绿家族）。
SESSION_PROBE = """async () => {
  const r = await fetch('/web/session/get_session_info', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})});
  const j = await r.json();
  return (j.result || {}).uid || 0;
}"""


def login(page, user, pwd):
    """登录并**验证**：返回 uid；失败抛 RuntimeError（由调用方响亮处理）。"""
    page.goto(BASE + "/web/login")
    page.fill("#login", user)
    page.fill("#password", pwd)
    page.locator(".oe_login_form button[type=submit]").first.click()
    # 等导航**落定**：只等 load，不等 networkidle —— 后端 web client 的轮询会让
    # networkidle 永不触发（实测 t81：口令错时就在那行 TimeoutError，把"未验证"
    # 变成 30 行堆栈）。等待失败只告警，判据仍在下一段的会话 uid 上。
    try:
        page.wait_for_load_state("load", timeout=15000)
    except Exception as exc:
        print("     [WARN] %s 登录后按 load 等页面落定超时：%s"
              % (role, type(exc).__name__))
    # 轮询会话 uid：跳转途中 evaluate 会因"执行上下文被销毁"抛错（实测），
    # 所以把 evaluate 失败**计入重试次数**、最终仍登不上就响亮失败（次数写进原因），
    # 不静默吞掉。
    uid, errors = 0, 0
    for _ in range(16):
        try:
            uid = page.evaluate(SESSION_PROBE)
        except Exception:
            errors += 1
            uid = 0
        if uid:
            break
        page.wait_for_timeout(400)
    if not uid:
        raise RuntimeError("登录失败：%s（会话未建立 uid=0；evaluate 重试 %d 次）"
                           "→ 本角色本轮**未验证**；口令可用 EDU_*_PASSWORD 覆盖"
                           "（口令不会被打印）" % (user, errors))
    return uid


def shot(page, name, url, wait=1200):
    page.goto(BASE + url, timeout=45000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(wait)
    path = OUT / f"timetable_{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"OK  {name} -> {path}")


failed_roles = []          # 未验证/失败的角色（决定退出码；不再"登录失败照样 OK"）
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    for role, user, pwd in ROLES:
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  locale="zh-CN")
        page = ctx.new_page()
        try:
            uid = login(page, user, pwd)
            print(f"     {role} 登录成功 uid={uid}")
            shot(page, role, "/student/timetable")
            if role == "student":
                shot(page, "student_prev_week", "/student/timetable?w=-1")
            if role == "admin" and ACTION_WEEK:
                page.goto(f"{BASE}/web#action={ACTION_WEEK}", timeout=45000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(4000)
                path = OUT / "timetable_admin_backend.png"
                page.screenshot(path=str(path))
                print(f"OK  admin_backend -> {path}")
        except Exception as e:
            failed_roles.append(role)
            print(f"FAIL {role}: {str(e)[:200]}")
        finally:
            ctx.close()
    browser.close()

if failed_roles:
    print("\n[FAIL] %d/%d 个角色未验证或失败：%s（登录失败时**不会**再打印 OK／不再出图）"
          % (len(failed_roles), len(ROLES), ", ".join(failed_roles)))
    raise SystemExit(1)
print("\n[OK] 四角色全部登录成功并出图：%s" % ", ".join(r for r, _, _ in ROLES))
