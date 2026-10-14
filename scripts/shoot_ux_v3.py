#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3 截图矩阵：4 角色 × 3 视口（1280 / 768 / 375）+ 每页 DOM 高度。

产出：
  tests/gap/shots/ux-v3/<role>/<width>/<page>.png   截图（全页）
  tests/gap/shots/ux-v3/heights.json                每页 DOM 高度（首页瘦身指标 M3）
  stdout                                            高度表 + M3 首页高度汇总

用法：
  python3 scripts/shoot_ux_v3.py                    # 全部（guest + 四角色 × 3 视口）
  python3 scripts/shoot_ux_v3.py --role student     # 只跑一个角色
  python3 scripts/shoot_ux_v3.py --page home        # 只跑指定页（名称子串匹配）
  python3 scripts/shoot_ux_v3.py --with-admin       # 追加 admin 角色
  python3 scripts/shoot_ux_v3.py --no-shots         # 只量高度，不落 PNG
退出码：0 = 全部页面拿到 200；1 = 有页面未达 200（详见输出）；2 = 运行错误。

凭据（t81 收口）：只在 CRED_DEFAULTS **一处**声明，可用
EDU_<角色>_LOGIN / EDU_<角色>_PASSWORD（角色 ∈ STU|FAC|PAR|BO|ADMIN）覆盖；
口令不出现在任何输出里（打印只出现登录名）。admin 用 demo123：旧值 ('admin','admin')
在本库实测 AccessDenied（本库口令即 demo123）。
登录失败的判据从 DOM（"还有没有密码框"）改为**会话 uid**：本库 /login 对已登录用户
也会渲染登录表单，DOM 判据两个方向都可能读错（详见 login() 注释）。
⚠ `--with-admin` 是**空操作**（t81 实测）：PAGES 里没有 'admin' 条目 ⇒ admin 会被
`if role not in PAGES: continue` 直接跳过，既不登录也不采样。现登记为**未验证面**
（结论受影响），要真正覆盖后台须先给 PAGES 补 admin 页面清单。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8069'
DB = 'edu19'
OUT_ROOT = Path('tests/gap/shots/ux-v3')

VIEWPORTS = [('1280', 1280, 900), ('768', 768, 1024), ('375', 375, 812)]

# 角色 -> (env 键, 登录名, 密码, 中文名)：**凭据唯一声明点**（t81）。
# 可用 EDU_<env 键>_LOGIN / EDU_<env 键>_PASSWORD 覆盖；口令**不打印、不入日志**
# （打印只出现登录名）。admin 用 demo123 —— 旧值 ('admin','admin') 在本库是
# **失效凭据**（实测 POST /web/session/authenticate → AccessDenied）。
CRED_DEFAULTS = {
    'student':    ('STU', 'stu@local', 'demo123', '学生'),
    'faculty':    ('FAC', 'faculty@local', 'demo123', '教师'),
    'parent':     ('PAR', 'parent@local', 'demo123', '家长'),
    'backoffice': ('BO', 'backoffice@local', 'demo123', '教务'),
    'admin':      ('ADMIN', 'admin', 'demo123', '管理员'),  # 生产/他库：覆盖 EDU_ADMIN_PASSWORD
}


def credentials(role):
    key, login, pwd, label = CRED_DEFAULTS[role]
    return (os.environ.get('EDU_%s_LOGIN' % key, login),
            os.environ.get('EDU_%s_PASSWORD' % key, pwd), label)


ROLES = {role: credentials(role) for role in CRED_DEFAULTS}
ROLE_ORDER = ['student', 'faculty', 'parent', 'backoffice']

# 每个角色的页面：name -> (path, 是否 M3 首页指标)
PAGES = {
    'guest': [
        ('site_home', '/'),
        ('site_programs', '/programs'),
        ('site_help', '/help'),
    ],
    'student': [
        ('home', '/my/home'),
        ('calendar', '/my/calendar'),
        ('downloads', '/downloads'),
        ('timetable', '/student/timetable'),
        ('study', '/my/study'),
        ('apps', '/my/apps'),
    ],
    'faculty': [
        ('home', '/my/home'),
        ('calendar', '/my/calendar'),
        ('downloads', '/downloads'),
        ('rollcall', '/my/rollcall'),
        ('leave_approvals', '/leave/approvals'),
    ],
    'parent': [
        ('home', '/my/home'),
        ('calendar', '/my/calendar'),
        ('downloads', '/downloads'),
        ('child', '/my/child'),
    ],
    'backoffice': [
        ('home', '/my/home'),
        ('calendar', '/my/calendar'),
        ('downloads', '/downloads'),
        ('ledger', '/ledger'),
        ('downloads_manage', '/downloads?mode=manage'),
    ],
}
# 首页瘦身指标 M3 的基准页（每角色首页）
M3_PAGES = {'home', 'site_home'}
# v3 待交付页（当前 404 → 记为 pending，不算失败）
PENDING_V3 = {'/login', '/apps', '/my/apps', '/my/study'}


SESSION_PROBE = """async () => {
  const r = await fetch('/web/session/get_session_info', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({jsonrpc:'2.0',method:'call',params:{}})});
  const j = await r.json();
  return (j.result || {}).uid || 0;
}"""


def login(page, user, pwd, tries=3):
    """登录；返回 (uid, 说明)（uid=0 即失败）。失败自动重试（升级窗口里 web 会重启 5–15 秒）。

    用 ?db=edu19 落到品牌登录页；判据是**会话里的 uid**，不是 URL 前缀、也不是
    「页面上还有没有密码输入框」—— 本库 t4 的 /login 对**已登录**用户也会渲染一张
    登录表单（P3），DOM 判据两个方向都可能读错（t81 改为唯一的会话判据）。
    """
    last = ''
    for attempt in range(1, tries + 1):
        try:
            page.goto(BASE + '/web/login?db=' + DB, wait_until='load', timeout=45000)
            if 'database/selector' in page.url:  # 兜底：点一下库名链接
                try:
                    page.click('a[href*="db=%s"]' % DB, timeout=5000)
                    page.wait_for_load_state('load', timeout=30000)
                except Exception:
                    pass
            page.fill('input[name="login"]', user, timeout=15000)
            page.fill('input[name="password"]', pwd, timeout=15000)
            # 提交按钮的选择器要跟得上 t4 的登录页改版（表单 action 已变成 /login，
            # 且页面里还藏着 d-none 的表单）——逐个候选试，仍失败就用回车提交，
            # 这是对标记变化最不敏感的方式。
            clicked = False
            for sel in ('form.oe_login_form:not(.d-none) button[type="submit"]',
                        'form[action="/login"] button[type="submit"]',
                        'form[action="/web/login"] button[type="submit"]',
                        'button[type="submit"]:visible',
                        '.demo-login-btn'):
                try:
                    page.click(sel, timeout=3000)
                    clicked = True
                    break
                except Exception:
                    continue
            if not clicked:
                page.press('input[name="password"]', 'Enter')
            page.wait_for_load_state('load', timeout=30000)
            page.wait_for_timeout(700)
            uid = page.evaluate(SESSION_PROBE)
            if uid:
                return uid, page.url
            last = '登录后会话仍无 uid（凭据被拒或页面被重置）: %s' % page.url
        except Exception as e:
            last = '%s: %s' % (type(e).__name__, str(e)[:70])
        if attempt < tries:
            page.wait_for_timeout(5000)   # 等 web 重启完
    return 0, last or '登录失败'


def measure(page):
    """返回 DOM 高度三元组。"""
    return page.evaluate("""() => ({
        scroll: document.documentElement.scrollHeight,
        body: document.body ? document.body.offsetHeight : 0,
        viewport: window.innerHeight,
    })""")


def run(roles, only_page=None, with_admin=False, no_shots=False):
    heights = {}
    fails = []
    login_failed = 0
    t0 = time.time()
    # ⚠ `--with-admin` 是**空操作**（t81 实测）：PAGES 里没有 'admin' 条目，下面的
    #   `if role not in PAGES: continue` 会把 admin 直接跳过 —— 既不登录、也不采样，
    #   退出码也不受影响，而参数说明写着"追加 admin（后台页）"⇒ 静默失效。
    #   本收口**不臆造**后台页面清单（那属产品/门禁设计，不属凭据收口），只把这种
    #   "请求了却没采样"显式登记为**未验证面**：结论受影响，不许当成通过。
    admin_face_unverified = with_admin and 'admin' not in PAGES
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for role in ['guest'] + roles:
            if role not in PAGES:
                continue
            pages = PAGES[role]
            if only_page:
                pages = [p for p in pages if only_page in p[0]]
            if not pages:
                continue
            ctx = browser.new_context(locale='zh-CN')
            page = ctx.new_page()
            if role != 'guest':
                user, pwd, label = credentials(role)
                ok, info = login(page, user, pwd)
                print('[%s %s] 登录 %s (uid=%s %s)'
                      % (role, label, 'OK' if ok else 'FAIL', ok, info))
                if not ok:
                    # 登录失败 = **该角色面未验证**：不进 PAGES 循环、不产生任何 200 读数
                    # （旧版把失败记进 fails 后 continue，方向是对的；这里补上 uid 口径）。
                    login_failed += 1
                    fails.append('%s 登录失败（该角色面未验证，不得当作通过）: %s'
                                 % (role, info))
                    ctx.close()
                    continue
            for width_name, w, h in VIEWPORTS:
                page.set_viewport_size({'width': w, 'height': h})
                for name, path in pages:
                    key = '%s/%s/%s' % (role, name, width_name)
                    row = dict(role=role, page=name, path=path, width=w, height=h)
                    # 匿名上下文没有 db 会话：不带 ?db= 时 Odoo 会落到
                    # /web/database/selector（该页会命中 404 或数据库选择页），
                    # 公开站截图必须显式绑定库，否则测到的是选择页而不是官网。
                    url = BASE + path
                    if role == 'guest':
                        url += ('&' if '?' in path else '?') + 'db=' + DB
                    try:
                        resp = page.goto(url, wait_until='load', timeout=45000)
                        status = resp.status if resp else 0
                        page.wait_for_timeout(700)
                        m = measure(page)
                        row.update(status=status, scroll=m['scroll'], body=m['body'],
                                   viewport_h=m['viewport'])
                        if status == 200:
                            if not no_shots:
                                out = OUT_ROOT / role / width_name
                                out.mkdir(parents=True, exist_ok=True)
                                page.screenshot(path=str(out / ('%s.png' % name)),
                                                full_page=True)
                            row['shot'] = str(OUT_ROOT / role / width_name / ('%s.png' % name))
                        elif status == 404 and path in PENDING_V3:
                            row['note'] = 'v3 待交付（404）'
                        else:
                            row['note'] = 'HTTP %s' % status
                    except Exception as e:
                        row.update(status='EXC', note=str(e)[:90])
                    heights[key] = row
                    flag = '' if row.get('status') == 200 else ('  <== %s' % row.get('note', row.get('status')))
                    print('  %-10s %-22s %-5s %s  h=%-6s%s' % (
                        role, name, width_name, row.get('status'), row.get('scroll'), flag))
                    if row.get('status') != 200 and not (row.get('status') == 404 and path in PENDING_V3):
                        fails.append('%s %s %s -> %s' % (role, name, width_name, row.get('status')))
            ctx.close()
        browser.close()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with open(OUT_ROOT / 'heights.json', 'w', encoding='utf-8') as f:
        json.dump(dict(base=BASE, viewports=[v[0] for v in VIEWPORTS], rows=heights,
                       generated=time.strftime('%Y-%m-%d %H:%M:%S')), f,
                  ensure_ascii=False, indent=1)

    print('\n============ M3 首页高度（DOM scrollHeight）============')
    print('%-12s %-10s %-10s %-10s' % ('角色', '1280', '768', '375'))
    for role in ['guest'] + roles:
        for name, _path in PAGES.get(role, []):
            if name not in M3_PAGES:
                continue
            cells = []
            for width_name, _w, _h in VIEWPORTS:
                r = heights.get('%s/%s/%s' % (role, name, width_name)) or {}
                cells.append(str(r.get('scroll', '-')))
            print('%-12s %-10s %-10s %-10s' % ('%s/%s' % (role, name), *cells))
    print('\n截图目录：%s（%d 张）' % (OUT_ROOT, sum(1 for v in heights.values() if v.get('shot'))))
    print('高度数据：%s' % (OUT_ROOT / 'heights.json'))
    print('耗时 %.1fs' % (time.time() - t0))
    if admin_face_unverified:
        print('\n[!] --with-admin 请求了 admin 面，但 PAGES 里没有 admin 条目 ⇒ '
              '**admin 面本轮未采样（未验证）**，该参数当前是空操作；'
              '要真正覆盖后台，请先给 PAGES 补 admin 页面清单。')
        fails.append('admin: --with-admin 空操作（PAGES 无 admin 条目）→ 未验证')
    if fails:
        print('\n-- 未达 200 的页面（%d）--' % len(fails))
        for x in fails:
            print('  ' + x)
        if login_failed and login_failed == len([r for r in roles if r in PAGES]):
            print('\n[!] 所有角色都登录失败 —— 采样窗口里 web 大概率在重启；若刚换过凭据，'
                  '也可能是口令错（EDU_<角色>_PASSWORD 覆盖）；**本份样本作废** —— '
                  '"没登上"≠"页面没问题"。等三步探活通过（无锁 / 容器 Up>30s / '
                  '带 cookie 探活 200/302/303）后重跑。')
            return 2
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description='v3 截图矩阵 + DOM 高度')
    ap.add_argument('--role', action='append', choices=ROLE_ORDER, help='只跑指定角色')
    ap.add_argument('--with-admin', action='store_true', help='追加 admin（后台页）')
    ap.add_argument('--page', help='只跑页名包含该子串的页面（如 home）')
    ap.add_argument('--no-shots', action='store_true', help='只量高度不落 PNG')
    args = ap.parse_args()
    roles = args.role or ROLE_ORDER
    if args.with_admin and 'admin' not in roles:
        roles = roles + ['admin']
    return run(roles, only_page=args.page, with_admin=args.with_admin, no_shots=args.no_shots)


if __name__ == '__main__':
    sys.exit(main())
