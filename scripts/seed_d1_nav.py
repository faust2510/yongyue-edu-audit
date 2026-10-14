# -*- coding: utf-8 -*-
"""D1 导航接线：按原站导航树补齐 website.menu 入口并接上真实路由（幂等，可重复执行）。

背景（tests/gap/P_public.md · D1）：
  品牌化时 scripts/setup_brand_yongyue.py 的 MENU_REMOVE_NAMES 删掉了原站的 14 个
  导航入口，导致本地导航只剩 首页/图书馆/考试/联系我们/课程 5 项。本脚本把缺失入口
  按原站顺序（reference/web__login.html 头部导航实测）补回，并全部指向本地真实路由。

规则：
- 只创建缺失项 / 更新已有项的 url 与 sequence；**绝不删除任何菜单**。
- 展示位置（Placements，企业版独有 /website/activity/announcement）明确跳过不加。
- 图书馆 /library/media → /digital-library、课程 /my-courses → /courses 属"改指"，非删除；
  原站语义即如此（公开数字图书馆、公开 Courses 目录页），学生个人课表另补「我的课程」入口。
- 考试(/student/exam)、首页(/)、联系我们(/contactus) 维持现状不动。

用法（主代理执行；⚠️ 必须在 setup_brand_yongyue.py 之后运行，否则会被其 MENU_REMOVE_NAMES 再删一遍）：

    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
        -r odoo -w odoo -d edu19 --no-http < scripts/seed_d1_nav.py
"""
env = env

Website = env['website.menu']
site = env['website'].browse(1)
# 现场（2026-09-12 实测）有两个菜单根：website.menu 1「默认主菜单」
# 与历史脚本建的 4「更多」；**真正渲染到公开页顶栏的是挂在本站
# （website_id=1、parent 为空）那一棵**。旧实现固定用 site.menu_id(=1)，
# 既找不到已有项（重复建菜单），新建项也落在不渲染的树里。
root = Website.search([('website_id', '=', site.id), ('parent_id', '=', False)],
                      limit=1) or site.menu_id or env.ref('website.main_menu')
root_path = '%s/%s/' % (root.parent_path, root.id)


def in_tree(m):
    """本站菜单：website_id 指向本站即可——不再用 parent_path 前缀判定，
    否则「更多」子树（parent 为空、website_id=1）会被漏掉（重复建菜单根因）。"""
    return bool(m and m.website_id and m.website_id.id == site.id)


def find(name):
    """按名字找挂在站点菜单树内的条目（兼容多站点重复）。"""
    ms = Website.search([('name', '=', name)])
    mine = [m for m in ms if in_tree(m)]
    return mine[0] if mine else None


def ensure(name, url, seq, parent=None):
    """存在→校准 url/sequence/parent；不存在→创建。返回记录。"""
    m = find(name)
    vals = {}
    if m and m.url != url:
        vals['url'] = url
    if m and m.sequence != seq:
        vals['sequence'] = seq
    if parent is not None and m and m.parent_id.id != parent.id:
        vals['parent_id'] = parent.id
    if m:
        if vals:
            m.write(vals)
            print('UPDATE %-10s -> %s (seq=%s%s)' % (
                name, url, seq,
                ', reparent' if 'parent_id' in vals else ''))
        else:
            print('OK(keep) %-10s %s' % (name, url))
        return m
    m = Website.create({'name': name, 'url': url, 'sequence': seq,
                        'parent_id': (parent or root).id,
                        'website_id': site.id})
    print('CREATE %-10s -> %s (seq=%s)' % (name, url, seq))
    return m


# ---- 一级入口（seq 沿用 fix_menus.py 的原站顺序约定）----
# v3 批次1（A2）：商店 /shop 入口已移除 —— 学坊无电商业务，保留会带出
# /shop/cart、/shop/wishlist 等电商残留（对应 edu_brand 的页头隐藏）。
# 站内「登录」入口改指友好路径 /login（旧 /web/login 302 兼容）
ensure('登录', '/login', 7)
ensure('现在预订', '/booking', 30)
ensure('图书馆', '/digital-library', 40)      # 改指公开数字图书馆（原站行为）
ensure('活动', '/event', 60)
ensure('论坛', '/forum', 70)
ensure('博客', '/blog', 80)

# ---- 「入场」下拉 ----
adm = ensure('入场', '#', 90)
# v3：菜单名一律中文（i18n-eng 在库内改过 186/187/189，但 ensure() 按 name 查重，
# 若这里仍写英文，重跑本脚本会再建出英文菜单并产生重复项）
ensure('开设课程', '/courses-offered', 91, parent=adm)
ensure('培养项目', '/program-offered', 92, parent=adm)

# ---- 「工作机会」下拉 + 顶级「工作」 ----
jobs = ensure('工作机会', '#', 100)
ensure('校友招聘', '/alumni/job/card', 101, parent=jobs)
ensure('校园工作', '/campus/jobs', 102, parent=jobs)
ensure('工作', '/jobs', 110)

# ---- 尾部入口 ----
ensure('校友', '/alumni', 130)
courses = find('课程') or find('Courses')     # 兼容历史英文名 Courses→课程 的改名
if courses:
    if courses.url != '/courses':
        courses.write({'url': '/courses', 'sequence': 140})
        print('UPDATE %-10s -> /courses (seq=140)  # 原 Courses 公开课目页语义' % courses.name)
    else:
        print('OK(keep) %s /courses' % courses.name)
else:
    ensure('课程', '/courses', 140)
ensure('我的课程', '/my-courses', 145)        # 学生个人课表入口（本地新增语义）

# 展示位置（Placements）：企业版独有，本地无对应路由 —— 明确跳过，不创建。


# ---- 菜单收敛（v3 批次1 · A2「公开站菜单只有一套」）----
# 实测：顶栏里「课程」出现 3 次（/slides、/courses、/my-courses 各一条）。
# 规则：同名项只保留语义正确的那条，其余 unlink —— 这是本脚本
# "绝不删除菜单" 的唯一例外，且只在「同名 + 不同 URL」时生效（可重复执行）。
KEEP_URL = {'课程': '/courses', 'Courses': '/courses', '我的课程': '/my-courses'}
# 按标签分组收敛：同一标签只保留 URL 正确的那一条，其余全部 unlink
# （name 是 jsonb 多语言字段，取 zh_CN 值做标签比较）。
site_menus = Website.search([('website_id', '=', site.id)])
kept = {}
for m in site_menus:
    label = (m.with_context(lang='zh_CN').name or m.name or '').strip()
    if label not in KEEP_URL:
        continue
    if m.url == KEEP_URL[label] and label not in kept:
        kept[label] = m.id
        continue
    print('DEDUPE %-8s %s (id=%s) -> 保留 %s' % (label, m.url, m.id, KEEP_URL[label]))
    m.unlink()

env.cr.commit()
print('D1 NAV SEED COMMITTED')
