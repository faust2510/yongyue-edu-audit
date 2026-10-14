# -*- coding: utf-8 -*-
{
    'name': '永约学坊品牌',
    'version': '19.0.1.1.0',
    'category': 'Website',
    'summary': '永约学坊中文落地页与品牌页脚（替换主题英文营销内容与假联系方式）',
    'description': """
永约学坊（COVENANT REFORMED SEMINARY）品牌模块：
- 整体替换 theme_web_openeducat 英文营销首页为中文落地页
- 品牌化页脚：校徽 + 已确认联系方式（仅邮箱）
- 去 Odoo 化（v3 批次1）：页面模板 xpath + 后端 OWL 模板继承 + session_info/发件人/回连模型覆盖
- 设计令牌复用旧项目 covenant.css 金色系
""",
    # 2026-09-24：摘掉 website_sale —— 见下方 assets 注释；本模块对它的唯一用途
    # 是「停用商品搜索视图 / 隐藏购物车图标」这两个补丁，模块整体卸载后不再需要。
    # 2026-10-04（第 65 轮，**全新库实测**）：原先是
    #   ['website', 'theme_web_openeducat', 'auth_totp_portal']
    # 但本模块的 data_brand/brand_debrand_data.xml 里有 **5 处** 引用 digest 的 xmlid
    #（digest_digest_default ×2、digest_tip_digest_0 ×2、digest_tip_digest_1；第 63/65/104/106/108 行），
    # 而 depends 里**没有 digest** ⇒ 在**没有装过 digest 的新库**上，本模块加载到第 65 行就 ParseError，
    # 整个安装中断（实测：`create database edu19_fresh; odoo -i edu_life --without-demo=all`
    #   → `ParseError: while parsing .../brand_debrand_data.xml:65`）。
    # 克隆库上看不出来，只因为生产早就装过 digest（Odoo 默认应用集里就有）——
    # 而**换新服务器/重建库时必然踩到**（本项目已经丢过一次生产库）。
    # 修法就是 Odoo 的标准做法：把用到的模块写进 depends，让模块图先装它。
    'depends': ['website', 'theme_web_openeducat', 'auth_totp_portal', 'digest'],
    'data': [
        'views/shared_ui.xml',
        'views/brand_templates.xml',
        'views/pages.xml',
        'views/login.xml',
        'views/odoo_debrand.xml',
        'data_brand/brand_debrand_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'edu_brand/static/src/css/brand.css',
            # 核心「转到应用」浮动切换器的位置修正（原来钉在 (0,0)，压住我们自己的
            # 门户 logo；教务/管理员可见，桌面+手机都复现）。理由与证据见该文件头部注释。
            'edu_brand/static/src/css/frontend_switcher.css',
        ],
        # ── 2026-09-24 前端瘦身（第二刀后收窄） ──
        # 第一刀曾在本清单里逐文件摘除 payment*/website_sale*/forum/slides 共 149 个入口；
        # 第二刀把这些模块**整族卸载**了，其资源自然不再进包，清单随之收窄到只剩仍在装的 account。
        # 依据与踩坑见 docs/deploy-malaysia.md「前端瘦身」两节。
        # ⚠ 保留项必须对应**仍在安装**的模块：模块一卸载，('remove', 它的文件) 会让
        # Odoo 抛 ValueError('not found in bundle') ⇒ 整页 500。
        'web.assets_frontend_lazy': [
            ('remove', 'account/static/src/interactions/account_portal.js'),
            ('remove', 'account/static/src/interactions/account_sidebar.js'),
            ('remove', 'account/static/src/components/tests_shared_js_python/tests_shared_js_python.js'),
            ('remove', 'account/static/src/helpers/account_tax.js'),
        ],
        'web.assets_backend': [
            'edu_brand/static/src/css/backend_b11.css',
            'edu_brand/static/src/js/user_menu_debrand.js',
            'edu_brand/static/src/js/backend_doc_link.js',
            'edu_brand/static/src/xml/backend_debrand.xml',
        ],
        'web._assets_primary_variables': [
            # v4 唯一颜色令牌源（docs/plans/color-system-v4.md §1.2）。
            # 必须排在 backend_variables.scss **之前**：后者要用 $brand-* / $teal-*
            # 等编译期变量重做 $o-btns-bs-override 等 map 快照；反序会让
            # sass 报未定义变量，前后台 CSS 一起挂。
            'edu_brand/static/src/scss/brand_tokens.scss',
            'edu_brand/static/src/scss/backend_variables.scss',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
