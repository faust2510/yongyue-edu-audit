#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""role=menu 那批 aria-* 的**机制性**查证（只查不修）：谁给的 role、能不能改、改了什么代价。

## 它回答什么

后台 7 页里稳定出现的 6 条「只读数」违规（aria-required-children ×3 / aria-required-parent ×1
/ aria-allowed-attr ×2）**不是同一件事**。本脚本把每一类钉到**具体元素 + 具体核心模板**上，
并在**浏览器内存里**做 7 组对照实验（不改仓库、不改数据库、不发写请求）：
    E0 基线 ｜ E1 去掉 systray 的 role=menu ｜ E2 去掉 sections 的 role=menu ｜ E3 两个都去
    E4 两个都换成 role=toolbar ｜ E5 给子项补 role=menuitem ｜ E6 去掉 o_menu_brand 的 menuitem
    E7 去 sections 的 menu **同时**去其子项的 menuitem
每组都**整页跑一次 axe**，并打印**所有** aria 规则的条数变化 —— 这样「去掉 role=menu 会不会
引出别的规则」是**实测**，不是推测。

## 跑法

    python3 tests/smoke/a11y_menu_role_probe.py                    # /odoo/contacts + /odoo/students
    python3 tests/smoke/a11y_menu_role_probe.py --path /odoo/batches --dump

## 退出码

0 = 量到（**只读工具，不判门禁**）｜ 1 = 某页量不到 ｜ 2 = ENV（锁 / 站点 / 登录 / 浏览器）
## 自清

只读：认证 + GET + **内存里改 DOM**；改完即关上下文，不落任何持久状态。
"""
import argparse
import json
import os
import sys

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
LOGIN = (os.environ.get('A11Y_BO_LOGIN', 'backoffice@local'),
         os.environ.get('A11Y_BO_PWD', 'demo123'))
DEFAULT_PATHS = ('/odoo/contacts', '/odoo/students', '/odoo/contacts/1')
ARIA_RULES = ('aria-required-children', 'aria-required-parent', 'aria-allowed-attr',
              'aria-prohibited-attr', 'aria-roles', 'aria-command-name', 'aria-allowed-role')

EXPERIMENTS = [
    ('E0', '基线（不动 DOM）', 'void 0;'),
    ('E1', '去掉 .o_menu_systray 的 role=menu',
     "const e=document.querySelector('.o_menu_systray'); if(e) e.removeAttribute('role');"),
    ('E2', '去掉 .o_menu_sections 的 role=menu',
     "const e=document.querySelector('.o_menu_sections'); if(e) e.removeAttribute('role');"),
    ('E3', 'E1 + E2 都去',
     "['.o_menu_systray','.o_menu_sections'].forEach(s=>{const e=document.querySelector(s); if(e) e.removeAttribute('role');});"),
    ('E4', '两个容器 role=menu → role=toolbar',
     "['.o_menu_systray','.o_menu_sections'].forEach(s=>{const e=document.querySelector(s); if(e) e.setAttribute('role','toolbar');});"),
    ('E5', '给容器里**直接子元素中非 menuitem 的**补 role=menuitem（「补 menuitem」方向）',
     "['.o_menu_systray','.o_menu_sections'].forEach(s=>{const c=document.querySelector(s); if(!c) return;"
     " [...c.children].forEach(ch=>{ if(!ch.getAttribute('role')) ch.setAttribute('role','menuitem'); });});"),
    ('E6', '去掉 .o_menu_brand 的 role=menuitem（第三条路：只动 brand）',
     "const e=document.querySelector('.o_menu_brand'); if(e) e.removeAttribute('role');"),
    ('E7', '去 sections 的 role=menu **同时**去其子项的 role=menuitem（APG 化）',
     "const c=document.querySelector('.o_menu_sections'); if(c){ c.removeAttribute('role');"
     " c.querySelectorAll('[role=\"menuitem\"]').forEach(e=>e.removeAttribute('role')); }"),
    ('E8', '只给 .o_menu_sections 的**直接 button 子元素**补 role=menuitem（对齐 APG，不动 systray）',
     "const c=document.querySelector('.o_menu_sections'); if(c){ [...c.children]"
     " .filter(e=>e.tagName==='BUTTON').forEach(e=>e.setAttribute('role','menuitem')); }"),
    ('E9', 'E1+E6：只做两处「纯收益」属性改（systray 去 menu、brand 去 menuitem）',
     "const a=document.querySelector('.o_menu_systray'); if(a) a.removeAttribute('role');"
     " const b=document.querySelector('.o_menu_brand'); if(b) b.removeAttribute('role');"),
    ('E11', '只给两个容器里**直接的 button 子元素**补 role=menuitem（外科式「补 menuitem」）',
     "['.o_menu_systray','.o_menu_sections'].forEach(s=>{const c=document.querySelector(s); if(!c) return;"
     " [...c.children].filter(e=>e.tagName==='BUTTON').forEach(e=>e.setAttribute('role','menuitem'));});"),
    ('E12', 'E1+E6+E8：三处属性改（systray 去 menu、brand 去 menuitem、sections 的 button 补 menuitem）',
     "const a=document.querySelector('.o_menu_systray'); if(a) a.removeAttribute('role');"
     " const b=document.querySelector('.o_menu_brand'); if(b) b.removeAttribute('role');"
     " const c=document.querySelector('.o_menu_sections'); if(c){ [...c.children]"
     " .filter(e=>e.tagName==='BUTTON').forEach(e=>e.setAttribute('role','menuitem')); }"),
    ('E13', '给 .o_notebook 的 ul.nav-tabs 补 role=tablist（**不是 navbar**：表单页的 tab）',
     "document.querySelectorAll('.o_notebook ul.nav-tabs').forEach(u=>u.setAttribute('role','tablist'));"),
    ('E14', 'E12 + E13 合并',
     "const a=document.querySelector('.o_menu_systray'); if(a) a.removeAttribute('role');"
     " const b=document.querySelector('.o_menu_brand'); if(b) b.removeAttribute('role');"
     " const c=document.querySelector('.o_menu_sections'); if(c){ [...c.children]"
     " .filter(e=>e.tagName==='BUTTON').forEach(e=>e.setAttribute('role','menuitem')); }"
     " document.querySelectorAll('.o_notebook ul.nav-tabs').forEach(u=>u.setAttribute('role','tablist'));"),
    ('E10', 'E1+E6+E8+E11：四路合并（能去 menu 的去 menu、该补 menuitem 的补）',
     "const a=document.querySelector('.o_menu_systray'); if(a) a.removeAttribute('role');"
     " const b=document.querySelector('.o_menu_brand'); if(b) b.removeAttribute('role');"
     " ['.o_menu_systray','.o_menu_sections'].forEach(s=>{const c=document.querySelector(s); if(!c) return;"
     " [...c.children].filter(e=>e.tagName==='BUTTON').forEach(e=>e.setAttribute('role','menuitem'));});"),
]

RUN_JS = r"""async (mode) => {
  const q = (s) => document.querySelectorAll(s).length;
  const snap = () => ({
    sections_role_menu: q('.o_menu_sections[role=menu]'),
    systray_role_menu: q('.o_menu_systray[role=menu]'),
    menuitem: q('[role=menuitem]'),
    brand_menuitem: q('.o_menu_brand[role=menuitem]'),
    nomenu_menuitem: [...document.querySelectorAll('[role=menuitem]')]
        .filter(e => !e.closest('[role=menubar],[role=menu],[role=group]')).length,
  });
  const run = async () => {
    const r = await axe.run(document, {resultTypes: ['violations'],
        runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa']}});
    const out = {};
    (r.violations || []).forEach(v => {
      out[v.id] = (v.nodes || []).map(n => ({t: n.target.join(' '),
        nav: !!(n.target.length && document.querySelector(n.target.join(' ')) &&
                document.querySelector(n.target.join(' ')).closest('.o_navbar'))}));
    });
    return out;
  };
  const before = await run();
  MODE_BODY
  const after = await run();
  return {before: before, after: after, snap_before: snap(), snap_after: snap()};
}""".replace('  MODE_BODY', '  {MODE}\n')


def probe_session():
    """就绪探针专用 Session：trust_env=False（理由见 a11y_ax_tree_probe.probe_session）。"""
    s = requests.Session()
    s.trust_env = False
    return s


def lock_path():
    return os.path.join(os.environ.get('TMPDIR') or '/tmp', 'edu19_upgrade.lock')


def preflight():
    if os.path.isdir(lock_path()):
        return '有升级在进行（%s 存在）' % lock_path()
    try:
        r = probe_session().get(BASE + '/web/login?db=' + DB, timeout=15, allow_redirects=False)
    except Exception as exc:
        return '站点不可达：%s' % exc
    if r.status_code not in (200, 302, 303):
        return '站点未就绪（/web/login → %s）' % r.status_code
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', json={'jsonrpc': '2.0', 'params': {
        'db': DB, 'login': LOGIN[0], 'password': LOGIN[1]}}, timeout=25)
    if r.status_code != 200:
        return '登录失败（HTTP %s）' % r.status_code
    if r.json().get('error'):
        return '登录被拒（%s）' % json.dumps(r.json()['error'])[:120]
    return [{'name': c.name, 'value': c.value, 'domain': 'localhost',
             'path': c.path or '/'} for c in s.cookies]


def fmt(counts):
    if not counts:
        return '（无 aria-* 违规）'
    return ' ｜ '.join('%s x%d%s' % (k, len(v), '（导航栏内 %d）' % len([x for x in v if x['nav']]))
                      for k, v in sorted(counts.items()))


def main():
    ap = argparse.ArgumentParser(description='role=menu 机制查证（只读 + 内存实验）')
    ap.add_argument('--path', default=','.join(DEFAULT_PATHS))
    ap.add_argument('--dump', action='store_true', help='打印每个命中的选择器')
    ap.add_argument('--json', dest='json_out')
    args = ap.parse_args()

    pre = preflight()
    if isinstance(pre, str):
        print('ENV：%s ⇒ 本轮作废（不是判据失败，也不当通过）' % pre)
        return 2
    cookies = pre
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print('ENV：playwright 不可用：%s' % exc)
        return 2

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
    import check_accessibility as GATE

    paths = [p.strip() for p in args.path.split(',') if p.strip()]
    fails, rows = [], {}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel='chrome', headless=True, args=['--no-proxy-server'])
            for path in paths:
                ctx = b.new_context(viewport={'width': 1280, 'height': 900}, locale='zh-CN')
                ctx.add_cookies(cookies)
                print('== %s ==' % path)
                got = {}
                for tag, label, body in EXPERIMENTS:
                    pg = ctx.new_page()
                    try:
                        r = pg.goto(BASE + path, wait_until='domcontentloaded', timeout=90000)
                        status = r.status if r else 0
                        pg.wait_for_selector('.o_navbar', timeout=25000)
                        pg.wait_for_timeout(2500 if tag == 'E0' else 1500)
                        pg.add_script_tag(content=GATE.axe_source()[0] or '')
                        if tag == 'E0':
                            pg.wait_for_timeout(1200)
                        js = RUN_JS.replace('{MODE}', body)
                        res = pg.evaluate(js)
                        got[tag] = dict(res, label=label, status=status)
                        print('  %-3s %-46s 前：%s' % (tag, label[:46],
                                                      fmt(dict((k, v) for k, v in res['before'].items()
                                                               if k.startswith('aria-')))))
                        if tag != 'E0':
                            _b, _a = res['before'], res['after']
                            gained = sorted(k for k in _a if k not in _b)
                            lost = sorted(k for k in _b if k not in _a)
                            # ⚠ 只对**非 aria** 规则额外报警：题目要的是「去掉 role=menu 会不会引出别的规则」
                            nonaria = sorted(k for k in set(list(gained) + list(lost))
                                             if not k.startswith('aria-'))
                            print('      %-46s 后：%s'
                                  % ('', fmt(dict((k, v) for k, v in _a.items()
                                                  if k.startswith('aria-')))))
                            print('      %-46s Δ规则：新增 %s ｜ 消失 %s ｜ menuitem %d→%d ｜ 失父 menuitem %d→%d'
                                  % ('', gained or '无', lost or '无',
                                     res['snap_before']['menuitem'], res['snap_after']['menuitem'],
                                     res['snap_before']['nomenu_menuitem'],
                                     res['snap_after']['nomenu_menuitem']))
                            if nonaria:
                                print('      %-46s ⚠ 非 aria 规则也变了（需人工看）：%s'
                                      % ('', nonaria))
                        if args.dump:
                            for phase in ('before', 'after'):
                                for rid, nodes in sorted(res[phase].items()):
                                    for n in nodes:
                                        print('        [%s/%s] %s %s'
                                              % (tag, phase, rid, n['t'][:80]))
                    except Exception as exc:
                        fails.append('%s %s：量不到（%s）' % (path, tag, str(exc)[:90]))
                        print('  %-3s EXC %s' % (tag, str(exc)[:90]))
                    finally:
                        pg.close()
                ctx.close()
                rows[path] = got
            b.close()
    except Exception as exc:
        print('ENV：浏览器不可用（%s）' % str(exc)[:120])
        return 2

    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)
        print('-> %s' % args.json_out)
    if fails:
        print('RESULT=FAIL')
        for f in fails:
            print('  - %s' % f)
        return 1
    print('RESULT=OK：%d 页 × %d 组实验全部量到（只读工具；结论见报告与 UX_V3_GATE.md §12）'
          % (len(paths), len(EXPERIMENTS)))
    return 0


if __name__ == '__main__':
    sys.exit(main())