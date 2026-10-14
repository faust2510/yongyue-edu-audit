# 实施代理 CC · 内容造数组（exec_CC）

日期：2026-08-23　范围铁律：仅【新建】`scripts/seed_c_content.py` 与本报告；未改任何现有文件；未执行 docker/odoo/curl（脚本交主代理统一跑）。

## 一、每页数据源结论（逐页 grep 控制器/模板确认）

| 页面 | 数据源 | 证据 | 渲染字段 |
|---|---|---|---|
| `/event` | 标准 `website_event` 的 **event.event**（无自定义控制器） | custom_addons 全部 route 清单无 /event；README L149 启用清单；原站抓页 `reference/public/event.html`（o19 站点） | name、date_begin/end、address_id、description |
| `/blog` | 标准 `website_blog` 的 **blog.blog + blog.post** | 同上，抓页 `reference/public/blog.html` | name、subtitle、content、published_date |
| `/campus/jobs` | `custom_addons/edu_public/controllers/main.py:153 campus_jobs()` 读 **hr.job** `search([])` | 控制器原文 | 仅 `j.name`（模板 `edu_jobs_shared`） |
| `/jobs`（职位卡片 href 目标） | 标准 `website_hr_recruitment`，同样读 **hr.job** | 原站抓页 `reference/public/jobs.html`（data-main-object=ir.ui.view(3678)）；edu_jobs_shared 卡片链接指向它 | name；上站需 website_published + state='recruit' |
| `/alumni/job/card` | `main.py:159 alumni_job_card()` 读 **hr.job** | 控制器原文 | 同 /campus/jobs |
| `/alumni` | `main.py:147 alumni()` 读 **op.student** `search([], limit=12)` | 控制器+模板 `edu_alumni` | s.name、partner 头像、`course_detail_ids[:1].course_id.name` |
| `/online-exams` | `main.py:73 public_exams()` 读 **op.exam**（order start_time desc，每页 9）——**不是 edu.quiz** | 控制器+模板 `edu_online_exams` | e.name、subject_id.name、start_time |
| `/courses-offered` | `main.py:165 courses_offered()` 读 **op.course** | 控制器+模板 `edu_courses_offered` | c.name、c.code |

**关键判定**
- `/online-exams` 不映射 edu.quiz ⇒ 按任务改为 op.exam 最小兜底：仅在表为空且存在 PRP-C* 科目时建 1 条「阶段考 · 小要理问答」（exam_code=EX-PRP-A）；已有记录（seed_yongyue_data.py 的 EX-DEMO-01 等）则不动。
- `/courses-offered` 的真实骨架六门课（CRS-MCS/BTH/BLA/BED/HSA/PRP）由 seed_yongyue_data.py 维护，本脚本不新造课程，只汇报数量——避免两套种子互相覆盖。
- 校友页模型即 op.student。已建 3 条档案「张/李/陈同学【演示】」并挂 CRS-PRP 选课记录（state='finished'，roll_number=ALUM-D01~03）。遵守本仓反拟真原则（seed_yongyue_data.py 头注），用通用演示名＋【演示】标记，未编真人姓名/邮箱。
- op.student.create 不会自动开登录账号（user 只在显式调用 create_student_user() 时创建，已读源码 student.py L164-176），造校友档案无用户副作用。

## 二、字段依据

- OpenEduCat 模型全部 grep 本仓源码核实：`op.exam`（exam.py：name/exam_code unique≤16/subject_id/start_time/end_time/total_marks/min_marks 必填；state 选值实为 **'schedule'** 而非 'scheduled'；session_id 可空时免日期约束）、`op.student`（gender 必填默认 m；name 继承自 partner）、`op.student.course`（course_id 必填，batch/roll_number/state 可选及唯一约束）、`op.course`（name/code 必填）。
- 核心 Odoo 19 模型（event.event / blog.blog / blog.post / hr.job）本机与仓库均无源码可 grep（find/mdfindex 无果），以公开资料佐证（如 [odoo/odoo website_blog 模型源](https://github.com/odoo/odoo/blob/e68aea3437fd3bcf4f7cc89de633d2e6d8711406/addons/website_blog/models/website_blog.py)、[hr_recruitment hr_job 源](https://github.com/odoo/odoo/blob/c8a1d17b873ddc381351cefdd00c069eaf970024/addons/hr_recruitment/models/hr_job.py)），并在脚本内做**运行时 schema 自探**：`safe_vals()/opt_write()/has()` 只写 `_fields` 里真实存在的键（website_published/company_id/subtitle/published_date/state='recruit' 等一律先探后写），正文取 content→description→body 第一个存在的字段并打印所用键名；单段 try/except+rollback，一段失败不影响其余段。

## 三、scripts/seed_c_content.py 说明（幂等 odoo shell 造数脚本）

- 开头 `env = env`（shell 注入）；结尾 `env.cr.commit()` 并打印各模型数量汇总。
- 幂等：活动/文章/职位按唯一 name 查重（已存在→跳过或刷新）；活动每次重跑把 date_begin/end 向前刷到未来（+10/+17/+24 天），保证 /event 永远是「未来日期」；博客按 blog_id+name 查重；考试按 exam_code 兜底条件控制；校友按 name 查重。
- 品牌：机构=永约学坊（2005 年创立、改革宗立场、四大信经表述与 brand_templates/pages.xml 原文一致）；联系方式全篇只出现 scrtsschool@gmail.com；无电话/地址/现代商业内容。内容清单：3 场活动（开学说明会、《威斯敏斯特小要理》读书会、公开讲座：宗教改革简史）、博客「永约学坊文集」+3 篇短文（教学札记/书目推荐/校史小记，各 3 段真实正文，书目引用学坊既有书单《天路历程》《殉道史》《思想的结果》）、3 个职位（古典语文教师/行政同工/图书馆管理员，职责要求各 3 条写入 description/requirements）。

## 四、主代理执行命令（仓库根目录）

```bash
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf \
    --db_host=db -r odoo -w odoo -d edu19 --no-http < scripts/seed_c_content.py
```

可重复执行。执行后验收点：`/event` 出现 3 条未来活动；`/blog` 出现文集与 3 篇文章；`/campus/jobs`、`/jobs` 各见 3 职位；`/alumni` 见 3 位【演示】校友（连同原有演示同学共 4 卡）；`/online-exams` 非空；`/courses-offered` 维持 6 门骨架课。若某段打印「忽略未知字段」或「失败」，把输出贴回即可定位。

## 五、自查结果

- `python3 -m py_compile scripts/seed_c_content.py` ✅
- 静态自检（AST/正则）：env 注入✅、结尾 commit✅、邮箱唯一 scrtsschool@gmail.com✅、无 curl/subprocess/requests 等执行手段✅。
- 未运行 Odoo/Docker（铁律），运行时字段兼容由脚本内 schema 自探兜底。
