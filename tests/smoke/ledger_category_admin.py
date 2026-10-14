# -*- coding: utf-8 -*-
"""费用分类「自助新建 / 停用 / 删除」行为级断言（三段模板，跑在本地 odoo shell 内）。

被测行为（校长 2026-09-16 要求「可以自己创建（和删除）」）：
  ① 新建一条分类后，前台记账表单**立刻**出现该选项；
  ② 用它记一笔账 → 台账按该分类筛选能筛到、明细显示分类名；
  ③ 停用后：新记账不再出现，**历史账仍显示原名**（不丢）；
  ④ 删除被账单引用的分类 → 被拒并给出「停用」出路；
  ⑤ 删掉账单后该分类可真删除（物理删）；
  ⑥ 还原并断言 leftover=0。

三段模板（docs/dev-workflow.md）：
  ① 绕过被测路径（ORM 建档案/账单，不走后台界面）
  ② 读真正的产物（HTTP 抓页面上的 <option> 与明细单元格）
  ③ 还原并断言 leftover=0

用法：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
        --db_host=db -r odoo -w odoo --no-http \
        < tests/smoke/ledger_category_admin.py
"""
import os
import re
import sys

import requests

os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
BASE = os.environ.get('EDU_BASE', 'http://127.0.0.1:8069')
LOGIN = os.environ.get('EDU_LOGIN', 'admin')
PWD = os.environ.get('EDU_PWD', 'admin')
CAT_NAME = '【临时·冒烟】测试分类'
CAT_CODE = 'smoke_tmp_cat'
BILL_NAME = '【临时·冒烟】分类接线用账单'
AMOUNT = 66.66

ok = fail = 0


def check(name, cond, detail=''):
    global ok, fail
    if cond:
        ok += 1
        print('PASS | %s | %s' % (name, detail))
    else:
        fail += 1
        print('FAIL | %s | %s' % (name, detail))


def session():
    s = requests.Session()
    r = s.get(BASE + '/web/login', timeout=20)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    s.post(BASE + '/web/login', timeout=20,
           data={'login': LOGIN, 'password': PWD,
                 'csrf_token': m.group(1) if m else '',
                 'redirect': '/my/home'})
    return s


def select_options(html, name):
    m = re.search(r'<select[^>]*name="%s"[^>]*>(.*?)</select>' % name, html, re.S)
    if not m:
        return []
    return [re.sub(r'<[^>]+>', '', lab).strip()
            for _, lab in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>',
                                     m.group(1), re.S)]


Cat = env['edu.fee.category'].sudo()
Bill = env['edu.fee.bill'].sudo()

# 清掉上次异常中断的残留（幂等前置）
stale_bills = Bill.search([('name', '=', BILL_NAME)])
if stale_bills:
    stale_bills.unlink()
stale_cats = Cat.search([('code', '=', CAT_CODE)])
if stale_cats:
    stale_cats.unlink()
env.cr.commit()

s = session()
html = s.get(BASE + '/ledger/new', timeout=20).text
before = select_options(html, 'category')
check('基线：记账表单没有该临时分类', CAT_NAME not in before,
      '现有 %d 条' % len(before))

# ① 绕过被测路径：ORM 新建档案
cat = Cat.create({'name': CAT_NAME, 'code': CAT_CODE,
                  'direction_hint': 'payable', 'sequence': 500})
env.cr.commit()
check('新建分类成功', cat.id > 0, 'id=%d code=%s' % (cat.id, cat.code))

# ② 读真正的产物：表单选项
html2 = s.get(BASE + '/ledger/new', timeout=20).text
after = select_options(html2, 'category')
check('新建后记账表单立刻出现该分类', CAT_NAME in after,
      '现有 %d 条' % len(after))

# ② 用它记一笔账
bill = Bill.create({'name': BILL_NAME, 'direction': 'payable',
                    'category_id': cat.id, 'amount': AMOUNT})
env.cr.commit()
html3 = s.get(BASE + '/ledger?category=%d' % cat.id, timeout=20).text
check('按该分类筛选能筛到这笔账', BILL_NAME in html3)
check('明细显示分类名', CAT_NAME in html3)
html_all = s.get(BASE + '/ledger', timeout=20).text
check('不筛选时那笔账也在（对照）', BILL_NAME in html_all)

# ③ 停用：新记账不再出现，历史账仍显示原名
cat.active = False
env.cr.commit()
html4 = s.get(BASE + '/ledger/new', timeout=20).text
check('停用后记账表单不再出现该分类',
      CAT_NAME not in select_options(html4, 'category'))
html5 = s.get(BASE + '/ledger', timeout=20).text
check('停用后历史账仍显示原分类名（不丢）', CAT_NAME in html5)

# ④ 删除被引用的分类 → 被拒 + 给出停用出路
from odoo.exceptions import UserError
blocked, msg = False, ''
try:
    cat.unlink()
except UserError as exc:
    blocked, msg = True, str(exc)
env.cr.rollback()
check('删除被引用的分类被拒绝', blocked, msg[:60].replace('\n', ' '))
check('拒绝提示给出「停用」出路', '停用' in msg, msg[:40].replace('\n', ' '))

# ⑤ 先删账单，再删分类 → 真删除
Bill.search([('name', '=', BILL_NAME)]).unlink()
cat = Cat.browse(cat.id)
cat.unlink()
env.cr.commit()
check('未被引用的分类可真删除（物理删）',
      not Cat.search([('code', '=', CAT_CODE)]).exists())

# ⑥ leftover=0
left_b = Bill.search_count([('name', '=', BILL_NAME)])
left_c = Cat.search_count([('code', '=', CAT_CODE)])
check('还原后 leftover=0', left_b == 0 and left_c == 0,
      'bill=%d cat=%d' % (left_b, left_c))

# 兜底解析：乱填分类参数时不许丢分类
fallback = Cat.browse(Cat.resolve_id('garbage')).exists()
check('非法分类参数回落到兜底分类', bool(fallback),
      '-> %s' % (fallback.name if fallback else '无'))

print('\n合计：PASS %d / FAIL %d' % (ok, fail))
if fail:
    raise SystemExit(1)
