# -*- coding: utf-8 -*-
"""联系页文案语境化（website.contactus 站点 COW 视图，本地 id=934）。

把通用「我们公司/服务」介绍改为本校语境的招生/教务文案（含咨询邮箱），
表单「公司」字段标签改为「单位/教会」；zh_CN 与 en_US 副本同步处理。

要点：本库激活语言为 zh_CN/zh_TW/en_US，但该视图的 ORM 英文读写在
源语言回退下不可靠（写 zh 会连带覆盖 jsonb 源键），因此：
- zh_CN 走 ORM（激活语言，读写正确）；
- en_US 以 zh_CN 终稿为基底生成英文副本后，用 jsonb_set 直写并失效缓存。

stdin 执行（数据脚本，允许直接跑；不算 -u/重启）：
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf \
  --db_host=db -r odoo -w odoo -d edu19 --no-http < scripts/fix_contactus_copy.py

幂等性：各步替换/比对不命中即输出「无变化」，重复执行安全；
末尾自查三语言副本不含 yourcompany/Fake 及旧通用文案，不过则抛错不提交。
"""
import json

V = env['ir.ui.view'].sudo()
v = V.browse(934)
assert v.exists(), '视图 934 不存在'
assert v.key == 'website.contactus', '视图 934 不是 website.contactus: %s' % v.key

ZH_INTRO_OLD = '如有任何关于我们公司或服务的疑问，欢迎联络我们。'
ZH_INTRO_NEW = '有关报名、课程与教务的疑问，欢迎来信至 scrtsschool@gmail.com'
ZH_INTRO2 = '我们会尽快回复您。'
EN_INTRO_NEW = ('For questions about admission, courses or school affairs, '
                'write to us at scrtsschool@gmail.com')
EN_INTRO2_NEW = 'We will get back to you as soon as possible.'
ZH_LABEL_OLD = '<span class="s_website_form_label_content">公司</span>'
ZH_LABEL_NEW = '<span class="s_website_form_label_content">单位/教会</span>'
EN_LABEL_NEW = ('<span class="s_website_form_label_content">'
                'Organization / Church</span>')
MAIL = 'scrtsschool@gmail.com'

# ---- zh_CN：ORM 路径（激活语言） --------------------------------------
vv = v.with_context(lang='zh_CN')
cur = vv.arch_db or ''
new = cur.replace(ZH_INTRO_OLD, ZH_INTRO_NEW).replace(ZH_LABEL_OLD,
                                                      ZH_LABEL_NEW)
print('zh_CN:', '已更新' if new != cur else '无变化（可能已处理过）')
if new != cur:
    vv.arch_db = new
env.cr.flush()

# ---- en_US：以 zh_CN 终稿为基底，jsonb 直写 --------------------------
env.cr.execute("SELECT arch_db->>'zh_CN', arch_db->>'en_US' "
               "FROM ir_ui_view WHERE id=934")
raw_zh, raw_en = env.cr.fetchone()
raw_zh, raw_en = raw_zh or '', raw_en or ''
target_en = (raw_zh
             .replace(ZH_INTRO_OLD, EN_INTRO_NEW)
             .replace(ZH_INTRO_NEW, EN_INTRO_NEW)
             .replace(ZH_INTRO2, EN_INTRO2_NEW)
             .replace(ZH_LABEL_OLD, EN_LABEL_NEW)
             .replace(ZH_LABEL_NEW, EN_LABEL_NEW))
assert MAIL in target_en and EN_INTRO_NEW in target_en, \
    '英文副本生成异常：缺少邮箱或新介绍句'
if target_en != raw_en:
    env.cr.execute(
        "UPDATE ir_ui_view "
        "SET arch_db = jsonb_set(arch_db, '{en_US}', %s::jsonb) "
        "WHERE id=934",
        (json.dumps(target_en, ensure_ascii=False),))
    v.invalidate_recordset(['arch_db'])
    print('en_US: 已更新（SQL jsonb 直写，含介绍段与 Company 标签）')
else:
    print('en_US: 无变化（可能已处理过）')

# ---- 提交前自查：三语言副本均不得残留占位/旧通用文案 ------------------
env.cr.execute("SELECT arch_db->>'zh_CN', arch_db->>'en_US', "
               "arch_db->>'zh_TW' FROM ir_ui_view WHERE id=934")
zc, en, tw = [x or '' for x in env.cr.fetchone()]
bad = []
for name, a in (('zh_CN', zc), ('en_US', en), ('zh_TW', tw)):
    for token in ('yourcompany', 'Fake', 'our company or services',
                  '我们公司或服务'):
        if token in a:
            bad.append((name, token))
if MAIL not in zc or MAIL not in en:
    bad.append(('required', MAIL))
if 'admission, courses or school affairs' not in en:
    bad.append(('en_US', 'missing new intro'))
if ZH_LABEL_OLD in zc or '>Company<' in en:
    bad.append(('label', 'old 公司/Company 标签仍在'))
print('自查残留:', bad if bad else '无')
if bad:
    raise Exception('contactus 自查未通过: %r' % bad)

env.cr.commit()
print('CONTACTUS COPY DONE')
