# -*- coding: utf-8 -*-
"""门户「我的账户」/my/account 的学籍区：学号自助填写（唯一真身 op.student.gr_no）。

=== 2026-09-25：删掉「院系 / 年级 / 学制」三条假标签（旧代码就在本文件）===
本文件原先把 res.partner 的三个**通用**字段改名为学籍字段：
    company_name（公司名称）→「院系」；vat（税号）→「年级」；
    street2（地址第二行）→「学制」，help「即本科、硕士等」
（旧 views/partner_labels.xml 同步把门户地址表单的这三条 label 换成同一套文案。）

实测危害（校长 2026-09-25 截图 + 生产库核对 edu19-prod）：
  · 地址第二行被叫成「学制」⇒ 学生把**城市**填了进去：res_partner 41 行里
    street2 唯一的非空值 = partner 64（王佐）的「台州市」；同页「院系/年级」是两个
    **空文本框**（其中 vat 是税号字段）；
  · 每加一个学籍字段就等于给同一个概念再开一个 owner —— res.partner 上散着学籍，
    与真模型各存一份。

真模型早已存在（院系/学制都是本仓自建，不是新概念）：
    院系 = op.department（经 op.course.department_id）
    学制 = op.program.level（经 op.course.edu_level_id，models/major_track.py:86）
    年级 = 学籍年届 / 班级（op.student.course.academic_years_id / batch_id）
docs/plans/major-track-elective-design.md:152 已把这对同名异义标为「重复 owner」隐患。
⇒ 整块删除（字段改名 + 视图文案）。地址表单回到 Odoo 原生语义；学籍真值改由
  「只读学籍卡」直接读学籍记录显示（views/partner_labels.xml +
  controllers/main.py 的 _prepare_my_account_rendering_values）。

=== 本文件为什么还在（别再删空它）===
1. models/__init__.py 已 import 本模块（删文件要动 __init__.py，而该目录本批次
   另有成员在改）；
2. **学号的唯一写入口**落在这里（见下方 OpStudentEduGrNo）—— 写规则必须与字段
   同址，控制器/单测才共用一份，不会长出第二套。

=== 学号的唯一真身（禁止再造一个）===
op.student.gr_no：openeducat_erp/openeducat_core/models/student.py:93（size=20），
唯一约束 _unique_gr_no 见 :106。它是**身份键**，被三处消费：
  · 评估名册：edu_assess/controllers/portal.py:638/671/701（学号为空则退姓名匹配，
    重名整行报错）；
  · 班级变更预检：edu_portal/controllers/roles.py:1854（按 gr_no 判重）；
  · Telegram 绑定（custom_addons/edu_telegram，本任务禁改）。
⇒ 绝不在 res.partner 上再开学号字段：两处真相必然发散，且会绕开上面的唯一约束。
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)

#: 学号长度上限 = 基座字段的 size（openeducat_core/models/student.py:93）
GR_NO_SIZE = 20


class OpStudentEduGrNo(models.Model):
    """学号（op.student.gr_no）的**门户自助填写**：只在为空时写一次。

    可编辑规则（队长裁定 2026-09-25）：学生**只在学号为空时可填**；填过即只读，
    改动走后台（教务处/管理员）。理由：gr_no 是评估名册 / Telegram 绑定 / 班级变更
    预检共用的唯一身份键，放开自由编辑等于允许甲改填乙的学号去顶替乙的身份
    （成绩、名册、绑定都会记到乙头上）。
    """

    _inherit = 'op.student'

    def edu_portal_fill_gr_no(self, value):
        """门户自助填学号：写入成功 / 无需写入返回 None；否则返回**给人看的中文原因**。

        调用方 = controllers/main.py 的 _create_or_update_address 覆盖（门户地址表单
        POST /my/address/submit）。那里把返回值塞进 Odoo 门户地址表单的错误协议
        {'invalid_fields': [...], 'messages': [...]}（core portal/controllers/portal.py:540-546；
        前端 portal/static/src/interactions/address.js:167-186 渲染成红字），
        ⇒ **本方法绝不 raise**：门户上抛异常就是一张 traceback 500，学生既看不懂
        也不知道下一步该找谁。
        """
        self.ensure_one()
        value = (value or '').strip()
        if not value:
            return None                       # 空的提交 = 这次没填，不算错
        current = (self.gr_no or '').strip()
        if current == value:
            return None                       # 幂等：只读字段原样回传时不得报错
        if current:
            return ('学号已设置（%s），学生端不能自行修改；如需更改请联系教务处。'
                    % current)
        if len(value) > GR_NO_SIZE:
            return ('学号最多 %d 个字符（这次填了 %d 个），请核对后再保存。'
                    % (GR_NO_SIZE, len(value)))
        dup = self.sudo().search(
            [('id', '!=', self.id), ('gr_no', '=', value)], limit=1)
        if dup:
            return ('学号「%s」已被其他同学使用，请核对后再保存；'
                    '若确信无误请联系教务处。' % value)
        try:
            # savepoint：唯一约束的**并发**窗口（预检通过、写入时别人恰好先写）
            # 只回滚这一笔，不污染整次请求的事务（否则门户整页 500，学生这次
            # 改的地址也一起白填）。
            with self.env.cr.savepoint():
                self.sudo().write({'gr_no': value})
        except Exception:                     # noqa: BLE001 - 任何写入失败都给人话
            _logger.warning('[edu_portal] 学号写入失败 student=%s gr_no=%r',
                            self.id, value, exc_info=True)
            return ('学号「%s」保存失败（可能刚被占用），请稍后重试或联系教务处。'
                    % value)
        # 留痕：本仓身份类写入的既有机制 = edu.audit.log（同口径先例见
        # models/registration.py:240 的「选课审批」、models/class_batch.py:124）。
        # _log 自身失败只告警、绝不阻断业务（models/audit.py:30-41）。
        self.env['edu.audit.log'].sudo()._log(
            '学号自助填写', 'op.student', self.id, self.name or '',
            '学号（空）→ %s（门户 /my/account 学生自助填写）' % value)
        return None
