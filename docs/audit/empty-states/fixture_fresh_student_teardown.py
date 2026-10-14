# -*- coding: utf-8 -*-
"""夹具拆除：删掉 fixture_fresh_student.py 建的账号（学生 → 账号 → 伙伴）。只动本机演示库。"""
LOGIN = "empty@local"
U = env["res.users"].sudo()
S = env["op.student"].sudo()
P = env["res.partner"].sudo()
user = U.search([("login", "=", LOGIN)], limit=1)
if user:
    stu = S.search([("user_id", "=", user.id)])
    partner = user.partner_id
    if stu:
        print("TEARDOWN students removed: %s" % stu.ids)
        stu.unlink()
    pid = partner.id
    user.unlink()
    if partner.exists():
        partner.unlink()
    print("TEARDOWN done user=%s partner=%s" % (user.id if user.exists() else "-", pid))
else:
    print("TEARDOWN nothing to do")
env.cr.commit()