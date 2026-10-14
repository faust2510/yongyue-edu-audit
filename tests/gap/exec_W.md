# 实施代理 W — B8 公开课程详情（/courses?course=N）

- 执行人：代理 W（公开课程组）｜ 日期：2026-02-15 ｜ 约束：仅改 edu_public/controllers/*.py、新建 views/course_detail.xml、manifest data 加一行；未执行 docker/odoo/curl。

## 数据源结论

- 列表与详情数据均来自 **op.course**（openeducat_core，非自定义模型），控制器用 `.sudo()` 读取、路由 `auth='public', website=True`，游客可达。
- op.course 可展示字段：`name`（必填）、`code`、`department_id`、`program_id`、`parent_id`、`evaluation_type`、`min/max_unit_load`、`subject_ids`(m2m op.subject)。
- **op.course 没有简介/图片字段** → 详情页简介与图片位按任务要求做占位区块兜底；相关科目取 `subject_ids`（科目名/代码/类型）。
- 列表模板 `edu_courses` 的课程卡**原本已带** `/courses?course=<id>` 链接（edu_public_views.xml:21，t-att-href），无需再加跳转——缺口只在控制器忽略参数。

## 变更清单（3 个文件，均在许可范围内）

1. `custom_addons/edu_public/controllers/main.py`
   - 新增 `_course_param(kw)`：解析 `?course=N`，缺失/空串/非整数返回 None。
   - 新增 `COURSE_EVAL_LABELS`：evaluation_type 四个选值→中文文案。
   - `public_courses`：先按 `[('id','=',cid)]` search（沿用 active 过滤）；命中→渲染 `edu_public.edu_course_detail`（传 title=课程名、course、subjects、eval_label）；**未命中/参数无效→原样回退列表逻辑**（分页代码未动）。auth 保持 public。
2. `custom_addons/edu_public/views/course_detail.xml`（**新建**）
   - 模板 `edu_course_detail`：顶部「返回课程列表」链接；课程头卡（图标占位+名称+code/考核方式/院系/项目/父课程/学分区间，全部 t-if 守卫）；「课程简介」占位区块；「相关科目」卡片列表（空则 oe-norec 占位）；「课时安排」占位区块。风格复用现有 o_portal_* / oe-norec 类。
3. `custom_addons/edu_public/__manifest__.py`
   - data 列表追加一行 `'views/course_detail.xml',`（仅此一处改动）。

## 参数处理矩阵（自查）

| 入参 | 行为 |
|---|---|
| 无 course 参数 | 原列表页（含分页）不变 |
| `?course=有效id` | 渲染详情，顶部可返回列表 |
| `?course=abc` / 空 / `3.0` | int 解析失败 → 回退列表 |
| `?course=0` / 负数 / 越界 id | search 无记录 → 回退列表 |
| 课程库为空 / 科目为空 / 可空字段缺失 | 占位区块或 t-if 守卫，不 500 |

## 自查结果

- [x] py_compile main.py、__manifest__.py eval、minidom 解析 course_detail.xml 全部通过。
- [x] 新模板已在 manifest 注册；未触碰 edu_public/views 已有模板文件与 edu_brand 目录；未执行 docker/odoo/curl。
- [ ] 运行时验证未做（本代理禁 docker/odoo）：需由有环境者升级模块后冒烟 `GET /courses?course=<任一id>` 与 `?course=999999`。
