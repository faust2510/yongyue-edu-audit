# -*- coding: utf-8 -*-
v = env['ir.ui.view'].sudo().browse(2060)
v.with_context(lang='zh_CN').write({
    'name': '永约学坊',
    'website_meta_title': '永约学坊',
    'website_meta_description': '永约学坊（Covenant Reformed Seminary）始创于2005年，持守改革宗神学立场与四大信经。2026年招生报名进行中。',
})
env.cr.commit()
print('META2060 DONE', v.website_meta_title)
