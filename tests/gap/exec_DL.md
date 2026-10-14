# 实施代理 DL · B5 数字图书馆（exec_DL）

日期：2026-08-23　范围铁律：仅动 `edu_public/controllers/main.py`、`edu_public/views/edu_public_views.xml`。未动 `__manifest__.py`（新模板落在已注册的既有数据文件内）。未执行 docker/odoo/curl。

## 303 根因结论

**模板链接指错目标，控制器本身无任何跳转逻辑。** `edu_public/views/edu_public_views.xml` 原第 86 行分类卡片写死 `href="/library/media?filterby=<id>"`；而 `/library/media` 全库唯一路由在 `edu_portal/controllers/batch2.py:564`，声明为 **`auth='user'`**（登录门户页）。游客点击 → Odoo 对未登录访问 auth='user' 路由发 303 → `/web/login`。即：不是 edu_public 控制器跳转，也不是权限记录规则，纯粹是公开模板引用了登录态路由。

## 改动清单

### 1. custom_addons/edu_public/controllers/main.py
- 新增 `_media_type_param(kw)`：解析 `?type=N`，缺失/非整数/0 → None（回退分类总览），风格对齐 `_course_param`。
- 重写 `digital_library`（保持 `/digital-library`、auth='public'、website=True）：
  - 保留类型卡片 cards + total_media；
  - 支持 `type` 参数过滤：无效类型 id（不存在）一律回退总览；有效时 `medias = op.media.search([('media_type_id','=',N)], order='name asc')` 并传 `current_type` 供模板高亮；
  - docstring 记录 303 历史。
- 新增 `GET /digital-library/material/<int:mid>`（auth='public'，website=True）：`browse(mid).exists()` 判存在，无效 id `request.redirect('/digital-library')`；传 media/media_type/authors/publishers/subjects。

### 2. custom_addons/edu_public/views/edu_public_views.xml
- 模板 `edu_digital_library`：
  - 卡片 href 改为 `/digital-library?type=<id>`（停留在公开页），当前选中卡加 `border border-primary` 高亮（无 filter 时保持原 text-bg-light）；
  - 新增过滤结果区：`current_type` 标题行（oe-cat-head + oe-cat-count，对齐开设课程页写法）+「查看全部分类」返回链接；该类下媒体逐条渲染为 `o_portal_index_card` 行（书名/作者串/版次），整卡链接 `/digital-library/material/<id>`；空分类用既有 `oe-norec` 空态。
- 新增模板 `edu_digital_library_material`（详情页，DOM/类名沿用本模块 course_detail 同款骨架）：
  - 返回链接「返回数字图书馆」；oe-cat-head 书名头；
  - 元信息条（o_portal_icon + text-bg-light）：类型/作者/出版社/版次一行、ISBN/内码一行，全部 t-if 守卫可空字段；
  - 简介：`media.description` 有值渲染文本块，否则 `oe-norec` 占位「即将发布」；
  - 关联科目：subject 卡片网格或 `oe-norec` 空态；
  - 在线阅读：固定 `oe-norec` 占位空态（本地无电子书文件，属正常空态）。

## 游客全流程自查（静态审计；运行环境不在本代理权限内）
- [x] 列表 `GET /digital-library`：auth='public' + website=True，与改动前一致 → 200。
- [x] 筛选 `GET /digital-library?type=5..9`：同一 public 控制器处理，页面不再出现任何指向 auth='user' 路由的链接；非整数/未知 type 回退总览仍 200。
- [x] 详情 `GET /digital-library/material/<id>`：auth='public' → 200；无效 id → 303 仅限回退到公开 `/digital-library`（符合任务要求的"回退"语义，不涉登录）。
- [x] grep 复核：edu_public 内已无功能性 `/library/media` 引用（仅剩注释说明）。
- [x] py_compile main.py 通过（PY_OK）；minidom 解析两份 XML 通过（XML_OK）。
- [x] 模板变量均有控制器供给：cards/current_type/medias 恒传入；op.media 的 author_ids/publisher_ids/name 字段与 op.author/op.publisher 的 name 字段已在源码确认存在。

## 主代理回归建议（需运行环境，本代理未执行）
1. 未登录状态依次访问 `/digital-library` → 点任一分类卡 → 应停留 `/digital-library?type=N` 且 URL 不变、HTTP 200、出现该类型媒体列表。
2. 点任一媒体行 → `/digital-library/material/<id>` 200，含书名/作者/出版社/类型/科目/简介占位/在线阅读占位。
3. 手工访问 `/digital-library/material/99999` 与 `/digital-library?type=abc` → 分别回退列表页/总览，均 200 无登录跳转。
4. 升级命令：`-u edu_public` 后生效（模板有改动）。
