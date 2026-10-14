# -*- coding: utf-8 -*-
"""综合评估门户（教师/管理员）。

Excel 式打分表：整表 POST 幂等 upsert；雷达图数据由控制器注入模板。
权限：internal 用户（教师/教务/管理员）；学生仅可见自己的学生型结果。
（原「评估中心」，2026 更名以与「行政评估」区分；路由 /my/evaluation 不变）
"""
import csv
import io
import json

from odoo import http
from odoo.http import request


TYPE_LABELS = {'freshman': '新生综合测试', 'student': '学生综合评估',
               'intern': '实习同工评估'}
DIM_LABELS = {'teacher': '教师评', 'self': '自评',
              'ta': 'TA评', 'pastor': '牧者评'}
GRADE_LABELS = {'fail': '不合格', 'pass': '合格', 'excellent': '优秀'}
STATE_LABELS = {'draft': '草稿', 'scoring': '打分中', 'done': '已完成'}


def _is_staff():
    return request.env.user.has_group('base.group_user')


class EduEvalPortal(http.Controller):

    # ------------------------- 中心首页 -------------------------
    @http.route('/my/evaluation', type='http', auth='user', website=True)
    def eval_center(self, **kw):
        env = request.env
        Task = env['edu.eval.task'].sudo()
        if _is_staff():
            tasks = Task.search([])
        else:
            stu = env['op.student'].sudo().search(
                [('user_id', '=', env.uid)], limit=1)
            tasks = Task.search([
                ('student_id', '=', stu.id if stu else 0),
                ('type_code', '=', 'student'),
                ('template_id.visible_to_student', '=', True)])
        stats = {
            'total': len(tasks),
            'scoring': sum(1 for t in tasks if t.state == 'scoring'),
            'done': sum(1 for t in tasks if t.state == 'done'),
            'excellent': sum(1 for t in tasks if t.grade == 'excellent'),
        }
        return request.render('edu_portal.edu_eval_center', {
            'title': '综合评估',
            'tasks': tasks,
            'stats': stats,
            'is_staff': _is_staff(),
            'type_labels': TYPE_LABELS, 'dim_labels': DIM_LABELS,
            'grade_labels': GRADE_LABELS, 'state_labels': STATE_LABELS,
            'page_name': 'eval_center',
        })

    # ------------------------- 新建任务 -------------------------
    @http.route(['/my/evaluation/new'], type='http', auth='user',
                website=True)
    def eval_new(self, **kw):
        if not _is_staff():
            return request.redirect('/my/evaluation')
        env = request.env
        return request.render('edu_portal.edu_eval_new', {
            'title': '新建评估',
            'templates': env['edu.eval.template'].sudo().search([]),
            'students': env['op.student'].sudo().search([]),
            'error': kw.get('error'),
            'page_name': 'eval_new',
        })

    @http.route('/my/evaluation/create', type='http', methods=['POST'],
                auth='user', website=True, csrf=True)
    def eval_create(self, **post):
        if not _is_staff():
            return request.redirect('/my/evaluation')
        env = request.env
        tpl = env['edu.eval.template'].sudo().browse(
            int(post.get('template_id', 0) or 0))
        stu = env['op.student'].sudo().browse(
            int(post.get('student_id', 0) or 0))
        etype = post.get('evaluator_type') or 'teacher'
        period = (post.get('period') or '2026秋').strip()[:20]
        if not tpl.exists() or not stu.exists() or tpl.line_count == 0:
            return request.redirect('/my/evaluation/new?error=1')
        dup = env['edu.eval.task'].sudo().search([
            ('template_id', '=', tpl.id),
            ('student_id', '=', stu.id),
            ('evaluator_type', '=', etype),
            ('period', '=', period)], limit=1)
        if dup:
            return request.redirect(f'/my/evaluation/task/{dup.id}')
        task = env['edu.eval.task'].sudo().create({
            'template_id': tpl.id, 'student_id': stu.id,
            'evaluator_type': etype, 'period': period,
        })
        env['edu.eval.score'].sudo().create([{
            'task_id': task.id,
            'template_line_id': line.id, 'score': 0.0}
            for line in tpl.line_ids])
        return request.redirect(f'/my/evaluation/task/{task.id}')

    # ------------------------- 打分表 -------------------------
    @http.route('/my/evaluation/task/<int:task_id>', type='http',
                auth='user', website=True)
    def eval_task(self, task_id, saved=None, **kw):
        if not _is_staff():
            return request.redirect('/my/evaluation')
        task = request.env['edu.eval.task'].sudo().browse(task_id)
        if not task.exists():
            return request.redirect('/my/evaluation')
        rows = [{
            'line': s.template_line_id,
            'score': s.score,
            'score_id': s.id,
        } for s in task.score_ids.sorted(
            lambda x: (x.template_line_id.sequence, x.id))]
        return request.render('edu_portal.edu_eval_task', {
            'title': f"打分：{task.student_id.name} · {task.template_id.name}",
            'task': task,
            'rows': rows,
            'saved': bool(saved),
            'page_name': 'eval_task',
        })

    @http.route('/my/evaluation/task/<int:task_id>/save', type='http',
                methods=['POST'], auth='user', website=True, csrf=True)
    def eval_task_save(self, task_id, **post):
        if not _is_staff():
            return request.redirect('/my/evaluation')
        env = request.env
        task = env['edu.eval.task'].sudo().browse(task_id)
        if not task.exists() or task.state == 'done':
            return request.redirect(f'/my/evaluation/task/{task_id}')
        Score = env['edu.eval.score'].sudo()
        for key, val in post.items():
            if not key.startswith('score_'):
                continue
            try:
                sid = int(key[6:])
                val_f = float(val)
            except (ValueError, TypeError):
                continue
            rec = Score.browse(sid)
            if rec.exists() and rec.task_id.id == task.id:
                max_s = rec.template_line_id.max_score or 0
                rec.write({'score': max(0.0, min(val_f, max_s))})
        return request.redirect(f'/my/evaluation/task/{task_id}?saved=1')

    # ------------------------- 汇总与雷达 -------------------------
    @http.route('/my/evaluation/results', type='http', auth='user',
                website=True)
    def eval_results(self, student_id=None, **kw):
        if not _is_staff():
            return request.redirect('/my/evaluation')
        env = request.env
        students = env['op.student'].sudo().search([])
        sel = None
        if student_id and student_id.isdigit():
            sel = env['op.student'].sudo().browse(int(student_id))
            if not sel.exists():
                sel = None
        tasks = env['edu.eval.task'].sudo().search(
            [('state', '=', 'done')] if True else [])
        if sel:
            tasks = tasks.filtered(lambda t: t.student_id == sel)

        # 雷达：按评估类型平均分（百分制归一）
        dims, vals = [], []
        for code, label in TYPE_LABELS.items():
            sub = tasks.filtered(lambda t: t.type_code == code)
            if sub:
                dims.append(label)
                vals.append(round(
                    sum(t.total_score for t in sub) / len(sub), 1))

        rows = [{'student': t.student_id.name,
                 'type': TYPE_LABELS.get(t.type_code, t.type_code),
                 'dim': DIM_LABELS.get(t.evaluator_type, ''),
                 'period': t.period,
                 'total': t.total_score,
                 'grade': GRADE_LABELS.get(t.grade, '')}
                for t in tasks]
        return request.render('edu_portal.edu_eval_results', {
            'title': '成绩汇总',
            'students': students,
            'sel_student': sel,
            'tasks': tasks,
            'rows': rows,
            'radar_dims': dims,
            'radar_vals': vals,
            'radar_dims_json': json.dumps(dims, ensure_ascii=False),
            'radar_vals_json': json.dumps(vals),
            'page_name': 'eval_results',
        })

    @http.route('/my/evaluation/results.csv', type='http', auth='user')
    def eval_results_csv(self, **kw):
        if not _is_staff():
            return request.redirect('/my/evaluation')
        tasks = request.env['edu.eval.task'].sudo().search([])
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['学生', '评估类型', '维度', '周期', '总分', '等级'])
        sel_map_t, sel_map_e, sel_map_g = TYPE_LABELS, DIM_LABELS, GRADE_LABELS
        for t in tasks:
            w.writerow([t.student_id.name,
                        sel_map_t.get(t.type_code, ''),
                        sel_map_e.get(t.evaluator_type, ''),
                        t.period, t.total_score,
                        sel_map_g.get(t.grade, '')])
        return request.make_response(
            buf.getvalue().encode('utf-8-sig'),
            headers=[('Content-Type', 'text/csv; charset=utf-8'),
                     ('Content-Disposition',
                      'attachment; filename="evaluation.csv"')])
