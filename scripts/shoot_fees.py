#!/usr/bin/env python3
"""财务缴费四角色截图 + 学生数据断言。

凭据（t81 收口）：只在 CRED_DEFAULTS **一处**声明，可用
EDU_<角色>_LOGIN / EDU_<角色>_PASSWORD（角色 ∈ STU|FAC|PAR|ADMIN）覆盖；
口令不出现在任何输出里（打印只出现登录名）。旧版写死 ('admin','admin')，
而本库 admin 的口令是 demo123 ⇒ 登录被拒后页面停在登录页，脚本照样打印
"OK fees_admin"、照样 exit 0（产物是登录页截图；同源事故见 check_odoo_trace.py t79）。
退出码：0 = 四角色全部已登录出图 且 学生数据断言全为 True；
        1 = 有角色未验证/失败，或学生断言为 False（**断言不再只打印不生效**）。
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8069"
OUT = Path(__file__).parent.parent / "shots" / "local"
ACTION = os.environ.get("EDU_FEES_ACTION", "")

# ---- 凭据：**唯一声明点**（t81）----
# 口令只在这里出现，且**不打印**（打印只出现登录名）。
CRED_DEFAULTS = [
    ("student", "STU", "stu@local", "demo123"),
    ("faculty", "FAC", "faculty@local", "demo123"),
    ("parent", "PAR", "parent@local", "demo123"),
    ("admin", "ADMIN", "admin", "demo123"),     # 生产/他库：EDU_ADMIN_PASSWORD 覆盖
]
CREDS = {role: (os.environ.get("EDU_%s_LOGIN" % key, login),
                os.environ.get("EDU_%s_PASSWORD" % key, pwd))
         for role, key, login, pwd in CRED_DEFAULTS}

# 登录成功的判据：会话里真有 uid（不用"页面上还有没有密码框"这类 DOM 判据 ——
# 本库 /login 对已登录用户也会渲染登录表单，DOM 判据会把"没登进去"读成"登进去了"）。
SESSION_PROBE = """async () => {
  const r = await fetch('/web/session/get_session_info', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})});
  const j = await r.json();
  return (j.result || {}).uid || 0;
}"""

failed = []


def login(page, role):
    """登录并**验证**：返回 uid；失败抛 RuntimeError（由调用方响亮处理）。"""
    user, pwd = CREDS[role]
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
        raise RuntimeError("登录失败：%s(%s)（会话未建立 uid=0；evaluate 重试 %d 次）"
                           "→ 本角色本轮**未验证**；口令可用 EDU_*_PASSWORD 覆盖"
                           "（口令不会被打印）" % (role, user, errors))
    return uid


def check(name, cond, detail=""):
    """学生数据断言：既打印**也**进退出码（旧版只 print，False 也能 exit 0）。"""
    cond = bool(cond)
    print("断言 %s: %s%s" % (name, cond, ("  [%s]" % detail) if detail else ""))
    if not cond:
        failed.append("断言 " + name)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)

    # 学生：页面内容断言 + 截图
    ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                              locale="zh-CN")
    page = ctx.new_page()
    try:
        uid = login(page, "student")
        print("     student 登录成功 uid=%s" % uid)
        page.goto(BASE + "/my/fees", timeout=45000)
        page.wait_for_load_state("networkidle")
        body = page.inner_text("body")
        # v3：术语已统一为「统筹费」（原断言串「2026 春季学费」失效，2026-09-12）
        check("统筹费账单在", "2026 春季统筹费" in body)
        check("部分缴纳徽标", "部分缴纳" in body)
        check("待缴合计提示", "待缴合计" in body)
        check("无报错", "Traceback" not in body)
        page.screenshot(path=str(OUT / "fees_student.png"), full_page=True)
        print("OK  fees_student")
    except Exception as e:
        failed.append("student")
        print(f"FAIL student: {str(e)[:200]}")
    finally:
        ctx.close()

    for role in ("faculty", "parent", "admin"):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  locale="zh-CN")
        page = ctx.new_page()
        try:
            uid = login(page, role)
            print("     %s 登录成功 uid=%s" % (role, uid))
            page.goto(BASE + "/my/fees", timeout=45000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT / f"fees_{role}.png"),
                            full_page=True)
            print(f"OK  fees_{role}")
            if role == "admin" and ACTION:
                page.goto(BASE + f"/web#action={ACTION}", timeout=60000)
                page.wait_for_timeout(9000)
                page.screenshot(path=str(OUT / "fees_admin_backend.png"))
                print("OK  fees_admin_backend")
        except Exception as e:
            failed.append(role)
            print(f"FAIL {role}: {str(e)[:200]}")
        finally:
            ctx.close()
    browser.close()

if failed:
    print("\n[FAIL] %d 项未验证/失败：%s（登录失败的角色的产物不再算数）"
          % (len(failed), ", ".join(failed)))
    sys.exit(1)
print("\n[OK] 四角色全部登录成功并出图，学生数据断言全为 True")
