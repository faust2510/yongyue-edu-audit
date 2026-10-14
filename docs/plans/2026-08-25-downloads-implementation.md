# 资料下载中心 — 实施计划
> **状态**：`归档` ｜ **主题**：`资料下载 v1 实施` ｜ **取代**：`downloads-v2-design.md` ｜ **核对**：`2026-10-06`
> ⚠️ 本文已被 [`downloads-v2-design.md`](downloads-v2-design.md) 取代，请优先阅读后者。

日期：2026-08-25
批准依据：docs/plans/downloads-design.md（已批准设计 spec，commit 4bd6d6a）

## Goal
在 custom_addons/edu_portal 内新增「资料下载中心」：管理员/教务上传行政通用表格
（请假表、阅读报告格式等），所有登录用户按分类浏览下载，下载次数统计。

## Architecture
- 新模型 edu.download.category / edu.download.file（轻量，与 op.media 定位分离）
- 门户路由 /downloads + /downloads/file/<int:fid>（auth='user'）
- 后台管理视图 + 菜单（groups=back_office_admin）
- 附件走 Odoo Binary 字段（ir.attachment 原生存储）

## Tech Stack
Odoo 19 + OpenEduCat；Python 3；QWeb 门户模板；无前端框架。

## Baseline / Authority Refs
- docs/plans/downloads-design.md（本次已批 spec）
- custom_addons/edu_portal/controllers/batch2.py（_YONGYUE_CARDS 卡片约定）
- scripts/gen_icons.py（瓦片图标生成约定）
- custom_addons/edu_schedule/views/menu.xml（教务菜单 groups 用法范例）

## Compatibility Boundary
- 不动 op.media / openeducat 现有材料体系
- 不开放教师上传（用户明确）
- 匿名不可见任何资料页/文件
- 停用(active=False)即隐藏+禁下
- Odoo19 约束：无 Environment.sudo()、用 models.Constraint、<list> 非 <tree>

## TDD Route
- Mode: off
- Decision: skipped（无用户 strict 要求；中等风险以升级+HTTP 冒烟回归）
- Verification: 本地 -u edu_portal 升级 EXIT=0 + requests 冒烟脚本断言

## Verification（全局）
1. docker exec edu19-clone-web-1 sh -c 'odoo -d edu19 --db_host=db --db_user=odoo --db_password=odoo -u edu_portal --stop-after-init --http-port 8071 > /tmp/dl.log 2>&1; echo EXIT=$?; grep -c Traceback /tmp/dl.log'  → EXIT=0, 0
2. docker restart edu19-clone-web-1；requests 冒烟：登录 admin 建分类+传文件 → 学生视角? 本地无学生 → 用 testpw 临时用户：/downloads 200 含分类标题；/downloads/file/<id> 202 内容为文件体；匿名 303；传完清理
3. 生产部署后 curl 探针

---

## Task 1 — 数据模型

Files:
- create: custom_addons/edu_portal/models/downloads.py
- modify: custom_addons/edu_portal/models/__init__.py（末尾追加 from . import downloads）

Why: 资料的唯一数据源；分类与文件两表。

Change Necessity: 新功能必须新表（spec 已定不复用 op.media），code-change 最小边界=两表+注册。

Impact: 新表无外部消费者；IR 权限由 Task 2 限定。

Verification: python3 -m py_compile custom_addons/edu_portal/models/downloads.py

Steps:
1. 写入以下完整文件内容：

```python
# -*- coding: utf-8 -*-
"""资料下载中心：行政通用表格（请假表、报告格式等）上传与下载。"""
from odoo import fields, models


class EduDownloadCategory(models.Model):
    _name = 'edu.download.category'
    _description = '资料分类'
    _order = 'name'

    name = fields.Char('分类名称', required=True)
    active = fields.Boolean('启用', default=True)

    file_count = fields.Integer(
        '资料数', compute='_compute_file_count')

    def _compute_file_count(self):
        counts = dict(self.env['edu.download.file'].sudo()
                      ._read_group([('active', '=', True)],
                                   ['category_id'], ['__count']))
        for rec in self:
            rec.file_count = counts.get(rec.id, 0)

    def _compute_download_file_count(self):
        return True


class EduDownloadFile(models.Model):
    _name = 'edu.download.file'
    _description = '下载资料'
    _order = 'category_id, name'

    name = fields.Char('标题', required=True)
    category_id = fields.Many2one(
        'edu.download.category', string='分类', required=True,
        ondelete='cascade')
    description = fields.Text('说明')
    file = fields.Binary('附件', required=True, attachment=True)
    file_name = fields.Char('文件名', readonly=True)
    active = fields.Boolean('启用', default=True)
    download_count = fields.Integer('下载次数', default=0, readonly=True)

    def action_download(self):
        """后台清单/表单快捷下载（可选）。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/downloads/file/%d' % self.id,
            'target': 'self',
        }
```

2. models/__init__.py 末尾追加：
```python
from . import downloads
```

3. 编译检查通过即完成。

## Task 2 — 访问权限

Files:
- modify: custom_addons/edu_portal/security/ir.model.access.csv（末尾追加两行）

Why: 管理=教务可写；教师/学生只读；匿名无权限。

Change Necessity: 新表必须有 ACL，否则默认全拒（Odoo 无记录=无权限），code-change 最小边界=两行 CSV。

Impact: 无既有角色影响。

Verification: 升级后 psql 查 ir_model_access 或直接冒烟（Task 6）。

Steps:
1. 追加：
```
access_edu_download_category_admin,edu.download.category admin,model_edu_download_category,openeducat_core.group_op_back_office_admin,1,1,1,1
access_edu_download_category_user,edu.download.category user,model_edu_download_category,base.group_user,1,0,0,0
access_edu_download_file_admin,edu.download.file admin,model_edu_download_file,openeducat_core.group_op_back_office_admin,1,1,1,1
access_edu_download_file_user,edu.download.file user,model_edu_download_file,base.group_user,1,0,0,0
```

## Task 3 — 后台管理视图与菜单

Files:
- create: custom_addons/edu_portal/views/downloads_views.xml

Why: 教务在后台可视化上传/分类管理。

Change Necessity: 管理界面必需；code-change 最小边界=一个 xml。

Impact: 仅教务组可见。

Verification: python3 -c "import xml.dom.minidom;xml.dom.minidom.parse('custom_addons/edu_portal/views/downloads_views.xml');print('ok')"

Steps:
1. 写入：

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_edu_download_category_list" model="ir.ui.view">
        <field name="name">edu.download.category.list</field>
        <field name="model">edu.download.category</field>
        <field name="arch" type="xml">
            <list string="资料分类" default_order="name">
                <field name="name"/>
                <field name="file_count" string="资料数"/>
                <field name="active" widget="boolean_toggle"/>
            </list>
        </field>
    </record>

    <record id="view_edu_download_category_form" model="ir.ui.view">
        <field name="name">edu.download.category.form</field>
        <field name="model">edu.download.category</field>
        <field name="arch" type="xml">
            <form string="资料分类">
                <sheet>
                    <group>
                        <field name="name"/>
                        <field name="active"/>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="action_edu_download_category" model="ir.actions.act_window">
        <field name="name">分类管理</field>
        <field name="res_model">edu.download.category</field>
        <field name="view_mode">list,form</field>
    </record>

    <record id="view_edu_download_file_list" model="ir.ui.view">
        <field name="name">edu.download.file.list</field>
        <field name="model">edu.download.file</field>
        <field name="arch" type="xml">
            <list string="下载资料" default_order="category_id, name">
                <field name="name"/>
                <field name="category_id"/>
                <field name="file_name"/>
                <field name="download_count" string="下载次数"/>
                <field name="active" widget="boolean_toggle"/>
            </list>
        </field>
    </record>

    <record id="view_edu_download_file_form" model="ir.ui.view">
        <field name="name">edu.download.file.form</field>
        <field name="model">edu.download.file</field>
        <field name="arch" type="xml">
            <form string="上传资料">
                <sheet>
                    <group>
                        <field name="name"/>
                        <field name="category_id"/>
                        <field name="description"/>
                        <field name="file" filename="file_name"/>
                        <field name="file_name" invisible="1"/>
                        <field name="active"/>
                        <field name="download_count" readonly="1"/>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="action_edu_download_file" model="ir.actions.act_window">
        <field name="name">上传资料</field>
        <field name="res_model">edu.download.file</field>
        <field name="view_mode">list,form</field>
    </record>

    <record id="menu_edu_download_root" model="ir.ui.menu">
        <field name="name">资料下载</field>
        <field name="web_icon">edu_portal,static/src/img/menu/downloads.svg</field>
        <field name="groups_id" eval="[(4, ref('openeducat_core.group_op_back_office_admin'))]"/>
        <field name="sequence">30</field>
    </record>
    <menuitem id="menu_edu_download_file"
              name="上传资料"
              parent="menu_edu_download_root"
              action="action_edu_download_file"
              sequence="10"
              groups="openeducat_core.group_op_back_office_admin"/>
    <menuitem id="menu_edu_download_category"
              name="分类管理"
              parent="menu_edu_download_root"
              action="action_edu_download_category"
              sequence="20"
              groups="openeducat_core.group_op_back_office_admin"/>
</odoo>
```

注意：menu root 用 groups_id eval 方式（避免 web_icon 与 groups 属性混用问题，与既有 menu_icons.xml 风格一致）。

## Task 4 — 门户下载页模板

Files:
- create: custom_addons/edu_portal/views/downloads_portal.xml

Why: 学生视角的分类浏览页。

Change Necessity: 门户页面必需；最小边界=一个 xml。

Verification: minidom parse ok

Steps:
1. 写入：

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <template id="edu_downloads_page" name="资料下载中心">
        <t t-call="edu_portal.edu_page">
            <h4 class="mb-1"><i class="fa fa-download me-2"/>资料下载</h4>
            <p class="text-muted mb-3">常用行政表格与模板（请假表、阅读报告格式等），点击即可下载。</p>

            <t t-if="not categories">
                <div class="alert alert-light border text-muted">暂无资料，请稍后再来。</div>
            </t>
            <t t-foreach="categories" t-as="cat">
                <div class="card shadow-sm border-0 rounded-3 mb-4">
                    <div class="card-header bg-white fw-semibold d-flex justify-content-between">
                        <span><i class="fa fa-folder-open me-1"/><t t-out="cat['name']"/></span>
                        <span class="badge rounded-pill text-bg-light text-muted"
                              t-out="str(len(cat['files'])) + ' 份'"/>
                    </div>
                    <div class="card-body p-0 table-responsive">
                        <table class="table table-hover align-middle mb-0">
                            <thead class="table-light">
                                <tr><th>标题</th><th>说明</th><th class="text-end">大小</th><th class="text-end">下载</th></tr>
                            </thead>
                            <tbody>
                                <t t-foreach="cat['files']" t-as="f">
                                    <tr>
                                        <td class="fw-semibold" t-out="f['name']"/>
                                        <td class="text-muted small" t-out="f['description']"/>
                                        <td class="text-end text-muted small text-nowrap" t-out="f['size_text']"/>
                                        <td class="text-end text-nowrap">
                                            <span class="badge text-bg-light text-muted me-2"
                                                  t-out="str(f['download_count']) + ' 次'"/>
                                            <a t-att-href="'/downloads/file/' + str(f['id'])"
                                               class="btn btn-sm btn-primary">
                                                <i class="fa fa-download me-1"/>下载
                                            </a>
                                        </td>
                                    </tr>
                                </t>
                            </tbody>
                        </table>
                    </div>
                </div>
            </t>
        </t>
    </template>
</odoo>
```

## Task 5 — 门户控制器

Files:
- create: custom_addons/edu_portal/controllers/downloads.py

Why: /downloads 列表 + /downloads/file/<id> 下载流与计数。

Change Necessity: 路由必需；最小边界=一个 controller。

Impact: auth='user' → 匿名 303；下载计数写入。

Verification: py_compile + Task 6 冒烟。

Steps:
1. 写入：

```python
# -*- coding: utf-8 -*-
"""资料下载中心：/downloads 列表页 + /downloads/file/<id> 下载流。"""
import base64

from odoo import http
from odoo.http import request


def _human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return '%.0f%s' % (n, unit)
        n /= 1024.0
    return '%.1fGB' % n


class EduDownloads(http.Controller):

    @http.route('/downloads', type='http', auth='user', website=True)
    def downloads_index(self, **kw):
        File = request.env['edu.download.file'].sudo()
        files = File.search([('active', '=', True)],
                            order='category_id, name')
        groups = {}
        for f in files:
            cid = f.category_id.id
            groups.setdefault(cid, {
                'id': cid,
                'name': f.category_id.name,
                'files': [],
            })['files'].append({
                'id': f.id,
                'name': f.name,
                'description': f.description or '',
                'size_text': _human_size(f.file_size or 0),
                'download_count': f.download_count,
            })
        return request.render('edu_portal.edu_downloads_page', {
            'title': '资料下载',
            'page_name': 'downloads',
            'categories': list(groups.values()),
        })

    @http.route('/downloads/file/<int:fid>', type='http', auth='user')
    def downloads_file(self, fid, **kw):
        rec = request.env['edu.download.file'].sudo().browse(fid)
        if not rec.exists() or not rec.active or not rec.file:
            return request.not_found()
        rec.sudo().write({'download_count': rec.download_count + 1})
        data = base64.b64decode(rec.file)
        headers = [
            ('Content-Type', 'application/octet-stream'),
            ('Content-Disposition',
             'attachment; filename="%s"' % (rec.file_name or rec.name)),
            ('Content-Length', str(len(data))),
        ]
        return request.make_response(data, headers=headers)
```

注：file_size 未定义 → 数据模型补 computed 字段。修改 Task 1 模型：

```python
    file_size = fields.Integer(
        '文件大小(字节)', compute='_compute_file_size', store=True)

    def _compute_file_size(self):
        for rec in self:
            rec.file_size = len(rec.file or b'') if rec.file else 0
```

（store=True 便于列表直接读；binary 字段 base64 字符串长度≈字节数。）

## Task 6 — 接线：manifest / __init__ / 图标 / 卡片

Files:
- modify: custom_addons/edu_portal/__manifest__.py（data 加两行，depends 不动）
- modify: custom_addons/edu_portal/controllers/__init__.py（追加 import downloads）
- modify: scripts/gen_icons.py（SPEC 加 downloads 与 menu/downloads）
- modify: custom_addons/edu_portal/controllers/batch2.py（_YONGYUE_CARDS 追加）
- modify: custom_addons/edu_portal/views/help_center.xml（学生版补小节）

Why: 使全部部件生效并可见。

Change Necessity: 接线必需；逐个点追加即可。

Verification: 见 Task 7 冒烟。

Steps:
1. __manifest__.py data 列表（views/help_center.xml 后）加：
```
        'views/downloads_views.xml',
        'views/downloads_portal.xml',
```
2. controllers/__init__.py 末尾追加： from . import downloads
3. gen_icons.py SPEC 追加两行（menu/downloads 瓦片 + 门户卡瓦片）：
```
 P+'downloads':                  ('#34D399', '#047857', G('doc')),
 'edu_portal/'+MENU+'downloads.svg': ('#34D399', '#047857', G('doc')),
```
   并执行：python3 scripts/gen_icons.py
4. batch2.py _YONGYUE_CARDS 追加：
```
    ('downloads', '资料下载', 'fa-download',
     '请假表、阅读报告格式等常用表格下载'),
```
5. help_center.xml 学生版章节内加：让学生知道路径 /downloads（教师版提及后台「资料下载」菜单）。

## Task 7 — 本地升级 + HTTP 冒烟

Files: 无（仅验证）

Steps:
1. 升级命令见 Verification 节。
2. docker restart edu19-clone-web-1（py 改动生效）。
3. 写 /tmp/dl_smoke.py：

```python
import re, requests
B = 'http://127.0.0.1:8069'
S = requests.Session(); S.trust_env = False
auth = S.post(B + '/web/session/authenticate',
              json={'jsonrpc':'2.0','params':{'db':'edu19','login':'admin','password':'admin'}})
assert auth.json()['result']['uid']
# 建分类+传文件
def kw(model, method, args):
    t = S.get(B + '/web/login')
    tk = re.findall(r'name="csrf_token"[^>]*value="([^"]+)"', t.text)[0]
    r = S.post(B + '/web/dataset/call_kw', json={'jsonrpc':'2.0','method':'call',
        'params':{'model':model,'method':method,'args':args,'kwargs':{'csrf_token':tk}}})
    return r.json().get('result')
cid = kw('edu.download.category', 'create', [{'name':'请假类'}])
fid = kw('edu.download.file', 'create', [{
    'name':'请假表模板','category_id':cid,
    'file':'aGVsbG8gZG93bmxvYWQ=', 'file_name':'qianjia.xlsx'}])
print('created:', cid, fid)
pg = S.get(B + '/downloads')
print('index 200+contains:', pg.status_code == 200 and '请假表模板' in pg.text)
r2 = S.get(B + '/downloads/file/%d' % fid)
print('download:', r2.status_code, r2.content == b'hello download')
kw('edu.download.file', 'unlink', [fid])
kw('edu.download.category', 'unlink', [cid])
# 匿名
A = requests.Session(); A.trust_env = False
print('anon:', A.get(B + '/downloads', allow_redirects=False).status_code)
```

断言语义按输出人工核对（created 非空、index True、download True、anon 303/302）。

## Task 8 — 提交 + 部署

Steps:
1. git add -A && git commit（feat(downloads): 资料下载中心）
2. bash scripts/deploy_myedu.sh 'edu_portal'
3. 生产探针：/downloads anon=303；/web/login=200；登录后冒烟（无 prod 凭据则仅探针）
4. 在帮助中心页确认 /downloads 链接已在生产渲染

## Risks / Rollback
- 本地环境偶发 postgres 恢复模式：冒烟失败重试/等待；生产升级失败 → git revert + 重部署前一 commit
- Binary 大文件：本功能面向表格模板（<10MB），无需分块
- file_size computed store 首次升级后由 ORM 初始化旧记录为 0 → 无历史数据（新表）无影响

## Retirement
- 无旧实现退役；op.media 体系保持原样（spec Non-goal）