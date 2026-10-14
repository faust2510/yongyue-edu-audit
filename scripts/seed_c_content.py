# -*- coding: utf-8 -*-
"""永约学坊 C 组内容种子脚本：活动 / 博客 / 职位 / 校友档案 / 考试兜底（幂等）

页面数据源侦察结论（2026-08-23，详见 tests/gap/exec_CC.md）：
- /event            → 标准 website_event 的 event.event（custom_addons 无自定义控制器；
                      README L149 启用清单与 reference/public/event.html 原站抓页均证实）
- /blog             → 标准 website_blog 的 blog.blog + blog.post
- /campus/jobs      → custom_addons/edu_public/controllers/main.py campus_jobs() 读 hr.job
- /jobs             → 标准 website_hr_recruitment 路由，同样读 hr.job
- /alumni/job/card  → 同上（edu_public main.py alumni_job_card()）
- /alumni           → edu_public main.py alumni() 读 op.student（limit 12）
- /online-exams     → edu_public main.py public_exams() 读 op.exam（不是 edu.quiz）
- /courses-offered  → edu_public main.py courses_offered() 读 op.course；
                      真实骨架六门课（CRS-*）由 seed_yongyue_data.py 负责，本脚本不新造课程

用法（主代理统一执行，仓库根目录）：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf \
        --db_host=db -r odoo -w odoo -d edu19 --no-http < scripts/seed_c_content.py

原则：
- 幂等：一律按唯一 name（或 code/exam_code）查重跳过；活动日期重跑时向前刷新，
  保证 /event 列表永远是「未来日期」。
- 所有可发布记录置 website_published=True（仅当字段存在）；公司归属 company_id=1
  （仅当字段存在）。
- 品牌红线：机构=永约学坊（2005 年创立，改革宗立场、持守四大信经），联系方式只有
  scrtsschool@gmail.com，不编电话/地址/真人姓名；校友档案为通用演示名并带【演示】标记。
"""
import datetime

env = env  # odoo shell 注入
COMPANY_ID = 1
EMAIL = 'scrtsschool@gmail.com'
DEMO = '【演示】'

S = lambda m: env[m].sudo()

now = datetime.datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
company = S('res.company').browse(COMPANY_ID).exists() \
    or S('res.company').search([], limit=1)


def has(model, *fields):
    """模型已安装且指定字段全部存在（核心模块源码不在本机，写入前一律探明）。"""
    return model in env and all(f in S(model)._fields for f in fields)


def opt_write(rec, vals):
    """只写字段真实存在的键，返回实际写入的键名列表。"""
    ok = {k: v for k, v in vals.items() if k in rec._fields}
    if ok:
        rec.write(ok)
    return sorted(ok)


def safe_vals(model, vals):
    """按运行时真实模型字段过滤 create 值，返回 (可用值, 被忽略的未知键)。"""
    f = S(model)._fields
    ok = {k: v for k, v in vals.items() if k in f}
    return ok, sorted(k for k in vals if k not in f)


def as_html_or_text(model, field, text, html):
    """hr.job 的 description/requirements 在不同版本中类型不同，按真实字段类型给值。"""
    if model in env and field in S(model)._fields \
            and S(model)._fields[field].type == 'html':
        return html
    return text


print("=" * 25, "C 组内容种子（活动/博客/职位/校友/考试兜底）", "=" * 25)

# ---------------------------------------------------------------- A. 活动 /event
print("=" * 30, "A. 活动 event.event ×3", "=" * 30)
ev_new = ev_kept = 0
try:
    if has('event.event', 'name', 'date_begin', 'date_end'):
        Event = S('event.event')
        EVENTS = [
            ("开学说明会", 10,
             "面向有意报读预备科的朋友。说明预备科的课程体系——小要理问答、基础信仰、"
             "圣经概览、救赎历史，以及阅读、古汉语、写作、英语诸科——并介绍学习方式与报名流程。",
             "形式：线上举行，会议链接报名后另发。"),
            ("《威斯敏斯特小要理》读书会", 17,
             "预备科「小要理问答」科目的延伸共读。逐问诵读、分段讨论，"
             "以问答为纲默想要道，欢迎在读同学与旁听朋友参加。",
             "地点：学坊教室（具体地址确认后另行通知）。"),
            ("公开讲座：宗教改革简史", 24,
             "回顾十六世纪宗教改革的来龙去脉：改教先驱的寻求、福音的重新发现，"
             "及其对后世教会的影响。免费公开讲座，欢迎旁听。",
             "地点：待定，请留意本页更新。"),
        ]
        for name, days_ahead, brief, venue in EVENTS:
            begin = now + datetime.timedelta(days=days_ahead)
            end = begin + datetime.timedelta(hours=2)
            desc = ("<p>%s</p><p>%s 报名垂询：%s</p>" % (brief, venue, EMAIL))
            vals, dropped = safe_vals('event.event', {
                'name': name, 'date_begin': begin, 'date_end': end,
                'description': desc})
            if dropped:
                print(" ! event.event 忽略未知字段", dropped)
            ev = Event.search([('name', '=', name)], limit=1)
            if ev:
                ev.write(vals)          # 重跑刷新日期，保证始终是未来活动
                ev_kept += 1
                print(" 活动(刷新)", name, "->", begin.strftime('%Y-%m-%d %H:%M'))
            else:
                ev = Event.create(vals)
                ev_new += 1
                print(" 活动(新建)", name, begin.strftime('%Y-%m-%d %H:%M'))
            opt_write(ev, {'website_published': True})
            if 'company_id' in ev._fields and company:
                ev.company_id = company.id
        env.cr.commit()
    else:
        print(" ! 未安装 website_event（event.event 不存在），跳过")
except Exception as e:
    env.cr.rollback()
    print(" ! 活动段失败:", str(e)[:150])
print(" 活动合计 新建 %d / 保留 %d" % (ev_new, ev_kept))

# ------------------------------------------------------------- B. 博客 /blog
print("=" * 30, "B. 博客 blog.blog + blog.post ×3", "=" * 30)
BLOG_NAME = '永约学坊文集'
POSTS = [
    ("教学札记：先讲故事，再背问答",
     "预备科「小要理问答」教学手记",
     ["预备科的「小要理问答」课上，我们常互相提醒：问答不是孤立的条目，"
      "而是整全救恩叙事的提纲。孩子背诵第一问之前，若从未听全故事，"
      "问答便容易沦为口舌的功夫。",
      "所以课堂的次序常常是：先讲一段救赎历史——创造、堕落、应许、成全——"
      "再回到问题本身：「人生的首要目的是什么？」故事先行，答案才有分量；"
      "背诵在后，记忆才有着落。",
      "愿与诸同工共勉。若您想了解预备科的这门课，欢迎来信 %s。" % EMAIL]),
    ("书目推荐：预备科阅读课程的几本书",
     "为什么是这些书",
     ["阅读课程是预备科十四门科目之一。选书不求新奇，惟求经典："
      "让初学者在年富力强的年月，先与经过时间检验的书打交道。",
      "《天路历程》教人看见天路的艰难与荣耀；《殉道史》提醒信仰历来有其代价；"
      "《思想的结果》则为愿意思考的人推开西方思想的大门。"
      "文学、传记、思想史并陈，正是盼望读者被造就为完整的人。",
      "书单逐年精修。欢迎学员与同道来信交流读书心得：%s。" % EMAIL]),
    ("校史小记：始于二〇〇五年",
     "永约学坊的由来",
     ["永约学坊始创于2005年，持守改革宗神学立场和四大信经——"
      "使徒信经、尼西亚信经、亚他拿修信经及迦克墩信经。"
      "二十年来所求的，不过是为教会多备几块基石。",
      "预备科是有志深造者的台阶：小要理问答立骨，基础信仰定准，圣经概览与"
      "救赎历史铺展脉络，阅读、古汉语、写作、英语诸课操练治学的功夫。",
      "校史尚短，恩典甚长。愿那开始了善工的，成全这工。"]),
]
bl_new = po_new = po_kept = 0
try:
    if has('blog.blog', 'name') and has('blog.post', 'name', 'blog_id'):
        Blog = S('blog.blog')
        Post = S('blog.post')
        blog = Blog.search([('name', '=', BLOG_NAME)], limit=1)
        if not blog:
            blog = Blog.create({'name': BLOG_NAME})
            bl_new += 1
        opt_write(blog, {'subtitle': '教学札记 · 书目推荐 · 校史小记'})
        print(" 博客", blog.name, "(新建)" if bl_new else "(已存在)")
        # 正文字段名按运行时 schema 判定（Odoo 14→19 一直叫 content，兜底再探）
        body_key = next((k for k in ('content', 'description', 'body')
                         if k in Post._fields), None)
        print(" 正文字段:", body_key or "未找到（文章将只有标题）")
        for i, (title, subtitle, paras) in enumerate(POSTS):
            content = "".join("<p>%s</p>" % p for p in paras)
            post = Post.search([('blog_id', '=', blog.id),
                                ('name', '=', title)], limit=1)
            vals_all = {'blog_id': blog.id, 'name': title}
            if body_key:
                vals_all[body_key] = content
            vals, dropped = safe_vals('blog.post', vals_all)
            if dropped:
                print(" ! blog.post 忽略未知字段", dropped)
            fresh = not post
            if post:
                post.write(vals)
                po_kept += 1
            else:
                post = Post.create(vals)
                po_new += 1
            opt_write(post, {'subtitle': subtitle,
                             'published_date': now - datetime.timedelta(days=i)})
            opt_write(post, {'website_published': True})
            print(" 文章(%s)" % ('新建' if fresh else '保留'), title)
        env.cr.commit()
    else:
        print(" ! 未安装 website_blog，跳过")
except Exception as e:
    env.cr.rollback()
    print(" ! 博客段失败:", str(e)[:150])
print(" 博客 新建 %d；文章 新建 %d / 保留 %d" % (bl_new, po_new, po_kept))

# ---------------------------------------------------- D. 校友档案 /alumni
print("=" * 30, "D. 校友档案 op.student ×3", "=" * 30)
al_new = al_kept = 0
try:
    if 'op.student' in env:
        prp = S('op.course').search([('code', '=', 'CRS-PRP')], limit=1)
        ALUMNI = [("张同学" + DEMO, 'm'), ("李同学" + DEMO, 'f'),
                  ("陈同学" + DEMO, 'f')]
        Student = S('op.student')
        SC = S('op.student.course')
        for i, (nm, g) in enumerate(ALUMNI, 1):
            stu = Student.search([('name', '=', nm)], limit=1)
            if not stu:
                stu = Student.create({'name': nm, 'gender': g})
                al_new += 1
                print(" 校友(新建)", nm)
            else:
                al_kept += 1
                print(" 校友(保留)", nm)
            if prp and not SC.search([('student_id', '=', stu.id),
                                      ('course_id', '=', prp.id)], limit=1):
                sc_vals = {'student_id': stu.id, 'course_id': prp.id,
                           'roll_number': 'ALUM-D%02d' % i, 'state': 'finished'}
                if 'state' not in SC._fields:
                    sc_vals.pop('state', None)
                SC.create(sc_vals)
        env.cr.commit()
    else:
        print(" ! openeducat_core 未安装（op.student 不存在），跳过")
except Exception as e:
    env.cr.rollback()
    print(" ! 校友段失败:", str(e)[:150])
print(" 校友合计 新建 %d / 保留 %d" % (al_new, al_kept))

# --------------------------- E. /online-exams 兜底（映射 op.exam，而非 edu.quiz）
print("=" * 30, "E. 在线考试兜底 op.exam", "=" * 30)
ex_created = 0
try:
    if 'op.exam' in env and not S('op.exam').search_count([]):
        subj = S('op.subject').search([('code', '=like', 'PRP-%')],
                                      order='id asc', limit=1)
        if subj:
            sel = []
            if 'state' in S('op.exam')._fields:
                sel = [v[0] for v in
                       (S('op.exam')._fields['state'].selection or [])]
            st_val = next((v for v in ('schedule', 'scheduled') if v in sel),
                          None)
            ex_kwargs = {'state': st_val} if st_val else {}
            begin = now + datetime.timedelta(days=7)
            S('op.exam').create({
                'name': '阶段考 · 小要理问答',
                'exam_code': 'EX-PRP-A',
                'subject_id': subj.id,
                'total_marks': 100, 'min_marks': 60,
                'start_time': begin,
                'end_time': begin + datetime.timedelta(hours=1, minutes=30),
                **ex_kwargs})
            ex_created = 1
            print(" 考试(新建) 阶段考 · 小要理问答 @ %s" %
                  begin.strftime('%Y-%m-%d %H:%M'))
        else:
            print(" ! 无 PRP-C* 科目（请先跑 seed_yongyue_data.py），跳过建考试")
    else:
        print(" 已有考试记录 %d 条，无需兜底" %
              (S('op.exam').search_count([]) if 'op.exam' in env else 0))
    env.cr.commit()
except Exception as e:
    env.cr.rollback()
    print(" ! 考试段失败:", str(e)[:150])

# ------------------------------------------------ F. 汇总（courses-offered 只报告）
print("=" * 30, "F. 数量汇总", "=" * 30)


def cnt(model):
    return S(model).search_count([]) if model in env else '未安装'


print(" event.event      :", cnt('event.event'))
print(" blog.blog        :", cnt('blog.blog'))
print(" blog.post        :", cnt('blog.post'))
print(" hr.job           :", cnt('hr.job'))
print(" op.student       :", cnt('op.student'),
      "(/alumni 页取前 12 人)")
print(" op.exam          :", cnt('op.exam'))
print(" op.course        :", cnt('op.course'),
      "(/courses-offered 页直接展示，骨架课由 seed_yongyue_data.py 维护)")

env.cr.commit()
print("SEED_C DONE ✅")
