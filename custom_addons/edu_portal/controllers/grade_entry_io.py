# -*- coding: utf-8 -*-
"""成绩中心 · 批量 IO（xlsx 导出 / 导入）—— 设计稿 docs/plans/gradebook-center-design.md §4.1。

为什么不用 base_import 导入（设计稿定案）：op.exam.attendees 的 exam_id / student_id 是必填，
且 exam_id 由容器链（班 × 学期 × 科目）算出来，通用字段映射给不出来；真正致命的是 base_import
**直接写表**，绕过 edu.grade.history 留痕与 op.result.line / op.marksheet.line 双写 —— 学生端
看不见、也查不到是谁改的。所以导入自己解一张自解释表，再走与 /grade-entry/save 同一条写入口径。

路由（权限与 /grade-entry 完全同一口径：教务 / 超管 = 全校；任课教师 = 本人任教的 (班, 科目)；
学生 / 家长 = 303 回门户）：

    GET  /grade-entry/xlsx          批量 IO 页（选目标 + 导出链接 + 上传表单）
    GET  /grade-entry/export.xlsx   导出当前 (班, 学期, 科目) 的自解释表
    POST /grade-entry/import        导入 xlsx，逐行回报

复用而不是复制（设计稿 §4.1 硬口径）：
  · 容器链 _ensure_container、可写范围 _scope_pairs、名册 _roster、既有值 _existing、
    默认学期 _default_term、班内科目 _batch_subjects、可选范围 _allowed_* —— 全部 import 自
    ./grade_entry，不新写第二套容器 / 权限 / 名册逻辑；
  · 唯一留痕写入口 edu.grade.history.edu_apply_marks（models/registration.py）：
    source='import' 让留痕把「文件导入」与「页面录入」分开（action 自动落 import）；
  · 上传解析 _read_table_file 复用 ./roles 里那一份（xlsx 走 openpyxl 3.1.2，csv 回退 gbk），
    不再造第三份读法（edu_assess 那份就是 roles 的拷贝）。

债（登记，不隐藏）：读侧双写（op.marksheet.line + op.result.line）目前**内联**在
/grade-entry/save 路由体里，没有可 import 的函数，本文件只能按同一口径复刻为
_sync_read_side()；两处必须同改。若那段被抽成公共函数，本文件应改为 import。

后台入口（只读）不在这里：见 views/grade_admin_views.xml。
"""

import base64
import io

from odoo import http
from odoo.http import request

from .grade_entry import (
    MAX_MARKS, _allowed_batches, _allowed_subjects, _batch_subjects, _default_term,
    _ensure_container, _entry_url, _existing, _roster, _safe_int, _scope_pairs)
from .roles import _read_table_file, current_faculty, privileged_staff

# 自解释表的形体：首行是「这份表是什么」，第二行才是列名（设计稿 §4.1 定案）
META_KEYS = ('班', '学期', '科目')
COLUMNS = ('学号', '姓名', '分数', '等级')
XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
# 一张表就是一次整班录分；超过这个行数更可能是传错了文件（不是成绩表）
MAX_ROWS = 2000

# 逐行回报的状态（前四种是设计稿 §4.1 点名的，后几种是本轮的边界补齐）
ST_OK = '成功'
ST_NOTFOUND = '学号未匹配'
ST_RANGE = '分数超范围（0..%d）' % MAX_MARKS
ST_SCOPE = '该身份无权录该（班,科目）'
ST_BLANK = '未填分数（跳过）'
ST_DUP = '学号重复（跳过）'
ST_BAD = '分数不是数字（跳过）'
ST_SAME = '无改动（已是最新值）'


# ----------------------------------------------------------------------
# 身份与目标（与 /grade-entry/save 同一判据，不另立第二套）
# ----------------------------------------------------------------------

def _identity(env):
    """当前身份的 (faculty, pairs)。

    pairs is None = 全校（教务 / 超管）；pairs == set() 且 faculty is None = 无任何可写范围
    （学生 / 家长）—— 两者必须分得开：None 是「全都行」，set() 是「什么都不行」。
    """
    if privileged_staff():
        return None, None
    faculty = current_faculty()
    if not faculty:
        return None, set()
    return faculty, _scope_pairs(env, faculty)


def _target(env, kw):
    """从请求里解析 (班, 学期, 科目) —— 入参 id **一律不信任**（设计稿 §2.3）。

    只用来 browse，取不到就是空记录；学期缺省时退化成「当前学期」（与录入页一致）。
    """
    def _rec(model, key):
        rid = _safe_int(kw.get(key))
        return (env[model].sudo().browse(rid).exists() if rid
                else env[model].sudo().browse())

    return (_rec('op.batch', 'batch_id'), _rec('op.subject', 'subject_id'),
            _rec('op.academic.term', 'term_id') or _default_term(env))


def _subjects_for(env, faculty, pairs, batch):
    """可选科目：选了班就只列这个班有的科目（教师再收敛到本人任教）。"""
    if not batch:
        return _allowed_subjects(env, faculty)
    subs = _batch_subjects(env, batch)
    if pairs is not None:
        subs = subs.filtered(lambda s: (batch.id, s.id) in pairs)
    return subs


def _read_side(env, batch, term, subject):
    """导出用的只读读数：(exam, info, bands, total)。

    **绝不建容器**：_ensure_container 是 get-or-create，导出必须是纯读 —— 否则「点一下导出」
    就给任意 (班, 学期, 科目) 造出一个空容器。等级字典优先取容器自带的
    result_template.grade_ids；容器还没建时退化成全表（七档），口径不变。
    """
    info = _existing(env, batch, term, [subject]).get(subject.id)
    exam = info['exam'] if info else env['op.exam'].sudo().browse()
    register = (env['op.marksheet.register'].sudo().search(
        [('exam_session_id', '=', exam.session_id.id)], limit=1) if exam
        else env['op.marksheet.register'].sudo().browse())
    bands = (register.result_template_id.grade_ids if register
             else env['op.grade.configuration'].sudo().search([]))
    return exam, info, bands, (exam.total_marks or MAX_MARKS)


def _grade_of(bands, marks, total):
    """百分制 → 等级名（单一映射函数，设计稿 §5 的债）。

    基座两处口径不一致：op.marksheet.line._compute_grade 用 percentage、op.result.line.
    _compute_grade 用原始分 （且缺 break，只有最后一档留得下）；本仓已在
    models/grade_line_grade.py 把 op.result.line 覆盖成 percentage 口径。这里按**覆盖后**
    的口径算，不沿用基座缺陷；等级字典就是容器自带的 op.grade.configuration。
    """
    if marks is None or not total:
        return ''
    pct = 100.0 * marks / total
    for band in bands:
        if (band.min_per or 0) <= pct <= (band.max_per or 0):
            return band.result or ''
    return ''


# ----------------------------------------------------------------------
# 写：唯一留痕入口 + 读侧同步（与 /grade-entry/save 同一口径）
# ----------------------------------------------------------------------

def _attendee(env, exam, sid):
    """考试参加者（写侧）—— get-or-create，与 /grade-entry/save 同一写法。"""
    Attendee = env['op.exam.attendees'].sudo()
    att = Attendee.search([('exam_id', '=', exam.id), ('student_id', '=', sid)], limit=1)
    return att or Attendee.create({'exam_id': exam.id, 'student_id': sid})


def _sync_read_side(env, exam, register, sid, marks):
    """读侧同步：op.marksheet.line + op.result.line。

    与 /grade-entry/save 的读侧双写同一口径（controllers/grade_entry.py 里那段内联的
    ”读侧：学生页读的是 op.result.line => 同步成同一个值“）—— 那段没有可 import 的函数，
    所以这里只能复刻一份；**两处必须同改**（登记为债）。不写这里 = 学生看不见。
    """
    Line = env['op.marksheet.line'].sudo()
    line = Line.search([('marksheet_reg_id', '=', register.id),
                        ('student_id', '=', sid)], limit=1)
    if not line:
        line = Line.create({'student_id': sid, 'marksheet_reg_id': register.id})
    Result = env['op.result.line'].sudo()
    rl = Result.search([('exam_id', '=', exam.id), ('student_id', '=', sid)], limit=1)
    if not rl:
        Result.create({'exam_id': exam.id, 'student_id': sid, 'marks': marks,
                       'marksheet_line_id': line.id})
    elif rl.marks != marks:
        rl.write({'marks': marks})


class EduGradeEntryIO(http.Controller):
    """批量 IO 三条路由。"""

    # ------------------------------------------------------------------
    # ① 批量 IO 页（选目标 → 导出 / 上传导入）
    # ------------------------------------------------------------------
    @http.route('/grade-entry/xlsx', type='http', auth='user', website=True)
    def grade_entry_xlsx(self, **kw):
        env = request.env
        faculty, pairs = _identity(env)
        if faculty is None and pairs == set():
            return request.redirect('/my/home')       # 学生 / 家长：回门户

        batch, subject, term = _target(env, kw)
        if batch and subject and pairs is not None and (batch.id, subject.id) not in pairs:
            # 越权目标当成没选：不报错也不算数（入参不可信，重新算）
            batch = env['op.batch'].sudo().browse()
            subject = env['op.subject'].sudo().browse()

        terms = env['op.academic.term'].sudo().search([])
        return request.render('edu_portal.edu_grade_entry_io', {
            # title 要显式传：edu_page / website.layout 会读它，缺了会抛 QWeb 未定义变量
            'title': '成绩批量导入 / 导出',
            'batches': _allowed_batches(env, faculty),
            'subjects': _subjects_for(env, faculty, pairs, batch),
            'terms': terms,
            'batch': batch,
            'subject': subject,
            'term': term,
            'max_marks': MAX_MARKS,
            'export_url': ('/grade-entry/export.xlsx?batch_id=%d&term_id=%d&subject_id=%d'
                           % (batch.id, term.id, subject.id)),
        })

    # ------------------------------------------------------------------
    # ② 导出（自解释表：首行 班 / 学期 / 科目，次行 学号 | 姓名 | 分数 | 等级）
    # ------------------------------------------------------------------
    @http.route('/grade-entry/export.xlsx', type='http', auth='user', website=True)
    def grade_entry_export(self, **kw):
        env = request.env
        faculty, pairs = _identity(env)
        if faculty is None and pairs == set():
            return request.redirect('/my/home')

        batch, subject, term = _target(env, kw)
        if (not batch or not subject
                or (pairs is not None and (batch.id, subject.id) not in pairs)):
            # 没选全 / 越权：回录入页去选（那里有名册与学期选择器），不在这里猜
            return request.redirect('/grade-entry')

        # 名册用与页面**同一次调用**（含手工加人那一路）—— 页面上看得见的人，
        # 导出里就必须有；否则导回来会报「学号未匹配」（同一份名单才有意义）。
        allowed_ids = None if pairs is None else set(s for _b, s in pairs)
        roster = _roster(env, batch, subject, _batch_subjects(env, batch),
                         term=term, allowed_subject_ids=allowed_ids)
        _exam, info, bands, total = _read_side(env, batch, term, subject)
        marks = (info or {}).get('marks') or {}

        import openpyxl
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.title = '成绩'
        sheet.append(['班', batch.name or '', '学期', term.name or '',
                      '科目', subject.name or ''])
        sheet.append(list(COLUMNS))
        for row in roster:
            st = row['student']
            m = marks.get(st.id)
            # 没录过的格子留空（不是 0）：空 = 不录入，与页面「空白格不写入」同一语义
            sheet.append([st.gr_no or '', st.name or '',
                          '' if m is None else m, _grade_of(bands, m, total)])
        for col, width in (('A', 14), ('B', 18), ('C', 10), ('D', 10)):
            sheet.column_dimensions[col].width = width
        buf = io.BytesIO()
        book.save(buf)
        filename = '成绩_%s_%s_%s.xlsx' % (term.name or '', batch.name or '',
                                          subject.name or '')
        return request.make_response(buf.getvalue(), headers=[
            ('Content-Type', XLSX_MIME),
            # 文件名玩法照抄既有实现（edu_assess/controllers/portal.py 的 _xlsx_response）：
            # ascii 兜底给老浏览器，filename*=UTF-8'' 给现代浏览器（中文名不乱码）
            ('Content-Disposition',
             "attachment; filename=\"%s\"; filename*=UTF-8''%s"
             % (filename.encode('ascii', 'replace').decode() or 'grade.xlsx',
                base64.b64encode(filename.encode('utf-8')).decode()))])

    # ------------------------------------------------------------------
    # ③ 导入（逐行回报；写入走 edu_apply_marks + 读侧双写）
    # ------------------------------------------------------------------
    @http.route('/grade-entry/import', type='http', auth='user', methods=['POST'],
                website=True, csrf=True)
    def grade_entry_import(self, **post):
        env = request.env
        faculty, pairs = _identity(env)
        if faculty is None and pairs == set():
            return request.redirect('/my/home')

        batch, subject, term = _target(env, post)
        upfile = request.httprequest.files.get('file')
        fname = (upfile.filename or '') if upfile else ''

        def _render(file_err='', rows=None, saved=0):
            return request.render('edu_portal.edu_grade_entry_io_result', {
                'title': '成绩导入结果',
                'batch': batch, 'subject': subject, 'term': term,
                'filename': fname, 'file_err': file_err,
                'rows': rows or [], 'saved': saved,
                'total_rows': len(rows or []),
                'entry_url': (_entry_url(batch, term, subject) if batch
                              else '/grade-entry'),
            })

        if not batch or not subject:
            return _render('没有选好班级 / 学期 / 科目：请回批量 IO 页选好再来导入。')

        header, data = _read_table_file(upfile)
        if not header:
            return _render('没有选择文件，或者文件是空的。')
        if len(data) > MAX_ROWS:
            return _render('这张表有 %d 行，超过单次导入上限 %d 行 —— 请拆成几个文件，'
                           '或者确认一下是不是传错了文件。' % (len(data), MAX_ROWS))
        if not data or header[0] != META_KEYS[0]:
            if all(c in header for c in COLUMNS):
                return _render('这张表缺首行（%s）：请先用「导出这张表」下载模板，'
                               '在它上面填分数再导回来。' % ' / '.join(META_KEYS))
            return _render('表头不认：第二行需要「%s」四列，'
                           '请先用「导出这张表」下载模板。' % '、'.join(COLUMNS))
        if not all(c in data[0] for c in COLUMNS):
            return _render('列名不认：第二行需要「%s」四列，'
                           '请先用「导出这张表」下载模板。' % '、'.join(COLUMNS))

        # 首行写的 (班, 学期, 科目) 必须与目标一致：教务手上有好几张表，导错了容器
        # 是**静默写错人**，比报错严重得多 —— 不一致就整表不写（逐行报「表头不符」）。
        meta = {}
        for i in range(0, len(header) - 1, 2):
            key = (header[i] or '').strip()
            if key:
                meta[key] = (header[i + 1] or '').strip()
        expect = {'班': batch.name or '', '学期': term.name or '',
                  '科目': subject.name or ''}
        mismatch = ['%s（表里「%s」，当前目标「%s」）'
                    % (key, meta.get(key, ''), expect[key])
                    for key in META_KEYS if meta.get(key, '') != expect[key]]
        if mismatch:
            return _render('表头与当前目标不一致，整表未写入：%s。'
                           '请确认导的是「%s · %s · %s」这张表。'
                           % ('；'.join(mismatch), term.name or '', batch.name or '',
                              subject.name or ''))

        # 名册（同一调用口径）→ 按学号索引：学号是这张表对外的唯一键
        allowed_ids = None if pairs is None else set(s for _b, s in pairs)
        roster = _roster(env, batch, subject, _batch_subjects(env, batch),
                         term=term, allowed_subject_ids=allowed_ids)
        by_no = {}
        for row in roster:
            st = row['student']
            key = (st.gr_no or '').strip()
            if key and key not in by_no:
                by_no[key] = st

        scope_ok = pairs is None or (batch.id, subject.id) in pairs
        seen, rows, writes = set(), [], []

        def _count(status, line, gr_no, name='', marks_text='', detail='',
                   sid=None, marks=None):
            row = {'line': line, 'gr_no': gr_no, 'name': name, 'marks_text': marks_text,
                   'status': status, 'detail': detail}
            rows.append(row)
            if status == ST_OK:
                writes.append({'row': row, 'sid': sid, 'marks': marks})

        for offset, raw_row in enumerate(data[1:]):
            line = offset + 3                      # 表里第几行（首行/列名行占 1、2）
            gr_no = (raw_row[0] if len(raw_row) > 0 else '').strip()
            name = (raw_row[1] if len(raw_row) > 1 else '').strip()
            raw = (raw_row[2] if len(raw_row) > 2 else '').strip()
            if not gr_no and not name and not raw:
                continue                           # 空行
            st = by_no.get(gr_no)
            if not scope_ok:
                _count(ST_SCOPE, line=line, gr_no=gr_no, name=name, marks_text=raw)
                continue
            if not gr_no or st is None:
                _count(ST_NOTFOUND, line=line, gr_no=gr_no, name=name, marks_text=raw,
                       detail=name if name else '')
                continue
            if st.id in seen:
                _count(ST_DUP, line=line, gr_no=gr_no, name=st.name or name,
                       marks_text=raw)
                continue
            seen.add(st.id)
            if not raw:
                _count(ST_BLANK, line=line, gr_no=gr_no, name=st.name or name)
                continue
            try:
                marks = int(float(raw))
            except (TypeError, ValueError):
                _count(ST_BAD, line=line, gr_no=gr_no, name=st.name or name,
                       marks_text=raw)
                continue
            if marks < 0 or marks > MAX_MARKS:
                _count(ST_RANGE, line=line, gr_no=gr_no, name=st.name or name,
                       marks_text=raw)
                continue
            _count(ST_OK, line=line, gr_no=gr_no, name=st.name or name,
                   marks_text=raw, sid=st.id, marks=marks)

        # 只在真有可写行时才建容器：整表都不合法 ⇒ 一个空容器都不该留下
        saved = 0
        if writes:
            _session, exam, register = _ensure_container(env, batch, term, subject)
            Hist = env['edu.grade.history'].sudo()
            note = 'xlsx 导入（%s）' % (fname or '未命名文件')[:60]
            for item in writes:
                att = _attendee(env, exam, item['sid'])
                before = att.marks
                # 唯一留痕写入口：source='import' ⇒ 留痕里 action/source 都落 import，
                # 教务一眼分得清「文件导入」与「页面录入」
                if Hist.edu_apply_marks(att, marks=item['marks'], source='import',
                                        note=note):
                    saved += 1
                    item['row']['detail'] = '原 %s → 现 %s' % (
                        '' if before is False or before is None else before, att.marks)
                else:
                    # 值没变 ⇒ edu_apply_marks 不写留痕（它的既定语义），状态如实改口
                    item['row']['status'] = ST_SAME
                    item['row']['detail'] = '已是 %s' % att.marks
                # 读侧同步照旧无条件执行（与 /grade-entry/save 一致）：两侧本来就可能
                # 因为后台直改而漂移，导入顺手把它对齐到同一个值
                _sync_read_side(env, exam, register, item['sid'], item['marks'])
            env['edu.audit.log'].sudo()._log(
                '成绩导入', 'op.exam', exam.id, exam.name or '',
                'xlsx 导入 %d 条 / 共 %d 行（班级 %s / 科目 %s / 文件 %s）'
                % (saved, len(rows), batch.name or '', subject.name or '',
                   (fname or '')[:60]))
        return _render('', rows, saved)
