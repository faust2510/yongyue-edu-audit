# -*- coding: utf-8 -*-
v = env['ir.ui.view'].sudo().browse(2060)
n = 0
for lang in ('zh_CN', 'en_US'):
    vv = v.with_context(lang=lang)
    a = vv.arch_db or ''
    if 't-set="title"' in a:
        continue
    marker = '<t t-call="website.layout">'
    i = a.find(marker)
    if i == -1:
        continue
    inj = '<t t-set="title" t-value="永约学坊 · 报名入学与教务系统"/>'
    # t-value 需要引号包裹字符串：改用双引号外层
    inj = "<t t-set=\"title\" t-value=\"'永约学坊 · 报名入学与教务系统'\"/>"
    a2 = a[:i + len(marker)] + inj + a[i + len(marker):]
    vv.arch_db = a2
    n += 1
env.cr.commit()
print("INJECTED", n)
