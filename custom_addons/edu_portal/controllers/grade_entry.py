# -*- coding: utf-8 -*-
"""门户「成绩录入」—— 教务 / 任课教师给整班录入各科成绩（2026-09-29）。

## 为什么是这条路（先复用，不新造第二套成绩模型）

本仓硬口径：**不新造成绩模型**。成绩的既有链路只有一条（基座 OpenEduCat）：

  写侧  op.exam.attendees.marks            -> 后台「时间表 / 考试 / 考试参加者」读的就是它
  读侧  op.marksheet.line -> op.result.line -> /grade-book、/users/result-overview、/my/study 读的就是它
  留痕  edu.grade.history                  -> 唯一受管写入口 edu_apply_marks()（本文件只调它）

基座把两侧连起来的是**后台一个手动按钮**（op.result.template.generate_result），而且不可重复
执行（op.result.line 上有 UNIQUE(exam_id, student_id)）=> 「录完学生就看得见」在基座上从来不是
自动的（实证见 docs/research/gradebook-entry.md 第 3 节：本地库同一条数据 attendee=20 / result_line=92）。

本文件的解法：**门户自己把两侧写齐**——
  ① 按需落一条「学期成绩单」容器链（session -> exam -> result.template -> marksheet.register）：
     一个 session = 一学期 x 一个班，一个 exam = 该班一科一个总分（用户口径「一科一个总分」）；
  ② 每次保存：op.exam.attendees.marks 走 edu.grade.history.edu_apply_marks()
     （留痕与站内信由既有钩子负责，本文件不重复实现），随后把该生的 op.result.line.marks
     改成同一个值 => 学生页 /grade-book 即时可见，且与后台是同一份数字；
  ③ 不迁移、不回填任何旧数据；容器 get-or-create（幂等）；改前改后行数可对账。

## 权限（四层模型里的第 2 / 3 层）

  · 教务 / 超管（group_op_back_office_admin / base.group_system）= 全校；
  · 任课教师（group_op_faculty）= **只限本人任教 (班级 x 科目)**，判据 = op.session 的
    (faculty_id, batch_id, subject_id) 三元组 —— 与 roles.py 的 _teacher_exam_domain() 同粒度；
  · 学生 / 家长 / 匿名 = 303 回门户首页。

⚠ 上面这三层是**控制器里的域收敛**，不是「页面不显示」。保存路由会**重新**按登录身份算一遍
可写的 (班级 x 科目) 集合，POST 里的 batch_id / subject_id / 学生 id **一律不信任**（学生必须
出现在服务端自己算出的名单里，否则整条丢弃）。
为什么必须这么写（本机实测，2026-09-29）：op.exam / op.exam.attendees 上**没有任何行级规则**；
op.marksheet.line / op.result.line 上那 4 条规则全挂在 openeducat_exam.group_op_exam_admin
**同一个组**上，而 Odoo 19 的组规则是**并集**（odoo/addons/base/models/ir_rule.py 的
_compute_domain：Domain.OR(group_domains)）=> 教务与教师都是「看得见全部行」。
**数据层不会替我们收敛，收敛必须写在写入路径上。**

## 2026-10-13 本轮新增：名单第 ③ 条来源 = 手工加人（设计稿 §4.2）

生产只读读数（2026-10-13）：op_student 51 人 / op_student_course 45 行 ⇒ **6 名「待分配」
学生（id 25/30/39/40/54/56）一行 op.student.course 都没有**，①②两条来源都读它 ⇒ 他们
**永远进不了任何成绩网格**；科目最多的总览班（batch 34）也是 0 学生 ⇒ 空网格。

加人 = 在 (班, 学期, 科目) 落一条**快照行**（edu.grade.entry.extra，见
models/grade_entry_extra.py 文件头）：**不写 op.student.course、不动学生档案**
（不越权改学生归属），加过的人重开本页仍在（持久化，不是会话态）。路由两条：

    POST /grade-entry/add-student      加人（**教务 / 超管专属**，教师一律 err=scope）
    POST /grade-entry/remove-student   移除（只删快照行，与加人同权）

权限口径（设计稿 §1 决策 #6 拍板原文「报课为主 + **教务**可手工加人」，§4.2 亦然）：
教师能**录分**，但**名单不由教师改** —— 名单是学籍侧的事实，教师塞人进来等于给学生页
制造一条**幻影课程成绩**。故两条写路由**只认 pairs is None**（教务/超管）；教师侧连 UI
卡片都不渲染（views/grade_entry.xml 的 t-if="is_registrar and term"）；而 _roster 的 ③
**读**不跟着收敛，教师照样看得见教务加进来的人（否则「教务加了、教师录分时看不见」就是
新缺陷）。

两条与保存路由共用**同一套** _scope_pairs：POST 里的 batch_id / subject_id / 学生 id /
快照行 id **一律不信任**，服务端逐个重算（越权一律按「不存在」处理，不泄露存在性）。
"""
import datetime

from odoo import http
from odoo.http import request

from .roles import current_faculty, privileged_staff

#: 容器考试的满分与及格线（百分制）。等级映射仍用既有字典 op.grade.configuration（7 档）。
MAX_MARKS = 100
MIN_MARKS = 60
#: 表格列数上限（超过则要求用「科目」筛选，避免一页几百个输入框）
MAX_COLUMNS = 20


# ----------------------------------------------------------------------
# 小工具
# ----------------------------------------------------------------------

def _safe_int(v):
    """宽松取整：拿不到就 None（POST 里的脏值一律当「没有」处理）。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _code(prefix, *ids):
    """确定性的短编号（op.exam(.session).exam_code 是 unique 且 size=16）。

    用 id 拼出来的编码是**幂等键**：同一 (班, 学期) / (班, 科, 学期) 永远得到同一个码，
    于是 get-or-create 只靠一次 search 就能命中，不需要额外存映射表。
    """
    return (prefix + ''.join(str(i) for i in ids))[:16]


def _default_term(env):
    """默认学期：覆盖今天的那个；没有就取第一个。"""
    Term = env['op.academic.term'].sudo()
    today = datetime.date.today()
    terms = Term.search([])
    for t in terms:
        if (t.term_start_date and t.term_end_date
                and t.term_start_date <= today <= t.term_end_date):
            return t
    return terms[:1]


def _session_dates(batch, term):
    """成绩单容器的日期区间（必须能装下容器考试的时间片）。"""
    if term and term.term_start_date and term.term_end_date:
        return term.term_start_date, term.term_end_date
    if batch.start_date and batch.end_date and batch.start_date <= batch.end_date:
        return batch.start_date, batch.end_date
    today = datetime.date.today()
    return today, today + datetime.timedelta(days=365)


def _container_type(env):
    """容器考试的类型字典：优先复用同码/同名的，没有才建一条（幂等，不重复建）。"""
    Type = env['op.exam.type'].sudo()
    rec = Type.search([('code', '=', 'TERM')], limit=1)
    if rec:
        return rec
    rec = Type.search([('name', '=', '学期总评')], limit=1)
    if rec:
        return rec
    return Type.create({'name': '学期总评', 'code': 'TERM'})


def _free_slot(env, subject, day_start, day_end):
    """给「一科一个总分」的容器考试找一个不冲突的 1 分钟占位时间片。

    为什么需要占位时间：基座 op.exam 的语义是「一场考试」—— start_time / end_time 必填，
    且 _check_overlapping_times 禁止**同科目**时间重叠。本功能借它当科目容器
    （见模块 docstring），因此必须给容器一个不与任何既有考试重叠的时间片。
    取法是确定性的：从区间起点起按 1 分钟步进，取第一个空位 => 可复现、可对账。
    """
    Ex = env['op.exam'].sudo()
    step = datetime.timedelta(minutes=1)
    cur = datetime.datetime.combine(day_start, datetime.time.min)
    limit = datetime.datetime.combine(day_end, datetime.time.max)
    while cur + step <= limit:
        end = cur + step
        clash = Ex.search_count([
            ('subject_id', '=', subject.id),
            ('start_time', '<', end.strftime('%Y-%m-%d %H:%M:%S')),
            ('end_time', '>', cur.strftime('%Y-%m-%d %H:%M:%S')),
        ])
        if not clash:
            return cur, end
        cur = end
    return None, None


def _ensure_container(env, batch, term, subject):
    """get-or-create：本科目在这一 (班, 学期) 的成绩单容器。

    返回 (session, exam, register)；任一步骤命中既有记录就直接复用。
    """
    Session = env['op.exam.session'].sudo()
    Exam = env['op.exam'].sudo()
    Template = env['op.result.template'].sudo()
    Register = env['op.marksheet.register'].sudo()

    term_id = term.id if term else 0
    s_code = _code('GB', batch.id, 'T', term_id)
    session = Session.search([('exam_code', '=', s_code)], limit=1)
    if not session:
        d0, d1 = _session_dates(batch, term)
        session = Session.create({
            'name': '%s · %s 成绩单' % (term.name if term else '本学期', batch.name),
            'exam_code': s_code,
            'course_id': batch.course_id.id or False,
            'batch_id': batch.id,
            'exam_type': _container_type(env).id,
            'evaluation_type': 'grade',
            'start_date': d0,
            'end_date': d1,
        })

    e_code = _code('GE', batch.id, 'S', subject.id, 'T', term_id)
    exam = Exam.search([('exam_code', '=', e_code)], limit=1)
    if not exam:
        start, end = _free_slot(env, subject, session.start_date, session.end_date)
        if not start:
            start, end = (datetime.datetime.combine(session.start_date,
                                                    datetime.time.min),
                          datetime.datetime.combine(session.start_date,
                                                    datetime.time.min)
                          + datetime.timedelta(minutes=1))
        exam = Exam.create({
            'name': '%s · %s 总评' % (subject.name, term.name if term else '本学期'),
            'exam_code': e_code,
            'subject_id': subject.id,
            'session_id': session.id,
            'start_time': start.strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': end.strftime('%Y-%m-%d %H:%M:%S'),
            'total_marks': MAX_MARKS,
            'min_marks': MIN_MARKS,
            # 基座口径：result.template 的约束要求 session 下所有 exam 都是 done；
            # 「一科一个总分」的容器本身就是已定稿的成绩条目，故直接落 done。
            'state': 'done',
            'note': '门户「成绩录入」按需生成的科目总评容器（非真实考试时间）。',
        })

    template = Template.search([('exam_session_id', '=', session.id)], limit=1)
    if not template:
        grades = env['op.grade.configuration'].sudo().search([])
        template = Template.create({
            'name': '%s 等级表' % (batch.name or '成绩单'),
            'exam_session_id': session.id,
            'grade_ids': [(6, 0, grades.ids)],
            'state': 'result_generated',
        })

    register = Register.search([('exam_session_id', '=', session.id)], limit=1)
    if not register:
        register = Register.create({
            'name': '%s 成绩单' % (batch.name or '班级'),
            'exam_session_id': session.id,
            'result_template_id': template.id,
            'generated_by': env.uid,
            'state': 'draft',
        })
    return session, exam, register


# ----------------------------------------------------------------------
# 范围（谁能录哪些班 / 哪些科）
# ----------------------------------------------------------------------

def _scope_pairs(env, faculty):
    """当前身份可写的 (batch_id, subject_id) 集合；None = 全校（教务 / 超管）。

    教师口径 = op.session 的 (faculty_id, batch_id, subject_id) 三元组 —— 与
    roles.py 的 _teacher_exam_domain() 同一粒度（「本人任教这个班的这一科」）。
    """
    if privileged_staff():
        return None
    if not faculty:
        return set()
    sessions = env['op.session'].sudo().search([('faculty_id', '=', faculty.id)])
    return set((s.batch_id.id, s.subject_id.id) for s in sessions
               if s.batch_id and s.subject_id)


def _allowed_batches(env, faculty):
    """可选班级（教师侧收敛到本人任教的班）。"""
    Batch = env['op.batch'].sudo()
    pairs = _scope_pairs(env, faculty)
    if pairs is None:
        return Batch.search([])
    return Batch.browse(sorted(set(b for b, _s in pairs))).exists()


def _allowed_subjects(env, faculty):
    """可选科目（教师侧收敛到本人任教的科目）。"""
    Subject = env['op.subject'].sudo()
    pairs = _scope_pairs(env, faculty)
    if pairs is None:
        return Subject.search([])
    return Subject.browse(sorted(set(s for _b, s in pairs))).exists()


# ----------------------------------------------------------------------
# 名单与网格
# ----------------------------------------------------------------------

def _batch_subjects(env, batch):
    """本班科目的两个来源的并集：本班课节（op.session）× 本班学生已报科目。

    它是"待分配学生要不要进这张表"的判据（见 _roster ②），也是列集合的底。
    """
    subjects = env['op.session'].sudo().search(
        [('batch_id', '=', batch.id)]).mapped('subject_id')
    scs = env['op.student.course'].sudo().search([('batch_id', '=', batch.id)])
    return (subjects | scs.mapped('subject_ids')).exists()


def _entry_url(batch, term, subject=None):
    """回到录入页的地址（带上当前班 / 学期 / 科目 —— 加人/移除后筛选不被清空）。"""
    parts = ['batch_id=%d' % (batch.id if batch else 0)]
    if term:
        parts.append('term_id=%d' % term.id)
    if subject:
        parts.append('subject_id=%d' % subject.id)
    return '/grade-entry?' + '&'.join(parts)


def _addable_students(env):
    """可加人的学生 = **全部在册学生**（口径 = 设计稿 §4.2「任意在册学生」）。

    为什么不收敛到本班：本功能存在的全部理由就是那 6 名「待分配」学生（他们
    一行 op.student.course 都没有、不在任何班的名单里，见模块 docstring）——
    按班级收敛等于把功能做没了。

    **只有教务 / 超管**会用到这份名单：加人是教务侧权限（设计稿 §1 决策 #6 拍板原文
    「报课为主 + **教务**可手工加人」，§4.2 亦然）。教师能录分，但**名单不由教师改**
    —— 名单是学籍侧的事实，教师塞人进来等于给学生页制造一条**幻影课程成绩**，
    而两条写路由（检查 pairs is None）正是拦这个。
    """
    return env['op.student'].sudo().search(
        [('active', '=', True)], order='gr_no, name')


def _manual_entries(env, batch, term, subject=None):
    """本 (班, 学期[, 科目]) 已有的手工加人行（页面「已手工加人」清单的数据源）。"""
    Extra = env['edu.grade.entry.extra'].sudo()
    if not batch or not term:
        return Extra.browse()
    domain = [('batch_id', '=', batch.id), ('term_id', '=', term.id)]
    if subject is not None:
        domain.append(('subject_id', '=', subject.id))
    return Extra.search(domain)


def _roster(env, batch, subject=None, batch_subjects=None, term=None,
            allowed_subject_ids=None):
    """整班名单（行）。

    口径三层，**缺一不可**（用户口径是「按报课名单」，但今天报课数据几乎为空 —— 见
    docs/research/gradebook-entry.md 第 6.5 节，纯报课口径今天录不了分）：

      ① 班级口径：op.student.course.batch_id = 本班（整班学生，成绩网格的主体）；
      ② 报课口径：op.student.course.subject_ids 含本科目 **且该生还没有班级归属**
         （【待分配】学生唯一能被录到分的通路；有班的学生由 ① 覆盖）；
      ③ 手工加人口径（2026-10-13 本轮新增，设计稿 §4.2）：edu.grade.entry.extra 里
         本 (班, 学期, 科目) 的快照行。为什么必须有它 —— 生产 6 名学生
         （id 25/30/39/40/54/56）一行 op.student.course 都没有，①② 都读它 ⇒ 他们
         永远进不了任何成绩网格；总览班 batch 34（14 科）0 学生 ⇒ 空网格。

    ①② 都要求 course_id 与本班的课程一致（防串课程）；③ 不看 op.student.course
    （那正是它存在的意义），只看快照表自己的四元组。

    参数：
      · term：给了就只认 **该学期** 的手工加人行（设计稿的四元组是 (班,学期,科目,学生)）；
        None 时退化成只按 (班, 科目) 过滤 —— 宁可宽一点，也不能让已加过的人凭空消失。
      · allowed_subject_ids：任课教师传本人任教的科目 id 集合，手工加人行只出他任教科目
        的（与 _columns 的「按身份收敛列」同一理由：他那张网格只有这几列，别的科目加进来
        的人对他就是一行没有内容的幻影行）。**这只收敛「看得见什么」，不是写权限** ——
        加人/移除本身是教务/超管专属（见 grade_entry_add_student）。教务 / 超管传 None ⇒ 不收敛。

    返回 [{student, source}]；source 是给教务看的「为什么他会在这张表上」。
    """
    SC = env['op.student.course'].sudo()
    course_id = batch.course_id.id
    rows, seen = [], set()

    def _course_ok(sc):
        return (not course_id) or (sc.course_id.id == course_id)

    for sc in SC.search([('batch_id', '=', batch.id)]):
        if not _course_ok(sc):
            continue
        st = sc.student_id
        if not st or not st.active or st.id in seen:
            continue
        seen.add(st.id)
        rows.append({'student': st, 'source': '班级'})

    # ② 报课口径：指定科目时 = 报了该科；矩阵（未指定科目）时 = 报的科目与本班科目有交集。
    #    只收**还没有班级归属**的学生 —— 有班的人由 ① 覆盖，不会因为报课而重复出现。
    take = None
    if subject is not None:
        take = subject
    elif batch_subjects is not None and batch_subjects:
        take = batch_subjects
    if take is not None:
        for sc in SC.search([('subject_ids', 'in', take.ids)]):
            if not _course_ok(sc):
                continue
            st = sc.student_id
            if not st or not st.active or st.id in seen or sc.batch_id:
                continue
            seen.add(st.id)
            rows.append({'student': st, 'source': '报课（未分班）'})

    # ③ 手工加人口径（2026-10-13 本轮新增，设计稿 §4.2）：edu.grade.entry.extra。
    #    与 ①② 的关键差别：**一行 op.student.course 都不读** —— 那正是它存在的理由
    #    （生产 6 名学生 id 25/30/39/40/54/56 无任何 op.student.course 行，读它的 ①②
    #    永远收不到他们）。加人只给这张 (班,学期,科目) 成绩名单补一个人，不动学生档案。
    #    学期：给了 term 就精确按四元组收；没给（矩阵页可以不选学期）退化成只按
    #    (班[,科目]) 收 —— 宁可宽一点，也不能让已加过的人凭空消失。
    extra_domain = [('batch_id', '=', batch.id)]
    if term:
        extra_domain.append(('term_id', '=', term.id))
    if subject is not None:
        extra_domain.append(('subject_id', '=', subject.id))
    for ex in env['edu.grade.entry.extra'].sudo().search(extra_domain):
        if allowed_subject_ids is not None and ex.subject_id.id not in allowed_subject_ids:
            continue          # 教师只看自己任教科目的手工加人行（收敛「看得见」，写权限另判 pairs）
        st = ex.student_id
        if not st or not st.active or st.id in seen:
            continue
        seen.add(st.id)
        rows.append({'student': st, 'source': '手工加人'})

    rows.sort(key=lambda r: (r['student'].gr_no or '', r['student'].id))
    return rows


def _columns(env, batch, roster, subject=None, batch_subjects=None,
             allowed_subject_ids=None):
    """科目列：指定了就一列；否则按「本班科目 ∪ 名单学生已报科目」取，按名称排序。

    2026-10-03 第三轮：新增 allowed_subject_ids —— **按身份收敛列**。
      · 教务 / 超管传 None ⇒ 列**一个不少**（他本来就能存全部列，收窄 = 平白降低能力）；
      · 任课教师传**本人任教的科目 id 集合** ⇒ 只出他存得进去的列。
    为什么必须有这一层（实测缺陷，2026-10-03）：行按班收敛、**列原先不按任教收敛**，
    于是教师看得见 10 个自己存不进去的输入框；填了保存 → 服务端丢弃 → 页面还说
    「本次没有新的改动」⇒ 用户视角是「我填了，没反应」，比看到拒止文案更糟。
    收敛口径与保存路由的 (batch.id, sub_id) in pairs **同源**，不新增第二份判据。
    """
    if subject is not None:
        return subject
    subjects = batch_subjects
    if subjects is None:
        subjects = _batch_subjects(env, batch)
    else:
        subjects = subjects.exists()
    scs = env['op.student.course'].sudo().search(
        [('student_id', 'in', [r['student'].id for r in roster])])
    subjects |= scs.mapped('subject_ids')
    subjects = subjects.exists()
    if allowed_subject_ids is not None:
        subjects = subjects.filtered(lambda s: s.id in allowed_subject_ids)
    if len(subjects) > MAX_COLUMNS:
        # 列太多就退化成「前 N 列」，并在页面上明确提示用科目筛选 —— 不静默截断
        subjects = subjects.sorted(lambda s: s.name or '')[:MAX_COLUMNS]
    return subjects.sorted(lambda s: s.name or '')


def _existing(env, batch, term, subjects):
    """既有容器读数：{subject_id: {exam, marks, attendee}}。

    两侧都读：**成绩单侧**（op.result.line = 学生看到的）与**后台侧**（op.exam.attendees
    = 后台「考试参加者」显示的）。两者不一致时页面会标出来（基座那座桥不自动同步）。
    """
    out = {}
    for sub in subjects:
        e_code = _code('GE', batch.id, 'S', sub.id, 'T', term.id if term else 0)
        exam = env['op.exam'].sudo().search([('exam_code', '=', e_code)], limit=1)
        if not exam:
            out[sub.id] = None
            continue
        marks, att_marks = {}, {}
        for rl in env['op.result.line'].sudo().search([('exam_id', '=', exam.id)]):
            marks[rl.student_id.id] = rl.marks
        for att in env['op.exam.attendees'].sudo().search([('exam_id', '=', exam.id)]):
            att_marks[att.student_id.id] = att.marks
        out[sub.id] = {'exam': exam, 'marks': marks, 'attendee': att_marks}
    return out


def _history(env, batch, limit=8):
    """最近若干条留痕（复用既有 edu.grade.history，不另开表）。

    这里刻意把记录摊平成 dict（而不是把 recordset 交给模板）：来源/动作的显示名要过
    selection 表，模板里做那种取值既绕又容易踩 QWeb 求值的坑。
    """
    hist = env['edu.grade.history'].sudo()
    exams = []
    prefix = _code('GE', batch.id, 'S')
    for exam in env['op.exam'].sudo().search([('batch_id', '=', batch.id)]):
        if exam.exam_code and exam.exam_code.startswith(prefix):
            exams.append(exam.id)
    if not exams:
        return []
    labels = dict(hist._fields['source'].selection)
    out = []
    for h in hist.search([('exam_id', 'in', exams)],
                         order='timemodified desc, id desc', limit=limit):
        out.append({
            'when': h.timemodified,
            'student': h.student_id.name or '',
            'subject': h.subject_id.name or '',
            'old': h.old_marks,
            'new': h.new_marks,
            'user': h.logged_user_id.name or '',
            'source': labels.get(h.source, h.source or ''),
        })
    return out


# ----------------------------------------------------------------------
# 控制器
# ----------------------------------------------------------------------

class EduGradeEntry(http.Controller):
    """教务 / 任课教师的成绩录入（门户侧，与后台同一份数据）。"""

    def _guard(self):
        """身份门禁：返回 (faculty, redirect)；教务 / 超管 faculty 可能为 None。"""
        if privileged_staff():
            return None, None
        fac = current_faculty()
        if not fac:
            return None, request.redirect('/my/home')
        return fac, None

    @http.route('/grade-entry', type='http', auth='user', website=True)
    def grade_entry(self, **kw):
        fac, redirect = self._guard()
        if redirect:
            return redirect
        env = request.env
        pairs = _scope_pairs(env, fac)
        batches = _allowed_batches(env, fac)

        batch = batches.browse([])
        bid = _safe_int(kw.get('batch_id'))
        if bid and (pairs is None or any(b == bid for b, _s in pairs)):
            batch = env['op.batch'].sudo().browse(bid).exists()
            if batch and batch not in batches:
                batch = batches.browse([])

        term = env['op.academic.term'].sudo().browse(
            _safe_int(kw.get('term_id')) or 0).exists() or _default_term(env)

        subject = None
        sid = _safe_int(kw.get('subject_id'))
        if sid:
            subject = env['op.subject'].sudo().browse(sid).exists()
            if subject and pairs is not None and (batch.id, subject.id) not in pairs:
                # 越权 / 不可用一律按「不存在」处理（与 /grading/* 的 _teacher_exam 同口径）
                subject = None

        values = {
            'title': '成绩录入',
            'page_name': 'grade_entry',
            'is_registrar': pairs is None,
            'batches': batches,
            'all_subjects': _allowed_subjects(env, fac),
            'terms': env['op.academic.term'].sudo().search([]),
            'batch': batch,
            'term': term,
            'subject_filter': subject,
            'saved': _safe_int(kw.get('saved')) or 0,
            'err': kw.get('err') or '',
            # 手工加人（设计稿 §4.2）的操作回执；空 batch 路径下也给默认值，
            # 免得模板求值时少键（QWeb 缺键是报错，不是空值）
            'added': _safe_int(kw.get('added')) or 0,
            'removed': _safe_int(kw.get('removed')) or 0,
            'addable_students': env['op.student'].sudo().browse(),
            'manual_rows': env['edu.grade.entry.extra'].sudo().browse(),
            'addable_subjects': env['op.subject'].sudo().browse(),
            # 2026-10-03 第三轮：被权限丢弃的格子数（带原因），用于给用户**正确的**反馈
            'skip_scope': _safe_int(kw.get('skip_scope')) or 0,
            'skip_roster': _safe_int(kw.get('skip_roster')) or 0,
            'rows': [],
            'columns': [],
            'history': [],
            'truncated': False,
            'roster_n': 0,
            'max_marks': MAX_MARKS,
        }
        if not batch:
            return request.render('edu_portal.edu_grade_entry', values)

        # 网格：行 = 整班名单，列 = 科目
        batch_subjects = _batch_subjects(env, batch)
        # 列 / 名单按身份收敛：教务/超管 pairs is None ⇒ 全部；教师 ⇒ 只出本人任教的科目
        # （与保存路由的 (batch.id, sub_id) in pairs 同一个 pairs，不另立口径）
        allowed_ids = None if pairs is None else {s for _b, s in pairs}
        # term 也要传进去：手工加人的四元组含学期（设计稿 §4.2），换学期名单就该换
        roster = _roster(env, batch, subject, batch_subjects,
                         term=term, allowed_subject_ids=allowed_ids)
        columns = _columns(env, batch, roster, subject, batch_subjects,
                           allowed_subject_ids=allowed_ids)
        if subject is None and len(columns) >= MAX_COLUMNS:
            values['truncated'] = True
        existing = _existing(env, batch, term, columns)

        cols = []
        for sub in columns:
            info = existing.get(sub.id)
            cols.append({
                'id': sub.id,
                'name': sub.name or '',
                'exam': info['exam'] if info else None,
                'count': len(info['marks']) if info else 0,
            })
        rows = []
        for r in roster:
            st = r['student']
            cells = []
            for sub in columns:
                info = existing.get(sub.id)
                shown = None
                mismatch = False
                if info:
                    shown = info['marks'].get(st.id)
                    att = info['attendee'].get(st.id)
                    if shown is not None and att is not None and att != shown:
                        mismatch = True
                cells.append({
                    'col_id': sub.id, 'value': shown, 'mismatch': mismatch,
                    # 显示串单独给：分数 0 必须显示成 "0"（不能用 or '' 兜底）
                    'text': '' if shown is None else str(shown),
                })
            rows.append({'student_id': st.id, 'name': st.name or '',
                         'gr_no': st.gr_no or '', 'source': r['source'],
                         'cells': cells})
        values.update({
            'rows': rows, 'columns': cols,
            'history': _history(env, batch),
            'roster_n': len(rows),
            # 手工加人卡片（设计稿 §4.2）：能加谁 + 能加到哪科 + 本格已经手工加了谁
            'addable_students': _addable_students(env),
            'manual_rows': _manual_entries(env, batch, term, subject).filtered(
                # 卡片本身只对教务/超管渲染（t-if="is_registrar and term"），这里保留
                # 与 _roster ③ 同源的科目收敛纯粹是纵深防御：万一将来放宽卡片条件，
                # 也不会出现「看得见、点移除却被服务端拒」的错配（本仓按缺陷处理）。
                lambda ex: allowed_ids is None or ex.subject_id.id in allowed_ids),
            # 可选科目 = 本班科目 ∩ 本人任教（教务 / 超管 = 本班全部科目）。
            # 不复用 all_subjects：那是「本人任教过的全部科目」（跨班），选中会把学生加进
            # 一个他并不教的班×科目 —— 服务端会拦，但让用户白填一遍同样是坏体验。
            'addable_subjects': (
                batch_subjects if allowed_ids is None
                else batch_subjects.filtered(lambda s: s.id in allowed_ids)),
        })
        return request.render('edu_portal.edu_grade_entry', values)

    @http.route('/grade-entry/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def grade_entry_save(self, **post):
        fac, redirect = self._guard()
        if redirect:
            return redirect
        env = request.env
        pairs = _scope_pairs(env, fac)
        batch = env['op.batch'].sudo().browse(
            _safe_int(post.get('batch_id')) or 0).exists()
        term = env['op.academic.term'].sudo().browse(
            _safe_int(post.get('term_id')) or 0).exists() or _default_term(env)
        back = '/grade-entry?batch_id=%d&term_id=%d' % (
            batch.id if batch else 0, term.id if term else 0)
        if not batch:
            return request.redirect('/grade-entry?err=nobatch')
        # 保存路由**重新**算一遍权限：不信任 POST 里的任何 id（见模块 docstring）
        if pairs is not None and not any(b == batch.id for b, _s in pairs):
            return request.redirect('/grade-entry?err=scope')

        # ① 只认服务端自己算出的名单（口径必须与展示同一套，否则会出现
        #    "页面能看见、保存被丢弃"的假象：矩阵页的名单 = 本班学生 + 报了本班科目的未分班学生
        #    + 手工加人的人（③，2026-10-13））。
        #    这里必须把 term 与 allowed_ids 一起传给 _roster：漏了 term 会放进别学期
        #    手工加的人，漏了 allowed_ids 会放进教师无权存的科目的名单行 —— 两者都会让
        #    「页面看得见」与「保存被丢弃」重新对不上（正是上一轮修过的缺陷）。
        save_allowed = None if pairs is None else {s for _b, s in pairs}
        allowed_students = set(
            r['student'].id
            for r in _roster(env, batch, None, _batch_subjects(env, batch),
                             term=term, allowed_subject_ids=save_allowed))
        # ② 解析 POST：只接受 (名单内学生, 有权录的科目) 的格子
        # 2026-10-03 第三轮：被丢弃的格子要**计数并回传**。原先是静默 continue，
        # 用户填了越权格子 → 保存 → 页面说「本次没有新的改动」—— 那是**错误的归因**：
        # 用户明明改了。静默失败在本仓按缺陷处理，故这里把「为什么没存」带到页面上。
        cells, bad = {}, []
        n_scope, n_roster = 0, 0        # 越权科目 / 不在名单 被丢弃的格子数
        for key, raw in post.items():
            if not key.startswith('m_'):
                continue
            parts = key.split('_')
            if len(parts) != 3:
                continue
            sid, sub_id = _safe_int(parts[1]), _safe_int(parts[2])
            if sid is None or sub_id is None:
                continue
            raw = (raw or '').strip()
            if sid not in allowed_students:
                n_roster += 1
                continue                      # 不在名单里的学生 => 整条丢弃
            if pairs is not None and (batch.id, sub_id) not in pairs:
                n_scope += 1
                continue                      # 越权科目 => 整条丢弃
            if raw == '':
                continue                      # 留空 = 不录入 / 不改动
            try:
                marks = int(float(raw))
            except (TypeError, ValueError):
                bad.append(key)
                continue
            if marks < 0 or marks > MAX_MARKS:
                bad.append(key)
                continue
            cells.setdefault(sub_id, {})[sid] = marks
        skip = ''
        if n_scope:
            skip += '&skip_scope=%d' % n_scope
        if n_roster:
            skip += '&skip_roster=%d' % n_roster
        if bad:
            return request.redirect(back + '&err=invalid')
        if not cells:
            # 一格都没存下：把「被忽略了几格、为什么」一并带回去（不是静默 saved=0）
            return request.redirect(back + '&saved=0' + skip)

        Hist = env['edu.grade.history'].sudo()
        Attendee = env['op.exam.attendees'].sudo()
        ResultLine = env['op.result.line'].sudo()
        MarksheetLine = env['op.marksheet.line'].sudo()
        n_changed, n_seen = 0, 0
        for sub_id, marks_by_student in cells.items():
            subject = env['op.subject'].sudo().browse(sub_id).exists()
            if not subject:
                continue
            session, exam, register = _ensure_container(env, batch, term, subject)
            for sid, marks in sorted(marks_by_student.items()):
                n_seen += 1
                att = Attendee.search([('exam_id', '=', exam.id),
                                       ('student_id', '=', sid)], limit=1)
                if not att:
                    att = Attendee.create({'exam_id': exam.id,
                                           'student_id': sid})
                # ③ 写侧：既有唯一受管入口（留痕 + 站内信由它 / 模型钩子负责）
                Hist.edu_apply_marks(att, marks=marks, source='manual')
                # ④ 读侧：学生页读的是 op.result.line => 同步成同一个值
                line = MarksheetLine.search(
                    [('marksheet_reg_id', '=', register.id),
                     ('student_id', '=', sid)], limit=1)
                if not line:
                    line = MarksheetLine.create(
                        {'student_id': sid, 'marksheet_reg_id': register.id})
                rl = ResultLine.search([('exam_id', '=', exam.id),
                                        ('student_id', '=', sid)], limit=1)
                if not rl:
                    ResultLine.create({'exam_id': exam.id, 'student_id': sid,
                                       'marks': marks,
                                       'marksheet_line_id': line.id})
                elif rl.marks != marks:
                    rl.write({'marks': marks})
                if att.marks == marks:
                    n_changed += 1
            env['edu.audit.log'].sudo()._log(
                '成绩录入', 'op.exam', exam.id, exam.name or '',
                '门户网格录入 %d 条（班级 %s / 科目 %s）' % (
                    len(marks_by_student), batch.name or '', subject.name or ''))
        # 部分保存时也要说清「另外有几格被忽略」——只报成功、不报忽略同样是静默失败
        return request.redirect(
            back + '&saved=%d&n=%d%s' % (n_changed, n_seen, skip))

    # ------------------------------------------------------------------
    # 手工加人 / 移除（2026-10-13 本轮新增，设计稿 §4.2）
    # ------------------------------------------------------------------
    # 为什么单开路由而不是塞进 /grade-entry/save：加人不产生任何成绩（落的是名单快照
    # edu.grade.entry.extra），留痕内容、失败原因、幂等性都与「存分」不同；混进保存
    # 路由只会把「哪些格子被丢弃」的口径搅浑。
    # 权限判据与保存路由**同一套** _scope_pairs —— 不另立第二份判据。
    # 失败一律 redirect 回录入页并带 err（用户口径：越权要「整条丢弃」，不是抛 500）。
    @http.route('/grade-entry/add-student', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def grade_entry_add_student(self, **post):
        """把一名**在册学生**手工加进 (班, 学期, 科目) 的成绩名单。

        谁能加人：**只有教务 / 超管**（判据 pairs is None）。教师能**录分**，但**名单不由教师改**
        —— 名单是**学籍侧**的事实（设计稿 §1 决策 #6 拍板原文「报课为主 + **教务**可手工加人」，
        §4.2 亦然），教师把学生塞进本班本课名单 = 给学生页制造一条**幻影课程成绩**，而他无权
        改学籍（本功能绝不写 op.student.course）。教师身份一律 err=scope。

        POST 一律不信任（batch_id / subject_id / student_id 都只当线索，服务端重算）：
          · 身份：pairs is not None（教师）⇒ 直接拒；教务/超管 pairs is None = 全校；
          · 科目：必须真存在（篡改表单塞假 id ⇒ err=scope，不泄露存在性）；
          · 学生：只要是 **active 的在册学生**即可，**不**要求他在本班 —— 本功能的全部
            意义就是收那 6 名「待分配」学生（他们一行 op.student.course 都没有，
            按班收敛等于把功能做没了，见 _addable_students）；
          · 学期：必填。四元组里它是定位的一半，缺了这条快照下次打开本页就找不回来。
        """
        fac, redirect = self._guard()
        if redirect:
            return redirect
        env = request.env
        pairs = _scope_pairs(env, fac)
        batch = env['op.batch'].sudo().browse(
            _safe_int(post.get('batch_id')) or 0).exists()
        term = env['op.academic.term'].sudo().browse(
            _safe_int(post.get('term_id')) or 0).exists()
        back = _entry_url(batch, term)
        if not batch:
            return request.redirect('/grade-entry?err=nobatch')
        if not term:
            return request.redirect(back + '&err=noterm')
        # 加人 = 教务 / 超管专属（pairs is None）。教师（pairs 非 None）一律拒：
        # 他能录分，但名单是学籍侧事实，不由教师改（设计稿 §1 决策 #6 / §4.2）。
        if pairs is not None:
            return request.redirect(back + '&err=scope')
        subject = env['op.subject'].sudo().browse(
            _safe_int(post.get('subject_id')) or 0).exists()
        if not subject:
            return request.redirect(back + '&err=scope')   # 篡改的科目 id 按「不存在」处理
        student = env['op.student'].sudo().browse(
            _safe_int(post.get('student_id')) or 0).exists()
        if not student or not student.active:
            return request.redirect(back + '&err=nofound')
        # 已在名单里（①班级 / ②报课 / ③手工任一来源）就别落第二条 —— 落了也看不见
        # （_roster 会因去重跳过），用户视角就是「我加了，没反应」= 静默失败。
        if any(r['student'].id == student.id
               for r in _roster(env, batch, subject, None, term=term)):
            return request.redirect(back + '&err=dupe')

        Extra = env['edu.grade.entry.extra'].sudo()
        dupe = Extra.search([('batch_id', '=', batch.id),
                             ('term_id', '=', term.id),
                             ('subject_id', '=', subject.id),
                             ('student_id', '=', student.id)], limit=1)
        if dupe:
            return request.redirect(back + '&err=dupe')
        row = Extra.create({
            'batch_id': batch.id, 'term_id': term.id, 'subject_id': subject.id,
            'student_id': student.id,
            'added_by': env.user.id,          # 谁加的：取自会话，不取自表单
            'note': (post.get('note') or '').strip()[:128],
        })
        # 留痕：加的是**名单**，不是成绩，也没碰学生档案（op.student.course 不写）
        env['edu.audit.log'].sudo()._log(
            '手工加人', 'op.student', student.id, student.name or '',
            '加进成绩名单：%s / %s / %s（快照行 #%d）' % (
                batch.name or '', term.name or '', subject.name or '', row.id))
        return request.redirect(back + '&added=1')

    @http.route('/grade-entry/remove-student', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def grade_entry_remove_student(self, **post):
        """移除手工加人：**只删快照行** —— 学生档案（op.student.course）一个字节不动。

        与加人**同权**：**只有教务 / 超管**（判据 pairs is None，理由见 grade_entry_add_student）。
        教师能在网格「名单来源」列看见「手工加人」标记（_roster ③ 只读不收敛），
        但改名单不是他的权（设计稿 §1 决策 #6 / §4.2），教师身份一律 err=scope。

        POST 里的 row_id 只当线索：行必须真属于本 (班, 学期)，否则按「不存在」处理
        （不泄露行是否存在）。
        """
        fac, redirect = self._guard()
        if redirect:
            return redirect
        env = request.env
        pairs = _scope_pairs(env, fac)
        batch = env['op.batch'].sudo().browse(
            _safe_int(post.get('batch_id')) or 0).exists()
        term = env['op.academic.term'].sudo().browse(
            _safe_int(post.get('term_id')) or 0).exists()
        back = _entry_url(batch, term)
        if not batch:
            return request.redirect('/grade-entry?err=nobatch')
        if not term:
            return request.redirect(back + '&err=noterm')
        # 与加人同权：教务 / 超管专属（pairs is None），教师一律拒。
        if pairs is not None:
            return request.redirect(back + '&err=scope')
        row = env['edu.grade.entry.extra'].sudo().browse(
            _safe_int(post.get('row_id')) or 0).exists()
        if (not row or row.batch_id.id != batch.id or row.term_id.id != term.id):
            return request.redirect(back + '&err=nofound')
        # 先把要留痕的字段读出来再删（删完再读记录会踩 MissingError）
        sid, who = row.student_id.id, row.student_id.name or ''
        what = '%s / %s / %s' % (batch.name or '', term.name or '',
                                 row.subject_id.name or '')
        row.unlink()
        env['edu.audit.log'].sudo()._log(
            '移除手工加人', 'op.student', sid, who, '从成绩名单移除：%s' % what)
        return request.redirect(back + '&removed=1')
