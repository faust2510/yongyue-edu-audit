# -*- coding: utf-8 -*-
"""订正单条账单的「方向 / 分类 / 报销状态 / 垫付人 / 备注」（幂等，带审计留痕）。

背景（2026-09-16 用户报告）：/ledger 与 /ledger/new 的下拉框因「QWeb 遍历 dict
未 .items()」而字母化（选项 e/p/e/a），记账表单的方向/分类选项值全非法 ⇒
控制器兜底成 receivable + other。已修（commit 24f2f8c）。

2026-09-16 晚扩展为「四合一」：校长的「接待 ¥850」需要一次性写到位 ——
方向=应付、分类=接待、转成报销单（申请中、自动取号）、垫付人暂未知先留空。

用法（容器内经 stdin 送入；odoo shell 结束会回滚，脚本内显式 commit）：

    docker compose exec -T -e BILL_ID=16 -e NEW_DIRECTION=payable \
        -e NEW_CATEGORY=jiedai -e NEW_REIMBURSE=request -e FIX_DRY_RUN=1 \
        web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
        --db_host=db -r odoo -w odoo --no-http < scripts/fix_bill_direction.py

环境变量：
    BILL_ID         必填，edu.fee.bill 的 id
    NEW_DIRECTION   可选，receivable|payable
    NEW_CATEGORY    可选，分类 code（jiedai）或中文名（接待）
    NEW_REIMBURSE   可选，request|approved|refused|paid；
                    置为 request 且尚无单号时**自动取号**（与门户同源序号）
    SET_PARTNER     可选，res.partner id（报销单的垫付人/申请人）
    CLEAR_PARTNER=1 清空垫付人/申请人（垫付人未知时用，避免把记账人误标成垫付人）
    APPEND_NOTE     可选，追加到 note 末尾
    FIX_DRY_RUN=1   只打印将要写入的值，不提交
"""
import os

DRY = os.environ.get('FIX_DRY_RUN', '') == '1'


def _int(name):
    try:
        return int(os.environ.get(name) or 0)
    except ValueError:
        return 0


BILL_ID = _int('BILL_ID')
NEW_DIRECTION = (os.environ.get('NEW_DIRECTION') or '').strip()
NEW_CATEGORY = (os.environ.get('NEW_CATEGORY') or '').strip()
NEW_REIMBURSE = (os.environ.get('NEW_REIMBURSE') or '').strip()
SET_PARTNER = _int('SET_PARTNER')
APPEND_NOTE = (os.environ.get('APPEND_NOTE') or '').strip()
CLEAR_PARTNER = os.environ.get('CLEAR_PARTNER', '') == '1'

assert BILL_ID, 'BILL_ID 必填'

Bill = env['edu.fee.bill'].sudo()
bill = Bill.browse(BILL_ID)
assert bill.exists(), '账单 %d 不存在' % BILL_ID

DIRECTIONS = dict(bill._fields['direction']._description_selection(env))
STATES = dict(bill._fields['reimburse_state']._description_selection(env))
if NEW_DIRECTION:
    assert NEW_DIRECTION in DIRECTIONS, '非法方向：%s（可选 %s）' % (
        NEW_DIRECTION, sorted(DIRECTIONS))
if NEW_REIMBURSE:
    assert NEW_REIMBURSE in STATES, '非法报销状态：%s（可选 %s）' % (
        NEW_REIMBURSE, sorted(STATES))

# 分类：接受 code 或中文名（含已停用的，订正历史账不受停用影响）
cat = env['edu.fee.category'].sudo()
cat_rec = cat.browse(())
if NEW_CATEGORY:
    cat_rec = cat.search([('code', '=', NEW_CATEGORY)], limit=1) \
        or cat.search([('name', '=', NEW_CATEGORY)], limit=1)
    assert cat_rec, '找不到分类「%s」（现有：%s）' % (
        NEW_CATEGORY,
        ', '.join(cat.search([]).mapped('name')))

partner_rec = env['res.partner'].sudo().browse(SET_PARTNER) \
    if SET_PARTNER else env['res.partner'].sudo().browse(())
if SET_PARTNER:
    assert partner_rec.exists(), '受理人 %d 不存在' % SET_PARTNER


def snapshot(b):
    return {
        'direction': b.direction,
        'category': b.category_id.name or '',
        'reimburse_state': b.reimburse_state or '',
        'reimburse_ref': b.reimburse_ref or '',
        'created_by_partner': b.created_by_partner.name or '',
        'note': (b.note or '')[:40],
    }


before = snapshot(bill)
vals = {}
notes = []
if NEW_DIRECTION and NEW_DIRECTION != bill.direction:
    vals['direction'] = NEW_DIRECTION
    notes.append('方向 %s→%s' % (before['direction'], NEW_DIRECTION))
if cat_rec and cat_rec != bill.category_id:
    vals['category_id'] = cat_rec.id
    notes.append('分类 %s→%s' % (before['category'] or '（空）', cat_rec.name))
if NEW_REIMBURSE and NEW_REIMBURSE != (bill.reimburse_state or ''):
    vals['reimburse_state'] = NEW_REIMBURSE
    notes.append('报销状态 %s→%s' % (before['reimburse_state'] or '（空）',
                                     NEW_REIMBURSE))
    if NEW_REIMBURSE == 'request' and not bill.reimburse_ref:
        ref = Bill._next_reimburse_ref()
        vals['reimburse_ref'] = ref
        notes.append('取报销单号 %s' % ref)
    if NEW_REIMBURSE in ('approved', 'paid') and not bill.approved_amount:
        vals['approved_amount'] = bill.amount
        notes.append('同意金额=申请金额 %.2f' % (bill.amount or 0))
if CLEAR_PARTNER and bill.created_by_partner:
    vals['created_by_partner'] = False
    notes.append('垫付人/申请人 %s→（待补）'
                 % (before['created_by_partner'] or '（空）'))
if partner_rec and partner_rec != bill.created_by_partner:
    vals['created_by_partner'] = partner_rec.id
    if not bill.partner_id:
        vals['partner_id'] = partner_rec.id
    notes.append('垫付人/申请人 %s→%s' % (
        before['created_by_partner'] or '（空）', partner_rec.name))
if APPEND_NOTE:
    new_note = (bill.note or '')
    new_note = (new_note + '\n' + APPEND_NOTE).strip()
    vals['note'] = new_note
    notes.append('备注追加：%s' % APPEND_NOTE)

print('== 订正账单 %d「%s」 ==' % (bill.id, bill.name))
print('   dry_run = %s' % DRY)
print('   改前    = %s' % before)
print('   拟写入  = %s' % (vals or '（无需改动，已幂等）'))

if not vals:
    print('   → 无需改动（幂等）')
elif DRY:
    print('   → DRY RUN：未写入')
else:
    bill.write(vals)
    env['edu.audit.log'].sudo()._log(
        '订正账目', 'edu.fee.bill', bill.id, bill.name,
        '；'.join(notes) + '（原因：下拉框字母化缺陷导致落库为兜底值 / 校长裁定）')
    env.cr.commit()
    print('   改后    = %s' % snapshot(bill))
    print('   → 已写入并提交（审计已留痕）')
