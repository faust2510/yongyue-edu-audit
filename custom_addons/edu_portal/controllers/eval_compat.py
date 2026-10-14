# -*- coding: utf-8 -*-
"""综合评估（A 套 /my/evaluation*）旧地址 → 新引擎 303 兼容层。

设计稿 docs/plans/evaluation-rebuild-design.md §7.4-2：旧 7 条路由改 303，
**不删模型、不删表、不改 ACL**（旧两套本期只冻结：只读化石，先建后删是校长钉死的顺序）。

做法：**继承** EduEvalPortal 并覆写方法。Odoo 的路由生成器
（odoo/http.py:_generate_routing_rules 的 leaf 覆盖机制）只实例化最底层的子类，
父类的同一路由不再单独注册 ⇒ 这里可以确定地接管这 7 条地址，
而 controllers/evaluation.py 的实现一行未删（回滚 = 删本文件）。

为什么不用「同名路由各写一遍」：两个互不为父子关系的控制器定义同一路由时，
归属随模块加载顺序漂移（scripts/check_view_xpath.py 规则 5 就是专门拦这个的）。
"""
from odoo import http
from odoo.http import request

from .evaluation import EduEvalPortal


class EduEvalCompat(EduEvalPortal):
    """旧地址 → 新引擎（303）。学生与教师分流由新引擎的 /assess 入口判断。"""

    @http.route('/my/evaluation', type='http', auth='user', website=True)
    def eval_center(self, **kw):
        return request.redirect('/assess')

    @http.route(['/my/evaluation/new'], type='http', auth='user', website=True)
    def eval_new(self, **kw):
        return request.redirect('/assess')

    @http.route('/my/evaluation/create', type='http', methods=['POST'],
                auth='user', website=True, csrf=True)
    def eval_create(self, **post):
        return request.redirect('/assess')

    @http.route('/my/evaluation/task/<int:task_id>', type='http', auth='user',
                website=True)
    def eval_task(self, task_id, **kw):
        return request.redirect('/assess')

    @http.route('/my/evaluation/task/<int:task_id>/save', type='http',
                methods=['POST'], auth='user', website=True, csrf=True)
    def eval_task_save(self, task_id, **post):
        return request.redirect('/assess')

    @http.route('/my/evaluation/results', type='http', auth='user',
                website=True)
    def eval_results(self, student_id=None, **kw):
        return request.redirect('/assess/my')

    @http.route('/my/evaluation/results.csv', type='http', auth='user')
    def eval_results_csv(self, **kw):
        return request.redirect('/assess/my')
