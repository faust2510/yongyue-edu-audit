# -*- coding: utf-8 -*-
# 资产演示数据（幂等）：5 件资产。
# 运行: docker exec -i edu19-clone-web-1 odoo shell -c /etc/odoo/odoo.conf \
#         -d edu19 --db_host=db -r odoo -w odoo --no-http < scripts/seed_assets_demo.py
Asset = env['edu.asset']
ITEMS = [
    ('【演示】投影仪 EP-01', 'ZC-001', 'device'),
    ('【演示】便携音响 ZY-02', 'ZC-002', 'device'),
    ('【演示】改革宗历史神学（上册）', 'TS-101', 'book'),
    ('【演示】圣经地图册', 'TS-102', 'book'),
    ('【演示】折叠讲台', 'QT-201', 'other'),
]
created, skipped = 0, 0
for name, code, cat in ITEMS:
    dup = Asset.search([('code', '=', code)], limit=1)
    if dup:
        skipped += 1
        continue
    Asset.create({'name': name, 'code': code, 'category': cat})
    created += 1
env.cr.commit()
print('ASSET-SEED created=%d skipped=%d total=%d DONE' % (
    created, skipped, Asset.search_count([])))
