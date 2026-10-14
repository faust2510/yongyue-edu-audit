#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""班级分配与管理（需求 7）**浏览器真机**验证（Playwright）：六步闸门第 6 步的 UI 面。

为什么还要这一支：tests/smoke/class_batch_mgmt.py 走的是 JSON-RPC + SQL，
能证明「写对了」，但证明不了「教务点得到、看得见」——本仓的规矩是
**改了入口必须有『打完就摸页面』的判据**（docs/dev-workflow.md 陷阱 2）。
本脚本用真实浏览器点：学生页的「分配班级」按钮、班级列表的「停用/恢复」与 ☰ 归档项、
回收站菜单、教师侧的批次菜单入口，并断言**页面上真的发生了**（不是只看 HTTP 200）。

用法：python3 tests/smoke/class_batch_mgmt_ui.py
结果落盘：tests/smoke/class_batch_mgmt_ui_results.json
截图：/tmp/cbm_ui/（失败时尤其要看）
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = os.environ.get('CBM_BASE', 'http://127.0.0.1:8069')
DB = os.environ.get('EDU_DB_NAME', 'edu19')
REPO = Path(__file__).resolve().parent.parent.parent
SHOTS = Path('/tmp/cbm_ui')
RESULTS_JSON = Path(__file__).resolve().parent / 'class_batch_mgmt_ui_results.json'

TAG = '【演示】班级分配UI冒烟'
STU_NAME = '班级分配UI冒烟生【演示】'
LOGIN_STU = 'cbm_ui_stu@local'
CODE_STU = 'CBM-UI-STU'
COURSE_NAME = '预备科'

BACKOFFICE = ('backoffice@local', 'demo123')
TEACHER = ('faculty@local', 'demo123')

RESULTS = []
FX = {}


def check(no, name, ok, detail=''):
    RESULTS.append({'no': no, 'name': name, 'pass': bool(ok),
                    'detail': str(detail)[:600]})
    print('  [%s] %-6s %s%s' % ('PASS' if ok else 'FAIL', no, name,
                                (' | ' + str(detail)[:300]) if detail else ''))
    return bool(ok)


def psql(sql):
    out = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'psql',
                          '-U', 'odoo', '-d', DB, '-tAc', sql],
                         capture_output=True, text=True, timeout=180, cwd=str(REPO))
    if out.returncode != 0:
        raise RuntimeError('psql: ' + (out.stderr or '')[:300])
    return out.stdout.strip()


def pscalar(sql):
    return int(psql(sql) or 0)


def shell_json(body, timeout=420):
    code = ('import json\nOUT = {}\n' + body +
            "\nprint('@@CBMUI@@' + json.dumps(OUT, ensure_ascii=False, "
            "default=str))\n")
    cmd = ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
           '-c', '/etc/odoo/odoo.conf', '--db_host=db', '--db_port=5432',
           '--db_user=odoo', '--db_password=odoo', '-d', DB, '--no-http']
    out = subprocess.run(cmd, input=code, capture_output=True, text=True,
                         timeout=timeout, cwd=str(REPO))
    blob = (out.stdout or '') + (out.stderr or '')
    m = re.search(r'@@CBMUI@@(.*)', blob)
    if not m:
        Path('/tmp/cbm_ui_shell_fail.txt').write_text(blob)
        raise RuntimeError('shell 未返回 JSON：' + blob[-800:])
    return json.loads(m.group(1))


FIX = """
import json
from odoo import fields
OUT = {}
env = env
TAG = @@TAG@@
LOGIN = @@LOGIN@@
CODE = @@CODE@@
NAME = @@NAME@@
Bd = env['op.batch'].sudo().with_context(active_test=False)
Se = env['op.session'].sudo().with_context(active_test=False)
Sc = env['op.student.course'].sudo().with_context(active_test=False)
St = env['op.student'].sudo().with_context(active_test=False)
Us = env['res.users'].sudo().with_context(active_test=False)
Pa = env['res.partner'].sudo().with_context(active_test=False)
Ic = env['edu.invite.code'].sudo()

# 幂等清场（只按本脚本的标记）
batches = Bd.search([('name', 'like', TAG + '%')])
users = Us.search([('login', '=', LOGIN)])
students = St.search([('name', 'like', '%班级分配UI冒烟%')])
students |= St.search([('user_id', 'in', users.ids)])
if batches:
    Se.search([('batch_id', 'in', batches.ids)]).unlink()
    Sc.search([('batch_id', 'in', batches.ids)]).unlink()
if students:
    Sc.search([('student_id', 'in', students.ids)]).unlink()
codes = Ic.search([('code', '=', CODE)])
partners = students.mapped('partner_id') | users.mapped('partner_id')
if students:
    students.unlink()
if codes:
    codes.unlink()
if users:
    users.unlink()
for p in partners:
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass
if batches:
    batches.unlink()
env.cr.commit()

b = Bd.create({'name': TAG + '·甲班', 'code': 'CBM-UI-A', 'course_id': 18,
               'start_date': '2026-09-01', 'end_date': '2027-07-31'})
sub = env['op.course'].sudo().browse(18).subject_ids[:1]
fac = Se.search([('batch_id', '=', 8)], limit=1).faculty_id
today = fields.Date.today().strftime('%Y-%m-%d')
Se.create({'course_id': 18, 'batch_id': b.id,
           'subject_id': sub.id, 'faculty_id': fac.id,
           'start_datetime': today + ' 18:15:00',
           'end_datetime': today + ' 19:00:00', 'state': 'draft'})
partner = Pa.create({'name': NAME})
user = Us.create({'name': NAME, 'login': LOGIN, 'password': 'demo123',
                  'partner_id': partner.id,
                  'group_ids': [(6, 0, [env.ref('base.group_portal').id])]})
code = Ic.create({'code': CODE, 'code_kind': 'tier', 'tier': 'student',
                  'use_limit': 0, 'note': TAG})
stu = code.create_pending_archive(user, NAME)
env.cr.commit()
OUT['batch'] = b.id
OUT['student'] = stu.id
OUT['student_name'] = stu.name
OUT['pending'] = bool(stu.edu_pending_setup)
OUT['course_id'] = 18
"""

CLEAN = """
env = env
Sc = env['op.student.course'].sudo().with_context(active_test=False)
St = env['op.student'].sudo().with_context(active_test=False)
Us = env['res.users'].sudo().with_context(active_test=False)
Pa = env['res.partner'].sudo().with_context(active_test=False)
Bd = env['op.batch'].sudo().with_context(active_test=False)
Se = env['op.session'].sudo().with_context(active_test=False)
Ic = env['edu.invite.code'].sudo()
TAG = @@TAG@@
LOGIN = @@LOGIN@@
batches = Bd.search([('name', 'like', TAG + '%')])
users = Us.search([('login', '=', LOGIN)])
students = St.search([('name', 'like', '%班级分配UI冒烟%')])
students |= St.search([('user_id', 'in', users.ids)])
if batches:
    Se.search([('batch_id', 'in', batches.ids)]).unlink()
    Sc.search([('batch_id', 'in', batches.ids)]).unlink()
if students:
    Sc.search([('student_id', 'in', students.ids)]).unlink()
Ic.search([('note', '=', TAG)]).unlink()
partners = students.mapped('partner_id') | users.mapped('partner_id')
if students:
    students.unlink()
if users:
    users.unlink()
for p in partners:
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass
if batches:
    batches.unlink()
env.cr.commit()
OUT['leftover_batch'] = Bd.search_count([('name', 'like', TAG + '%')])
OUT['leftover_student'] = St.search_count([('name', 'like', '%班级分配UI冒烟%')])
OUT['leftover_user'] = Us.search_count([('login', '=', LOGIN)])
"""


def fmt(tpl, **kw):
    out = tpl
    for k, v in kw.items():
        out = out.replace('@@%s@@' % k.upper(), json.dumps(v))
    return out


def login(page, user, pwd):
    """登录：先用 requests 拿 session（本仓 /web/login 被 edu_portal 改写成
    主题页，登录表单默认 d-none、要用站点 JS 才显示），再把 session_id 注进
    浏览器上下文 —— 之后所有页面都是**真实浏览器渲染**的后台页面。"""
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', timeout=30, json={
        'jsonrpc': '2.0', 'method': 'call',
        'params': {'db': DB, 'login': user, 'password': pwd}})
    uid = ((r.json() or {}).get('result') or {}).get('uid')
    sid = s.cookies.get('session_id')
    if not (uid and sid):
        raise RuntimeError('登录失败 user=%s uid=%s' % (user, uid))
    page.context.add_cookies([{'name': 'session_id', 'value': sid,
                               'url': BASE}])
    return uid


def confirm_dialog(page):
    """点掉 Odoo 的确认弹窗（返回实际命中的选择器 —— 留给证据用）。

    ⚠ 别只写 .modal button.btn-primary：Odoo 19 的对话框是 .o_dialog，
    且页面里可能有多个 .o_dialog（第一个常是隐藏的），点了不生效还不报错。
    """
    for sel in ('.o_dialog button:has-text("确定")',
                '.o_dialog button:has-text("OK")',
                '.modal button:has-text("确定")',
                '.o_dialog button.btn-primary',
                '.modal button.btn-primary'):
        loc = page.locator(sel)
        n = loc.count()
        for i in range(n):
            try:
                if loc.nth(i).is_visible():
                    loc.nth(i).click()
                    return sel
            except Exception:
                continue
    return None


def text_of(loc, limit=200):
    """安全取文本（空态不抛异常、不空等 30s）—— 判据自己要先把"取不到"当合法态。"""
    try:
        if loc.count() == 0:
            return ''
        return (loc.first.inner_text(timeout=5000) or '')[:limit]
    except Exception as exc:
        return '<取不到文本：%s>' % repr(exc)[:60]


def shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(SHOTS / (name + '.png')), full_page=True)
    except Exception:
        pass


# Odoo 19 的 Many2one 下拉在不同组件里类名不同，逐个试（都属"事实"而非猜测）
_DROP = ['.o_dialog .dropdown-item', '.modal .dropdown-item',
         '.o-autocomplete--dropdown-item', '.dropdown-menu.show .dropdown-item',
         'body > .dropdown-menu .dropdown-item', '.o_field_many2one .dropdown-item']


def pick_many2one(page, field, text):
    """在 Many2one 字段里选一条：聚焦 → 输入 → 点命中项（点不到就回车选第一项）。"""
    box = page.locator('div[name="%s"] input' % field).last
    box.wait_for(state='visible', timeout=20000)
    box.click()
    box.fill(text)
    page.wait_for_timeout(1500)
    for sel in _DROP:
        items = page.locator(sel)
        n = items.count()
        for i in range(n):
            try:
                t = items.nth(i).inner_text(timeout=2000) or ''
            except Exception:
                continue
            if text in t and items.nth(i).is_visible():
                items.nth(i).click()
                page.wait_for_timeout(900)
                return t
    box.press('ArrowDown')
    box.press('Enter')
    page.wait_for_timeout(900)
    return '<回车兜底：%s>' % text


def main():
    rc = 0
    try:
        fx = shell_json(fmt(FIX, tag=TAG, login=LOGIN_STU, code=CODE_STU,
                            name=STU_NAME))
    except Exception as exc:
        check('UI0', '夹具建立', False, repr(exc)[:300])
        return write(1)
    FX.update(fx)
    check('UI0.1', '夹具：【待分配】学生 + 有课节的演示班',
          fx['student_name'].startswith('【待分配】') and fx['batch'] > 0,
          'student=%s batch=%s' % (fx['student'], fx['batch']))
    url_stu = '%s/odoo/students/%d?db=%s' % (BASE, fx['student'], DB)
    # ?view_type=list：学生动作默认开**看板**，行内按钮只在列表视图里；
    # 显式钉住视图类型，避免"载体不是列表"导致的假红/假绿。
    url_stu_list = '%s/odoo/students?view_type=list&db=%s' % (BASE, DB)
    url_bat = '%s/odoo/batches?db=%s' % (BASE, DB)
    url_bin = '%s/odoo/batches-stopped?db=%s' % (BASE, DB)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale='zh-CN',
                                  viewport={'width': 1440, 'height': 1000})
        page = ctx.new_page()

        # ============ 一、教务：学生页面「分班」（主入口 = 学生列表行内按钮） ============
        login(page, *BACKOFFICE)
        page.goto(url_stu_list, wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        shot(page, '00_student_list_backoffice')
        # 用搜索框筛到这一名学生（= 教务日常：先筛「待分配」，再逐个分班）
        search = page.locator('.o_searchview_input')
        check('UI1.0', '学生列表有搜索框（教务可按姓名/待分配筛）',
              search.count() >= 1)
        if search.count() >= 1:
            search.first.click()
            search.first.type(STU_NAME, delay=20)
            page.keyboard.press('Enter')
            page.wait_for_timeout(2500)
        shot(page, '01_student_list_filtered')
        check('UI1.0b', '载体合法：确实是**列表视图**（不是看板）',
              page.locator('.o_list_view').count() >= 1,
              '列表容器数=%s' % page.locator('.o_list_view').count())
        rows = page.locator('.o_data_row')
        check('UI1.0c', '筛选后列表里正好是这名学生一行',
              rows.count() == 1 and STU_NAME in text_of(rows),
              '行数=%s · 行文本=%s' % (rows.count(), text_of(rows, 90)))
        btn = page.locator('button[name="action_edu_assign_batch"]')
        check('UI1.1', '教务在学生列表看到这一行的「分班」按钮',
              btn.count() >= 1 and btn.first.is_visible(),
              '按钮数=%s' % btn.count())
        btn.first.click()
        page.wait_for_timeout(3000)
        shot(page, '02_assign_dialog')
        dlg = page.locator('.o_dialog, .modal').last
        check('UI1.2', '点开是「分班」对话框且标题带学生名',
              ('分班' in (dlg.inner_text() or ''))
              and (STU_NAME in (dlg.inner_text() or '')),
              text_of(dlg, 130).replace('\n', ' '))
        try:
            page.wait_for_selector('div[name="course_id"] input',
                                   timeout=25000)
            got_form = True
        except Exception as exc:
            got_form = False
            check('UI1.3', '分班表单（课程/班级）出现', False, repr(exc)[:200])
        if got_form:
            check('UI1.3', '分班表单出现且学生已预填（default_student_id 生效）',
                  STU_NAME in text_of(page.locator('.o_dialog').last, 600),
                  text_of(page.locator('.o_dialog').last, 130)
                  .replace('\n', ' '))
            got_course = pick_many2one(page, 'course_id', COURSE_NAME)
            check('UI1.4', '选了课程', COURSE_NAME in got_course, got_course)
            page.wait_for_timeout(900)
            got_batch = pick_many2one(page, 'batch_id', '甲班')
            check('UI1.5', '选了班级', '甲班' in got_batch, got_batch)
            page.wait_for_timeout(900)
            shot(page, '03_assign_filled')
            save = page.locator(
                '.o_dialog button.o_form_button_save, '
                '.o_dialog button:has-text("保存"), '
                '.modal button:has-text("保存"), '
                '.o_dialog button:has-text("Save")')
            check('UI1.6', '分班表单有保存按钮', save.count() >= 1)
            if save.count() >= 1:
                save.first.click()
                page.wait_for_timeout(3500)
        shot(page, '05_after_save')
        # 保存没有报错（页面无红条 "Missing required fields" 之类）
        check('UI1.6b', '保存没有报"必填"错误（分班表单不带费用必填）',
              'Missing required' not in (page.locator('body').inner_text()
                                         or ''))
        row = psql('select coalesce(batch_id,0) from op_student_course '
                   'where student_id=%d' % fx['student'])
        check('UI1.7', '浏览器保存后库里有了班级档案（UI 写路径真跑通）',
              row.strip() == str(fx['batch']), 'batch_id=%s' % row.strip())
        nm = psql('select p.name from res_partner p join op_student s on '
                  's.partner_id=p.id where s.id=%d' % fx['student'])
        check('UI1.8', '分班后名字里的「【待分配】」已被去掉',
              not nm.startswith('【待分配】'), 'name=%s' % nm)
        flag = psql('select edu_pending_setup from op_student where id=%d'
                    % fx['student'])
        check('UI1.9', 'edu_pending_setup 已清', flag.strip() in ('f', ''),
              'flag=%s' % flag.strip())
        # 学生**表单**上也有入口（截图留证）；如实登记一个真实边界：
        # 表单里任何 object 按钮都会先保存记录，而【待分配】档案缺 first_name
        # （基座表单标了 required）⇒ 表单按钮在这种档案上会被自己的保存挡下，
        # 所以主入口用的是列表行内按钮（上面 UI1.1 那条）。
        page.goto(url_stu, wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        shot(page, '01b_student_form_backoffice')
        fbtn = page.locator('button[name="action_edu_assign_batch"]')
        check('UI1.10', '学生表单上也有「分配班级」按钮（截图留证）',
              fbtn.count() >= 1 and fbtn.first.is_visible(),
              '按钮数=%s' % fbtn.count())
        check('UI1.11', '学生表单有「班级与课程」页签（看得见现在在哪个班）',
              page.locator('a.nav-link:has-text("班级与课程")').count() >= 1)
        # 教务日常入口：学生列表的「待分配（未分班）」过滤器
        page.goto(url_stu_list, wait_until='domcontentloaded')
        page.wait_for_timeout(2500)
        tog = page.locator('button.o_searchview_dropdown_toggler')
        if tog.count() >= 1:
            tog.first.click()
            page.wait_for_timeout(1200)
        shot(page, '01c_pending_filter')
        panel = text_of(page.locator('.o_search_panel, .o_cp_searchview, '
                                     '.o_searchview_dropdown, body'), 4000)
        check('UI1.12', '学生列表有「待分配（未分班）」过滤器（教务日常入口）',
              '待分配（未分班）' in panel,
              '含过滤器=%s' % ('待分配（未分班）' in panel))

        # ============ 二、教务：班级列表（状态列 / 停用按钮 / ☰ 归档项） ============
        page.goto(url_bat, wait_until='domcontentloaded')
        page.wait_for_timeout(2500)
        shot(page, '06_batch_list_backoffice')
        body = page.locator('.o_content').inner_text() or ''
        check('UI2.1', '班级列表看得见演示班', TAG in body)
        check('UI2.2', '列表上有「状态」列（active 已进视图）',
              '状态' in body, body[:80].replace('\n', ' '))
        stop_btn = page.locator('button[name="action_edu_stop"]')
        check('UI2.3', '教务在列表上看得见「停用」按钮（校长拍板用词）',
              stop_btn.count() >= 1, '按钮数=%s' % stop_btn.count())
        # ☰ 菜单（Odoo 自带归档项 = 回收站能力的必要条件）
        # 选择器取自实机 DOM dump：控制面板上的「操作」菜单 = button[data-hotkey="u"]，
        # 未选中任何行时其 data-tooltip="操作"、aria-label="操作菜单"。
        cog = page.locator('.o_control_panel button[data-hotkey="u"]')
        check('UI2.4', '班级列表有 ☰（操作菜单）按钮', cog.count() >= 1,
              '匹配数=%s' % cog.count())
        # ⚠ 未选中任何行时 ☰ 里只有「导入记录/仪表板」——归档项要选中行才出现
        row_b = page.locator('.o_data_row', has_text=TAG).first
        check('UI2.4b', '列表里找得到演示班那一行（按唯一名定位，不按第 N 条）',
              row_b.count() == 1, text_of(row_b, 80).replace('\n', ' '))
        if row_b.count() == 1:
            row_b.locator('td.o_list_record_selector input, '
                          '.o_list_record_selector input').first.click()
            page.wait_for_timeout(1200)
        if cog.count() >= 1:
            cog.first.click()
            page.wait_for_timeout(1200)
            shot(page, '07_cog_menu')
            menu = page.locator('.dropdown-menu.show, .o-dropdown--menu').last
            mtext = menu.inner_text() or ''
            check('UI2.5', '☰ 里有「归档 / 存档」项（含 active 字段才会出现）',
                  ('归档' in mtext) or ('存档' in mtext),
                  mtext.replace('\n', ' ')[:200])

        # ============ 三、教务：停用 → 回收站可见 → 恢复 ============
        page.keyboard.press('Escape')
        page.wait_for_timeout(500)
        # ⚠ 必须**按班级名定位这一行**再点它的按钮：第一版用 stop_btn.first，
        # 结果停用的是列表第一行（预备科 · 2026级【演示】）—— 判据引用对象
        # 用了"第 N 条"这种非唯一键（dev-workflow 同族教训）。本版按 TAG 唯一名取行。
        stop_btn = row_b.locator('button[name="action_edu_stop"]')
        used_ok = None
        if stop_btn.count() >= 1:
            stop_btn.first.click()
            page.wait_for_timeout(1500)
            shot(page, '08_stop_confirm')
            used_ok = confirm_dialog(page)
            page.wait_for_timeout(3000)
        check('UI3.0', '「停用」有确认弹窗（防手滑）', bool(used_ok),
              '确认按钮选择器=%s' % used_ok)
        active = psql('select active from op_batch where id=%d' % fx['batch'])
        check('UI3.1', '界面上点「停用」后库里 active=false',
              active.strip() == 'f', 'active=%s' % active.strip())
        page.reload(wait_until='domcontentloaded')
        page.wait_for_timeout(2500)
        shot(page, '09_list_after_stop')
        body2 = page.locator('.o_content').inner_text() or ''
        check('UI3.2', '停用后默认列表里看不见它（回收站语义）', TAG not in body2)
        restore_btn = page.locator('button[name="action_edu_restore"]')
        check('UI3.3', '默认列表里没有「恢复」按钮（它不在使用中列表里）',
              restore_btn.count() == 0, '按钮数=%s' % restore_btn.count())
        # 回收站菜单页面
        page.goto(url_bin, wait_until='domcontentloaded')
        page.wait_for_timeout(2500)
        shot(page, '10_recycle_bin')
        body3 = page.locator('.o_content').inner_text() or ''
        check('UI3.4', '「已停用班级」回收站页面看得见它', TAG in body3,
              body3[:120].replace('\n', ' '))
        row_r = page.locator('.o_data_row', has_text=TAG).first
        rb = row_r.locator('button[name="action_edu_restore"]')
        check('UI3.5', '回收站里这一行有「恢复」按钮（同样按唯一名定位）',
              rb.count() >= 1, '按钮数=%s · 行=%s'
              % (rb.count(), text_of(row_r, 80).replace('\n', ' ')))
        if rb.count() >= 1:
            rb.first.click()
            page.wait_for_timeout(3000)
            shot(page, '11_after_restore')
        active2 = psql('select active from op_batch where id=%d' % fx['batch'])
        check('UI3.6', '界面上点「恢复」后库里 active=true（回得来）',
              active2.strip() == 't', 'active=%s' % active2.strip())
        ids = psql('select count(*) from op_batch where id=%d and active'
                   % fx['batch'])
        check('UI3.7', '恢复后它回到使用中集合（active 查询命中）',
              ids.strip() == '1')

        # ============ 四、教师：能看见批次菜单 / 能建班 / 归档被拒 ============
        ctx2 = browser.new_context(locale='zh-CN',
                                   viewport={'width': 1440, 'height': 1000})
        page2 = ctx2.new_page()
        login(page2, *TEACHER)
        page2.goto(url_bat, wait_until='domcontentloaded')
        page2.wait_for_timeout(2500)
        shot(page2, '12_batch_list_teacher')
        tbody = page2.locator('.o_content').inner_text() or ''
        check('UI4.1', '教师能打开 /odoo/batches 并看见班名（菜单已可见）',
              TAG in tbody, tbody[:120].replace('\n', ' '))
        check('UI4.2', '教师看不到「停用」按钮（按校长拍板：归档归教务）',
              page2.locator('button[name="action_edu_stop"]').count() == 0)
        # 教师用 Odoo 自带归档 → 应被人话拒绝
        trow = page2.locator('.o_data_row',
                             has_text=TAG).first
        if trow.count() == 0:
            check('UI4.3', '教师列表里找得到演示班行', False)
        else:
            trow.locator('.o_list_record_selector input, td.o_list_record_selector input').first.click()
            page2.wait_for_timeout(800)
            cog2 = page2.locator('.o_control_panel .dropdown-toggle').last
            cog2.click()
            page2.wait_for_timeout(1200)
            menu2 = page2.locator('.dropdown-menu.show, .o-dropdown--menu').last
            mtext2 = menu2.inner_text() or ''
            check('UI4.3', '教师 ☰ 里也有「归档 / 存档」项（这正是设计稿说的陷阱）',
                  ('归档' in mtext2) or ('存档' in mtext2),
                  mtext2.replace('\n', ' ')[:160])
            arch = menu2.locator('a, span, .dropdown-item',
                                 has_text=re.compile('归档|存档')).first
            if arch.count() >= 1:
                arch.click()
                page2.wait_for_timeout(1500)
                ok2 = page2.locator('.modal button:has-text("确定"), '
                                    '.o_dialog button.btn-primary')
                if ok2.count() >= 1:
                    ok2.first.click()
                    page2.wait_for_timeout(3000)
                shot(page2, '13_teacher_archive_denied')
                red = page2.locator('.modal, .o_notification, .o_dialog').last
                rtext = red.inner_text() or ''
                check('UI4.4', '教师归档被人话拒绝（文案含「教务处」）',
                      '教务处' in rtext, rtext.replace('\n', ' ')[:220])
        active3 = psql('select active from op_batch where id=%d' % fx['batch'])
        check('UI4.5', '教师那一下没有改动数据（active 仍为 true）',
              active3.strip() == 't', 'active=%s' % active3.strip())
        ctx2.close()
        browser.close()

    # ============ 五、清理 ============
    try:
        out = shell_json(fmt(CLEAN, tag=TAG, login=LOGIN_STU))
        check('UI5.1', '清理后 leftover = 0',
              all(int(v or 0) == 0 for v in out.values()),
              json.dumps(out, ensure_ascii=False))
    except Exception as exc:
        check('UI5.1', '清理', False, repr(exc)[:300])

    fails = [r for r in RESULTS if not r['pass']]
    rc = 1 if fails else 0
    print('\n== UI 汇总：%d 条，PASS %d / FAIL %d =='
          % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    for f in fails:
        print('  FAIL %s %s | %s' % (f['no'], f['name'], f['detail'][:200]))
    return write(rc)


def write(rc):
    RESULTS_JSON.write_text(json.dumps({
        'revision': 'cb-ui1', 'base': BASE, 'db': DB,
        'fixture': FX, 'checks': RESULTS,
        'pass': len([r for r in RESULTS if r['pass']]),
        'fail': len([r for r in RESULTS if not r['pass']]), 'rc': rc,
        'shots': str(SHOTS),
    }, ensure_ascii=False, indent=2))
    print('结果落盘：%s' % RESULTS_JSON)
    return rc


if __name__ == '__main__':
    sys.exit(main())
