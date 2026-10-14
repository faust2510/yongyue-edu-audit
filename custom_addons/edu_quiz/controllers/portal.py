# -*- coding: utf-8 -*-
"""学生端测验：列表 / 作答 / 自动判分 / 结果。"""
import json
import re

from odoo import http
from odoo.http import request


class EduQuizPortal(http.Controller):

    def _student(self):
        return request.env['op.student'].sudo().search(
            [('user_id', '=', request.env.uid)], limit=1)

    def _visible_course_ids(self):
        """t62：本角色可见课程 id；**None 表示全目录**（教师/教务）。

        口径与 edu_portal 的 student_course() 同源（op.student.course），但
        **在本模块内重写**：edu_quiz 的 depends 只有 openeducat_core/exam/mail，
        没有 edu_portal —— 跨模块 import 会引入未声明依赖并可能影响加载顺序，
        故只复用「同一数据来源」，不引入跨模块 import。
        无学生档案者返回空列表（不泄露全目录）——与 edu_portal 的
        _subjects_for「无档案学生不泄露全目录」同口径。
        """
        env, user = request.env, request.env.user
        if user.has_group('base.group_user'):
            return None
        student = self._student()
        if not student:
            return []
        Scs = env['op.student.course'].sudo()
        scs = Scs.search([('student_id', '=', student.id),
                          ('state', '=', 'running')]) or Scs.search(
            [('student_id', '=', student.id)])
        return scs.mapped('course_id').ids

    @http.route('/quiz', type='http', auth='user', website=True)
    def quiz_list(self, **kw):
        student = self._student()
        search = (kw.get('search') or '').strip()
        domain = [('state', '=', 'published')]
        if search:
            domain += ['|', ('name', 'ilike', search),
                       ('category', 'ilike', search)]
        # t62：非内部用户按本角色课程收敛（此前零收敛 → 学生可见全部已发布测验）
        courses = self._visible_course_ids()
        if courses is not None:
            domain.append(('course_id', 'in', courses))
        quizzes = request.env['edu.quiz'].sudo().search(domain)
        attempts = request.env['edu.quiz.attempt'].sudo().search(
            [('student_id', '=', student.id)]) if student else []
        best = {}
        latest = {}
        for a in attempts:  # attempts 按 _order=create_date desc：setdefault 即最近一次
            pct = round(a.score * 100.0 / a.total) if a.total else 0
            best[a.quiz_id.id] = max(best.get(a.quiz_id.id, 0), pct)
            latest.setdefault(a.quiz_id.id, a.id)
        items = []
        for q in quizzes:
            items.append({
                'quiz': q,
                'best_pct': best.get(q.id),
                'tried': q.id in best,
                'best_attempt_id': latest.get(q.id),
            })
        return request.render('edu_quiz.edu_quiz_portal_list', {
            'title': '在线测验',
            'items': items,
            'search': search,
        })

    @http.route('/quiz/my', type='http', auth='user', website=True)
    def quiz_my(self, **kw):
        """3d：我的测验成绩（逐次记录，attempt 数据已有此前未展示）。"""
        student = self._student()
        if not student:
            return request.redirect('/quiz')
        attempts = request.env['edu.quiz.attempt'].sudo().search(
            [('student_id', '=', student.id)],
            order='create_date desc, id desc')
        rows = []
        for a in attempts:
            pct = round(a.score * 100.0 / a.total) if a.total else 0
            rows.append({
                'attempt': a,
                'quiz_name': a.quiz_id.name or '（已删除）',
                'score_str': '%s/%s' % (a.score, a.total),
                'pct': pct,
                'date': a.create_date.strftime('%Y-%m-%d %H:%M')
                if a.create_date else '',
                'href': '/quiz/%d/result/%d' % (a.quiz_id.id, a.id),
            })
        return request.render('edu_quiz.edu_quiz_my', {
            'title': '我的测验成绩',
            'rows': rows,
        })

    @http.route('/quiz/<int:qid>/take', type='http', auth='user', website=True)
    def quiz_take(self, qid, **kw):
        student = self._student()
        quiz = request.env['edu.quiz'].sudo().browse(qid)
        if not quiz.exists() or quiz.state != 'published':
            return request.redirect('/quiz')
        # D 组第一批（P1）：作答页是**学生自己的答卷界面**，只该给学生看。
        # 此前只过了 _visible_course_ids() —— 而它对任何 base.group_user（教师/
        # 教务/管理员）返回 None（= 全目录不限），于是教师、教务能直接打开学生的
        # 作答界面（真机读数：fac/bo/admin 200 /quiz/1/take）。判据与同文件的写路由
        # quiz_submit 对齐（那里第一行就是“没有学生档案就 303 回列表”）—— 同一个
        # 「作答者」条件，不新增第二套口径；非学生一律 303 回列表，不泄露存在性差异。
        if not student:
            return request.redirect('/quiz')
        # t62：作答页与列表同口径 —— 非本课测验按"不存在"处理（同一个 redirect，
        # 不泄露存在性差异），否则拼 URL 即可作答任意已发布测验
        courses = self._visible_course_ids()
        if courses is not None and quiz.course_id.id not in courses:
            return request.redirect('/quiz')
        return request.render('edu_quiz.edu_quiz_take', {
            'title': quiz.name,
            'quiz': quiz,
        })

    @http.route('/quiz/<int:qid>/submit', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def quiz_submit(self, qid, **post):
        student = self._student()
        quiz = request.env['edu.quiz'].sudo().browse(qid)
        if not student or not quiz.exists() or quiz.state != 'published':
            return request.redirect('/quiz')
        # t62：写入路径同口径（否则绕开作答页直接 POST 仍可造出越权 attempt）
        courses = self._visible_course_ids()
        if courses is not None and quiz.course_id.id not in courses:
            return request.redirect('/quiz')

        score = 0.0
        answers = {}
        for q in quiz.question_ids:
            key = f'q_{q.id}'
            answer = (q.answer or '').strip()
            if q.qtype == 'multi':
                vals = sorted(v.strip().upper()
                              for v in request.httprequest.form.getlist(key) if v)
                ok = vals == sorted(re.sub(r'[\s,]', '', answer).upper())
                answers[key] = ','.join(vals)
            elif q.qtype == 'text':
                val = post.get(key, '').strip().lower()
                ok = bool(val) and val in answer.lower()
                answers[key] = val
            else:
                val = post.get(key, '').strip().upper()
                ok = val == answer.upper()
                answers[key] = val
            if ok:
                score += q.points

        attempt = request.env['edu.quiz.attempt'].sudo().create({
            'quiz_id': quiz.id,
            'student_id': student.id,
            'score': score,
            'total': quiz.total_points,
            'answers_json': json.dumps(answers, ensure_ascii=False),
            'state': 'submitted',
        })
        return request.redirect(f'/quiz/{quiz.id}/result/{attempt.id}')

    @http.route('/quiz/<int:qid>/result/<int:aid>', type='http',
                auth='user', website=True)
    def quiz_result(self, qid, aid, **kw):
        student = self._student()
        attempt = request.env['edu.quiz.attempt'].sudo().browse(aid)
        # B6 下钻入口增多，补归属校验：仅本人（op.student.user_id=当前用户）
        # 且 quiz 与 URL 一致的 attempt 可见。
        if not attempt.exists() or not student \
                or attempt.student_id.id != student.id \
                or attempt.quiz_id.id != qid:
            return request.redirect('/quiz')
        return request.render('edu_quiz.edu_quiz_result', {
            'title': '测验结果',
            'attempt': attempt,
        })
