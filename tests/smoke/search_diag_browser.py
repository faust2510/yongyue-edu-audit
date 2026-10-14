#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""浏览器实测搜索框（排除「输入框本身不可用」）—— 先诊断再断言。"""
import json, sys
import requests
from playwright.sync_api import sync_playwright

BASE='http://localhost:8069'; DB='edu19'; PW='demo123'

def session_id(login):
    """用 JSON-RPC 拿 session_id 再注入浏览器（本站登录页被改成 /login 身份选择器，
    直接点它和不点它都会踩到另一件事 —— 与本任务无关，别让它掩住搜索结论）。"""
    s=requests.Session(); s.trust_env=False
    for _ in range(20):
        try:
            s.post(BASE+'/web/session/authenticate', json={'jsonrpc':'2.0','params':{
                'db':DB,'login':login,'password':PW}}, timeout=30)
            break
        except Exception:
            import time; time.sleep(4)
    return s.cookies.get('session_id')
TAG = sys.argv[1] if len(sys.argv)>1 else 'x'
OUT='tests/smoke/out_search_diag/browser_check_%s.json' % TAG
res={}

with sync_playwright() as pw:
    b=pw.chromium.launch(headless=True)
    ctx=b.new_context(locale='zh-CN', viewport={'width':1280,'height':900})
    sid=session_id('stu@local')
    res['session_id_len']=len(sid or '')
    ctx.add_cookies([{'name':'session_id','value':sid,'domain':'localhost','path':'/'}])
    page=ctx.new_page()
    page.goto(BASE+'/my/home', wait_until='domcontentloaded')
    res['url_after_login']=page.url
    page.goto(BASE+'/my/home', wait_until='domcontentloaded')
    res['url_home']=page.url
    res['home_title']=page.title()
    res['form_count']=page.locator('form').count()
    res['form_actions']=page.eval_on_selector_all('form','els=>els.map(e=>e.getAttribute("action"))')
    res['inputs_named_q']=page.eval_on_selector_all('input[name="q"]','els=>els.map(e=>e.outerHTML.slice(0,160))')
    res['topbar_count']=page.locator('.b11-topbar').count()
    res['topbar_visible']=page.locator('.b11-topbar').first.is_visible() if page.locator('.b11-topbar').count() else None
    res['body_head']=page.inner_text('body')[:200].replace('\n',' | ')
    page.screenshot(path='tests/smoke/out_search_diag/browser_home_%s.png'%TAG, full_page=False)

    if res['inputs_named_q']:
        box=page.locator('input[name="q"]').first
        res['box_visible']=box.is_visible()
        res['box_editable']=box.is_editable()
        res['box_bbox']=box.bounding_box()
        box.click(); box.fill('教材')
        page.keyboard.press('Enter')
        page.wait_for_load_state('domcontentloaded')
        res['enter_url']=page.url
        body=page.inner_text('body')
        res['enter_has_result']='搜索结果' in body
        res['enter_has_bill']='教材资料费' in body
        res['enter_snippet']=body[:260].replace('\n',' | ')
        page.screenshot(path='tests/smoke/out_search_diag/browser_result_%s.png'%TAG, full_page=False)
        # 放大镜按钮
        page.goto(BASE+'/my/home', wait_until='domcontentloaded')
        page.locator('input[name="q"]').first.fill('选课')
        btn=page.locator('form[action="/my/search"] button[type="submit"]').first
        res['btn_visible']=btn.is_visible(); res['btn_aria']=btn.get_attribute('aria-label')
        btn.click()
        page.wait_for_load_state('domcontentloaded')
        res['btn_url']=page.url
        b2=page.inner_text('body')
        res['btn_has_result']='搜索结果' in b2 and '没有找到' not in b2
    ctx.close(); b.close()

json.dump(res, open(OUT,'w'), ensure_ascii=False, indent=1)
for k,v in res.items():
    print('%-20s %s' % (k, str(v)[:240]))
