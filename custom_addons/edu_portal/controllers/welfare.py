# -*- coding: utf-8 -*-
"""福利系统组控制器：学生自助打卡（已收口到 edu_life）+ 积分基础版。

⚠ 打卡收口（t5，2026-09-17）：本模块**不再持有打卡实现**。
学生打卡的唯一实现与唯一入口都是 edu_life：
  - 页面  GET  /my/checkins         （edu_life/controllers/life.py）
  - 写    POST /my/checkins/check   （edu_life）
  - 导出  GET  /my/checkins/export  （edu_life）
  - 统计  GET  /checkins/stats      （edu_life，教师）
原先这一套（edu.daily.checkin + /my/checkin*）已被废弃，只保留**兼容重定向**，
写路径一律断掉 —— 收口后全站不存在能写 edu.daily.checkin 的入口
（旧表/旧模型/旧记录全量保留，只停写；清理前置条件见
docs/audit/checkin-merge-report.md）：

路由清单（本模块）：
  GET  /my/checkin         → 303 /my/checkins        （旧「每日打卡」页）
  GET  /my/checkin/save    → 303 /my/checkins        （旧写路由已废；直连也断）
  POST /my/checkin/save    → 303 /my/checkins        （不解析表单、不落库）
  GET  /my/checkin/export  → 303 /my/checkins/export （旧 CSV 导出）
  GET  /my/checkin/board   → 200 打卡看板（**数据源已换成 edu.checkin.record**）

  GET  /my/points         教师给学生加减分页（current_faculty 归属校验）
  POST /my/points/give    教师发放积分流水（granted_by=当前用户）
  GET  /my/points/me      学生查看个人合计与流水

工程红线：QWeb 模板中不出现 % 格式化表达式，日期/分值符号一律
在 Python 侧预格式化后传入模板。写操作 POST+csrf。
"""
import datetime

from odoo import fields, http
from odoo.http import request

from .main import current_student
from .roles import current_faculty

# 快捷原因按钮组：标签 | 预置分值（可被自定义原因文本覆盖）
QUICK_REASONS = [
    ('课堂表现', 2),
    ('作业优秀', 5),
    ('纪律提醒', -3),
    ('服务奉献', 3),
]
# 自定义发放的分值选项（正加负减）
DELTA_OPTIONS = [-10, -5, -3, -2, -1, 1, 2, 3, 5, 10]
MAX_ABS_DELTA = 100


def _fmt_dt(dt):
    return dt.strftime('%Y-%m-%d %H:%M') if dt else ''


def _fmt_delta(delta):
    return ('+%d' % delta) if delta > 0 else str(delta)


class EduWelfare(http.Controller):

    # ------------------ 任务1 学生自助打卡（t5 已收口 → edu_life） ------------------
    #
    # 本模块只保留**兼容重定向**，不再读也不写 edu.daily.checkin。
    # 重定向统一 303（See Other）：浏览器把后续请求转成 GET，旧 POST 也不会被重放。

    @http.route('/my/checkin', type='http', auth='user', website=True)
    def my_checkin(self, **kw):
        """旧「每日打卡」页 → edu_life 的 /my/checkins。"""
        return request.redirect('/my/checkins', code=303)

    @http.route('/my/checkin/export', type='http', auth='user')
    def my_checkin_export(self, **kw):
        """旧 CSV 导出 → edu_life 的 /my/checkins/export。"""
        return request.redirect('/my/checkins/export', code=303)

    @http.route('/my/checkin/save', type='http', auth='user', website=True,
                methods=['GET', 'POST'], csrf=True)
    def my_checkin_save(self, **kw):
        """旧打卡写路由：**已废**。

        收口后写路径只有 edu_life 的 POST /my/checkins/check。
        这里刻意只返回 303 —— 不解析表单、不校验、不落库，
        也不回传任何旧页面的 saved/error 查询串，避免留下"还能写"的错觉。
        （GET 也收：旧模板有可以直接点开的导出/看板链接，GET 直连同样断掉。）
        """
        return request.redirect('/my/checkins', code=303)

    # ------------------- v2-B6 打卡看板（t5 换数据源） -------------------
    #
    # 看板 = 本周（周一~周日）全体学生的**到堂**情况。
    # t5 起数据源改为 edu_life 的 edu.checkin.record + 「到堂打卡」类型 ——
    # 原来的 edu.daily.checkin 已停写，继续读它会得到永远停在 2026-09-17 的僵尸看板。
    # 门槛维持原状（base.group_user，即内部用户）：看板展示全体学生，向学生开放
    # 属隐私/产品决策，本轮只做收口，不扩功能（队长 2026-09-17 裁定）。

    @http.route('/my/checkin/board', type='http', auth='user', website=True)
    def checkin_board(self, **kw):
        if not request.env.user.has_group('base.group_user'):
            return request.redirect('/my/checkins', code=303)
        env = request.env
        today = fields.Date.today()
        monday = today - datetime.timedelta(days=today.weekday())
        days = [monday + datetime.timedelta(days=i) for i in range(7)]

        # 到堂类型按 name 查（get-or-create 在 scripts/migrations/checkin_merge.py），
        # 不硬编码 id；类型缺失时看板退化为「全员未打卡」而不是 Traceback。
        attend_type = env['edu.checkin.type'].sudo().search(
            [('name', '=', '到堂打卡')], limit=1)
        ok = set()
        if attend_type:
            recs = env['edu.checkin.record'].sudo().search([
                ('type_id', '=', attend_type.id),
                ('checkin_date', '>=', days[0]),
                ('checkin_date', '<=', days[-1]),
            ])
            ok = {(r.student_id.id, r.checkin_date) for r in recs}

        students = env['op.student'].sudo().search([], order='name')
        rows, missing = [], []
        for s in students:
            cells = []
            for d in days:
                done = (s.id, d) in ok
                cells.append({'d': d, 'done': done, 'future': d > today})
            rows.append({'student': s, 'cells': cells})
            today_cell = next((c for c in cells if c['d'] == today), None)
            if today_cell and not today_cell['done']:
                missing.append(s)
        day_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        return request.render('edu_portal.edu_welfare_board', {
            'title': '打卡看板',
            'days': zip(days, day_names[:len(days)]),
            'rows': rows,
            'missing': missing,
            'page_name': 'checkin_board',
        })

    # ------------------------- 任务2 积分基础版 -------------------------

    @http.route('/my/points', type='http', auth='user', website=True)
    def my_points_give_page(self, **kw):
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        env = request.env
        q = (kw.get('q') or '').strip()
        domain = [('name', 'ilike', q)] if q else []
        students = env['op.student'].sudo().search(
            domain, order='name', limit=200)
        quick_reasons = [{
            'label': label,
            'delta_fmt': _fmt_delta(delta),
            'value': '%s|%d' % (label, delta),
        } for label, delta in QUICK_REASONS]
        mine = env['edu.point.log'].sudo().search(
            [('granted_by', '=', request.env.uid)],
            order='date desc', limit=20)
        flows = [{
            'who': r.student_id.name or r.teacher_user_id.name or '-',
            'delta_fmt': _fmt_delta(r.delta),
            'reason': r.reason or '',
            'when': _fmt_dt(r.date),
        } for r in mine]
        values = {
            'title': '学生积分',
            'page_name': 'welfare_points_give',
            'faculty': fac,
            'q': q,
            'students': students,
            'quick_reasons': quick_reasons,
            'delta_options': [str(d) for d in DELTA_OPTIONS],
            'flows': flows,
            'saved': kw.get('saved') == '1',
            'error': kw.get('error') == '1',
        }
        return request.render('edu_portal.edu_welfare_points_give', values)

    @http.route('/my/points/give', type='http', auth='user', website=True,
                methods=['POST'], csrf=True)
    def my_points_give(self, **kw):
        fac = current_faculty()
        if not fac:
            return request.redirect('/my/home')
        try:
            sid = int(kw.get('student_id') or 0)
        except (TypeError, ValueError):
            sid = 0
        student = request.env['op.student'].sudo().browse(sid)
        if not student.exists():
            return request.redirect('/my/points?error=1')
        reason_custom = (kw.get('reason_custom') or '').strip()
        try:
            delta = int(kw.get('delta') or 0)
        except (TypeError, ValueError):
            delta = 0
        if reason_custom:
            # 自定义原因文本覆盖快捷按钮，分值走下拉选择
            reason = reason_custom[:256]
            if not delta or abs(delta) > MAX_ABS_DELTA:
                return request.redirect('/my/points?error=1')
        else:
            # 快捷按钮：value 形如 "课堂表现|2"
            raw = kw.get('preset') or ''
            label, _, num = raw.partition('|')
            reason = label.strip()[:256]
            try:
                delta = int(num)
            except (TypeError, ValueError):
                delta = 0
            if not reason or not delta:
                return request.redirect('/my/points?error=1')
        request.env['edu.point.log'].sudo().create({
            'person_kind': 'student',
            'student_id': student.id,
            'delta': delta,
            'reason': reason,
            'note': (kw.get('note') or '').strip(),
            'granted_by': request.env.uid,
            'date': fields.Datetime.now(),
        })
        return request.redirect('/my/points?saved=1')

    @http.route('/my/points/me', type='http', auth='user', website=True)
    def my_points_me(self, **kw):
        student = current_student()
        if not student:
            return request.redirect('/my/home')
        Log = request.env['edu.point.log']
        domain = [('person_kind', '=', 'student'),
                  ('student_id', '=', student.id)]
        logs = Log.sudo().search(domain, order='date desc', limit=100)
        total = sum(logs.mapped('delta'))
        flows = [{
            'delta_fmt': _fmt_delta(r.delta),
            'reason': r.reason or '',
            'note': r.note or '',
            'by': r.granted_by.name or '-',
            'when': _fmt_dt(r.date),
        } for r in logs]
        values = {
            'title': '我的积分',
            'page_name': 'welfare_points_me',
            'student': student,
            'total': total,
            'total_fmt': _fmt_delta(total),
            'flows': flows,
            'count': len(flows),
        }
        return request.render('edu_portal.edu_welfare_points_me', values)
