# -*- coding: utf-8 -*-
"""生产币种切换 USD -> CNY（用户 2026-09-14 明确批复）。

依据 docs/plans/data-provenance.md §9.2 的四步；**幂等、可重跑**。
回滚（§9.4）：
    UPDATE res_company SET currency_id=(SELECT id FROM res_currency WHERE name='USD') WHERE id=1;
    UPDATE edu_fee_bill SET currency_id=(SELECT id FROM res_currency WHERE name='USD');
    UPDATE res_currency SET active=false WHERE name='CNY';

在容器内跑（必须 commit，odoo shell 结束会回滚）：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo --no-http < scripts/switch_currency_cny.py
"""
env = env
company = env['res.company'].sudo().browse(1)
Cur = env['res.currency'].sudo()

# §9.2 坑：res.currency 有 active 字段，ORM 默认加 active_test 过滤；不带 context 搜不到未激活的 CNY
cny = Cur.with_context(active_test=False).search([('name', '=', 'CNY')], limit=1)
usd = Cur.with_context(active_test=False).search([('name', '=', 'USD')], limit=1)

print('[cur] 改前：company=%s currency=%s | CNY(id=%s active=%s) | USD(id=%s active=%s)' % (
    company.name, company.currency_id.name, cny.id, cny.active, usd.id, usd.active))
print('[cur] 改前：账单数=%d 其中 USD=%d CNY=%d' % (
    env['edu.fee.bill'].sudo().search_count([]),
    env['edu.fee.bill'].sudo().search_count([('currency_id', '=', usd.id)]),
    env['edu.fee.bill'].sudo().search_count([('currency_id', '=', cny.id)])))

if not cny:
    raise UserError('未找到 CNY —— 若报错请检查是否漏了 active_test=False')

# 1) 激活 CNY  2) 公司币种切 CNY  3) 存量账单币种改标为 CNY（不换算数字）
if not cny.active:
    cny.active = True
if company.currency_id.id != cny.id:
    company.currency_id = cny.id
bills = env['edu.fee.bill'].sudo().search([('currency_id', '=', usd.id)])
if bills:
    bills.write({'currency_id': cny.id})

env.cr.commit()
print('[cur] 已提交 env.cr.commit()')

print('[cur] 改后：company=%s currency=%s | CNY active=%s' % (
    company.name, company.currency_id.name, cny.active))
print('[cur] 改后：账单数=%d 其中 USD=%d CNY=%d' % (
    env['edu.fee.bill'].sudo().search_count([]),
    env['edu.fee.bill'].sudo().search_count([('currency_id', '=', usd.id)]),
    env['edu.fee.bill'].sudo().search_count([('currency_id', '=', cny.id)])))
print('[cur] 复核 SQL：select c.name, cur.name, cur.symbol from res_company c join res_currency cur on cur.id=c.currency_id;')
