# -*- coding: utf-8 -*-
"""基座 openeducat_parent 五处缺陷的在仓覆盖（任务 G 两处 + 任务 H 三处，2026-09-17）。

## 为什么在这里修

基座 openeducat_erp/ 是官方源码只读快照（铁律：一个字节都不改），所以只能在本仓
用 _inherit 覆盖。承载模块选 **edu_portal**：op.parent / op.student 的档案与门户关联
本来就是它的地盘（同模块 models/invite_code.py:470/486 已经各有一层 _inherit，
家长端 /my/child、通讯录重绑、以及家长档案 ACL 都在这里）。

## 覆盖的是什么（基座 openeducat_parent/models/parent.py，版本 19.0.1.0）

1. OpParent.create（基座 49-105 行）——**新建伙伴分支**把 mobile 写进了不存在的
   op.parent.phone（基座第 93 行 vals['phone'] = parent_mobile）。op.parent 只有
   mobile（同文件第 33 行），于是 super().create() 抛
   ValueError: Invalid field 'phone' in 'op.parent'（odoo/orm/models.py:4654）。
   触发条件：name 传字符串且 name/email/phone 三路都搜不到已有 res.partner
   （即下面 else 分支）。管理员同样炸 —— 该分支先于任何权限判定。
   ⇒ 覆盖后只把这一处改成 vals['mobile'] = parent_mobile（与上一行 vals['email'] 对称，
   正是基座作者的原意；mobile 是 op.parent 自己的字段）。

2. OpStudent.unlink（基座 203-210 行）——删学生时对家长侧门户关联做清理，但用了
   无保护的 list.remove()：基座第 208 行 child_ids.remove(record.user_id.id)。
   当学生没有门户账号（record.user_id.id is False）、或家长没有 op.parent.user_id
   （列表为空）、或该学生本就不在列表里时，抛
   ValueError: list.remove(x): x not in list，**整条删除动作失败**。
   门户账号对学生是可选字段（本地 4 名学生里有 3 名没有），所以「删有家长的学生」几乎必炸。
   ⇒ 覆盖后加一条成员判定：只有确实在列表里才 remove + 回写；不在列表里 = 本来就没有
   这条关联，无需清理（同时避免拿空列表去清别人 child_ids 的破坏性回写）。
   清理语义不变：该清的时候照旧清（回写目标见第 5 条，任务 H 统一到 parent.user_id）。

### 任务 H 追加的三处（同一个文件，不另开第二个覆盖同一方法的文件——MRO 会打架）

3. OpParent.create 的「找已有伙伴」模糊搜索（基座 68-73 行）——**已经造成数据污染**的
   主缺陷。域是 `name OR email OR phone`，而 email / mobile 传空时
   `('email','=',None)` / `('phone','=',None)` 会退化成「该字段为空的任意伙伴」
   ⇒ 与请求毫不相干的联系人被认领：base 给它写 `is_parent=True`、回填手机号/邮箱，
   `op.parent` 也挂到它身上（数据污染），第二次再撞 `unique(name)` → UniqueViolation。
   本地实测：`op.parent.create({'name': '张三', ...})` 不传 email/mobile 时，命中库里
   第一条无邮箱伙伴（实测 canary `!。【临时·冒烟H】…`、真实库里是 Administrator id=3），
   它被写 `is_parent=True phone='13100000001'`，op.parent.name 指向它。
   ⇒ 覆盖后只改这一处：**空值不参与搜索**（email/mobile 为空就不加那一条），
   三条都为空时**不搜索**、直接走「新建伙伴」分支。有值时域与基座同形、语义不变。

4. OpStudent.write 末段（基座 195-199 行）——读 `parent_id.user_id.child_ids`、
   却写 `parent_id.name.user_id.child_ids`。两个 user 不同时，学生账号挂到**别的账号**
   上；家长真正的登录账号（`op.parent.user_id`）反而拿不到这条关联。
   ⚠ Odoo 19 的 `res.partner.user_id` 是「销售员」字段（core res_partner.py:229-236
   "Warning: user_id is a Salesperson, not the inverse of partner_id in res.users"），
   不是伙伴的登录账号：本地实测新建门户账号后 `partner.user_id` 仍是 False ⇒ 基座这条
   写在真实数据上多半是**静默丢失**（写空 recordset），偶尔才落在别的（销售员）账号上。
   ⇒ 覆盖后统一到 `parent_id.user_id`（家长登录账号的规范字段，见下）；家长没有账号时
   跳过（没有 child_ids 可同步），不回头去写 name.user_id。

5. OpStudent.unlink（基座 203-210 行）与 4 同型：207 读 `parent_id.user_id`、
   209 写 `parent_id.name.user_id`。两个 user 不同时，清理落到别的账号上——家长账号
   留着已删学生的僵尸关联，而另一个账号的 child_ids 被整体 REPLACE 清空（丢兄弟）。
   ⇒ 覆盖后回写目标与 207 行的读同源（`parent_id.user_id`）。

   `op.parent.user_id` 为什么是「家长登录账号的规范字段」：门户按它认家长
   （controllers/downloads.py:149、ical.py:62 `search([('user_id','=',uid)])`）、
   绑人码/邀请码也写它（models/invite_code.py:309、343），本文件 create 末尾与
   OpParent.write/unlink 同样写它。

   复现/对照脚本：`tests/smoke/parent_link_identity.py`（改前 12 条 FAIL = 复现，
   改后全 PASS）。

## 实现细节（改的时候别踩）

本层在 MRO 里位于基座那一层**之上**（edu_portal 在 openeducat_parent 之后加载，
op.parent 现在的 MRO 形如
edu_portal… → openeducat_parent.models.parent.OpParent → odoo.orm.models.Model），
所以复制体**不能**用裸 super() 结尾 —— 那会再次执行基座那套有缺陷的代码。
三处都写成 super(基座类, self).create/write/unlink(...)：从 MRO 里**基座那一层之后**继续，
等价于基座自己 super(OpStudent, self).unlink() 的效果（不吞掉其它层的实现）。
（OpStudent.write 是任务 H 新增的覆盖层，同样从基座那一层之后继续。）

⚠ 基座升级时要回来逐行对拍：本文件的方法体是基座方法体的**逐字副本**（只改了上面五处，
其余包括「已有伙伴」分支的 is_parent/email/phone 回填、OpStudent.write 里 parent_ids 那两段
（含 193 行无保护 remove）、child_ids 同步、self.env.registry.clear_cache() 之类都不动）。
"""
from odoo import api, models

# 基座那一层（只读快照）。显式引用它，才能从 super() 链里「跳过它自己」——
# 见模块 docstring「实现细节」。这也是本模块在 manifest 里声明 openeducat_parent 的原因。
from odoo.addons.openeducat_parent.models.parent import OpParent as _BaseOpParent
from odoo.addons.openeducat_parent.models.parent import OpStudent as _BaseOpStudent


class OpParent(models.Model):
    _inherit = 'op.parent'

    @api.model_create_multi
    def create(self, vals_list):
        # 下方方法体 = 基座 openeducat_parent/models/parent.py:49-105 的逐字副本，
        # 唯一改动：第 93 行 vals['phone'] → vals['mobile']（基座缺陷，见模块 docstring）。
        for vals in vals_list:
            partner_id = vals.get('name')
            parent_email = vals.get('email')
            parent_mobile = vals.get('mobile')

            if isinstance(partner_id, int):
                partner = self.env['res.partner'].browse(partner_id)
                if partner.exists():
                    update_vals = {'is_parent': True}
                    if parent_email and not partner.email:
                        update_vals['email'] = parent_email
                    if parent_mobile and not partner.phone:
                        update_vals['phone'] = parent_mobile
                    partner.write(update_vals)
                    continue

            parent_name = vals.get('name')
            # ↓ 基座 68-73 行原样是「name OR email OR phone」搜已有伙伴。email / mobile
            #   为空时，('email','=',None) / ('phone','=',None) 退化成「该字段为空的任意
            #   伙伴」⇒ 与请求毫无关系的联系人被认领成家长：它被写 is_parent=True、被回填
            #   手机号/邮箱，op.parent 也挂到它身上；第二次再撞 unique(name)（UniqueViolation）。
            #   复现见 tests/smoke/parent_link_identity.py ①。
            #   修法（任务 H）：**空值不参与搜索**；三条都为空时干脆不搜索，直接走下面的
            #   「新建伙伴」分支 —— 绝不退化成「匹配任意记录」。有值时语义与基座一致。
            criteria = []
            if parent_name:
                criteria.append(('name', '=', parent_name))
            if parent_email:
                criteria.append(('email', '=', parent_email))
            if parent_mobile:
                criteria.append(('phone', '=', parent_mobile))
            if criteria:
                # ['|'] * (n-1) + leaves = 基座 OR 域的同形写法（n=3 时即 ['|','|',...]）
                partner = self.env['res.partner'].search(
                    ['|'] * (len(criteria) - 1) + criteria, limit=1)
            else:
                partner = self.env['res.partner']

            if partner:
                update_vals = {'is_parent': True}
                if parent_email and not partner.email:
                    update_vals['email'] = parent_email
                if parent_mobile and not partner.phone:
                    update_vals['phone'] = parent_mobile
                partner.write(update_vals)

                vals['name'] = partner.id
            else:
                new_partner = self.env['res.partner'].create({
                    'name': parent_name,
                    'email': parent_email,
                    'phone': parent_mobile,
                    'is_parent': True,
                })
                vals['name'] = new_partner.id
                vals['email'] = parent_email
                # ↓ 基座此处写的是 vals['phone']，而 op.parent 没有该字段（只有 mobile）。
                #   这正是「新建家长必炸」的根因，且先于任何权限判定（管理员同样失败）。
                vals['mobile'] = parent_mobile

        res = super(_BaseOpParent, self).create(vals_list)

        for record in res:
            if record.student_ids and record.name.user_id:
                user_ids = [s.user_id.id for s in record.student_ids if s.user_id]
                record.user_id.child_ids = [(6, 0, user_ids)]

            if record.name and not record.name.is_parent:
                record.name.is_parent = True

        return res


class OpStudent(models.Model):
    _inherit = 'op.student'

    def write(self, vals):
        # 下方方法体 = 基座 openeducat_parent/models/parent.py:178-201 的逐字副本，
        # 唯一改动：末段（基座 195-199）把「读 parent.user_id / 写 parent.name.user_id」
        # 统一成同一个 user（基座缺陷，见模块 docstring 第 4 条）。
        res = super(_BaseOpStudent, self).write(vals)
        if vals.get('parent_ids', False):
            user_ids = []
            if self.parent_ids:
                for parent in self.parent_ids:
                    if parent.user_id:
                        user_ids = [parent.user_id.id for parent in parent.student_ids
                                    if parent.user_id]
                        parent.user_id.child_ids = [(6, 0, user_ids)]
            else:
                user_ids = self.env['res.users'].search([
                    ('child_ids', 'in', self.user_id.id)])
                for user_id in user_ids:
                    child_ids = user_id.child_ids.ids
                    child_ids.remove(self.user_id.id)
                    user_id.child_ids = [(6, 0, child_ids)]
        if vals.get('user_id', False):
            for parent_id in self.parent_ids:
                # ↓ 基座 197 读 parent_id.user_id、199 却写 parent_id.name.user_id：
                #   两个 user 不同时，学生账号会挂到别的账号上（复现见
                #   tests/smoke/parent_link_identity.py ③）。统一到 op.parent.user_id——
                #   它才是家长的登录账号（门户按它认家长：controllers/downloads.py:149、
                #   ical.py:62；也跟本文件 create 末尾、OpParent.write/unlink 的写法一致）。
                #   Odoo 19 的 res.partner.user_id 是「销售员」字段（core res_partner.py
                #   229-236），不是伙伴的登录账号，所以不做回退写它。
                parent_user = parent_id.user_id
                if not parent_user:
                    # 家长没有门户账号 ⇒ 没有 child_ids 可同步（不是「丢一次回写」）
                    continue
                child_ids = parent_user.child_ids.ids
                child_ids.append(vals['user_id'])
                parent_user.child_ids = [(6, 0, child_ids)]
        self.env.registry.clear_cache()
        return res

    def unlink(self):
        # 下方方法体 = 基座 openeducat_parent/models/parent.py:203-210 的逐字副本，
        # 两处改动（均为基座缺陷，见模块 docstring 第 2/5 条）：
        #   ① remove 前加成员判定；
        #   ② 回写目标由 parent_id.name.user_id 统一成 parent_id.user_id（与 207 行的读同源）。
        for record in self:
            if record.parent_ids:
                for parent_id in record.parent_ids:
                    child_ids = parent_id.user_id.child_ids.ids
                    student_uid = record.user_id.id
                    # 基座原样是 child_ids.remove(record.user_id.id)：
                    # 学生没门户账号时它是 False、家长没账号时列表为空、学生本就不在列表里时
                    # 抛 ValueError: list.remove(x): x not in list，整条删除失败。
                    # 不在列表里 ⇒ 本来就没有这条关联要清，无需 remove、也不必回写
                    # （基座那种「无条件回写」在这里还会用空列表清掉别人 child_ids）。
                    if student_uid and student_uid in child_ids:
                        child_ids.remove(student_uid)
                        # 基座 209 行写的是 parent_id.name.user_id：读 A 写 B，
                        # 两个 user 不同时清理落到别的账号上（复现见 ⑤），
                        # 家长真正的账号反而留着已删学生的僵尸关联。
                        parent_id.user_id.child_ids = [(6, 0, child_ids)]
        return super(_BaseOpStudent, self).unlink()
