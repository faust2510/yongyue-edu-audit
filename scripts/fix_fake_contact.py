# -*- coding: utf-8 -*-
"""通用假联系资料清理（按内容搜索，跨语言副本，可在任何环境重复执行）"""
V = env['ir.ui.view'].sudo()

def scrub(a):
    if not a:
        return a
    a = a.replace('<h5>My Company</h5>', '<h5>联系我们</h5>')
    a = a.replace('<h5>我的公司</h5>', '<h5>联系我们</h5>')
    a = a.replace('我的公司', '永约学坊')
    a = a.replace('<li><i class="fa fa-map-marker fa-fw me-2"/><span class="o_force_ltr">3575 Fake Buena Vista Avenue</span></li>',
                  '<li><i class="fa fa-envelope fa-fw me-2"/><span>scrtsschool@gmail.com</span></li>')
    a = a.replace('<li><i class="fa fa-phone fa-fw me-2"/><span class="o_force_ltr">+1 555-555-5556</span></li>',
                  '<li><i class="fa fa-info-circle fa-fw me-2"/><span>咨询、报名与提交文件均请来信，并留意邮箱回复。</span></li>')
    a = a.replace('<li><i class="fa fa-1x fa-fw fa-envelope me-2"/><span>info@yourcompany.example.com</span></li>', '')
    a = a.replace('info@yourcompany.example.com', 'scrtsschool@gmail.com')
    a = a.replace('3575 Fake Buena Vista Avenue', '')
    a = a.replace('+1 555-555-5556', '')
    return a

hits = V.search(['|', '|', '|',
                 ('arch_db', 'ilike', 'Fake Buena'),
                 ('arch_db', 'ilike', 'yourcompany.example.com'),
                 ('arch_db', 'ilike', '555-555-5556'),
                 ('name', 'ilike', '我的公司')])
print("命中视图:", len(hits))
for v in hits:
    changed = False
    for lang in ('zh_CN', 'en_US'):
        vv = v.with_context(lang=lang)
        cur = vv.arch_db
        if not cur:
            continue
        new = scrub(cur)
        if new != cur:
            vv.arch_db = new
            changed = True
    print(" 视图", v.id, v.key or '', "已清理" if changed else "(跳过)")

# 页眉占位句（含假串的站点副本一律停用）
for v in V.search([('key', '=', 'website.header_text_element'), ('website_id', '!=', False)]):
    if v.active and ('Fake Buena' in (v.arch_db or '') or 'yourcompany' in (v.arch_db or '')):
        v.active = False
        print(" 停用占位页眉", v.id)

# 公司联系人字段兜底清空（保留名称与已确认邮箱）
comp = env['res.company'].sudo().search([], limit=1)
p = comp.partner_id
dirty = {}
for f in ('phone', 'street', 'street2', 'city', 'zip'):
    if f in p._fields and getattr(p, f, False):
        dirty[f] = False
if dirty:
    p.write(dirty)
    print(" 公司联系人冗余字段已清:", list(dirty.keys()))

# 社交默认链接清空
w = env['website'].sudo().search([], limit=1)
w.write({'social_twitter': False, 'social_facebook': False,
         'social_github': False, 'social_linkedin': False,
         'social_youtube': False, 'social_instagram': False})
print(" 社交链接已清空")
env.cr.commit()
print("REMOTE CONTACT FIX DONE")
