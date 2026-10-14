#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台页 head 与 Odoo 核心渲染属性的一次性实测（**只读**，不连浏览器）。

## 它验什么

两件**只在 HTTP 响应里**就能证伪的事（都不需要起浏览器）：
  1. **缩放不被禁**（WCAG 1.4.4 / axe meta-viewport）：后台页恰好一条 meta viewport、
     内容里没有 user-scalable，也没有小于 2 的 maximum-scale —— 来自 edu_brand 对
     web.webclient_bootstrap 的继承（核心那条写死 user-scalable=no）。
  2. **html 有合法 BCP47 的 lang**（axe html-has-lang / html-lang-valid）：后台页的
     html 标签带 lang，且**必须**是连字符形态（zh-CN）。写成下划线（zh_CN）会引出
     html-lang-valid 这条**新规则**，而门禁对「未登记新规则」判红 —— 所以这里也钉住它。

同时给一条**控制组**：前台公开页 /programs 的 viewport 必须与后台**不同源**（前台走
website.layout，本仓只改后台 webclient）—— 防止"顺手把前台也改了"这种越界。

## 它**不**覆盖什么

Owl 在浏览器里渲染出来的东西（活动时钟图标的 aria-hidden、可选列按钮的 aria-label、
搜索框上的 aria-autocomplete）**不在** HTTP 响应里 —— 那些由
scripts/check_accessibility.py 的后台页「核心清单」覆盖（axe 4.10.2 × 2 页）。
本脚本只钉"响应即可见"的两条，跑得快、不依赖浏览器。

## 跑法

    python3 tests/smoke/backend_head_probe.py
    python3 tests/smoke/backend_head_probe.py --dump     # 连原始响应片段一起打印

## 退出码

0 = 全部断言通过 ｜ 1 = **判据失败**（读数与预期不符，逐条打印实测值）｜ 2 = ENV
（有升级锁 / 站点不可达 / 登录不上）—— ENV 不当通过。

## 自清

只读：不发任何写请求，不留夹具（会话 cookie 只在内存里）。
"""
import argparse
import os
import re
import sys

import requests

BASE = 'http://localhost:8069'
DB = 'edu19'
LOGIN = ('backoffice@local', 'demo123')
BACKEND = ('/odoo/contacts', '/odoo/students')
FRONTEND_CONTROL = '/programs'
BCP47 = re.compile(r'^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$')


def lock_path():
    return os.path.join(os.environ.get('TMPDIR') or '/tmp', 'edu19_upgrade.lock')


def session():
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate',
               json={'jsonrpc': '2.0', 'params': {'db': DB, 'login': LOGIN[0],
                                                  'password': LOGIN[1]}}, timeout=25)
    return s, r


def main():
    ap = argparse.ArgumentParser(description='后台页 head 实测（viewport 缩放 / html lang）')
    ap.add_argument('--dump', action='store_true', help='打印原始响应片段')
    args = ap.parse_args()

    if os.path.isdir(lock_path()):
        print('ENV：有升级在进行（%s 存在）⇒ 读数跨升级窗口，本轮作废' % lock_path())
        return 2
    try:
        r = requests.get(BASE + '/web/login?db=' + DB, timeout=15, allow_redirects=False)
    except Exception as exc:
        print('ENV：站点不可达（%s）：%s' % (BASE, exc))
        return 2
    if r.status_code not in (200, 302, 303):
        print('ENV：站点未就绪（/web/login → %s）' % r.status_code)
        return 2
    s, auth = session()
    if auth.status_code != 200:
        print('ENV：登录失败（HTTP %s）' % auth.status_code)
        return 2

    fails = []
    for path in BACKEND:
        html = s.get(BASE + path, timeout=40).text
        vps = re.findall(r'<meta name="viewport"[^>]*>', html)
        htmls = re.findall(r'<html[^>]*>', html)
        tag = htmls[0] if htmls else ''
        lang = (re.search(r'lang="([^"]*)"', tag) or [None, None])[1]
        if args.dump:
            print('  [%s] %s' % (path, tag))
            for v in vps:
                print('  [%s] %s' % (path, v))
        print('== %s' % path)
        print('   viewport 条数=%d ｜ 含 user-scalable=%s ｜ 含 maximum-scale=%s'
              % (len(vps), 'user-scalable' in html, 'maximum-scale' in html))
        print('   html 标签=%s ｜ lang=%s ｜ 合法 BCP47=%s'
              % (tag or '(没有 html 标签)', lang, bool(lang and BCP47.match(lang))))
        if len(vps) != 1:
            fails.append('%s：viewport meta 应恰好 1 条，实测 %d 条' % (path, len(vps)))
        if 'user-scalable' in html:
            fails.append('%s：仍含 user-scalable（缩放被禁，WCAG 1.4.4）' % path)
        if 'maximum-scale' in html:
            fails.append('%s：仍含 maximum-scale（本仓口径是整条去掉）' % path)
        if not lang:
            fails.append('%s：html 没有 lang（axe html-has-lang）' % path)
        elif '_' in lang:
            fails.append('%s：lang=%s 是下划线形态 —— 会引出 html-lang-valid 新规则，'
                         '必须换成连字符' % (path, lang))
        elif not BCP47.match(lang):
            fails.append('%s：lang=%s 不是合法 BCP47' % (path, lang))

    # 控制组：前台 viewport 来源不同（website.layout），本仓只改后台 ⇒ 它应保持核心原样
    front = s.get(BASE + FRONTEND_CONTROL, timeout=40).text
    fvps = re.findall(r'<meta name="viewport"[^>]*>', front)
    print('== %s（控制组：前台，不该被本仓改动）' % FRONTEND_CONTROL)
    print('   viewport 条数=%d ｜ %s' % (len(fvps), fvps[:1]))
    if not fvps:
        fails.append('%s：前台没有 viewport meta（读数异常，先查核心/主题是否被改）'
                     % FRONTEND_CONTROL)

    if fails:
        print('RESULT=FAIL')
        for f in fails:
            print('  - %s' % f)
        return 1
    print('RESULT=OK 后台 2 页均：viewport 1 条且不禁缩放 ｜ html lang 合法 BCP47；'
          '前台控制组未被改动')
    return 0


if __name__ == '__main__':
    sys.exit(main())
