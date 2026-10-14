# -*- coding: utf-8 -*-
"""Telegram webhook：多角色教务前端。

- 回复写在 HTTP 响应体（{"method": "sendMessage"/"editMessageText"}），
  由 Telegram 代发，本机无需出站访问 api.telegram.org。
- 处理器全部显式接收 env，纯逻辑可在测试里直接调用。
- inline 按钮：课表切周、成绩/图书翻页；回复附「打开网页端」深链。
"""
import datetime
import hashlib
import hmac
import json
import logging
import re
import time

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_MSG = 4000
PAGE_SIZE = 6

HELP = (
    "📚 教务助手\n"
    "点下方按钮或输入命令：\n"
    "学生：课表 考试 成绩 成绩单 作业 交作业 考勤 图书 缴费\n"
    "　　档案 校历 请假 预约 布告 学生证 在读证明 考勤报表\n"
    "教师：课表 考试 图书 课时 点名 成绩录入\n"
    "家长：课表 成绩 考勤 缴费（按孩子）\n"
    "管理员：概览 公告管理\n"
    "多步操作随时 /取消 中止。\n"
    "绑定：网页端 /my/telegram 取绑定码，发送 /start 绑定码；\n"
    "备用：/start 学号或工号 出生年月(YYYYMMDD)\n"
    "解绑：/解绑"
)

KB_STUDENT = {'keyboard': [['课表', '考试', '成绩'],
                           ['成绩单', '作业', '交作业'],
                           ['图书', '缴费', '考勤'],
                           ['请假', '预约', '布告'],
                           ['档案', '帮助']],
              'resize_keyboard': True}
KB_FACULTY = {'keyboard': [['课表', '考试'], ['点名', '成绩录入'],
                           ['课时', '图书', '帮助']],
              'resize_keyboard': True}
KB_PARENT = {'keyboard': [['课表', '成绩'], ['考勤', '缴费'], ['帮助']],
             'resize_keyboard': True}
KB_ADMIN = {'keyboard': [['概览'], ['帮助']], 'resize_keyboard': True}
KB_GUEST = {'keyboard': [['帮助']], 'resize_keyboard': True}

KEYBOARDS = {'student': KB_STUDENT, 'faculty': KB_FACULTY,
             'parent': KB_PARENT, 'admin': KB_ADMIN, None: KB_GUEST}


def param(env, key, default=None):
    return env['ir.config_parameter'].sudo().get_param(key, default)


def base_url(env):
    return (param(env, 'edu_telegram.public_base_url')
            or param(env, 'web.base.url') or '').rstrip('/')


def student_course(env, student):
    if not student or student._name != 'op.student':
        return None, None
    sc = env['op.student.course'].sudo().search(
        [('student_id', '=', student.id)], limit=1)
    return (sc.course_id, sc.batch_id) if sc else (None, None)


def _f(v):
    return v and v.strftime('%m-%d %H:%M') or '待定'


# ------------------------- 列表渲染 -------------------------

def _pager(data_prefix, offset, step, span):
    """返回上一页/下一页 inline 按钮行。"""
    row = []
    if offset - step >= -span:
        row.append({'text': '◀️ 上一页', 'callback_data':
                    '%s:%d' % (data_prefix, offset - step)})
    row.append({'text': '•', 'callback_data': 'noop'})
    if offset + step <= span:
        row.append({'text': '下一页 ▶️', 'callback_data':
                    '%s:%d' % (data_prefix, offset + step)})
    return row


def _week_rows(sessions, now):
    if not sessions:
        return "该周没有排课。"
    wd = '一二三四五六日'
    lines, cur_day = [], None
    for s in sessions:
        st = s.start_datetime
        day = st.date()
        label = ('今天' if day == now.date() else
                 '明天' if day == (now + datetime.timedelta(days=1)).date()
                 else '周' + wd[st.weekday()] + '(%d/%d)' % (st.month, st.day))
        if label != cur_day:
            lines.append("\n📅 " + label)
            cur_day = label
        lines.append("%02d:%02d %s @%s %s" % (
            st.hour, st.minute, s.subject_id.name or '课程',
            s.classroom_id.name or '待定',
            '(' + s.faculty_id.name + ')' if s.faculty_id.name else ''))
    return "\n".join(lines)


def cmd_timetable(env, rec, week=0):
    Session = env['op.session'].sudo()
    now = datetime.datetime.now()
    start = now + datetime.timedelta(days=7 * week)
    dom = [('start_datetime', '>=', start.replace(hour=0, minute=0)),
           ('start_datetime', '<',
            start.replace(hour=0, minute=0) + datetime.timedelta(days=7))]
    if rec._name == 'op.student':
        _, batch = student_course(env, rec)
        if not batch:
            return "未查到班级信息，无法拉取课表。"
        dom.append(('batch_id', '=', batch.id))
    else:
        dom.append(('faculty_id', '=', rec.id))
    title = "📅 课表（%s 起）" % (
        now.strftime('%m/%d') if week == 0 else start.strftime('%m/%d'))
    return title + "\n" + _week_rows(
        Session.search(dom, order='start_datetime asc'), now)


EXAM_STATE = {'draft': '草稿', 'open': '进行中', 'held': '已开考',
              'finished': '已结束', 'cancelled': '已取消'}


def cmd_exams(env, rec):
    Exam = env['op.exam'].sudo()
    now = datetime.datetime.now()
    dom = []
    if rec._name == 'op.student':
        course, _b = student_course(env, rec)
        if course:
            dom.append(('course_id', '=', course.id))
        exams = Exam.search(
            dom + [('start_time', '>=', now - datetime.timedelta(days=1))],
            order='start_time asc', limit=8)
        if not exams:
            exams = Exam.search(dom, order='start_time desc', limit=5)
    else:
        exams = Exam.search([('responsible_id', 'in', [rec.id])],
                            order='start_time desc', limit=8)
        if not exams:
            return "暂没有分配给你负责的考试。"
    out = ["📝 考试安排"]
    for e in exams:
        out.append("• %s [%s]\n  时间:%s 满分:%d 及格:%d %s" % (
            e.subject_id.name or e.name, e.exam_code, _f(e.start_time),
            e.total_marks, e.min_marks,
            '⚠️ 未排时间' if not e.start_time
            else ('🟢 ' + EXAM_STATE.get(e.state, e.state)
                  if e.start_time >= now else '✔️ 已考完')))
    return "\n".join(out)


def _grades_text(env, student, page=0):
    Result = env['op.result.line'].sudo().search(
        [('student_id', '=', student.id)], order='id desc')
    if not Result:
        return None, "还没有已发布的成绩。"
    total = len(Result)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = Result[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    out = ["📊 成绩单 第%d/%d页" % (page + 1, pages)]
    for r in chunk.sorted(key=lambda x: x.exam_id.start_time or x.id):
        out.append("• %s：%d 分 %s（%s）" % (
            r.exam_id.subject_id.name or r.exam_id.name,
            r.marks, r.grade or '',
            '通过' if r.status == 'pass' else '未通过'))
    return (page, pages), "\n".join(out)


def cmd_grades(env, rec, page=0):
    rng, text = _grades_text(env, rec, page)
    return text


ASSIGN_STATE = {'draft': '草稿', 'publish': '已发布', 'finish': '已截止',
                'reject': '已驳回'}


def cmd_assignments(env, rec):
    _, batch = student_course(env, rec)
    if not batch:
        return "未查到班级信息，无法拉取作业。"
    Asg = env['op.assignment'].sudo().search(
        [('batch_id', '=', batch.id)], order='submission_date desc', limit=5)
    if not Asg:
        return "最近没有作业。"
    out = ["📒 最近作业"]
    for a in Asg:
        out.append("• %s（%s）\n  截止:%s 分值:%s %s" % (
            a.name, a.subject_id.name or a.course_id.name,
            _f(a.submission_date), a.point or '-',
            ASSIGN_STATE.get(a.state, a.state)))
    return "\n".join(out)


def cmd_attendance(env, rec):
    Line = env['op.attendance.line'].sudo().search(
        [('student_id', '=', rec.id)])
    if not Line:
        return "还没有考勤记录。"
    # 2026-10-03（跨页一致性复核）：原先是**互斥的 if/elif 链**且 `present` 排在最前 ——
    # 而 `op.attendance.line` 的 present/late/absent/excused 是**四个独立布尔**，
    # 「迟到」那条的 present 也是 True ⇒ `late` 这一支**永远轮不到**，迟到恒显示 0。
    # 实测（学生 5）：present 23 ｜ late 1 ｜ absent 25 ｜ total 48；
    # 门户三页都已按「迟到算到堂、迟到单独标『其中迟到』」的口径收口，这里对齐。
    n = {'present': 0, 'absent': 0, 'late': 0, 'excused': 0}
    for l in Line:
        if l.present or l.late:
            n['present'] += 1      # 到堂（含迟到），与门户同口径
        if l.late:
            n['late'] += 1         # 独立标志：单独计数，供「其中迟到」显示
        if l.absent:
            n['absent'] += 1
        if l.excused:
            n['excused'] += 1
    total = len(Line)
    rate = 100.0 * n['present'] / total if total else 0
    out = ["✅ 考勤概况（共 %d 次）" % total,
           "出勤率 %.0f%%｜出勤 %d（其中迟到 %d）｜缺席 %d｜请假 %d" % (
               rate, n['present'], n['late'], n['absent'], n['excused']),
           "", "最近记录："]
    for l in Line.sorted(key=lambda x: x.attendance_id.attendance_date,
                         reverse=True)[:5]:
        mark = ('✔️出勤' if l.present else
                '📝请假' if l.excused else
                '⏰迟到' if l.late else '❌缺席')
        out.append("• %s %s" % (
            l.attendance_id.attendance_date.strftime('%m-%d'), mark))
    return "\n".join(out)


def _movement_q(rec):
    return ([('student_id', '=', rec.id)] if rec._name == 'op.student'
            else [('faculty_id', '=', rec.id)])


def _library_text(env, rec, page=0):
    Move = env['op.media.movement'].sudo().search(
        _movement_q(rec), order='return_date asc')
    if not Move:
        return None, "没有借阅记录。"
    today = datetime.date.today()
    total = len(Move)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    out = ["📚 借阅记录 第%d/%d页" % (page + 1, pages)]
    for m in Move[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        due = m.return_date
        tag = ''
        if not m.actual_return_date and due:
            late = (due - today).days
            tag = ('⚠️ 已逾期 %d 天 罚金 %s' % (-late, m.penalty or 0)
                   if late < 0 else '（剩 %d 天）' % late)
        elif m.actual_return_date:
            tag = '✔️ 已还'
        out.append("• 《%s》\n  应还:%s %s" % (
            m.media_id.name,
            due.strftime('%Y-%m-%d') if due else '待定', tag))
    return (page, pages), "\n".join(out)


def cmd_library(env, rec, page=0):
    _rng, text = _library_text(env, rec, page)
    return text


FEE_STATE = {'draft': '未开票', 'invoice': '已开票', 'cancel': '已取消'}


def cmd_fees(env, rec):
    Fees = env['op.student.fees.details'].sudo().search(
        [('student_id', '=', rec.id)], order='date desc')
    if not Fees:
        return "没有缴费记录。"
    out = ["💰 缴费记录"]
    total_due = 0.0
    for f in Fees:
        paid = f.invoice_state == 'paid'
        if not paid and f.state != 'cancel':
            total_due += f.amount
        out.append("• %s ¥%.2f %s %s" % (
            f.product_id.name or '费用项', f.amount,
            FEE_STATE.get(f.state, f.state),
            '✅已缴清' if paid else
            ('❌已取消' if f.state == 'cancel' else '⚠️待缴')))
    out.append("\n合计待缴：¥%.2f" % total_due)
    return "\n".join(out)


def cmd_overview(env, _rec):
    def cnt(model):
        try:
            return env[model].sudo().search_count([])
        except Exception:
            return 0
    return ("🏫 全校概览\n"
            "学生：%d\n教师：%d\n课程：%d\n班级：%d\n"
            "科目：%d\n教室：%d\n未来7天课次：%d\n"
            "图书馆藏：%d\n在借册数：%d\n试卷数：%d\nTelegram绑定：%d" % (
                cnt('op.student'), cnt('op.faculty'), cnt('op.course'),
                cnt('op.batch'), cnt('op.subject'), cnt('op.classroom'),
                cnt('op.session'), cnt('op.media.unit'),
                cnt('op.media.movement'), cnt('op.exam'),
                cnt('op.telegram.chat')))


def _report_token(env, payload):
    """payload 形如 'ms||999'；返回 '<exp>-<sig>'。"""
    secret = param(env, 'edu_telegram.webhook_secret', '')
    exp = int(time.time()) + 600
    sig = hmac.new(secret.encode(), ('report|%s|%d' % (payload, exp)).encode(),
                   hashlib.sha256).hexdigest()[:32]
    return '%d-%s' % (exp, sig)


def _check_report_token(env, payload, exp, sig):
    if int(exp) < time.time():
        return False
    secret = param(env, 'edu_telegram.webhook_secret', '')
    good = hmac.new(secret.encode(),
                    ('report|%s|%s' % (payload, exp)).encode(),
                    hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(good, sig)


PURPOSES = {'护照': 'passport', '银行': 'bank_account', '奖学金': 'scholarship',
            '实习': 'internship', '签证': 'visa', '住址': 'address_proof'}
PURPOSE_DISPLAY = {'passport': 'Passport Application',
                   'bank_account': 'Bank Account Opening',
                   'scholarship': 'Scholarship', 'internship': 'Internship',
                   'visa': 'Visa', 'address_proof': 'Address Proof'}


def cmd_report(env, rec, chat_id):
    return _doc_link(env, rec, chat_id, 'ms', '')


def _doc_link(env, rec, chat_id, kind, extra, label='文档'):
    url = base_url(env)
    if not url:
        return "未配置站点地址，暂不能下载。"
    payload = '%s|%s|%s' % (kind, extra, chat_id)
    link = "%s/telegram/report/%s?chat=%s" % (
        url, _report_token(env, payload), chat_id)
    return "📄 %s PDF，10 分钟内有效：\n%s" % (label, link)


def cmd_profile(env, rec):
    if rec._name == 'op.student':
        sc = env['op.student.course'].sudo().search(
            [('student_id', '=', rec.id)], limit=1)
        roll = sc.roll_number if sc else '-'
        course = sc.course_id.name if sc else '-'
        batch = sc.batch_id.name if sc else '-'
        return ("👤 %s\n学号：%s\n课程：%s\n班级：%s\n性别：%s\n"
                "出生：%s" % (
                    rec.name, roll, course, batch,
                    dict(rec._fields['gender'].selection).get(rec.gender, '-')
                    if rec.gender else '-',
                    rec.birth_date or '-'))
    dept = rec.main_department_id.name or '-'
    subs = '、'.join(rec.faculty_subject_ids.mapped('name')) or '-'
    emp = rec.emp_id.identification_id or '-'
    return "👤 %s（教师）\n工号：%s\n院系：%s\n授课科目：%s" % (
        rec.name, emp, dept, subs)


def cmd_calendar(env, rec):
    years = env['op.academic.year'].sudo().search(
        [], order='start_date desc', limit=3)
    if not years:
        return "暂无校历数据。"
    out = ["📆 校历"]
    for y in years:
        out.append("• %s  %s ~ %s" % (
            y.name, y.start_date or '?', y.end_date or '?'))
        for t in y.academic_term_ids:
            out.append("   - %s: %s ~ %s" % (
                t.name, t.term_start_date or '?', t.term_end_date or '?'))
    return "\n".join(out)


def cmd_load(env, rec):
    now = datetime.datetime.now()
    n = env['op.session'].sudo().search_count(
        [('faculty_id', '=', rec.id),
         ('start_datetime', '>=', now.replace(day=1, hour=0, minute=0)),
         ('start_datetime', '<',
          (now.replace(day=28) + datetime.timedelta(days=4))
          .replace(day=1, hour=0, minute=0))])
    total = env['op.session'].sudo().search_count(
        [('faculty_id', '=', rec.id)])
    return ("📈 本月课时：%d 节\n累计排课：%d 节" % (n, total))


PURPOSE_KEYS = list(PURPOSES) + ['其他']


def cmd_doc(env, rec, chat_id, kind, arg=''):
    """统一报表下载入口：kind ∈ id/tk/tw/ar/bf。"""
    if kind == 'id':
        label = '学生证'
    elif kind == 'tk':
        sess = env['op.exam.session'].sudo().search([], order='id desc',
                                                    limit=1)
        if not sess:
            return "暂无考试场次，无法生成准考证。"
        arg = str(sess.id)
        label = '准考证'
    elif kind == 'tw':
        arg = arg or datetime.date.today().strftime('%Y%m%d')
        if not re.match(r'^\d{8}$', arg):
            return "日期格式：YYYYMMDD"
        label = '本周课表'
    elif kind == 'ar':
        parts = arg.split('-')
        if len(parts) != 2 or not all(re.match(r'^\d{8}$', p)
                                      for p in parts):
            d = datetime.date.today()
            arg = '%s-%s' % ((d - datetime.timedelta(days=30))
                             .strftime('%Y%m%d'), d.strftime('%Y%m%d'))
        label = '考勤区间报表'
    elif kind == 'bf':
        key = next((v for k, v in PURPOSES.items() if arg.startswith(k)),
                   'other')
        other = arg[len(next((k for k in PURPOSES if arg.startswith(k)),
                             '')):] if key == 'other' and arg else ''
        arg = '%s:%s' % (key, other)
        label = '在读证明'
    else:
        return "未知文档类型。"
    return _doc_link(env, rec, chat_id, kind, arg, label)


# 命令注册表：别名 -> (函数名, 允许角色集合或 None=绑定即可用)
REGISTRY = {
    '/课表': ('cmd_timetable', None), '/timetable': ('cmd_timetable', None),
    '/考试': ('cmd_exams', None), '/exam': ('cmd_exams', None),
    '/图书': ('cmd_library', None), '/library': ('cmd_library', None),
    '/成绩': ('cmd_grades', {'student', 'parent'}),
    '/grades': ('cmd_grades', {'student', 'parent'}),
    '/成绩单': ('cmd_report', {'student'}),
    '/report': ('cmd_report', {'student'}),
    '/作业': ('cmd_assignments', {'student'}),
    '/hw': ('cmd_assignments', {'student'}),
    '/考勤': ('cmd_attendance', {'student', 'parent'}),
    '/attendance': ('cmd_attendance', {'student', 'parent'}),
    '/缴费': ('cmd_fees', {'student', 'parent'}),
    '/fees': ('cmd_fees', {'student', 'parent'}),
    '/概览': ('cmd_overview', {'admin'}),
    '/overview': ('cmd_overview', {'admin'}),
    '/档案': ('cmd_profile', None), '/profile': ('cmd_profile', None),
    '/校历': ('cmd_calendar', None), '/calendar': ('cmd_calendar', None),
    '/课时': ('cmd_load', {'faculty'}), '/load': ('cmd_load', {'faculty'}),
    '/学生证': ('cmd_doc', {'student'}), '/idcard': ('cmd_doc', {'student'}),
    '/准考证': ('cmd_doc', None), '/ticket': ('cmd_doc', None),
    '/课表PDF': ('cmd_doc', None), '/weekpdf': ('cmd_doc', None),
    '/考勤报表': ('cmd_doc', {'student', 'parent'}),
    '/attrep': ('cmd_doc', {'student', 'parent'}),
    '/在读证明': ('cmd_doc', {'student'}), '/bonafide': ('cmd_doc', {'student'}),
    '/布告': ('cmd_notice', None), '/notice': ('cmd_notice', None),
}

DOC_KIND = {'/学生证': 'id', '/idcard': 'id', '/准考证': 'tk',
            '/ticket': 'tk', '/课表PDF': 'tw', '/weekpdf': 'tw',
            '/考勤报表': 'ar', '/attrep': 'ar', '/在读证明': 'bf',
            '/bonafide': 'bf'}

# ------------------------- 多步对话流 -------------------------

def _notify_roles(env, roles, text, inline=None):
    """给某几个角色的全部绑定会话入队消息（可带 inline 按钮）。"""
    Out = env['edu.telegram.outbox'].sudo()
    for ch in env['op.telegram.chat'].sudo().search(
            [('role', 'in', list(roles))]):
        Out.sudo().create({
            'chat_id': ch.chat_id, 'text': text[:MAX_MSG],
            'keyboard': json.dumps({'inline_keyboard': inline})
            if inline else None})


def flow_hw_start(env, role, rec):
    _c, batch = student_course(env, rec)
    Asg = env['op.assignment'].sudo().search(
        [('batch_id', '=', batch.id), ('state', '=', 'publish')],
        limit=8) if batch else env['op.assignment']
    if not Asg:
        return "当前没有待提交的作业。"
    rows = [[{'text': (a.subject_id.name or a.name)[:22],
              'callback_data': 'hwsub:%d' % a.id}] for a in Asg]
    return {'text': "选择要提交的作业：", 'inline': rows}


def flow_rsv_start(env, role, rec):
    Unit = env['op.media.unit'].sudo().search(
        [('state', '=', 'available')], limit=8)
    if not Unit:
        return "暂无可预约的馆藏。"
    rows = [[{'text': u.media_id.name[:22],
              'callback_data': 'rsv:%d' % u.id}] for u in Unit]
    return {'text': "选择要预约的书目：", 'inline': rows}


def flow_leave_start(env, role, rec):
    rows = [[{'text': n, 'callback_data': 'lvt:%s' % k}]
            for k, n in (('sick', '病假'), ('personal', '事假'),
                         ('other', '其他'))]
    return {'text': "选择请假类型：", 'inline': rows}


def cmd_notice(env, rec):
    notices = env['op.notice'].sudo().search([], limit=5)
    if not notices:
        return "暂无公告。"
    out = ["📢 公告"]
    for n in notices:
        out.append("• %s%s\n  %s" % (
            '[重要] ' if n.priority == 'high' else '',
            n.title, (n.body or '')[:60]))
    return "\n".join(out)


FLOW_STEPS = {
    'hw': [('desc', '请直接回复作业内容说明（纯文本）')],
    'rsv': [('d1', '请回复开始使用日期（YYYYMMDD）'),
            ('d2', '请回复结束归还日期（YYYYMMDD）')],
    'leave': [('d1', '请回复开始日期（YYYYMMDD）'),
              ('d2', '请回复结束日期（YYYYMMDD）'),
              ('reason', '请一句话回复请假事由')],
}


def flow_feed(env, chat_id, text):
    """推进进行中的流；返回 (reply, finished)。"""
    import json as _json
    Flow = env['edu.telegram.flow'].sudo()
    fl = Flow.get(chat_id)
    if not fl:
        return None, True
    role, rec = env['op.telegram.chat'].identity_of(chat_id)
    if not rec:
        env['edu.telegram.flow'].sudo().drop(chat_id)
        return "绑定已失效，流程终止。", True
    steps = FLOW_STEPS[fl.flow]
    d = _json.loads(fl.data or '{}')
    idx = next((i for i, s in enumerate(steps) if s[0] == fl.step), None)
    if idx is None:
        env['edu.telegram.flow'].sudo().drop(chat_id)
        return None, True
    key = steps[idx][0]
    if 'd' in (key,) and not re.match(r'^\d{8}$', text):
        return ("日期格式不对，示例：20260901。请重发。", False)
    d[key] = text
    nxt = idx + 1
    if nxt < len(steps):
        Flow.set(fl, step=steps[nxt][0], **d)
        return steps[nxt][1], False
    flow_kind = fl.flow
    Flow.drop(chat_id)
    # ---- 收尾落库 ----
    if flow_kind == 'hw':
        aid = int(d.get('id', 0))
        asg = env['op.assignment'].sudo().browse(aid)
        if not asg.exists():
            return "该作业已不存在。", True
        sl = env['op.assignment.sub.line'].sudo().create({
            'assignment_id': aid, 'student_id': rec.id,
            'description': d.get('desc', '')})
        try:
            sl.act_submit()
        except Exception:
            pass
        _notify_roles(env, ('faculty', 'admin'),
                      "📥 新作业提交：%s\n学生：%s\n内容：%s" % (
                          asg.name, rec.name, d.get('desc', '')[:200]))
        return "✅ 已提交《%s》，等待教师批阅。" % asg.name, True
    if flow_kind == 'rsv':
        unit = env['op.media.unit'].sudo().browse(int(d.get('unit', 0)))
        vals = {'partner_id': rec.partner_id.id,
                'media_id': unit.media_id.id,
                'date_from': '%s-%s-%s' % (d['d1'][:4], d['d1'][4:6],
                                           d['d1'][6:]),
                'date_to': '%s-%s-%s' % (d['d2'][:4], d['d2'][4:6],
                                         d['d2'][6:]),
                'state': 'request'}
        card = env['op.library.card'].sudo().search(
            [('student_id', '=', rec.id)], limit=1)
        if card:
            vals['library_card_id'] = card.id
        try:
            env['op.media.queue'].sudo().create(vals)
            return "📖 已提交《%s》预约（%s ~ %s），等待馆员审核。" % (
                unit.media_id.name, vals['date_from'], vals['date_to']), True
        except Exception:
            _logger.exception("reserve failed")
            return "预约失败，请联系管理员。", True
    if flow_kind == 'leave':
        lv = env['op.leave.request'].sudo().create({
            'student_id': rec.id, 'leave_type': d.get('type', 'other'),
            'date_from': '%s-%s-%s' % (d['d1'][:4], d['d1'][4:6], d['d1'][6:]),
            'date_to': '%s-%s-%s' % (d['d2'][:4], d['d2'][4:6], d['d2'][6:]),
            'reason': d.get('reason', '')})
        _notify_roles(env, ('faculty', 'admin'),
                      lv.summary(),
                      inline=[[{'text': '✅ 批准',
                                'callback_data': 'lva:%d:1' % lv.id},
                               {'text': '❌ 驳回',
                                'callback_data': 'lva:%d:0' % lv.id}]])
        return lv.summary() + "\n已提交，等待审批。", True
    return None, True


FLOW_STARTERS = {'hw': flow_hw_start, 'rsv': flow_rsv_start,
                 'leave': flow_leave_start}


DEEP_CMDS = {'/选课': ('cmd_subject_reg', {'student'}, '选课申请'),
             '/subjectreg': ('cmd_subject_reg', {'student'}, '选课申请'),
             '/点名': ('cmd_rollcall', {'faculty'}, '进入点名'),
             '/rollcall': ('cmd_rollcall', {'faculty'}, '进入点名'),
             '/成绩录入': ('cmd_marks', {'faculty'}, '进入录分'),
             '/marks': ('cmd_marks', {'faculty'}, '进入录分')}


def handle_deep_cmd(env, role, rec, cmd, chat_id):
    name, roles, btn = DEEP_CMDS[cmd]
    if role not in roles:
        return {'type': 'send',
                'text': "⛔ 该功能不对当前身份开放。"}
    text, path = globals()[name](env, rec, chat_id)
    inline = None
    if base_url(env):
        inline = [[{'text': '🌐 ' + btn,
                    'url': base_url(env) + path}]]
    return {'type': 'send', 'text': text, 'inline': inline}

def _deep_link(env, path):
    url = base_url(env)
    return (url + path) if url else None


def cmd_subject_reg(env, rec, chat_id):
    link = _deep_link(env, '/my/subject-reg')
    if not link:
        return "未配置站点地址。"
    Reg = env['op.subject.registration'].sudo()
    reg = Reg.search([('student_id', '=', rec.id)], order='id desc',
                     limit=1)
    state_txt = ''
    if reg:
        state_txt = "当前申请：%s（%s）\n" % (
            reg.name, dict(Reg._fields['state'].selection)[reg.state])
    return ("📚 选课注册\n%s点下方按钮选择选修科目并提交审批。"
            % state_txt), '/my/subject-reg'


def cmd_rollcall(env, rec, chat_id):
    import datetime as _dt
    link = _deep_link(env, '/my/rollcall')
    if not link:
        return "未配置站点地址。"
    n = env['op.session'].sudo().search_count(
        [('faculty_id', '=', rec.id),
         ('start_datetime', '>=',
          _dt.datetime.combine(_dt.date.today(), _dt.time.min)),
         ('start_datetime', '<',
          _dt.datetime.combine(_dt.date.today(), _dt.time.max))])
    return "✅ 点名\n今天有 %d 节你的课。\n点下方按钮进入点名页。" % n, '/my/rollcall'


def cmd_marks(env, rec, chat_id):
    link = _deep_link(env, '/my/marks')
    if not link:
        return "未配置站点地址。"
    n = len(env['op.exam'].sudo().search(
        [('responsible_id', 'in', [rec.id]),
         ('end_time', '<', datetime.datetime.now()),
         ('results_entered', '=', False)]))
    return "📝 成绩录入\n待录入考试：%d 场。\n点下方按钮进入录分页。" % n, '/my/marks'

PAGINATED = {  # 支持 callback 翻页的命令 -> (回调前缀, 步长, 跨度)
    'tt': ('cmd_timetable', 1, 2),
    'gr': ('cmd_grades', 1, 99),
    'lb': ('cmd_library', 1, 99),
}


def _inline_extra(env, role, prefix, offset):
    """命令回复自带的 inline 行：翻页 + 网页端深链。"""
    rows = []
    if prefix:
        fn_name, step, span = PAGINATED[prefix]
        rows.append(_pager(prefix, offset, step, span))
    url = base_url(env)
    if url and role in ('student', 'faculty', 'parent'):
        rows.append([{'text': '🌐 打开网页端', 'url': url + '/my/home'}])
    if url and prefix == 'tt' and role == 'student':
        pass
    return rows


def _dispatch_cmd(env, role, rec, cmd, chat_id, extra_args=None):
    """执行注册表命令，返回 dict(text, inline)。"""
    name, roles = REGISTRY[cmd]
    if roles is not None and role not in roles:
        return {'text': "⛔ 该功能不对当前身份开放（你是%s）。" %
                         dict(env['op.telegram.chat']
                              ._fields['role'].selection)[role]}
    kw = {}
    if extra_args:
        kw.update(extra_args)
    try:
        fn = globals()[name]
        args = [env, rec]
        if name in ('cmd_timetable', 'cmd_grades', 'cmd_library'):
            args.append(kw.get('offset', 0))
        if name == 'cmd_report':
            args.append(chat_id)
        if name == 'cmd_doc':
            kind = DOC_KIND.get(kw.get('cmd', ''), '')
            args += [chat_id, kind, kw.get('arg', '')]
        text = fn(*args)
    except Exception:
        _logger.exception("telegram command failed: %s", cmd)
        return {'text': "查询出错，请稍后再试。"}
    prefix = next((p for p, spec in PAGINATED.items()
                   if spec[0] == name), None)
    inline = _inline_extra(env, role, prefix, kw.get('offset', 0)) \
        if prefix else _inline_extra(env, role, None, 0)
    # 家长视角标注孩子（rec 本身是 op.parent）
    if role == 'parent' and rec._name == 'op.parent':
        kids = rec.student_ids
        if len(kids) == 1:
            text = "👶 %s\n%s" % (kids[0].name, text)
        elif len(kids) > 1:
            names = "、".join(kids.mapped('name'))
            text = "👶 孩子：%s\n%s" % (names, text)
    return {'text': text, 'inline': inline}


def handle_update(env, update):
    """处理 Telegram update，返回 (chat_id, action)；action 见 webhook。"""
    cb = update.get('callback_query')
    msg = cb.get('message') if cb else None
    msg = msg or update.get('message') or update.get('edited_message') or {}
    chat = msg.get('chat') or {}
    chat_id = str(chat.get('id', ''))
    sender = (cb or {}).get('from') or msg.get('from') or {}
    tg_name = sender.get('first_name') or ''
    if not chat_id:
        return None, None

    Chat = env['op.telegram.chat']

    # ---- inline：翻页 / 流程选择 / 审批 ----
    if cb:
        data = (cb.get('data') or '')
        mid = msg.get('message_id')
        if data == 'noop' or ':' not in data:
            return chat_id, None
        prefix = data.split(':', 1)[0]

        # —— 流程类回调 ——
        Flow = env['edu.telegram.flow'].sudo()
        if prefix in ('hwsub', 'rsv', 'lvt'):
            role, rec = Chat.identity_of(chat_id)
            if not rec or role != 'student':
                return chat_id, {'type': 'send',
                                 'text': "仅学生可用该流程。"}
            value = data.split(':', 1)[1]
            if prefix == 'hwsub':
                Flow.start(chat_id=chat_id, flow='hw', step='desc',
                           data={'id': int(value)})
                prompt = "请直接回复作业内容说明（纯文本）。\n发送 /取消 放弃。"
            elif prefix == 'rsv':
                unit = env['op.media.unit'].sudo().browse(int(value))
                Flow.start(chat_id=chat_id, flow='rsv', step='d1',
                           data={'unit': int(value)})
                prompt = ("《%s》已选。\n%s\n发送 /取消 放弃。"
                          % (unit.media_id.name,
                             FLOW_STEPS['rsv'][0][1]))
            else:
                Flow.start(chat_id=chat_id, flow='leave', step='d1',
                           data={'type': value})
                prompt = FLOW_STEPS['leave'][0][1] + "\n发送 /取消 放弃。"
            return chat_id, {'type': 'send', 'text': prompt}
        if prefix == 'lva':
            lid, _, flag = data.partition(':')[2].partition(':')
            role, _rec = Chat.identity_of(chat_id)
            if role not in ('faculty', 'admin'):
                return chat_id, {'type': 'send', 'text': "⛔ 无审批权限。"}
            lv = env['op.leave.request'].sudo().browse(int(lid))
            if lv.exists():
                lv.write({'state': 'approved' if flag == '1'
                          else 'rejected'})
                stu_chat = env['op.telegram.chat'].sudo().search(
                    [('student_id', '=', lv.student_id.id)], limit=1)
                if stu_chat:
                    env['edu.telegram.outbox'].sudo().enqueue(
                        stu_chat.chat_id, "你的请假单 #%d %s"
                        % (lv.id, lv.STATE_ZH[lv.state]))
            return chat_id, {'type': 'send',
                             'text': "已处理请假单 #%d。" % int(lid)}

        # —— 翻页回调 ——
        if prefix in PAGINATED:
            fn_name, _step, _span = PAGINATED[prefix]
            off = data.split(':', 1)[1]
            role, rec = Chat.identity_of(chat_id)
            if not rec:
                return chat_id, None
            try:
                off = int(off)
            except ValueError:
                off = 0
            kwargs = {'week': off} if prefix == 'tt' else {'page': off}
            try:
                text = globals()[fn_name](env, rec, **kwargs)
            except Exception:
                _logger.exception("telegram callback failed: %s", data)
                text = "查询出错，请稍后再试。"
            inline = _inline_extra(env, role, prefix, off)
            return chat_id, {'type': 'edit', 'message_id': mid,
                             'text': text, 'inline': inline}
        return chat_id, None
        fn_name, _step, _span = PAGINATED[prefix]
        role, rec = Chat.identity_of(chat_id)
        if not rec:
            return chat_id, None
        try:
            off = int(off)
        except ValueError:
            off = 0
        kwargs = {'week': off} if prefix == 'tt' else {'page': off}
        try:
            text = globals()[fn_name](env, rec, **kwargs)
        except Exception:
            _logger.exception("telegram callback failed: %s", data)
            text = "查询出错，请稍后再试。"
        inline = _inline_extra(env, role, prefix, off)
        return chat_id, {'type': 'edit', 'message_id': mid,
                         'text': text, 'inline': inline}

    text_in = (msg.get('text') or '').strip()
    if not text_in:
        return chat_id, None

    # ---- 进行中流程的文本捕获（优先于一切命令）----
    if not text_in.startswith('/'):
        fl = env['edu.telegram.flow'].sudo().get(chat_id)
        if fl:
            try:
                reply, done = flow_feed(env, chat_id, text_in)
            except Exception as e:
                import traceback as _tb
                try:
                    with open('/tmp/flow_tb.txt', 'w') as fh:
                        fh.write(_tb.format_exc())
                except Exception:
                    pass
                _logger.error("telegram flow failed: %r", e)
                env['edu.telegram.flow'].sudo().drop(chat_id)
                return chat_id, {'type': 'send',
                                 'text': "流程出错，已中止，请重新发起。"}
            role_kb = KEYBOARDS.get(
                Chat.identity_of(chat_id)[0], KB_GUEST)
            if reply is None:
                return chat_id, None
            act = {'type': 'send', 'text': reply}
            if not done:
                act['kb'] = None
            else:
                act['kb'] = role_kb
            return chat_id, act
        text_in = '/' + text_in.split()[0]

    parts = text_in.split()
    cmd = parts[0].split('@')[0].lower()

    if cmd == '/start':
        if len(parts) >= 3:
            rec = Chat.bind(chat_id, tg_name, parts[1], parts[2])
        elif len(parts) == 2:
            rec = Chat.bind_by_code(chat_id, tg_name, parts[1])
        else:
            rec = False
            reply = ("用法：\n/start 绑定码\n"
                     "备用：/start 学号或工号 出生年月(YYYYMMDD)")
        if len(parts) >= 2:
            if rec:
                role_name = dict(Chat._fields['role'].selection)[rec.role]
                who = (rec.student_id.name or rec.faculty_id.name
                       or (rec.role == 'parent'
                           and rec.parent_id.name.name)
                       or rec.telegram_name)
                reply = "✅ 绑定成功：%s（%s）\n点下方按钮开始使用。" % (
                    who, role_name)
            else:
                reply = "❌ 编号/绑定码不对或已过期。\n网页端 /my/telegram 可取新码。"
        return chat_id, {'type': 'send', 'text': reply, 'kb': KEYBOARDS[
            rec.role if rec else None]}

    if cmd in ('/解绑', '/unbind'):
        n = Chat.sudo().search([('chat_id', '=', chat_id)]).unlink()
        return chat_id, {'type': 'send',
                         'text': "已解绑。" if n else "本来就没有绑定。",
                         'kb': KB_GUEST}

    if cmd == '/取消':
        had = bool(env['edu.telegram.flow'].sudo().get(chat_id))
        env['edu.telegram.flow'].sudo().drop(chat_id)
        role0, _r = Chat.identity_of(chat_id)
        return chat_id, {'type': 'send',
                         'text': '已取消当前操作。' if had
                                 else '没有进行中的操作。',
                         'kb': KEYBOARDS.get(role0, KB_GUEST)}

    FLOW_CMDS = {'/交作业': ('hw', {'student'}),
                 '/submit': ('hw', {'student'}),
                 '/预约': ('rsv', {'student'}),
                 '/reserve': ('rsv', {'student'}),
                 '/请假': ('leave', {'student'}),
                 '/leave': ('leave', {'student'})}
    if cmd in FLOW_CMDS:
        flow_key, roles = FLOW_CMDS[cmd]
        role, rec = Chat.identity_of(chat_id)
        if not rec:
            return chat_id, {
                'type': 'send',
                'text': "请先绑定账户：网页端 /my/telegram 取绑定码后发 "
                        "/start 绑定码",
                'kb': KB_GUEST}
        if role not in roles:
            return chat_id, {
                'type': 'send',
                'text': "⛔ 该流程仅学生可用（你是%s）。" %
                        dict(Chat._fields['role'].selection)[role]}
        out = globals()['flow_%s_start' % flow_key](env, role, rec)
        if isinstance(out, dict):
            return chat_id, {'type': 'send', **out}
        return chat_id, {'type': 'send', 'text': out,
                         'kb': KEYBOARDS.get(role, KB_GUEST)}

    if cmd in DEEP_CMDS:
        role, rec = Chat.identity_of(chat_id)
        if not rec:
            return chat_id, {'type': 'send',
                             'text': "请先绑定账户。",
                             'kb': KB_GUEST}
        act = handle_deep_cmd(env, role, rec, cmd, chat_id)
        act['kb'] = KEYBOARDS.get(role, KB_GUEST)
        return chat_id, act

    if cmd in REGISTRY:
        role, rec = Chat.identity_of(chat_id)
        if not rec:
            return chat_id, {
                'type': 'send',
                'text': "请先绑定账户：网页端 /my/telegram 取绑定码后发 "
                        "/start 绑定码",
                'kb': KB_GUEST}
        # 家长命令以孩子（学生）档案执行
        if role == 'parent' and rec._name == 'op.parent':
            kids = rec.student_ids
            if not kids:
                return chat_id, {'type': 'send',
                                 'text': "未关联孩子，请联系管理员。",
                                 'kb': KEYBOARDS['parent']}
            rec = kids[0]
        act = _dispatch_cmd(env, role, rec, cmd, chat_id,
                            extra_args={'cmd': cmd,
                                        'arg': ' '.join(parts[1:])})
        act.update({'type': 'send', 'kb': KEYBOARDS.get(role, KB_GUEST)})
        return chat_id, act

    if cmd in ('/帮助', '/help'):
        role, _rec = Chat.identity_of(chat_id)
        return chat_id, {'type': 'send', 'text': HELP,
                         'kb': KEYBOARDS.get(role, KB_GUEST)}
    return chat_id, None


class TelegramWebhook(http.Controller):

    @http.route('/telegram/webhook', type='http', auth='public',
                csrf=False, methods=['POST'], save_session=False)
    def telegram_webhook(self, **kw):
        env = request.env
        secret = param(env, 'edu_telegram.webhook_secret')
        got = request.httprequest.headers.get('X-Telegram-Bot-Api-Secret-Token')
        # 2026-10-03 加固：原写法 `if secret and got != secret` 是 **fail-open** ——
        # 一旦这个参数被清空/漏配，本路由（auth='public'）就**完全不校验**，
        # 任何人都能 POST 进来驱动机器人（而 bot_token 是配好的 ⇒ 可代机器人发消息）。
        # 同文件 338 行本来就在用 `hmac.compare_digest`，这里却用 `!=`（非常量时间）—— 一并统一。
        # 写法对齐接替它的新模块 edu_tg_bind/controllers/webhook.py:47-50（fail-closed + compare_digest），
        # 那边的注释本身就点名了本处这个毛病。
        # 行为影响：**secret 已配置时行为不变**（本机/生产都配了 32 字符）；只有「未配置」从「放行」变「403」。
        if not secret or not hmac.compare_digest(secret, got or ''):
            return request.make_json_response({'ok': False}, status=403)
        chat_id, act = handle_update(env,
                                     request.httprequest.get_json(
                                         silent=True) or {})
        if not act:
            return request.make_json_response({'ok': True})
        if param(env, 'edu_telegram.dry_run') in ('1', 'true', 'True'):
            return request.make_json_response(
                {'ok': True, 'would_send': act})
        # 出站队列：宿主中继经代理调 Telegram API 投递
        kb = None
        method, mid = 'sendMessage', 0
        if act['type'] == 'edit':
            method, mid = 'editMessageText', act.get('message_id') or 0
            if act.get('inline'):
                kb = json.dumps({'inline_keyboard': act['inline']})
        elif act.get('inline'):
            # 单条消息只能带一种 reply_markup：优先 inline，
            # 回复键盘等下一条无翻页消息自动恢复
            kb = json.dumps({'inline_keyboard': act['inline']})
            act['text'] += '\n(键盘按钮下一条消息恢复)'
        else:
            kb = json.dumps(act['kb']) if act.get('kb') else None
        env['edu.telegram.outbox'].sudo().enqueue(
            chat_id, act['text'][:MAX_MSG], kb, method, mid)
        return request.make_json_response({'ok': True})

    @http.route('/telegram/report/<string:token>', type='http',
                auth='public', methods=['GET'])
    def telegram_report(self, token, p='', **kw):
        """token='<exp>-<sig>'，p='<kind>|<extra>|<chat>' 全部入签。"""
        env = request.env
        try:
            exp, sig = token.split('-', 1)
            kind, extra, chat = p.split('|')
        except ValueError:
            return request.not_found()
        if not _check_report_token(env, p, exp, sig):
            return request.make_response('链接无效或已过期', status=403)
        role, rec = env['op.telegram.chat'].identity_of(chat)
        if not rec or (role != 'student' and kind != 'tk'):
            return request.make_response('无权下载', status=403)
        try:
            pdf = self._build_pdf(env, role, rec, kind, extra)
        except Exception:
            _logger.exception("report render failed")
            return request.make_response('生成失败', status=500)
        if pdf is None:
            return request.make_response('暂无可打印的数据', status=404)
        return request.make_response(
            pdf, [('Content-Type', 'application/pdf'),
                  ('Content-Disposition',
                   'attachment; filename="%s.pdf"' % kind)])

    def _build_pdf(self, env, role, rec, kind, extra):
        Render = env['ir.actions.report'].sudo()
        stu = rec if rec._name == 'op.student' else None
        if kind == 'ms':
            lines = env['op.marksheet.line'].sudo().search(
                [('student_id', '=', rec.id)])
            if not lines:
                return None
            return Render._render_qweb_pdf(
                'openeducat_exam.report_marksheet_report', lines.ids)[0]
        if kind == 'id':
            return Render._render_qweb_pdf(
                'openeducat_core.report_student_idcard', [rec.id])[0]
        if kind == 'bf':
            key, _, other = extra.partition(':')
            return Render._render_qweb_pdf(
                'openeducat_core.report_student_bonafide', [rec.id],
                data={'certificate_purpose': key,
                      'other_purpose': other,
                      'purpose_display':
                      PURPOSE_DISPLAY.get(key, other or 'Other')})[0]
        if kind == 'ar':
            d1, d2 = extra.split('-')
            fmt = lambda s: "%s-%s-%s" % (s[:4], s[4:6], s[6:])
            return Render._render_qweb_pdf(
                'openeducat_attendance.student_attendance_report', [],
                data={'student_id': rec.id,
                      'from_date': fmt(d1), 'to_date': fmt(d2)})[0]
        if kind == 'tw':
            d = datetime.datetime.strptime(extra, '%Y%m%d').date()
            start = d - datetime.timedelta(days=d.weekday())
            end = start + datetime.timedelta(days=6)
            Wiz = env['time.table.report'].sudo()
            wiz_vals = {'start_date': start, 'end_date': end,
                        'state': 'faculty' if role == 'faculty'
                        else 'student'}
            if role == 'faculty':
                wiz_vals['faculty_id'] = rec.id
            else:
                _c, batch = student_course(env, rec)
                if batch:
                    wiz_vals.update({'batch_id': batch.id,
                                     'course_id': batch.course_id.id})
            wiz = Wiz.create(wiz_vals)
            data = wiz.read(['start_date', 'end_date', 'course_id',
                             'batch_id', 'state', 'faculty_id'])[0]
            Session = env['op.session'].sudo()
            dom = [('start_datetime', '>=',
                    datetime.datetime.combine(start, datetime.time.min)),
                   ('start_datetime', '<=',
                    datetime.datetime.combine(end, datetime.time.max))]
            if role == 'faculty':
                dom.append(('faculty_id', '=', rec.id))
                data['teacher_time_table_ids'] = Session.search(
                    dom, order='start_datetime asc').ids
                ref = 'openeducat_timetable.report_teacher_timetable_generate'
            else:
                if wiz.batch_id:
                    dom.append(('batch_id', '=', wiz.batch_id.id))
                data['time_table_ids'] = Session.search(
                    dom, order='start_datetime asc').ids
                ref = 'openeducat_timetable.report_student_timetable_generate'
            Render = Render.with_context(active_model='time.table.report',
                                         active_id=wiz.id)
            return Render._render_qweb_pdf(ref, [wiz.id], data=data)[0]
        if kind == 'tk':
            ctx = {'active_model': 'op.exam.session',
                   'active_id': int(extra)}
            sess = env['op.exam.session'].with_context(
                **ctx).sudo().browse(int(extra))
            if not sess.exists() or sess.state != 'schedule':
                return None
            return Render.with_context(**ctx)._render_qweb_pdf(
                'openeducat_exam.report_ticket', [int(extra)],
                data={'context': {'active_id': int(extra)}})[0]
        return None
