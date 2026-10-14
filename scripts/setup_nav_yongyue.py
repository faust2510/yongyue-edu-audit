# -*- coding: utf-8 -*-
"""公开导航整备（幂等）：加入永约导航、保留全部功能入口、清除占位与拟真残留。

用法：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
        -r odoo -w odoo -d edu19 --no-http < scripts/setup_nav_yongyue.py
"""
DEMO = "【演示】"
S = lambda m: env[m].sudo()

# ---- 1. 页眉占位句「请管理员填充」：停用（不是功能入口，是构建器残句）----
v = S('ir.ui.view').browse(2996)
if v.exists() and v.active:
    v.active = False
    print("占位页眉已停用")

# ---- 2. 社交默认假链接清空 ----
w = S('website').browse(1)
w.write({'social_twitter': False, 'social_facebook': False,
         'social_github': False, 'social_linkedin': False,
         'social_youtube': False, 'social_instagram': False})
print("社交链接已清空")

# ---- 3. 假教师遗留联系人 ----
gone = S('res.partner').search([('id', 'in', [33, 34])])
gone.unlink()
print("遗留联系人删除:", len(gone))

# ---- 4. 拟真名中性化（账号保留）----
fu = S('res.users').search([('login', '=', 'fac@local')], limit=1)
if fu and fu.partner_id.name != '停用教师账号' + DEMO:
    fu.partner_id.name = '停用教师账号' + DEMO
pu = S('res.users').search([('login', '=', 'parent@local')], limit=1)
if pu and pu.partner_id.name == '张家长':
    pu.partner_id.name = '家长' + DEMO
print("账号显示名已中性化")

# ---- 5. 演示商品（活动报名价目，纯演示）----
# 注：utm 营销活动是招聘模块功能数据，按「空置也保留」原则不删
try:
    n = S('product.template').search([('id', '=', 2)]).unlink()
    print("event演示商品删除")
except Exception as e:
    print("  ! 商品删除失败:", str(e)[:80])
    env.cr.rollback()

# ---- 6. 导航整备：功能入口全保留，前排插入永约项 ----
M = S('website.menu')
menus = M.search([('website_id', '=', 1)])
root = menus.filtered(lambda m: not m.parent_id and m.id != 1)
for r in root:
    if r.name != '更多':
        r.name = '更多'
        print("根菜单改名:", r.id, "->", r.name)
# 重复的图书馆入口去重（同 URL 保留最早一条）
dup = M.search([('url', '=', '/digital-library'), ('website_id', '=', 1)],
               order='id asc')
if len(dup) > 1:
    extra = dup[1:]
    print("重复图书馆菜单删除:", len(extra))
    extra.unlink()
# 永约导航（不存在才建；顺序置顶）
NAV = [("学院概况", "/about"), ("专业设置", "/programs"),
       ("报名入学", "/apply"),
       ("招生信息", "/admissions"), ("SCRTS校刊", "/journal"),
       ("登录", "/web/login")]
seq = 2
created = []
for name, url in NAV:
    m = M.search([('url', '=', url), ('website_id', '=', 1)], limit=1)
    if not m:
        m = M.create({'name': name, 'url': url, 'website_id': 1,
                      'parent_id': False, 'sequence': seq})
        created.append(name)
    m.sequence = seq
    seq += 1
print("新增导航项:", created or "无（均已存在）")
# 联系我们指向首页联系区锚点（我们自己的中文内容）
cu = M.search([('url', '=', '/contactus'), ('website_id', '=', 1)], limit=1)
if cu:
    cu.url = '/#contact'
    print("联系我们 -> /#contact")

env.cr.commit()
print("NAV SETUP DONE")
