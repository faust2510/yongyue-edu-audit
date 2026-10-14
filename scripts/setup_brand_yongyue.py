# -*- coding: utf-8 -*-
"""永约学坊品牌数据初始化：公司名/邮箱/logo、网站默认语言、演示菜单清理。

用法（沿用本项目 odoo shell 管道模式；严禁管道接 head，防止 SIGPIPE 中断导致不提交）：
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 --no-http < scripts/setup_brand_yongyue.py 2>&1 | tail -40
"""
import base64

env = env
LOGO = '/mnt/custom-addons/edu_brand/static/src/img/logo-medallion.png'

BRAND_NAME = '永约学坊'
BRAND_EMAIL = 'scrtsschool@gmail.com'

# 演示/死链菜单：商店、预订、活动、论坛、博客、入场(及其子项)、工作机会(及子项)、校友、展示位置
MENU_REMOVE_NAMES = [
    '商店', '现在预订', '活动', '论坛', '博客', '入场', 'Course', 'Program',
    '工作机会', '工作', 'Alumni Jobs', '校园工作', '校友', '展示位置',
]


def mk(tag, fn):
    try:
        with env.cr.savepoint():
            fn()
            print('OK %s' % tag)
    except Exception as e:
        print('ERR %s: %s' % (tag, str(e).replace('\n', ' ')[:200]))


def mk_strict(tag, fn):
    """严格版 mk：**不吞异常**。

    失败的步骤会向上抛，让 odoo shell 以非零退出码结束；因为最后的
    env.cr.commit() 不会执行，整脚本零提交（不留半套状态）。用于
    「源码改了但线上没变」这类静默故障的步骤（当前 = homepage-transplant）。
    """
    with env.cr.savepoint():
        fn()
    print('OK %s' % tag)


def _fingerprint(path):
    """容器内看到的文件指纹：大小 / mtime / md5（挂载失步诊断用）。"""
    import hashlib
    import os
    import time
    try:
        st = os.stat(path)
        with open(path, 'rb') as fh:
            data = fh.read()
    except OSError as exc:
        return '不可读：%s' % exc
    return '大小 %d 字节 / mtime %s / md5 %s' % (
        len(data), time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime)),
        hashlib.md5(data).hexdigest())


def _mount_desync_hint(src, why):
    print('[homepage-transplant] ✗ %s' % why)
    print('[homepage-transplant]   容器内指纹：%s' % _fingerprint(src))
    print('[homepage-transplant]   宿主对照：在仓库根执行  md5 -q custom_addons/edu_brand/views/brand_templates.xml')
    print('[homepage-transplant]   两者不一致 = Docker Desktop 挂载失步（已知故障），处置：')
    print('[homepage-transplant]       docker compose up -d --force-recreate web')
    print('[homepage-transplant]   重建容器后重跑本脚本；若两侧一致仍失败，则是文件本身 XML 损坏，需人工检查。')


# ---- 1. 公司与联系人品牌信息（不虚构电话/地址，仅写已确认邮箱） ----
def do_company():
    company = env['res.company'].browse(1)
    company.write({'name': BRAND_NAME, 'email': BRAND_EMAIL, 'phone': False})
    with open(LOGO, 'rb') as f:
        logo = base64.b64encode(f.read())
    company.partner_id.write({
        'name': BRAND_NAME, 'email': BRAND_EMAIL, 'phone': False,
        'image_1920': logo,
    })
    print('COMPANY:', company.name, company.email)

mk('company-brand', do_company)

# ---- 2. 网站名称与默认语言 ----
def do_website():
    w = env['website'].browse(1)
    lang = env.ref('base.lang_zh_CN')
    vals = {'name': BRAND_NAME}
    if lang and w.default_lang_id != lang:
        vals['default_lang_id'] = lang.id
    w.write(vals)
    print('WEBSITE:', w.name, 'default_lang:', w.default_lang_id.code)

mk('website-brand', do_website)

# ---- 3. 菜单清理：删演示项，Courses 改中文 ----
def do_menus():
    ms = env['website.menu'].search([('name', 'in', MENU_REMOVE_NAMES)])
    for m in ms:
        print('DROP MENU:', m.id, m.name)
    ms.unlink()
    c = env['website.menu'].search([('name', '=', 'Courses')], limit=1)
    if c:
        c.with_context(lang='zh_CN').write({'name': '课程'})
        print('RENAME Courses -> 课程 (id=%s)' % c.id)

mk('menus-cleanup', do_menus)

# ---- 4. 首页落地：主题首页被 COW 成站点专属视图（无 xmlid，升级不覆盖）。
#        从模块 XML 提取中文落地页 arch，直接移植进该视图；
#        模块数据里的独立模板记录仅作源码载体，移植后删除避免孤儿渲染。 ----
def do_homepage_transplant():
    import os
    import xml.etree.ElementTree as ET

    # 允许用环境变量覆盖来源文件（仅用于验证「解析失败」这条路径）：
    #   docker compose exec -e YONGYUE_BRAND_XML=/tmp/broken.xml ...
    src = os.environ.get('YONGYUE_BRAND_XML') \
        or '/mnt/custom-addons/edu_brand/views/brand_templates.xml'
    # 一次性读入全文：既拿到指纹，也避免边写边读拿到半截文件
    try:
        with open(src, 'rb') as fh:
            raw = fh.read()
    except OSError as exc:
        _mount_desync_hint(src, '来源文件读不到：%s' % exc)
        raise
    print('SOURCE %s -> %s' % (src, _fingerprint(src)))
    if not raw.rstrip().endswith(b'</odoo>'):
        _mount_desync_hint(src, '来源文件看起来被截断（末尾不是 </odoo>）')
        raise RuntimeError('brand_templates.xml 截断：%s' % src)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        print('[homepage-transplant]   若两侧 md5 一致，通常是文件本身 XML 损坏，不是挂载问题')
        _mount_desync_hint(src, 'XML 解析失败：%s' % exc)
        raise
    node = None
    for t in root.iter('template'):
        if t.get('id') == 'homepage_yongyue':
            node = t
            break
    if node is None:
        raise ValueError('homepage_yongyue template not found in %s' % src)
    # 视图 arch 必须是**单根**（2026-09-12 实测）：
    #   ① 多根会在 write 时被 _check_xml 拒绝：'Extra content at the end of the document'；
    #   ② 包 <data> 也不行——本视图是继承+站点专属（COW）视图，Odoo 会把 <data> 的每个
    #      子节点当成继承定位指令，于是 <t t-set="title"> 变成 xpath 去父视图里找同名节点，
    #      渲染时炸 '上级视图内找不到元素'（2026-09-12 实测）。
    # 结论：只取承载页面内容的 <t t-call="website.layout"> 作为 arch 根；
    # 其余顶层节点（如 title 的 t-set）会被跳过并 WARN，避免"源码改了线上没变"静默发生。
    parts = list(node)
    root_node = next((c for c in parts if c.tag == 't' and 'website.layout' in (c.get('t-call') or '')), None)
    if root_node is None:
        if len(parts) != 1:
            raise ValueError('homepage_yongyue 需要唯一的 <t t-call="website.layout"> 根节点，实际 %d 个顶层节点：%s' % (len(parts), [c.tag for c in parts]))
        root_node = parts[0]
    skipped = [ET.tostring(c, encoding='unicode')[:60] for c in parts if c is not root_node]
    if skipped:
        print('WARN homepage-transplant: 跳过 %d 个非内容顶层节点（不参与站点视图，若需要请改设计）：%s' % (len(skipped), skipped))
    arch = ET.tostring(root_node, encoding='unicode')
    if not arch.strip():
        raise ValueError('homepage_yongyue arch 为空：%s' % src)

    View = env['ir.ui.view']
    target = False
    for v in View.search([('key', '=', 'theme_web_openeducat.homepage')]):
        if v.website_id:
            target = v
            break
    if not target:
        target = View.search([('key', '=', 'theme_web_openeducat.homepage')], limit=1)
    if not target:
        raise ValueError('theme homepage view not found')
    try:
        target.write({'name': '永约学坊首页', 'arch_db': arch})
    except Exception as exc:
        print('[homepage-transplant] 写入站点首页视图失败（view %s）：%s' % (target.id, exc))
        print('[homepage-transplant]   常见原因：arch 不是单根（多个顶层节点需包 <data>）或含非法 XML，请检查 %s' % src)
        raise

    # 回读自检：防「写了但没生效 / 写进去的还是旧内容」
    target.invalidate_recordset(['arch_db'])
    back = target.arch or ''
    missing = [m for m in ('yylc-kicker', '永约学坊', '/login') if m not in back]
    if missing:
        raise AssertionError(
            '同步后回读自检失败：view %s 的 arch 缺少标记 %s' % (target.id, missing))
    if '/web/login' in back:
        raise AssertionError(
            '同步后 arch 仍含 /web/login（view %s）：来源文件未更新或同步到了旧内容' % target.id)
    print('TRANSPLANTED homepage arch -> view %s (website %s), %d 字节'
          % (target.id, target.website_id.id or '-', len(back)))
    print('SELFTEST ok: kicker/永约学坊//login 标记齐全且无 /web/login')

    junk = View.search([('key', '=', 'edu_brand.homepage_yongyue')])
    for j in junk:
        j.unlink()
        print('REMOVED source-carrier view %s' % j.id)


mk_strict('homepage-transplant', do_homepage_transplant)

# ---- 5. 存量演示数据汉化 + 门户账号语言（官方模块 selection 标签随用户语言渲染） ----
def do_data_zh():
    renames = [
        ('op.exam.type', [('code', '=', 'SES')], '阶段考'),
        ('grading.assignment.type', [('code', '=', 'HW')], '课后作业'),
        ('op.activity.type', [('name', '=', 'Presentation')], '课堂展示'),
        ('op.media.type', [('code', '=', 'CB')], '课程用书'),
        ('op.media.type', [('code', '=', 'RB')], '参考书'),
        ('op.media.type', [('code', '=', 'MG')], '杂志'),
        ('op.media.type', [('code', '=', 'RP')], '研究论文'),
    ]
    for model, dom, name in renames:
        recs = env[model].search(dom)
        for r in recs:
            r.name = name
        print('RENAME %s %s -> %s (%d)' % (model, dom, name, len(recs)))
    cmap = {
        'Grievance About Grades': '成绩复核申请',
        'Academic / Grades Issues': '学业 / 成绩问题',
        'Hostel Service irregular': '宿舍服务异常',
        'Non-Academic / Issues related to transport facility': '非学业 / 交通与住宿问题',
    }
    for g in env['edu.grievance'].search([]):
        if g.subject in cmap:
            g.subject = cmap[g.subject]
        if g.category in cmap:
            g.category = cmap[g.category]
    for login in ['stu@local']:
        u = env['res.users'].search([('login', '=', login)], limit=1)
        if u and u.lang != 'zh_CN':
            u.lang = 'zh_CN'
            print('LANG %s -> zh_CN' % login)

mk('data-zh', do_data_zh)

env.cr.commit()
print('COMMITTED')
