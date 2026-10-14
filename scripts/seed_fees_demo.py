# -*- coding: utf-8 -*-
# 财务缴费演示数据（幂等）：王小明两笔账单，其一含部分到账。
# 运行: docker exec -i edu19-clone-web-1 odoo shell -c /etc/odoo/odoo.conf \
#         -d edu19 --db_host=db -r odoo -w odoo --no-http < scripts/seed_fees_demo.py
from datetime import date

Student = env['op.student']
Bill = env['edu.fee.bill']
Payment = env['edu.fee.payment']

stu = Student.search([('user_id.login', '=', 'stu@local')], limit=1)
if not stu:
    raise Exception('未找到演示学生 stu@local')

created_bills, created_payments, skipped = 0, 0, 0


def ensure_bill(name, amount, due, payments):
    global created_bills, created_payments, skipped
    dup = Bill.search([('student_id', '=', stu.id),
                       ('name', '=', name)], limit=1)
    if dup:
        skipped += 1
        return dup
    bill = Bill.create({
        'student_id': stu.id,
        'name': name,
        'amount': amount,
        'due_date': due,
    })
    created_bills += 1
    for amt, method, d in payments:
        Payment.create({'bill_id': bill.id, 'amount': amt,
                        'method': method, 'payment_date': d,
                        'note': '【演示】到账'})
        created_payments += 1
    return bill


ensure_bill('【演示】2026 春季统筹费', 12000.0,
            date(2026, 3, 31), [])
ensure_bill('【演示】教材资料费', 300.0,
            date(2026, 2, 28),
            [(100.0, 'wechat', date(2026, 2, 10))])

env.cr.commit()
print('FEES-SEED bills=%d pays=%d skipped=%d total=%d' % (
    created_bills, created_payments, skipped, Bill.search_count([])))
print('DONE')
