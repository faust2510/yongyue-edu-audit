# -*- coding: utf-8 -*-
"""应付待付汇总卡 行为级断言（三段模板，跑在本地 odoo shell 内）。

被测行为：/ledger 顶部的「应付待付（open+partial）」必须把**手工记的应付账单**
（direction=payable 且 reimburse_state 为空）算进去 —— 它是一条已成立的义务。

三段模板（docs/dev-workflow.md）：
  ① 绕过被测路径：用 ORM 直接建一条临时应付账单（不走门户表单）；
  ② 读真正的产物：HTTP 抓 /ledger 页面上的卡片数字（不读返回值）；
  ③ 还原并断言 leftover=0：删除临时账单，确认库里再无残留。

用法（本机克隆，web 容器在跑）：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
        --db_host=db -r odoo -w odoo --no-http \
        < tests/smoke/ledger_payable_card.py
"""
import os
import re
import sys

import requests

os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
BASE = os.environ.get('EDU_BASE', 'http://127.0.0.1:8069')
LOGIN = os.environ.get('EDU_LOGIN', 'admin')
PWD = os.environ.get('EDU_PWD', 'admin')
TEMP_NAME = '【临时·冒烟】应付待付卡断言'
DASH = 1234.56

ok = fail = 0


def check(name, cond, detail=''):
    global ok, fail
    if cond:
        ok += 1
        print('PASS | %s | %s' % (name, detail))
    else:
        fail += 1
        print('FAIL | %s | %s' % (name, detail))


def _session():
    s = requests.Session()
    r = s.get(BASE + '/web/login', timeout=20)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    s.post(BASE + '/web/login', timeout=20,
           data={'login': LOGIN, 'password': PWD,
                 'csrf_token': m.group(1) if m else '',
                 'redirect': '/my/home'})
    return s


def card_value(html, label):
    i = html.find(label)
    if i < 0:
        return None
    seg = re.sub(r'<[^>]+>', ' ', html[i:i + 400])
    m = re.search(r'[¥￥]\s*([0-9]+(?:\.[0-9]+)?)', seg)
    return float(m.group(1)) if m else None


Bill = env['edu.fee.bill'].sudo()
# 清掉上一次异常中断可能留下的残留（幂等前置）
stale = Bill.search([('name', '=', TEMP_NAME)])
if stale:
    print('清理上次残留 %d 条' % len(stale))
    stale.unlink()
    env.cr.commit()

s = _session()
html = s.get(BASE + '/ledger', timeout=20).text
check('登录并打开 /ledger', '应付待付' in html)
base_pay = card_value(html, '应付待付')
base_recv = card_value(html, '应收未收')
print('基线：应付待付 = %s ／ 应收未收 = %s' % (base_pay, base_recv))

# ① 绕过被测路径：ORM 建临时应付账单（无 reimburse_state = 手工应付账）
tmp = Bill.create({
    'name': TEMP_NAME,
    'direction': 'payable',
    'category_id': env['edu.fee.category'].sudo().resolve_id('qita'),
    'amount': DASH,
    'note': 'tests/smoke/ledger_payable_card.py 自动清理，勿手工删除',
})
env.cr.commit()
check('临时应付账单已落库', tmp.id > 0, 'id=%d' % tmp.id)

# ② 读真正的产物：页面上的卡片数字
html2 = s.get(BASE + '/ledger', timeout=20).text
pay2 = card_value(html2, '应付待付')
recv2 = card_value(html2, '应收未收')
print('建单后：应付待付 = %s ／ 应收未收 = %s' % (pay2, recv2))
check('应付待付 计入手工应付账（+%.2f）'
      % DASH, pay2 is not None and abs(pay2 - (base_pay + DASH)) < 0.01,
      '期望 %s，实际 %s' % (base_pay + DASH, pay2))
check('应收未收 不受影响', recv2 == base_recv,
      '期望 %s，实际 %s' % (base_recv, recv2))

# ②b 待批报销单也必须计入（校长 2026-09-16：钱已由他人垫付）
tmp.write({'reimburse_state': 'request',
           'reimburse_ref': Bill._next_reimburse_ref()})
env.cr.commit()
html2b = s.get(BASE + '/ledger', timeout=20).text
pay2b = card_value(html2b, '应付待付')
check('待批报销单也计入应付待付', pay2b is not None
      and abs(pay2b - (base_pay + DASH)) < 0.01,
      '期望 %s，实际 %s' % (base_pay + DASH, pay2b))

# ②c 已驳回的不计入（义务不成立）
tmp.write({'reimburse_state': 'refused'})
env.cr.commit()
html2c = s.get(BASE + '/ledger', timeout=20).text
pay2c = card_value(html2c, '应付待付')
check('已驳回的报销单不计入应付待付', pay2c == base_pay,
      '期望 %s，实际 %s' % (base_pay, pay2c))

# ③ 还原 + leftover=0
tmp.unlink()
env.cr.commit()
left = Bill.search_count([('name', '=', TEMP_NAME)])
check('还原后 leftover=0', left == 0, 'leftover=%d' % left)
html3 = s.get(BASE + '/ledger', timeout=20).text
check('还原后卡片回到基线', card_value(html3, '应付待付') == base_pay,
      '%s -> %s' % (pay2, card_value(html3, '应付待付')))

print('\n合计：PASS %d / FAIL %d' % (ok, fail))
if fail:
    raise SystemExit(1)
