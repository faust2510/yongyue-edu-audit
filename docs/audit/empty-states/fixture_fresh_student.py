# -*- coding: utf-8 -*-
"""空态审计夹具：在**本机演示库**建一个「什么都没有」的学生账号（生产侧的口径见报告）。

为什么需要它：本地 edu19 是演示库（6 个学生、288 节课、48 条考勤、22 条申诉），
生产库才是「刚重建、几乎为空」的状态（1 个学生 / 0 条选课单）。要拿到**首次登录**
那一屏的真实 DOM，就得有一个「没分班、没选课、没考勤、没账单」的账号 ——
否则页面走的是有数据分支，空态根本没有被渲染，也就无从取证。

只动本机演示库；账号带【演示】标记；可逆（teardown 脚本）。

用法（odoo shell 从 stdin 读脚本）：
  docker compose exec -T web odoo shell --db_host=db --db_port=5432 --db_user=odoo \
    --db_password=odoo --no-http -c /etc/odoo/odoo.conf -d edu19 \
    < docs/audit/empty-states/fixture_fresh_student.py
"""
LOGIN = "empty@local"
PWD = "demo123"
STU_NAME = "【演示】空态测试学生"
GR_NO = "EMPTY-DEMO-001"

P = env["res.partner"].sudo()
U = env["res.users"].sudo()
S = env["op.student"].sudo()

partner = P.search([("name", "=", STU_NAME)], limit=1) or P.create({"name": STU_NAME})
user = U.search([("login", "=", LOGIN)], limit=1)
if not user:
    user = U.create({"name": STU_NAME, "login": LOGIN, "password": PWD,
                     "partner_id": partner.id,
                     "group_ids": [(6, 0, [env.ref("base.group_portal").id])]})
    print("FIXTURE user created: %s" % user.id)
else:
    print("FIXTURE user exists: %s" % user.id)
stu = S.search([("user_id", "=", user.id)], limit=1)
if not stu:
    stu = S.create({"partner_id": partner.id, "user_id": user.id, "name": STU_NAME,
                    "gr_no": GR_NO, "gender": "m"})
    print("FIXTURE student created: %s" % stu.id)
else:
    print("FIXTURE student exists: %s" % stu.id)
env.cr.commit()
print("FIXTURE ok student=%s user=%s partner=%s login=%s pwd=%s"
      % (stu.id, user.id, partner.id, LOGIN, PWD))