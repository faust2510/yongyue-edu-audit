# -*- coding: utf-8 -*-
"""命令矩阵自测：绑定码、角色越权、翻页、报表签名。"""
import datetime

from odoo.tests import TransactionCase


class TestCommands(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Chat = self.env['op.telegram.chat']
        self.Binding = self.env['edu.telegram.binding']

    def _student(self):
        Student = self.env['op.student']
        stu = Student.search([('user_id', '!=', False)], limit=1)
        if not stu:
            user = self.env['res.users'].create({
                'name': '测试生', 'login': 'tg_test_stu',
                'email': 'tg_test_stu@local',
                'group_ids': [(6, 0,
                               [self.env.ref('base.group_portal').id])]})
            stu = Student.create({
                'name': '测试生', 'first_name': '测', 'last_name': '试生',
                'user_id': user.id, 'gender': 'm',
                'birth_date': datetime.date(2006, 1, 1)})
            course = self.env['op.course'].search([], limit=1)
            batch = self.env['op.batch'].search([], limit=1)
            if course and batch:
                self.env['op.student.course'].create({
                    'student_id': stu.id, 'course_id': course.id,
                    'batch_id': batch.id, 'roll_number': 'TG0001'})
        return stu

    def test_registry_functions_exist(self):
        from odoo.addons.edu_telegram.controllers.main import REGISTRY
        import odoo.addons.edu_telegram.controllers.main as M
        for name, (_fn, roles) in REGISTRY.items():
            self.assertTrue(callable(getattr(M, _fn)), name)
            if roles:
                self.assertTrue(roles <= {'student', 'faculty', 'parent',
                                          'admin'})

    def test_bind_by_code_and_role_gate(self):
        stu = self._student()
        code = self.Binding.issue(user=stu.user_id).code
        rec = self.Chat.bind_by_code('999001', 'Tester', code)
        self.assertTrue(rec)
        self.assertEqual(rec.role, 'student')
        # 码是一次性的
        rec2 = self.Chat.bind_by_code('999002', 'Other', code)
        self.assertIsNone(rec2)

        from odoo.addons.edu_telegram.controllers.main import handle_update
        chat_id, act = handle_update(self.env, {
            'message': {'chat': {'id': 999001}, 'text': '/概览'}})
        self.assertIn('⛔', act['text'])

    def test_grades_pagination_contract(self):
        stu = self._student()
        rng, text = None, None
        from odoo.addons.edu_telegram.controllers.main import \
            _grades_text
        rng, text = _grades_text(self.env, stu, 0)
        if rng is not None:
            page, pages = rng
            self.assertLessEqual(page, pages - 1)

    def test_report_token_roundtrip(self):
        from odoo.addons.edu_telegram.controllers.main import (
            _report_token, _check_report_token)
        tok = _report_token(self.env, '555')
        exp, sig = tok.split('-', 1)
        self.assertTrue(_check_report_token(self.env, '555', exp, sig))
        self.assertFalse(_check_report_token(self.env, '556', exp, sig))

    def test_notice_command_and_push(self):
        from odoo.addons.edu_telegram.controllers.main import handle_update
        Notice = self.env['op.notice']
        Notice.create({'title': '测试公告', 'body': '明天放假',
                       'priority': 'high'})
        stu = self._student()
        code0 = self.Binding.issue(user=stu.user_id).code
        handle_update(self.env, {'message': {
            'chat': {'id': 777002}, 'text': '/start %s' % code0}})
        chat_id, act = handle_update(self.env, {
            'message': {'chat': {'id': 777002}, 'text': '/布告'}})
        self.assertIn('测试公告', act['text'])
        Notice.push_new()
        Out = self.env['edu.telegram.outbox']
        self.assertTrue(Out.search_count([('text', 'like', '测试公告')]))

    def test_leave_flow_happy_path(self):
        from odoo.addons.edu_telegram.controllers.main import (
            handle_update, flow_feed)
        stu = self._student()
        code = self.Binding.issue(user=stu.user_id).code
        handle_update(self.env, {'message': {
            'chat': {'id': 888001}, 'text': '/start %s' % code}})
        Flow = self.env['edu.telegram.flow']
        Flow.start(chat_id='888001', flow='leave', step='d1')
        r1, done1 = flow_feed(self.env, '888001', '20260901')
        self.assertFalse(done1)
        r2, done2 = flow_feed(self.env, '888001', '20260903')
        self.assertFalse(done2)
        r3, done3 = flow_feed(self.env, '888001', '家里有事')
        self.assertTrue(done3)
        lv = self.env['op.leave.request'].search(
            [('student_id', '=', stu.id)], limit=1)
        self.assertTrue(lv.exists())
        self.assertEqual(lv.state, 'submitted')

    def test_unbind_then_guard(self):
        from odoo.addons.edu_telegram.controllers.main import handle_update
        self.Chat.bind_by_code  # 触发模型加载
        chat_id, act = handle_update(self.env, {
            'message': {'chat': {'id': 777001}, 'text': '/成绩'}})
        self.assertIn('绑定', act['text'])
