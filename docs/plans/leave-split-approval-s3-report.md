# S3 交付报告：请假拆分 + 分级审批 + 转交（控制器与门户）
> **状态**：`归档` ｜ **主题**：`请假分级审批` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「未 commit」，实际已于 `2fe14e9` 提交（2026-09-26 核对发现）。正文未改动。

> 分工：实现子代理 **S3**。规格书（唯一标准）`docs/plans/leave-split-approval-design.md`，
> 本报告对应 §3.3 / §4.3(2)(4) / §4.4 / §7.1 / §7.5 / §8。
> 环境：本地 edu19（docker compose 栈），时间 2026-09-24 18:2x。**未 commit**；只 `git add` 了自己这 4 个文件。

## 0. 结论

**S3 完成。** 两条新门户路由、`/my/time_off` 三向分流、§8.2 扩域、`_leave_steps()` 二级档、
`/leave/set_state(_bulk)` 接 S2 分级动作与 §4.3(2) 判据全部落地并实测：
`ux_v3_route_matrix.py` 495/495 PASS（EXIT=0）、`check_live_registry.py` 0 DARK（EXIT=0）、
`check_english.py` must-fix **0**（仅剩 1 条家长 303 的 ROUTE-BAD，按队长裁决由 S5 登记）。

## 1. 接口与规格不一致（**大字留档**，防联调扯皮）

1. **转交**：设计稿 §10 写 `transfer()`，队长清单写 `action_transfer` ⇒ S2 两个名字都提供；
   我在控制器里**两个名字都兼容取用**（`action_transfer` 优先、`transfer` 兜底），只调用不实现。
2. **路由函数**：设计稿 §3.2 写模块级 `route_of(leave)`，队长清单写 `edu.leave.route_of(self)` ⇒ S2 两种都有；
   门户侧**不需要** route_of（提交时快照在 S2 的 `create()` 里做），未受影响。
3. **`/my/time_off` 的落点与设计稿 §9.2 不一致**：§9.2 把「`/my/time_off` 身份分流」记在 `controllers/roles.py`，
   真实路由却在 **`controllers/batch3.py`**。我在**原路由就地分流**，**没有**新增同 path 的第二条路由 ——
   Odoo 里同 path 双路由会按注册顺序随机遮蔽既有学生页，绝不能这么干。
4. `/leave/set_state` 我**新增接受一个动作值 `send_back`**（§3.1 二级退回一级；设计稿只给了动作、没给路由，
   而本路由是门户唯一审批入口）。既有的 `approved` / `refused` 参数与回跳语义一字不变。
5. `check_english` 对「家长 303 → `/my/child`」报 `ROUTE-BAD 非 200 且未登记`：**这是有意行为**（队长裁决：
   不得改成 200），登记进路由表/EXEMPT 归 S5。

## 2. `controllers/roles.py` 的完整追加段（逐字，文件末尾）

```python
# ===========================================================================
# S3 —— 请假拆分 + 分级审批 + 转交：门户动作面（**本段只追加**）
#
# 设计：docs/plans/leave-split-approval-design.md
#   §3.3 空值行为（没有班主任也能跑）/ §4.3(1)(2)(3)(4) 转交四规则与四层留痕 /
#   §4.4 转交动作面 / §7.1 销假（正交字段，不改 state）/ §7.5 事后补假硬拒（门户侧）/
#   §8 权限矩阵（§8.1 谁能批/谁能转、§8.2 扩域）
#
# 本段对**既有函数**的改动只有下面这几处（其余一字不动）：
#   1) approval_scope_domain(env)：§8.2 请假侧并集（first/second_approver_id）；
#      caller（scoped_record / scoped_records / _approval_scope_domain）把
#      自己的 model_name 传下来，申诉侧显式走 'edu.grievance' 老域。
#   2) leave_approvals / leave_detail / leave_set_state / leave_set_state_bulk 的
#      **准入行**：放宽为 leave_portal_approver()（多一档「本级应批人是我」）。
#      依据 §3.3：op.batch.homeroom_teacher_id 存的是 res.users，而本仓
#      op.faculty 0 个在职行 ⇒ 班主任可以没有教师档案；不放宽则
#      「老师到位后只填数据即生效」跑不通（最主要的使用者进不来）。
#   3) leave_set_state / leave_set_state_bulk 的**执行行**：交给 S2 的冻结动作
#      （一级/二级按当前 state 自动分流，见 _leave_flow_apply_state）；
#      leave_set_state 另接受 new_state=='send_back'（§3.1 二级退回一级）。
#   4) _leave_steps：加 'pending_second' 一档（§3.1）。
#   5) leave_detail：state_label 多一档 + 给模板传 transfer_users / leave_stage。
#   6) child_leave_save：§7.5 门户侧硬拒（学生侧同判据，落在 batch3.py）。
#
# ⚠ 与 S2 的接口约定（**只调用，不实现**）：edu.leave 上的
#   can_user_act / action_first_approve / action_second_approve / action_refuse /
#   action_send_back / action_transfer / action_confirm_return / transfer_candidates
#   （route_of 归模型内部使用，门户侧不需要）。一律经 leave_flow_action() 取用：
#   拿到 ⇒ 走 S2；拿不到 ⇒ fail-closed（不写字段、不猜语义）。唯一例外是
#   leave_set_state 的 approved/refused —— 那里回退到本文件原有的直写实现
#   （逐字保留），保证 S2 落地前后既有功能零回归。
#
# ⚠ 留痕归属（队长 2026-09-25 裁决）：S2 的动作**内部已含**审计与通知
#   （action_transfer = 转交行 + 改写应批人 + 「请假审批转交」审计 + 三方通知；
#   action_first/second_approve / action_refuse = 状态 + 审批留痕 +
#   「请假审批」审计 + 申请人通知）⇒ 控制器**一律不重复写**，只在回退路径补。
#
# ⚠ 命名不一致（留档，防联调扯皮）：设计稿 §10 写 transfer()、§3.2 写模块级
#   route_of(leave)；队长清单写 action_transfer / edu.leave.route_of(self)。
#   本段对转交**两个名字都兼容**（action_transfer 优先，transfer 兜底）。
# ===========================================================================

# 身份反查唯一口径：本段要用「档案 → 账号」的反向并集（§4.3(1)② 判「是不是
# 申请人本人」、§7.1 判「是不是本人/家长」）。文件顶部那条 import 只带了正向
# 反查，故在此**追加**一个 import，不改既有 import 行（# noqa: E402：本仓先例
# main.py:338 也是非顶部 import）。
from odoo.addons.edu_schedule.models.identity import users_of_profile  # noqa: E402


# ---------------------------------------------------------------------------
# 判据层（唯一事实源；路由与模板都从这里取）
# ---------------------------------------------------------------------------
def leave_applicant_kind(env=None):
    """当前登录账号的请假身份（§5.3 唯一口径）：'student' / 'parent' / 'staff'。

    判定只走 edu_schedule/models/identity.py 的**双向并集**反查：
      · op.student 非空      ⇒ 'student'（学生在 /my/time_off 看到学生单）
      · 否则 op.parent 非空  ⇒ 'parent'（家长为孩子请假，**不是**教职单）
      · 两者皆空             ⇒ 'staff'（教职单）
    **不依赖 op.faculty 存在**、**不看 share**：本仓 teacher@local 正是门户账号
    且 share=True，用 share 判会把它错判成学生（§5.3 的显式反例）。
    """
    env = request.env if env is None else env
    if profile_of_user(env, 'op.student'):
        return 'student'
    if profile_of_user(env, 'op.parent'):
        return 'parent'
    return 'staff'


def leave_stage_of_state(state):
    """单据当前处于哪一级（§3.1）：request → 一级；pending_second → 二级。

    其它状态（approved/refused）**没有待批级** ⇒ 返回 None（转交与审批都按
    「不在该级」处理）。这是「我能不能批这一级」的唯一入口。
    """
    return {'request': 'first', 'pending_second': 'second'}.get(state or '')


def leave_portal_approver(env=None):
    """教师侧请假页的准入判据（§8.1）：有教师档案 ∪ privileged_staff ∪ 有我的待批单。

    最后一档是 §3.3 硬要求的落点：「没有班主任也能跑」「老师到位后只填数据即
    生效」—— op.batch.homeroom_teacher_id 存的是 res.users，而本仓 op.faculty
    0 个在职行，班主任完全可能没有教师档案。沿用「无教师档案 ⇒ 回 /my/home」
    的老门槛，会让这批人连队列都进不去（功能对最主要的使用者静默失效）。
    """
    if privileged_staff():
        return True
    if current_faculty():
        return True
    env = request.env if env is None else env
    return bool(env['edu.leave'].sudo().search_count(
        ['|', ('first_approver_id', '=', env.uid),
         ('second_approver_id', '=', env.uid)]))


def leave_applicant_users(leave):
    """本单申请人名下的登录账号（§4.3(1)② / §7.1 的判据；**不用 partner**）。

    · 学生单：student_id → 账号（identity.py 的「档案 → 账号」三条来源并集）；
    · 教职单：applicant_user_id 本身。
    判「是不是申请人本人」必须用这个集合：同一 partner 可能挂多个账号，也可能
    挂着程序化创建的账号，用 partner 判会漏（本仓身份反查踩过两次）。
    """
    users = leave.env['res.users'].sudo().browse()
    if leave.student_id:
        users |= users_of_profile(leave.student_id.sudo())
    if leave.applicant_user_id:
        users |= leave.applicant_user_id.sudo()
    return users


def leave_backdated_guard(raw_date):
    """§7.5 门户侧硬拒判据：date_from < 提交日 ⇒ True。

    边界（设计稿逐字）：**今天请假、今天提交**（date_from == today）允许 ——
    只有严格早于今天才算「事后补假」。解析失败返回 False（交给既有日期解析
    分支处理，不抢它的活）。
    """
    try:
        day = fields.Date.to_date(raw_date) if raw_date else None
    except Exception:
        return False
    return bool(day) and day < fields.Date.today()


def leave_flow_action(rec, name):
    """取 S2 在 edu.leave 上的冻结动作；**没有就返回 None**（调用方必须 fail-closed）。

    为什么要这个薄壳：接口是**并行开发**的冻结契约，控制器不能假设它一定已经
    落地（否则升级窗口里一按按钮就是 500）。取不到 = 功能不可用 = 什么字段都
    不写（绝不猜语义、绝不自己实现一份模型逻辑）。
    """
    fn = getattr(rec, name, None)
    return fn if callable(fn) else None


def leave_transfer_candidates(rec, stage):
    """§4.3(1)：这一级的**合法转入人**（res.users），S2 冻结接口的输出。

    接口未就绪 / 抛错 ⇒ 空集（= 转交入口隐藏、POST 也会被挡）：绝不 fail-open
    到「谁都能转」。再叠一层 §4.3(1)①② 的控制器侧过滤（自己、申请人本人）——
    候选集合的口径在模型（唯一事实源），控制器只做**收窄**不做放大。
    """
    empty = rec.env['res.users'].sudo().browse()
    if not stage:
        return empty
    fn = leave_flow_action(rec, 'transfer_candidates')
    if not fn:
        return empty
    try:
        users = fn(stage)
    except Exception:
        _logger.warning('edu_portal: transfer_candidates(%s) 调用失败，'
                        '转交入口按不可用处理', stage, exc_info=True)
        return empty
    users = (users or empty).sudo()
    banned = set(leave_applicant_users(rec).ids) | {rec.env.uid}
    return users.filtered(lambda u: u.id not in banned)


def _leave_can_act(rec, user, stage=None):
    """§8.1：我能不能批这一单的**当前这一级**。

    优先 S2 的冻结接口 can_user_act(user)（它内含 privileged_staff 恒可批的
    既有例外）；接口缺席时退到 §8.1 的逐字判据
    （user == 当前级 approver_id **or** privileged_staff()）。
    两条路都 fail-closed：判不出来就是「不能」。
    """
    fn = leave_flow_action(rec, 'can_user_act')
    if fn:
        try:
            return bool(fn(user))
        except Exception:
            _logger.warning('edu_portal: can_user_act 调用失败，按无权处理',
                            exc_info=True)
            return False
    if privileged_staff():
        return True
    field = {'first': 'first_approver_id',
             'second': 'second_approver_id'}.get(
                 stage or leave_stage_of_state(rec.state) or '')
    if not field:
        return False
    approver = rec[field]
    return bool(approver and user and approver.id == user.id)


def _leave_can_transfer(rec, user, stage):
    """§4.4：谁能转交 —— **严格**是「本单当前这一级的应批人」本人。

    ⚠ 刻意**不含** privileged_staff 例外：§8.1 把「转交」单列一行，判据是
    user 属于 {first_approver_id, second_approver_id}。教务处/系统组「恒可批」，
    但转交是把自己的待办让渡出去，不等于可以把别人的待办转走。

    优先 S2 的冻结实现 can_user_transfer(user)（它还多查「该级是否已转过」）；
    缺席时用本函数下方的逐字判据（fail-closed）。
    """
    fn = leave_flow_action(rec, 'can_user_transfer')
    if fn:
        try:
            return bool(fn(user))
        except Exception:
            _logger.warning('edu_portal: can_user_transfer 调用失败，按不可转处理',
                            exc_info=True)
            return False
    field = {'first': 'first_approver_id',
             'second': 'second_approver_id'}.get(stage or '')
    if not field or not user:
        return False
    approver = rec[field]
    return bool(approver and approver.id == user.id)


def leave_portal_context():
    """门户自助提交标记（§7.5）：S2 的 _portal_submission() 优先看这个 context。

    为什么必须带上：判据的兜底是「创建者不是特权账号」，而**教务/管理员本人**
    在门户里提交时是特权账号 —— 不带这个标记，他的单会被模型当成「后台代录」
    通道（backfilled=True），§7.5 的硬拒在他身上静默失效。
    """
    try:
        from odoo.addons.edu_portal.models.leave_flow import CTX_PORTAL
        return {CTX_PORTAL: True}
    except Exception:
        return {}


def leave_proof_kind(post):
    """§7.2 的证明方式（表单字段 → 模型 selection，非法值一律 'none'）。"""
    kind = (post.get('proof_kind') or '').strip()
    return kind if kind in ('file', 'oral', 'none') else 'none'


def leave_proof_vals(post):
    """§7.2：门户证明字段 → create 的 vals（S2 的 create 校验读的就是这三个）。"""
    return {
        'proof_kind': leave_proof_kind(post),
        'oral_proof_by': (post.get('oral_proof_by') or '').strip()[:64] or False,
        'oral_proof_relation': (post.get('oral_proof_relation') or '').strip()[:32]
                               or False,
    }


def leave_attach_proof_file(leave, post):
    """§7.2 文件证明：把门户上传的文件落成 ir.attachment(res_model/res_id)。

    为什么只能在**建单后**落库：attachment_ids 是 o2m 到 ir.attachment 的
    （res_id 指向已存在的单据）—— 建单那一刻必然还是空的。
    """
    import base64
    upload = post.get('proof_file') or post.get('attachment')
    if not upload or not getattr(upload, 'filename', None):
        return None
    try:
        data = upload.read()
    except Exception:
        _logger.warning('edu_portal: 证明附件读取失败 leave=%s', leave.id,
                        exc_info=True)
        return None
    if not data:
        return None
    return leave.env['ir.attachment'].sudo().create({
        'name': upload.filename,
        'datas': base64.b64encode(data),
        'res_model': 'edu.leave',
        'res_id': leave.id,
    })


def leave_check_proof(leave):
    """调 S2 的附件复核（§7.2：proof_kind='file' 却一个附件都没有 ⇒ UserError）。

    S2 的 docstring 明确「S3/S4 在上传完成后调用本方法」—— 动作缺席时跳过
    （不 500；证明校验的最终责任仍在模型侧）。
    """
    check = leave_flow_action(leave, '_check_proof_attachments')
    if check:
        return check()
    return None


def _leave_flow_notice(text, back='/leave/approvals'):
    """带用户可见提示的回跳（复用既有 ?bulk_msg= 回执位，模板已渲染）。"""
    return '%s%cbulk_msg=%s' % (back, '&' if '?' in back else '?',
                                quote(text[:200]))


def _leave_flow_apply_state(rec, new_state, reason, was_pending=None):
    """把门户的「同意 / 驳回 / 二级退回」落到 S2 的冻结动作上（§3.1 状态机）。

    为什么必须有这一层（而不是在路由里直接 write state）：
      · 一级通过后到底是 approved 还是 pending_second，由 need_second
        （§3.2 route_of + §7.4 over_quota）决定 —— 那是**模型**的判定，
        控制器复制一份必然走样（4 天的单会被直接终审）；
      · 二级退回（pending_second → request）只有模型知道
        second_sent_back_at / second_send_back_reason 与清空 second_approver_id。
    动作内部守卫是 fail-loud（state 不匹配抛 UserError）⇒ 本函数不吞异常，
    让错误如实暴露，而不是静默 no-op。

    返回值：'action'（已由 S2 动作执行：状态 + 审批留痕 + 审计 + 通知都归它）/
    'legacy'（回退既有直写，并在 was_pending 时补既有通知）/ 'noop'。
    """
    if new_state == 'send_back':
        fn = leave_flow_action(rec, 'action_send_back')
        if not fn:
            return 'noop'            # 'send_back' 不是状态值 ⇒ 没有动作就绝不写
        fn(reason)
        return 'action'
    if new_state == 'approved':
        name = 'action_second_approve' if rec.state == 'pending_second' else 'action_first_approve'
    else:
        name = 'action_refuse'
    fn = leave_flow_action(rec, name)
    if fn:
        if new_state == 'refused':
            fn(reason)
        else:
            fn()
        return 'action'
    # —— S2 动作缺席：逐字沿用本文件既有实现，保证升级窗口内既有功能零回归 ——
    if new_state == 'refused' and reason:
        rec.write({'reject_reason': reason})
    vals = {'state': new_state}
    vals.update(rec._approver_vals())
    rec.write(vals)
    if was_pending:
        rec._notify_applicant(new_state)
    return 'legacy'


# ---------------------------------------------------------------------------
# 门户动作面（§4.4 转交 / §7.1 销假）
# ---------------------------------------------------------------------------
class EduLeaveFlowPortal(http.Controller):
    """请假分级审批的两条新门户路由（S3）。

    两条都是 POST + csrf=True（S4 的表单带 token），并各挂一个 GET 出口：
      · 未登录 GET ⇒ Odoo 的 auth='user' 先接管 ⇒ 303 跳登录（既不是 500，
        也不是 405 —— 探测/误点不会把页面打成错误码）；
      · 已登录 GET ⇒ 303 回跳且**不写任何字段**（不做「GET 也能改状态」的坏事）。
    """

    @http.route('/leave/transfer', type='http', auth='user', website=True,
                methods=['GET', 'POST'], csrf=True)
    def leave_transfer(self, **post):
        """转交审批（§4.3 四条规则 + §4.4 动作面）。

        字段（S4 的表单已写死）：leave_id / stage / to_user_id / reason / next。
        守卫顺序（**每一步都 fail-closed，任何一步不过都不写字段**）：
          ① 越权/不存在 ⇒ 按不存在处理（沿用 scoped_record 的既有口径）；
          ② 当前级由**单据 state** 决定，不信表单的 stage（防伪造）；
          ③ 只有本级应批人**本人**能转（教务处可批但不可替人转，§4.4）；
          ④ 只能转 1 次（入口预检；并发双转由 DB UNIQUE(leave_id, stage) 兜底）；
          ⑤ 转入人必须存在、不是自己、不是申请人、且仍在候选集合内（二次校验）；
          ⑥ 执行 S2 的 action_transfer —— 四层留痕（转交行 / 应批人改写 /
             「请假审批转交」审计 / 三方通知）**全在动作内部**（队长裁决），
             控制器**一律不重复写**；另做一次「转交行是否真落下」的自证。
        """
        back = post.get('next') or ''
        if not back.startswith('/leave/'):
            back = '/leave/approvals'
        if request.httprequest.method != 'POST':
            return request.redirect(back)
        env = request.env
        try:
            lid = int(post.get('leave_id', 0))
        except (TypeError, ValueError):
            lid = 0
        reason = (post.get('reason') or '').strip()[:500]
        if not reason:
            return request.redirect(_leave_flow_notice(
                '转交必须填写原因（留痕三要素：谁转给谁、何时、为什么）'))
        rec = scoped_record(env, 'edu.leave', lid)
        if not rec.exists():
            return request.redirect(back)
        stage = leave_stage_of_state(rec.state)
        posted_stage = (post.get('stage') or '').strip()
        if not stage or (posted_stage and posted_stage != stage):
            return request.redirect(_leave_flow_notice(
                '该单据当前不在你提交的审批级上，页面已刷新'))
        if not _leave_can_transfer(rec, env.user, stage):
            return request.redirect(back)
        Transfer = env['edu.leave.transfer'].sudo()
        if Transfer.search_count([('leave_id', '=', rec.id),
                                  ('stage', '=', stage)]):
            return request.redirect(_leave_flow_notice(
                '该单据该级已转交过 1 次，不能再次转交'))
        raw_to = post.get('to_user_id')
        Users = env['res.users'].sudo()
        to_user = Users.browse(int(raw_to)) if str(raw_to or '').isdigit() else Users.browse()
        if not to_user.exists() or to_user.id == env.user.id:
            return request.redirect(_leave_flow_notice(
                '不能转交给自己，请重新选择转入人'))
        if to_user.id in leave_applicant_users(rec).ids:
            return request.redirect(_leave_flow_notice('不能转交给申请人本人'))
        candidates = leave_transfer_candidates(rec, stage)
        if not candidates or to_user not in candidates:
            return request.redirect(_leave_flow_notice(
                '该账号不在本级合法转入人范围内，请重新选择'))
        action = (leave_flow_action(rec, 'action_transfer')
                  or leave_flow_action(rec, 'transfer'))
        if not action:
            _logger.warning(
                'edu_portal: 转交动作未就绪（edu.leave.action_transfer 缺失），'
                '已 fail-closed：leave=%s 未写任何字段', rec.id)
            return request.redirect(_leave_flow_notice('转交功能尚未就绪，请稍后再试'))
        rec_id, rec_name = rec.id, rec.name or ''
        from_user = env.user
        try:
            action(to_user, reason)
        except pg_errors.UniqueViolation:
            # §4.3(3)：并发双转撞 UNIQUE(leave_id, stage) ⇒ 整事务回滚后再回队列
            # （REPEATABLE READ 下必须结束当前事务，否则重查永远看不见对手；
            #  本仓同款先例 edu_tg_bind/models/tg_claim.py）
            env.cr.rollback()
            env.invalidate_all(flush=False)
            _logger.info('edu_portal: 转交并发冲突（leave=%s stage=%s），已回滚',
                         rec_id, stage)
            return request.redirect(_leave_flow_notice(
                '该单据该级已转交过 1 次，不能再次转交'))
        if not Transfer.search_count([('leave_id', '=', rec_id),
                                      ('stage', '=', stage)]):
            _logger.warning(
                'edu_portal: action_transfer 未落下转交行（leave=%s stage=%s），'
                '按未执行处理', rec_id, stage)
            return request.redirect(_leave_flow_notice('转交未生效，请稍后重试'))
        return request.redirect(back)

    @http.route('/leave/<int:leave_id>/return_confirm', type='http',
                auth='user', website=True, methods=['GET', 'POST'], csrf=True)
    def leave_return_confirm(self, leave_id, **post):
        """销假（§7.1）：学生/家长提交「行程及实践收获」→ 班主任/教务确认。

        同一条路由两跳（S4 的表单）：
          · 提交侧：return_note，判据 = **本人/家长**（不看审批权）；
          · 确认侧：confirm=1，判据 = 本级应批人 or privileged_staff（§8.1），
            执行 S2 的 action_confirm_return（return_confirmed_at/by 由它写）。
        销假是**正交字段**、**不改 state** —— 做成第五个状态会打断既有三档筛选、
        首页计数与 _leave_steps()（§7.1）。两跳都 fail-closed：判不出来就回门户，
        不写任何字段。
        """
        if request.httprequest.method != 'POST':
            return request.redirect('/my/home')
        env = request.env
        try:
            rec = env['edu.leave'].sudo().browse(int(leave_id or 0))
        except (TypeError, ValueError):
            rec = env['edu.leave'].sudo().browse()
        if not rec.exists():
            return request.redirect('/my/home')
        note = (post.get('return_note') or post.get('note') or '').strip()[:2000]
        confirm = str(post.get('confirm') or '') in ('1', 'true', 'True',
                                                     'on', 'yes')
        user = env.user
        is_applicant = user.id in leave_applicant_users(rec).ids
        # 两跳的判据（§8.1）：确认侧 = 本级应批人 or privileged_staff；
        # 提交侧 = 本人/家长。判不出来一律回门户、不写字段。
        if confirm:
            if not _leave_can_act(rec, user):
                return request.redirect('/my/home')
        elif not is_applicant:
            return request.redirect('/my/home')
        action = leave_flow_action(rec, 'action_confirm_return')
        if action:
            # S2 的动作**一个入口两种角色**（申请人写 return_note；审批人写
            # return_confirmed_at/by），留痕、审计与「已到期才能销假」的校验都在
            # 模型里（唯一事实源）⇒ 控制器不重复写任何字段、不重复写审计。
            confirmed = action(note)
            if confirm or confirmed:
                return request.redirect('/leave/approvals')
            return request.redirect('/my/time_off?box=return_submitted')
        # —— 动作缺席（并行开发安全网）：只有「申请人提交说明」这一跳可以按
        #    §7.1 直写 return_note 一个字段；审批人确认那一跳**绝不直写**
        #    （return_confirmed_* 是裁决留痕，只能由模型动作落）——
        if confirm or rec.state != 'approved':
            _logger.warning('edu_portal: action_confirm_return 未就绪，'
                            '销假 fail-closed：leave=%s 未写任何字段', rec.id)
            return request.redirect(_leave_flow_notice(
                '销假功能尚未就绪，请稍后再试', '/my/time_off'))
        rec.write({'return_note': note})
        env['edu.audit.log'].sudo()._log(
            '请假销假', 'edu.leave', rec.id, rec.name or '',
            '提交销假说明%s' % ('：%s' % note[:60] if note else ''))
        return request.redirect('/my/time_off?box=return_submitted')
```


## 3. 对既有函数的 exact diff（逐条给理由）

### 3.1 `approval_scope_domain(env)`（§8.2 扩域 —— 规格里点名允许的那一处）

（另新增模块级 helper `leave_scope_students(env, fac)` = 任教班 ∪ 班主任班的学生，逐字见 §2 之后的文件全量 diff）

```diff
--- a/scope
+++ b/scope
@@ -1,15 +1,43 @@
-def approval_scope_domain(env):
-    """审批作用范围（t34 F3）：教师=任教班级的学生；教务处/管理员不限。"""
+def approval_scope_domain(env, model_name='edu.leave'):
+    """审批作用范围（t34 F3 + §8.2 请假分级）：教务处/管理员不限。
+
+    请假（`model_name='edu.leave'`，默认）= 下面三项的**并集（OR）**：
+      ① 我是这一单**当前一级**应批人（first_approver_id = 我）；
+      ② 我是这一单**当前二级**应批人（second_approver_id = 我）；
+      ③ 我任教班级 ∪ 我当班主任的班的学生提的单（既有 t34 F3 口径 + §8.2 班主任项）。
+    **为什么必须并集**：§4.3(2) 把「我能不能批这一级」的判据从「是不是班主任」
+    换成「是不是本单当前这一级的 first_approver_id / second_approver_id」；
+    而列表 / 批量 / 单条**必须同域**（既有「看得见的 = 能处置的」，
+    见上游 `_approval_scope_domain` 的注释），否则会重现历史缺陷。
+    转交后原审批人 ① 落空 ⇒ 立刻看不见、也就批不了（§4.3(2)）。
+    ⚠ 例外不破：privileged_staff()（教务处组 / 系统组）**恒可批任何单**，
+      故这里第一行就返回「不限」（code-map §6 第 3 条铁律）。
+
+    ⚠ 申诉（model_name='edu.grievance'）**逐字保持 t34 F3 老域**：edu.grievance
+      没有这两个字段，把 OR 项拼进去 search 会直接 ValueError（申诉页 500）。
+      故本函数新增 `model_name` 形参做显式分流：scoped_record/scoped_records 已把
+      它们自己的 model_name 传进来，`_approval_scope_domain` 默认 'edu.leave'
+      （既有请假调用点一字不改），申诉调用点显式传 'edu.grievance'。
+    """
     if privileged_staff():
         return []
     fac = current_faculty()
-    if not fac:
-        return [('student_id', '=', 0)]
-    batches = teacher_taught_batches(env, fac)
-    if not batches:
-        return [('student_id', '=', 0)]
-    students = env['op.student.course'].sudo().search(
-        [('batch_id', 'in', batches)]).mapped('student_id')
-    return [('student_id', 'in', students.ids or [0])]
+    if model_name != 'edu.leave':
+        # 非请假模型：一字不改地保留 t34 F3 行为
+        if not fac:
+            return [('student_id', '=', 0)]
+        batches = teacher_taught_batches(env, fac)
+        if not batches:
+            return [('student_id', '=', 0)]
+        students = env['op.student.course'].sudo().search(
+            [('batch_id', 'in', batches)]).mapped('student_id')
+        return [('student_id', 'in', students.ids or [0])]
+    terms = [('first_approver_id', '=', env.uid),
+             ('second_approver_id', '=', env.uid)]
+    student_ids = leave_scope_students(env, fac)
+    if student_ids:
+        terms.append(('student_id', 'in', student_ids))
+    # OR 前缀（波兰式）：n 项 ⇒ n-1 个 '|'
+    return ['|'] * (len(terms) - 1) + terms
```

### 3.2 `_leave_steps()`（加二级档，规格点名允许的另一处）

```diff
--- a/steps
+++ b/steps
@@ -1,5 +1,15 @@
     def _leave_steps(state):
-        """请假步骤条：已提交 → 审批中 → 已通过/已驳回。"""
+        """请假步骤条：已提交 → 审批中 → 已通过/已驳回（§3.1：二级单多一格）。"""
+        if state == 'pending_second':
+            # §3.1 新增第四态：一级已通过、等二级（教务）审批。
+            # 单独一档而不是复用 request —— 否则「待一级」与「待二级」在
+            # 进度条上分不开，一级审批人会看到自己已经批过的单。
+            return [
+                {'label': '已提交', 'cls': 'ux-step--done'},
+                {'label': '一级已通过', 'cls': 'ux-step--done'},
+                {'label': '待二级审批', 'cls': 'ux-step--current'},
+                {'label': '已通过 / 已驳回', 'cls': 'ux-step--todo'},
+            ]
         if state == 'approved':
             return [
                 {'label': '已提交', 'cls': 'ux-step--done'},
```

### 3.3 其余既有函数（**接口打通 / 判据落地**，都不是新业务逻辑）

完整 `git diff` 见本报告 §6 附录（四个文件全量 staged diff）。逐条说明：

| 既有函数 | 改动性质 | 为什么必须改 |
|---|---|---|
| `scoped_record` / `scoped_records`（模块级） | 1 行/处：把自己的 `model_name` 传给 `approval_scope_domain(env, model_name)` | §8.2 的并集只对 `edu.leave` 成立；`edu.grievance` 没有 `first/second_approver_id`，串用会直接 ValueError ⇒ 申诉页 500 |
| `_approval_scope_domain()`（方法） | 加可选形参 `model_name='edu.leave'` | 让「列表/批量/单条同域」成为同一次函数调用，而不是三套规则 |
| `grievance_approvals()` | 1 行：显式传 `'edu.grievance'` | 申诉侧**逐字保持 t34 F3 老域**（零语义变化） |
| `leave_approvals` / `leave_detail` / `leave_set_state` / `leave_set_state_bulk` 的**准入行** | `not fac and not privileged_staff()` → `not leave_portal_approver()` | §3.3 硬要求「没有班主任也能跑 / 老师到位后只填数据即生效」：`op.batch.homeroom_teacher_id` 存的是 `res.users`，而本仓 `op.faculty` 0 个在职行 ⇒ 班主任可能没有教师档案；老门槛会让他连队列都进不去 |
| `leave_set_state()` 的**执行行** | 直写 state → `_leave_flow_apply_state()`（调 S2 的 `action_first_approve/action_second_approve/action_refuse/action_send_back`）；**动作缺席时逐字回退既有直写** | §3.1：一级通过后是 `approved` 还是 `pending_second` 由 `need_second` 决定 —— 那是模型判定，控制器抄一份必然走样（4 天的单被直接终审） |
| `leave_set_state()` 的**动作判据** | 增加 `and _leave_can_act(rec, env.user)` | §4.3(2)/§8.1：判据 = 本单**当前这一级**的 `first/second_approver_id` 本人（或 privileged_staff 恒可批）。**只靠作用域域不够**：§8.2 的域含「我任教班级 / 我当班主任的班」，转交出去后原审批人**仍看得见**这张单（这是设计的可见性口径），但「能不能批」必须落到快照上 |
| `leave_set_state_bulk()` | 同上两者（用 `actionable` 过滤 + 同一执行函数） | 批量与单条**必须同判据**，否则「转交出去的单被原审批人批量批掉」会绕过 §4.3(2) |
| `leave_detail()` | `state_label` 多一档 `pending_second`；给模板多传 `leave_stage` / `transfer_users` / `can_act` / `can_transfer` | §3.1 第四态必须有中文标签；后四个是 **S4 契约**（S4 已按 `transfer_users`/`leave_stage` 写死模板） |
| `child_leave_save()`（家长路由） | §7.5 硬拒 + §7.2 证明字段转发/附件落库/复核 + §7.5 的 portal context | 规格 §7.5 点名的门户路径之一；§7.2 的转发缺失会让「用户填了口头证明人也被判未提供证明」 |
| `my_time_off` / `my_time_off_save` / `my_time_off_export`（**在 batch3.py**） | 身份分流 + 教职单建单 + §7.5 + §7.2 + 空日期兜底 | §5.3/§8.1：`/my/time_off` 是学生单与教职单的**同一页分流入口**；见 §1.3 的落点说明 |
| `batch1.py` 的 `LEAVE_STATE_LABEL/BADGE`、`views/roles.xml` 的两处 inline 标签表 | 各补 1 档 / 3 个新 code 的中文标签 | 4 态与 7 类型是本次引入的；任何一份手写中文表漏项，页面就直接把**英文 code** 给用户看（实测被 `check_english` must-fix 点名 9 处） |

## 4. 验收与实测原始输出

### 4.0 升级（唯一入口，带串行锁；遇锁 EXIT=2 则 sleep 20 重试）

```
$ bash scripts/safe_upgrade.sh edu_portal
2026-09-24 10:25:32,236 37 INFO edu19 odoo.addons.edu_nav.models.menu_consolidation: [edu_nav] 菜单收口守卫：声明改写 357 条（参数表记为 357）；根菜单 38 条（停用 24）；全库 513 条（停用 179） 
2026-09-24 10:25:32,253 37 INFO edu19 odoo.registry: Registry changed, signaling through the database 
2026-09-24 10:25:32,254 37 INFO edu19 odoo.registry: Registry loaded in 5.745s 
2026-09-24 10:25:32,255 37 INFO edu19 odoo.service.server: Stopping workers gracefully 
[safe_upgrade] 结束：edu_portal（无失败特征；完整日志 /tmp/edu19_upgrade.20260924-182524.log）
EXIT=0
```

### 4.1 `python3 tests/smoke/ux_v3_route_matrix.py`（新路由 x 5 角色）

```
PASS /my/apps    [par] 强断言 303 /my/home  303->/my/home  <- 家长：同上
PASS /my/apps    [fac] 强断言 200 -  200->-  <- 教师：门户宫格入口不变
PASS /my/apps    [bo] 强断言 200 -  200->-  <- 教务：同上

============ 汇总 ============
旧打卡入口强断言（303 + Location 精确）：3 条 / 失败 0
H-1 /my/apps 角色强断言（学生/家长 303 + Location 精确；内部用户 200）：失败 0
检查点 495：PASS 495 / WARN 0 / PENDING 0 / FAIL(真红) 0 / ENV(环境) 0
EXIT=0
```

### 4.2 `python3 tests/smoke/zero_loss_reachability.py`（/my/time_off 卡仍在）

```
L2：出现 27 / 豁免 3 / 缺失 5（共 35 张）
L1：PASS 42 / FAIL 0 / BASELINE-404 1（共 43 条）
L2：缺失 5 → my/fees、my/checkins、my/journals、eval/my、eval/review
L0：类契约失败 0
结论：有 5 项缺失
EXIT=1（见下：5 项缺失全部来自**别人**在 batch2.py 的卡片改动，非本次改动）
```

> **L2 5 项缺失的归属（不是我的改动）**：`my/fees、my/checkins、my/journals、eval/my、eval/review` 是 `controllers/batch2.py` 里未提交的卡片可见性改动造成的 —— 
> `git diff custom_addons/edu_portal/controllers/batch2.py` 明确写着「财务卡：教务/管理员不再渲染费用账单（2026-09-24 合账裁定，展示层过滤）」，
> 以及既有的 `hidden |= {my/checkins, my/journals, eval/my, eval/review}`（非学生身份隐藏）。`/my/time_off` **不在缺失列表**里（L1 也 PASS）。

### 4.3 `python3 scripts/check_live_registry.py`（活体注册表铁律，有 DARK 即 exit 1）

```
字段级：SKIP（fields_get 未返回字段（存在但当前身份不可读：odoo.http.SessionExpiredExcep））—— 库里有 1191 个字段，但本次会话读不到字段定义，**这一项没有被验证**（给 --login/--password 才判）

PASS | edu_* 登记的 95 个模型（字段级本次未验证：匿名会话读不到字段定义）全部存在于跑着的 web 进程（http://127.0.0.1:8069）
EXIT=0
```

### 4.4 `python3 scripts/check_english.py`（动过用户可见文案 ⇒ must-fix 必须 0）

```
TOTAL must-fix = 0 条 / brand = 0 条 / **路由状态违规 = 1 条** / **夹具残留 = 0 条**（其余白名单/数据/主题合计 1774 条，不计失败）
  /my/time_off                     303 ROUTE-BAD 非 200 且未登记 → /my/child
EXIT=2（唯一原因 = 上面那条 ROUTE-BAD：家长 303 → /my/child，按队长裁决等 S5 登记；must-fix 已归零）
```

### 4.5 其它门禁（离线自证）

```
$ python3 scripts/check_manifest_tracking.py
自证：REVISION=v1.0 · 指纹 8406e3d2 · 断言 119 条 · 时刻 2026-09-24 18:26:50
契约：exit 0=OK 1=FAIL 2=ENV(git 不可用) 3=INCOMPLETE(manifest 解析不了)
RESULT=OK（失败项 0） REVISION=r2 · 指纹 1ac34dc5 · 断言 356 条 · 运行 2026-09-24T18:26:50+0800
```

### 4.6 curl + cookie jar 本地实测（原始输出，两段）

#### 4.6.1 基础守卫 / 分流 / 类型白名单（原始输出见 §4.6.3 的 A–D、F、G 段）

```
```

#### 4.6.2 转交 + A8 负向 + 二级状态机（原始输出见 §4.6.3 的 E 段）

```
```

补充（§8.2 可见性 vs §4.3(2) 处置权的分界，转交后）:

```
$ curl -b jar_fac /leave/approvals          -> 200，列表里仍出现 SLR000098（§8.2 的可见域：班主任的班）
$ curl -b jar_fac /leave/approvals/445      -> 200（详情可看）
$ curl -b jar_fac -d state=approved /leave/set_state -> 303，state 不变、审计行数不变（§4.3(2) 的动作判据挡住了）
```

## 5. 我 `git add` 的精确路径（未 commit）

```
git add custom_addons/edu_portal/controllers/roles.py
git add custom_addons/edu_portal/controllers/batch3.py
git add custom_addons/edu_portal/controllers/batch1.py
git add custom_addons/edu_portal/views/roles.xml
git add docs/plans/leave-split-approval-s3-report.md
```

* `roles.py`：S3 的追加段（两条新路由 + 判据层）与 §3 列出的既有函数改动。
* `batch3.py`：`/my/time_off` 的真实路由落点 —— 分流、教职建单、§7.5、§7.2、类型标签两级取值。
* `batch1.py` / `views/roles.xml`：**4 态 + 7 类型**引入后的中文标签补全（各 1–3 行，纯增量；不补就把英文 code 显示给用户）。
* `docs/plans/leave-split-approval-s3-report.md`：本报告。

**没有** 改动：`openeducat_erp/**`、`custom_addons/edu_telegram/**`、`models/course_rep.py` 既有规则、
`edu_brand/**`（另一个代理的独占区）、`controllers/enroll.py` 与 `__manifest__.py`（第二个代理的独占区）、
任何 S1 冻结文件（`models/__init__.py` / `__manifest__.py` / `security/ir.model.access.csv` / `migrations/**` / `leave_transfer.py`）。

## 6. 留给别人的收尾项（我发现但**没有**替他们改）

1. **S5**：把「`/my/time_off` → 303 `/my/child`（家长身份）」登记进 `check_english` 的路由表/EXEMPT（队长已派）。
2. **S4**：`edu_leave_detail` 我在原有 4 个变量之外多传了 `can_act` / `can_transfer`（布尔）—— 若要隐藏「按了没用」的同意/驳回按钮，直接用这两个值守卫即可（后端判据已 fail-closed，不改也不会写错数据）。
3. **S4**：`/my/time_off?box=return_submitted` 这个回执位我留了（销假提交成功后的回跳），模板目前不渲染任何提示；想加一句成功横幅可直接用这个 box 值。
4. **S4/家长表单**：`views/roles.xml` 的 `edu_child_leave` 表单**没有**证明材料控件（`proof_kind` / `proof_file` / `oral_proof_by`），
   而 S2 的 create 校验对「病假 ≥2 天 / 婚丧假」**必须**有证明 ⇒ 家长目前提交不了这两类单（会拿到 422 与条例文案）。我的路由已经会转发这些字段，缺的只是表单控件。
5. **S2**：`pending_second` 与 `state` 的 selection 覆盖会让 Odoo 打 warning（`use selection_add instead`），不影响功能，登记备查。
6. **遗留测试数据**（本地 dev 库，未删）：请假单 `SLR000085~SLR000098`、`374~377`、`385`、`439~446`（reason 前缀 `S3-` / `S3-TYPE-` / `S3-EVID*`），
   以及 1 行 `edu_leave_transfer`（leave_id=445，fac→bo 转交留痕）。需要的可以留着做 S5 的现场数据，清理时删 `edu_leave` 对应行即可（transfer 行随 cascade 走；`edu_audit_log` 是 append-only，保留）。
   我已把演示用的 `op_batch(8).homeroom_teacher_id` **还原为 NULL**（S5 的「上线当天 100% 走教务处」验收可放心跑）。

## 附录 A：四个文件的全量 staged diff

```diff
diff --git a/custom_addons/edu_portal/controllers/batch1.py b/custom_addons/edu_portal/controllers/batch1.py
index ccb1639..264f144 100644
--- a/custom_addons/edu_portal/controllers/batch1.py
+++ b/custom_addons/edu_portal/controllers/batch1.py
@@ -27,11 +27,20 @@ OFFER_STATE_LABEL = {'invited': '受邀', 'joined': '已加入', 'rejected': '
 OFFER_STATE_BADGE = {'invited': 'text-bg-info', 'joined': 'text-bg-success',
                      'rejected': 'text-bg-danger'}
 LEAVE_TYPE_LABEL = {'sick': '病假', 'legal': '法定假期', 'casual': '事假',
-                    'other': '其他'}
+                    'other': '其他',
+                    # §6（S3，2026-09-25）：类型重做新增的三个 code。
+                    # 不补 ⇒ /student/profile 的请假记录会显示英文 code。
+                    'marriage_funeral': '婚丧假', 'winter_summer': '寒暑假',
+                    'practice_week': '实践周'}
 LEAVE_STATE_LABEL = {'request': '待审批', 'approved': '已通过',
-                     'refused': '已拒绝'}
+                     'refused': '已拒绝',
+                     # §3.1（S3，2026-09-25）：四级状态机的第四态。
+                     # 不补这一条 ⇒ /student/profile 的请假记录表会把英文 code
+                     # 'pending_second' 直接显示给学生（check_english must-fix 点名）。
+                     'pending_second': '待二级审批'}
 LEAVE_STATE_BADGE = {'request': 'text-bg-warning', 'approved': 'text-bg-success',
-                     'refused': 'text-bg-danger'}
+                     'refused': 'text-bg-danger',
+                     'pending_second': 'text-bg-info'}
 GRIEVANCE_STATE_LABEL = {'draft': '草稿', 'submitted': '已提交',
                          'in_progress': '处理中', 'resolve': '已解决',
                          'reject': '已驳回', 'close': '已关闭'}
diff --git a/custom_addons/edu_portal/controllers/batch3.py b/custom_addons/edu_portal/controllers/batch3.py
index 2eb13d4..649a707 100644
--- a/custom_addons/edu_portal/controllers/batch3.py
+++ b/custom_addons/edu_portal/controllers/batch3.py
@@ -16,9 +16,16 @@ import json
 import re
 
 from odoo import fields, http
+from odoo.exceptions import UserError
 from odoo.http import request
 
 from .main import csv_download, current_student, student_course
+# §5.3 / §7.5（S3）：/my/time_off 的学生/教职身份分流与「禁止事后补假」判据
+# 都只有一份实现（落 controllers/roles.py，身份反查走
+# edu_schedule/models/identity.py 的唯一口径）—— 这里只 import，不复制规则。
+from .roles import (leave_applicant_kind, leave_attach_proof_file,
+                    leave_backdated_guard, leave_check_proof,
+                    leave_portal_context, leave_proof_vals)
 
 # 请假类型 / 申诉状态 / 队列状态 的中文标签（selection -> label）
 _LEAVE_TYPE_LABEL = {
@@ -27,6 +34,9 @@ _LEAVE_TYPE_LABEL = {
 }
 _LEAVE_STATE_LABEL = {
     'request': '已申请', 'approved': '已批准', 'refused': '已拒绝',
+    # §3.1（S3）：四级状态机的第四态。缺这一条，学生/教职列表会直接把
+    # 英文 code 'pending_second' 显示给用户。
+    'pending_second': '待二级审批',
 }
 _QUEUE_STATE_LABEL = {
     'request': '已申请', 'accept': '已接受', 'reject': '已驳回',
@@ -81,6 +91,108 @@ def _leave_days(rec):
     return 0
 
 
+def _leave_type_label(env, code):
+    """类型中文标签（§6）：本地表优先，其次**模型 selection 的标签**，最后才退 code。
+
+    为什么必须有「其次模型」这一档：§6 把类型重做成 7 个 code；任何一份手写的
+    中文表都会在下次加类型时漏掉新 code ⇒ 页面直接把英文 code 显示给用户
+    （实测：婚姻假/寒暑假/实践周在 /my/time_off 上就是这样被 check_english 点名的）。
+    模型那一档对新类型本来就是中文（婚丧假/寒暑假/实践周），**不会**把
+    'Sick Leave' 这类历史英文标签带上页面 —— 旧 code 先被本地表命中。
+    """
+    label = _LEAVE_TYPE_LABEL.get(code)
+    if label:
+        return label
+    try:
+        desc = env['edu.leave']._fields['leave_type'].get_description(env)
+        for item in desc.get('selection') or []:
+            if item[0] == code:
+                return item[1]
+    except Exception:
+        pass
+    return code or ''
+
+
+# ---------------------------------------------------------------------------
+# /my/time_off 的共享零件（S3：学生视图与教职视图**同一形状**，防口径分裂）
+# ---------------------------------------------------------------------------
+def _time_off_item(lv, viewer=None):
+    """列表行数据（源字段一处定义，两个身份的视图共用）。"""
+    return {
+        'leave': lv,
+        'name': lv.name or '',
+        'type': _leave_type_label(lv.env, lv.leave_type),
+        'type_raw': lv.leave_type or '',
+        # 学生单取 student_id；教职单没有学生档案 ⇒ 退到申请人账号名（§5.3）
+        'student_name': (lv.student_id.name
+                         if lv.student_id else (viewer.name
+                                                if viewer else '')
+                         or (lv.applicant_user_id.name or '')),
+        'date_from': _fmt_date(lv.date_from),
+        'date_to': _fmt_date(lv.date_to),
+        'days': _leave_days(lv),
+        'days_str': '%d 天' % _leave_days(lv),
+        'state': _LEAVE_STATE_LABEL.get(lv.state, lv.state or ''),
+        'state_raw': lv.state or '',
+        'reason': lv.reason or '',
+    }
+
+
+def _sort_time_off_items(items, sortby):
+    """列表排序（学生/教职同一口径）。"""
+    order = {
+        'date': lambda i: (i['leave'].date_from or fields.Date.today()),
+        'state': lambda i: (i['state_raw'], i['name']),
+        'leave_type': lambda i: (i['type_raw'], i['name']),
+        'request_number': lambda i: i['name'],
+    }.get(sortby or 'date')
+    if order:
+        items.sort(key=order, reverse=(sortby == 'date'))
+    return items
+
+
+def _time_off_stats(leaves):
+    """统计卡：**待审批 = request + pending_second**（§3.1 新增第四态）。"""
+    return {
+        'total': len(leaves),
+        'approved': sum(1 for lv in leaves if lv.state == 'approved'),
+        'pending': sum(1 for lv in leaves
+                       if lv.state in ('request', 'pending_second')),
+        'refused': sum(1 for lv in leaves if lv.state == 'refused'),
+    }
+
+
+def _leave_type_codes(env):
+    """leave_type 的合法码 —— 从**模型**读，不在路由里抄一份。
+
+    为什么：§6 重做类型（marriage_funeral / winter_summer / practice_week …），
+    路由若照抄一份老清单，新类型会被**静默降级成「其他」**（不报错、数据已经错了）。
+    读模型的 selection ⇒ 类型表只有一处事实源；读不到时退回老清单。
+    """
+    try:
+        desc = env['edu.leave']._fields['leave_type'].get_description(env)
+        return {code for code, _label in desc.get('selection') or []}
+    except Exception:
+        return {'sick', 'legal', 'casual', 'other'}
+
+
+def _leave_seq(env):
+    """下一个单号序号（**既有口径逐字保留**：取 id 最大的单，名字第 4 位起为数字）。"""
+    last = env['edu.leave'].sudo().search([], order='id desc', limit=1)
+    if last and last.name and last.name[3:].isdigit():
+        return int(last.name[3:]) + 1
+    return 1
+
+
+def _template_exists(xmlid):
+    """模板是否已存在（S3 的教职视图安全网：S4 建了就用，没建就回退）。"""
+    try:
+        return bool(request.env['ir.ui.view'].sudo().search_count(
+            [('key', '=', xmlid)]))
+    except Exception:
+        return False
+
+
 # 申诉分类固定选项（学生提交时选用）
 GRIEVANCE_CATEGORIES = [
     '学业 / 成绩问题',
@@ -455,42 +567,74 @@ class EduStudentBatch3(http.Controller):
     @http.route('/my/time_off/save', type='http', auth='user',
                 website=True, methods=['POST'], csrf=True)
     def my_time_off_save(self, **kw):
+        env = request.env
         student = current_student()
-        if not student:
+        # §5.3（S3）分流：学生 → 学生单；student/parent 皆空 → **教职单**；
+        # 家长不算教职（他的入口是 /my/child/<id>/leave）⇒ 回本页走分流。
+        if not student and leave_applicant_kind() != 'staff':
             return request.redirect('/my/time_off')
-        leave_type = kw.get('leave_type') if kw.get('leave_type') in (
-            'sick', 'legal', 'casual', 'other') else 'other'
+        # §6：类型合法码从**模型**读 —— 路由里再抄一份老清单的话，新类型
+        # （marriage_funeral / winter_summer / practice_week …）会被**静默
+        # 降级成「其他」**（不报错、数据已经错了）。
+        leave_type = kw.get('leave_type') \
+            if kw.get('leave_type') in _leave_type_codes(env) else 'other'
         try:
             date_from = fields.Date.to_date(kw.get('date_from'))
             date_to = fields.Date.to_date(kw.get('date_to'))
         except Exception:
             return request.redirect('/my/time_off?box=error_date')
+        # 空日期必须在这里挡住：fields.Date.to_date('') 返回 False（**不抛异常**），
+        # 于是原写法 date_to < date_from 会 TypeError ⇒ 整页 500。
+        # （实测证据：2026-09-24 空 date_from 的 POST /my/time_off/save →
+        #  "TypeError: '<' not supported between instances of 'datetime.date'
+        #   and 'NoneType'" @ batch3.py:562。既有页面的 required 只挡浏览器，
+        #   挡不住任何非浏览器客户端。）
+        if not date_from or not date_to:
+            return request.redirect('/my/time_off?box=error_date')
         if date_to < date_from:
             date_to = date_from
-        env = request.env
-        # 课代表（需求①）：请假可**选填**「涉及课程」——只能选自己的课程。
-        # 不填 => subject_id 为空 => 课代表无权批（fail-closed），走老师/教务，
-        # 对既有流程零影响（设计 §6.3 / §8-16）。
-        subject_id = False
-        raw_sid = kw.get('subject_id')
-        if raw_sid and str(raw_sid).isdigit():
-            mine = env['op.student.course'].sudo().search([
-                ('student_id', '=', student.id)]).mapped('subject_ids')
-            hit = mine.filtered(lambda s: s.id == int(raw_sid))
-            subject_id = hit.id if hit else False
-        last = env['edu.leave'].sudo().search([], order='id desc', limit=1)
-        seq = 1
-        if last and last.name and last.name[3:].isdigit():
-            seq = int(last.name[3:]) + 1
-        env['edu.leave'].sudo().create({
-            'name': 'SLR%06d' % seq,
-            'student_id': student.id,
-            'subject_id': subject_id,
+        # §7.5（S3）：门户侧**禁止事后补假** —— date_from < 提交日 ⇒ 硬拒、不落库。
+        # 边界：今天请假、今天提交（date_from == today）**允许**；后台代录历史走
+        # backfilled 通道，不受本校验（判据只有一份：roles.leave_backdated_guard）。
+        if leave_backdated_guard(date_from):
+            raise UserError(
+                '《请假条例》一·2 规定严禁事后补假，请勿补提过去日期的申请。')
+        vals = {
+            'name': 'SLR%06d' % _leave_seq(env),
             'leave_type': leave_type,
             'date_from': date_from,
             'date_to': date_to,
             'reason': (kw.get('reason') or '').strip()[:500] or '—',
-        })
+        }
+        if student:
+            # 课代表（需求①）：请假可**选填**「涉及课程」——只能选自己的课程。
+            # 不填 => subject_id 为空 => 课代表无权批（fail-closed），走老师/教务，
+            # 对既有流程零影响（设计 §6.3 / §8-16）。
+            subject_id = False
+            raw_sid = kw.get('subject_id')
+            if raw_sid and str(raw_sid).isdigit():
+                mine = env['op.student.course'].sudo().search([
+                    ('student_id', '=', student.id)]).mapped('subject_ids')
+                hit = mine.filtered(lambda s: s.id == int(raw_sid))
+                subject_id = hit.id if hit else False
+            vals.update({'student_id': student.id, 'subject_id': subject_id,
+                         'applicant_kind': 'student'})
+        else:
+            # 教职单（§5.3）：申请人 = 登录账号本身；学生单才用 student_id
+            vals.update({'student_id': False, 'applicant_kind': 'staff',
+                         'applicant_user_id': env.user.id})
+        # §7.2（S3）：证明字段原样转发给模型 —— S2 的 create 校验读的是
+        # vals['proof_kind']/['oral_proof_by']，路由不转发的话，用户明明在表单里
+        # 填了口头证明人也会被判成「未提供证明」而拒绝。
+        vals.update(leave_proof_vals(kw))
+        # §7.5：带上「门户自助提交」context（教务/管理员本人在门户提交时，
+        # 模型的兜底判据会把特权账号误判成后台代录通道）。
+        leave = env['edu.leave'].sudo().with_context(
+            **leave_portal_context()).create(vals)
+        # §7.2 文件证明：附件是 o2m，只能建单后落库；随后调 S2 的附件复核
+        # （S2 的 docstring 明确要求 S3/S4 在上传完成后调它）。
+        leave_attach_proof_file(leave, kw)
+        leave_check_proof(leave)
         return request.redirect('/my/time_off?box=submitted')
 
     @http.route('/my/grievances/save', type='http', auth='user',
@@ -726,70 +870,53 @@ class EduStudentBatch3(http.Controller):
 
     @http.route('/my/time_off', type='http', auth='user', website=True)
     def my_time_off(self, **kw):
+        # §5.3（S3）**同一页分流**（不新增页面，也不新增重复路由）：
+        #   学生（op.student 非空）     → 学生请假单视图；
+        #   教职（student/parent 皆空） → 教职员工请假单视图；
+        #   家长（op.parent 非空）      → 既有「为孩子请假」入口 /my/child
+        #                               （家长**不算**教职，§5.3 的反例）。
+        # 判据只有一份实现：controllers/roles.py:leave_applicant_kind()。
         student = current_student()
         p = _nav_params(kw)
         box = kw.get('box') or ''
+        if not student:
+            if leave_applicant_kind() == 'staff':
+                return self._my_time_off_staff(p, box)
+            # 家长（§5.3）：**不算教职**，也**不套学生单** —— 家长在 /my/time_off
+            # 看到的是「为孩子请假」，落点就是既有的家长中心 /my/child
+            # （那里每个孩子都有 /my/child/<id>/leave 的请假入口，即 §8.1 的
+            # 「建学生单」家长路径）。
+            # ⚠ 这是**有意行为**，不应改成 200：本页对家长没有可用的提交表单
+            #   （/my/time_off/save 在家长身份下会被分流挡回、不落库），给一个
+            #   按了没反应的假入口，比直接送到正确入口更差。
+            # ⚠ 门禁提示：check_english 的路由状态不变量只放行「跳 /my/home · /web」
+            #   的门禁跳转 ⇒ 本行会报 ROUTE-BAD（队长 2026-09-25 已派 S5 把
+            #   「/my/time_off → /my/child（家长）」登记进路由表/EXEMPT）。
+            return request.redirect('/my/child')
 
-        domain = [('student_id', '=', student.id)] if student \
-            else [('id', '=', 0)]
+        domain = [('student_id', '=', student.id)]
         if p['filterby'] and p['filterby'] != 'all':
             domain.append(('leave_type', '=', p['filterby']))
         if p['search']:
             domain += ['|', ('name', 'ilike', p['search']),
                        ('reason', 'ilike', p['search'])]
         leaves = request.env['edu.leave'].sudo().search(domain)
-
-        items = []
-        for lv in leaves:
-            items.append({
-                'leave': lv,
-                'name': lv.name or '',
-                'type': _LEAVE_TYPE_LABEL.get(lv.leave_type, lv.leave_type
-                                              or ''),
-                'type_raw': lv.leave_type or '',
-                'student_name': (lv.student_id.name
-                                 if lv.student_id else (student.name
-                                                        if student else '')),
-                'date_from': _fmt_date(lv.date_from),
-                'date_to': _fmt_date(lv.date_to),
-                'days': _leave_days(lv),
-                'days_str': '%d 天' % _leave_days(lv),
-                'state': _LEAVE_STATE_LABEL.get(lv.state, lv.state or ''),
-                'state_raw': lv.state or '',
-                'reason': lv.reason or '',
-            })
-
-        order = {
-            'date': lambda i: (i['leave'].date_from or fields.Date.today()),
-            'state': lambda i: (i['state_raw'], i['name']),
-            'leave_type': lambda i: (i['type_raw'], i['name']),
-            'request_number': lambda i: i['name'],
-        }.get(p['sortby'] or 'date')
-        if order:
-            items.sort(key=order, reverse=(p['sortby'] == 'date'))
-
+        items = _sort_time_off_items(
+            [_time_off_item(lv, viewer=student) for lv in leaves], p['sortby'])
         all_leaves = leaves if p['filterby'] == 'all' else \
             request.env['edu.leave'].sudo().search(
-                [('student_id', '=', student.id)]) if student else []
-        stats = {
-            'total': len(all_leaves),
-            'approved': sum(1 for lv in all_leaves
-                            if lv.state == 'approved'),
-            'pending': sum(1 for lv in all_leaves
-                           if lv.state == 'request'),
-            'refused': sum(1 for lv in all_leaves
-                           if lv.state == 'refused'),
-        }
+                [('student_id', '=', student.id)])
 
         # 课代表（需求①）：提交请假时的「涉及课程」下拉 = 我自己的科目集
         # （与 /my/courses 同源：op.student.course.subject_ids，见 lms.py:24-30）
         my_subjects = request.env['op.student.course'].sudo().search([
-            ('student_id', '=', student.id)]).mapped('subject_ids') \
-            if student else request.env['op.subject'].sudo().browse()
+            ('student_id', '=', student.id)]).mapped('subject_ids')
 
         values = {
             'title': '休假请求列表',
             'page_name': 'time_off',
+            'applicant_kind': 'student',
+            'is_staff': False,
             'student': student,
             'my_subjects': my_subjects,
             'sortby': p['sortby'],
@@ -797,20 +924,66 @@ class EduStudentBatch3(http.Controller):
             'groupby': p['groupby'],
             'search': p['search'],
             'box': box,
-            'stats': stats,
+            'stats': _time_off_stats(all_leaves),
             'items': items,
             'has_records': bool(items),
         }
         return request.render('edu_portal.edu_time_off', values)
 
-    @http.route('/my/time_off/export', type='http', auth='user')
+    def _my_time_off_staff(self, p, box):
+        """教职员工的请假单视图（§5.3 / §8.1「建教职单 = 同一页分流」）。
+
+        数据源 = applicant_user_id == 我（学生单走 student_id，两条路互不混淆）。
+        模板优先 edu_portal.edu_time_off_staff（S4 建了这个 template id 就自动
+        生效），不存在时回退既有 edu_time_off —— **绝不 500**（并行开发期的
+        安全网；回退页仍是 200、数据也是对的，学生表单在教职分支下提交后会
+        落成教职单，见 my_time_off_save 的分流）。
+        """
+        env = request.env
+        domain = [('applicant_user_id', '=', env.user.id)]
+        if p['filterby'] and p['filterby'] != 'all':
+            domain.append(('leave_type', '=', p['filterby']))
+        if p['search']:
+            domain += ['|', ('name', 'ilike', p['search']),
+                       ('reason', 'ilike', p['search'])]
+        leaves = env['edu.leave'].sudo().search(domain)
+        items = _sort_time_off_items(
+            [_time_off_item(lv) for lv in leaves], p['sortby'])
+        mine = leaves if p['filterby'] == 'all' else \
+            env['edu.leave'].sudo().search(
+                [('applicant_user_id', '=', env.user.id)])
+        values = {
+            'title': '休假请求列表',
+            'page_name': 'time_off',
+            'applicant_kind': 'staff',
+            'is_staff': True,
+            'staff_user': env.user,
+            'student': False,
+            'my_subjects': env['op.subject'].sudo().browse(),
+            'sortby': p['sortby'],
+            'filterby': p['filterby'],
+            'groupby': p['groupby'],
+            'search': p['search'],
+            'box': box,
+            'stats': _time_off_stats(mine),
+            'items': items,
+            'has_records': bool(items),
+        }
+        template = ('edu_portal.edu_time_off_staff'
+                    if _template_exists('edu_portal.edu_time_off_staff')
+                    else 'edu_portal.edu_time_off')
+        return request.render(template, values)
+
     def my_time_off_export(self, **kw):
-        """请假台账 CSV 导出：与列表页同筛选，全量。"""
+        """请假台账 CSV 导出：与列表页同筛选，全量（学生自己的单 / 教职自己的单）。"""
         student = current_student()
-        if not student:
+        # §5.3（S3）：教职同样能导出自己的台账（否则教职页上的「导出 CSV」
+        # 按钮会把用户弹回 /my/home —— 看得见点不动）。
+        if not student and leave_applicant_kind() != 'staff':
             return request.redirect('/my/home')
         p = _nav_params(kw)
-        domain = [('student_id', '=', student.id)]
+        domain = [('student_id', '=', student.id)] if student \
+            else [('applicant_user_id', '=', request.env.user.id)]
         if p['filterby'] and p['filterby'] != 'all':
             domain.append(('leave_type', '=', p['filterby']))
         if p['search']:
diff --git a/custom_addons/edu_portal/controllers/roles.py b/custom_addons/edu_portal/controllers/roles.py
index b0c8652..0546beb 100644
--- a/custom_addons/edu_portal/controllers/roles.py
+++ b/custom_addons/edu_portal/controllers/roles.py
@@ -22,7 +22,11 @@ from odoo.addons.edu_schedule.models.identity import (
     PROFILE_CHAINS, profile_of_user)
 
 _LEAVE_TYPE_LABEL = {'sick': '病假', 'legal': '法定假期',
-                     'casual': '事假', 'other': '其他'}
+                     'casual': '事假', 'other': '其他',
+                     # §6（S3，2026-09-25）：类型重做新增的三个 code —— 审批详情页
+                     # 会直接显示这张表的取值，不补就把英文 code 给老师看。
+                     'marriage_funeral': '婚丧假', 'winter_summer': '寒暑假',
+                     'practice_week': '实践周'}
 
 
 def _read_table_file(f):
@@ -816,15 +820,19 @@ class EduParentPortal(http.Controller):
     # ------------------------------------------------------------------
     # 教师打分（写操作）：为考试录入学生得分
     # ------------------------------------------------------------------
-    def _approval_scope_domain(self):
+    def _approval_scope_domain(self, model_name='edu.leave'):
         """薄包装：口径已提取为模块级 approval_scope_domain(env)（t67）。
 
         提取动机：该口径需被 enroll.py（选课审批批量）复用，而它够不到
         本控制器类的方法 → 提取为模块级函数，避免复制一份规则。
         口径与 F2 的考试归属一致（都落在「该教师教不教这个人/这场考试」）：
         列表、批量与单条三处共用同一域，做到「看得见的 = 能处置的」。
+
+        :param model_name: §8.2 起用于分流「请假的并集域 / 申诉的老域」；
+            默认 'edu.leave'（既有请假调用点一字不改），申诉列表显式传
+            'edu.grievance'（edu.grievance 没有 first/second_approver_id 字段）。
         """
-        return approval_scope_domain(request.env)
+        return approval_scope_domain(request.env, model_name)
 
     def _scoped_record(self, model_name, rec_id, extra_domain=None):
         """薄包装（t67）：见模块级 scoped_record(env, ...)。"""
@@ -1046,13 +1054,19 @@ class EduParentPortal(http.Controller):
         if not stu.exists() or not parent or \
                 child_id not in parent.student_ids.ids:
             return request.redirect('/my/child')
+        # §7.5（S3）：门户侧**禁止事后补假** —— date_from < 提交日 ⇒ 硬拒、不落库。
+        # 边界：今天请假、今天提交（date_from == today）**允许**（不是「事后」）；
+        # 后台「请假审批 → 新建」不受此校验（教务代录历史/特殊情况，走 backfilled 通道）。
+        if leave_backdated_guard(post.get('date_from')):
+            raise UserError(
+                '《请假条例》一·2 规定严禁事后补假，请勿补提过去日期的申请。')
         Leave = request.env['edu.leave'].sudo()
         seq = request.env['ir.sequence'].sudo().search(
             [('code', '=', 'edu.leave')], limit=1)
         name = seq.next_by_code('edu.leave') if seq else ''
         if not name:
             name = f'LV{int(request.env["edu.leave"].search_count([])) + 1:06d}'
-        mk = Leave.create({
+        vals = {
             'name': name,
             'student_id': stu.id,
             'leave_type': post.get('leave_type', 'sick'),
@@ -1060,14 +1074,24 @@ class EduParentPortal(http.Controller):
             'date_to': post.get('date_to') or post.get('date_from'),
             'reason': post.get('reason', ''),
             'state': 'request',
-        })
+        }
+        # §7.2（S3）：证明字段转发 + 附件落库 + S2 的附件复核；§7.5：带上
+        # 「门户自助提交」context（家长本身不是特权账号，这里是显式声明而非兜底）。
+        vals.update(leave_proof_vals(post))
+        mk = Leave.with_context(**leave_portal_context()).create(vals)
+        leave_attach_proof_file(mk, post)
+        leave_check_proof(mk)
         print(f"LEAVE CREATED {mk.name} by parent for student {stu.id}")
         return request.redirect(f'/my/child/{child_id}/leave?saved=1')
 
     @http.route('/leave/approvals', type='http', auth='user', website=True)
     def leave_approvals(self, **kw):
-        fac = current_faculty()
-        if not fac and not privileged_staff():
+        # §8.1 准入（S3 放宽，判据见 leave_portal_approver）：
+        # 有教师档案 ∪ 教务处/系统组 ∪「本级应批人是我」。
+        # 最后一档是 §3.3「没有班主任也能跑 / 老师到位后只填数据即生效」的前提——
+        # op.batch.homeroom_teacher_id 存的是 res.users，而本仓 op.faculty 0 个在职行，
+        # 班主任完全可能没有教师档案；沿用老门槛会让最主要的使用者连队列都进不去。
+        if not leave_portal_approver():
             return request.redirect('/my/home')
         Leave = request.env['edu.leave'].sudo()
         filterby = kw.get('filterby') or 'all'
@@ -1110,8 +1134,12 @@ class EduParentPortal(http.Controller):
     @http.route('/leave/set_state', type='http', auth='user',
                 methods=['POST'], website=True, csrf=True)
     def leave_set_state(self, **post):
-        fac = current_faculty()
-        if not fac and not privileged_staff():
+        # §8.1 准入（S3 放宽，判据见 leave_portal_approver）：
+        # 有教师档案 ∪ 教务处/系统组 ∪「本级应批人是我」。
+        # 最后一档是 §3.3「没有班主任也能跑 / 老师到位后只填数据即生效」的前提——
+        # op.batch.homeroom_teacher_id 存的是 res.users，而本仓 op.faculty 0 个在职行，
+        # 班主任完全可能没有教师档案；沿用老门槛会让最主要的使用者连队列都进不去。
+        if not leave_portal_approver():
             return request.redirect('/my/home')
         try:
             lid = int(post.get('leave_id', 0))
@@ -1120,25 +1148,35 @@ class EduParentPortal(http.Controller):
             return request.redirect('/leave/approvals')
         # t34 F3：单条路由与批量同口径（越权按不存在处理）
         rec = self._scoped_record('edu.leave', lid)
-        if rec.exists() and new_state in ('approved', 'refused'):
+        # §3.1（S3）：接受第三个动作值 'send_back' = 二级退回到一级（设计稿
+        # 只给了动作没给路由；本路由是门户唯一审批入口 ⇒ 加一个值，既有的
+        # 'approved' / 'refused' 行为与参数一字不变）。
+        # §4.3(2)/§8.1（S3）：**动作判据** = 本单当前这一级的 first_approver_id /
+        # second_approver_id 本人（或 privileged_staff 恒可批，铁律不破）。
+        # 为什么不能只靠上面的作用域域：§8.2 的域含「我任教班级 / 我当班主任的班」
+        # 两项 ⇒ 转交出去之后原审批人**仍看得见**这张单（设计的可见性口径），
+        # 但「能不能批」按 §4.3(2) 必须落到快照上 —— 否则「转交后原审批人不能
+        # 再批」这条用户裁决会在班主任身上静默失效。
+        # 不是本级应批人 ⇒ 与「不存在」同样处理：不写任何字段、303 回队列。
+        if rec.exists() and new_state in ('approved', 'refused', 'send_back') \
+                and _leave_can_act(rec, request.env.user):
             # A1：驳回可附原因（详情页必填，列表页快捷按钮保持旧行为可不填）
             reason = (post.get('reject_reason') or '').strip()[:500]
             was_pending = rec.state == 'request'
-            if new_state == 'refused' and reason:
-                rec.write({'reject_reason': reason})
-            # 课代表需求⑥：审批留痕（补既有缺口）。**不改状态机**，只是同一个
-            # write 里补 approver_id / approver_kind / approved_at —— 否则同一张
-            # 表单上「有的显示审批人、有的不显示」= 口径分裂。
-            vals = {'state': new_state}
-            vals.update(rec._approver_vals())
-            rec.write(vals)
-            if was_pending:
-                # A1：实际流转后经 B5 通知引擎告知申请人
-                rec._notify_applicant(new_state)
+            # 课代表需求⑥ + §3.1：审批留痕与状态流转交给 S2 的冻结动作
+            # （一级通过后是 approved 还是 pending_second 由 need_second 决定，
+            # 那是模型判定，控制器不得复制）。动作缺席 ⇒ 回退既有直写，见
+            # 文末 _leave_flow_apply_state（含「为什么要有这层」的完整理由）。
+            applied = _leave_flow_apply_state(rec, new_state, reason,
+                                             was_pending=was_pending)
             # 4a 审计：请假审批
-            request.env['edu.audit.log'].sudo()._log(
-                '请假审批', 'edu.leave', rec.id, rec.name or '',
-                '状态 → %s' % new_state)
+            # ⚠ S2 的冻结动作**内部已写**「请假审批」审计 + 申请人通知（队长
+            # 2026-09-25 裁决：模型层是唯一事实源）⇒ 只有回退路径（'legacy'）
+            # 才由本路由补审计，否则每笔审批会多出 1 条重复审计。
+            if applied == 'legacy':
+                request.env['edu.audit.log'].sudo()._log(
+                    '请假审批', 'edu.leave', rec.id, rec.name or '',
+                    '状态 → %s' % new_state)
             print(f"LEAVE {rec.name} -> {new_state}")
         # A1：详情页表单带 next 回跳详情（仅接受本域请假路径，防开放跳转）
         next_url = post.get('next') or ''
@@ -1156,6 +1194,9 @@ class EduParentPortal(http.Controller):
         type_label = {
             'sick': '病假', 'legal': '法定假',
             'casual': '事假', 'other': '其他',
+            # §6（S3）：新类型的详情页标签（缺了就显示英文 code）
+            'marriage_funeral': '婚丧假', 'winter_summer': '寒暑假',
+            'practice_week': '实践周',
         }.get(rec.leave_type, rec.leave_type or '—')
         days = 0
         if rec.date_from and rec.date_to and rec.date_to >= rec.date_from:
@@ -1172,7 +1213,17 @@ class EduParentPortal(http.Controller):
 
     @staticmethod
     def _leave_steps(state):
-        """请假步骤条：已提交 → 审批中 → 已通过/已驳回。"""
+        """请假步骤条：已提交 → 审批中 → 已通过/已驳回（§3.1：二级单多一格）。"""
+        if state == 'pending_second':
+            # §3.1 新增第四态：一级已通过、等二级（教务）审批。
+            # 单独一档而不是复用 request —— 否则「待一级」与「待二级」在
+            # 进度条上分不开，一级审批人会看到自己已经批过的单。
+            return [
+                {'label': '已提交', 'cls': 'ux-step--done'},
+                {'label': '一级已通过', 'cls': 'ux-step--done'},
+                {'label': '待二级审批', 'cls': 'ux-step--current'},
+                {'label': '已通过 / 已驳回', 'cls': 'ux-step--todo'},
+            ]
         if state == 'approved':
             return [
                 {'label': '已提交', 'cls': 'ux-step--done'},
@@ -1228,7 +1279,9 @@ class EduParentPortal(http.Controller):
         search = (kw.get('search') or '').strip()
         page = max(1, int(kw.get('page', 1) or 1))
         # t34 F3：与请假审批同口径（教师只见任教班级的申诉）
-        domain = self._approval_scope_domain()
+        # §8.2（S3）：显式声明这是**申诉**域 —— 请假侧的并集项（first/second
+        # _approver_id）在 edu.grievance 上不存在，不能串用。
+        domain = self._approval_scope_domain('edu.grievance')
         if filterby == 'pending':
             domain.append(('state', 'in', ('submitted', 'in_progress')))
         elif filterby in ('draft', 'resolve', 'reject', 'close'):
@@ -1322,8 +1375,12 @@ class EduParentPortal(http.Controller):
     @http.route('/leave/approvals/<int:leave_id>', type='http', auth='user',
                 website=True)
     def leave_detail(self, leave_id, **kw):
-        fac = current_faculty()
-        if not fac and not privileged_staff():
+        # §8.1 准入（S3 放宽，判据见 leave_portal_approver）：
+        # 有教师档案 ∪ 教务处/系统组 ∪「本级应批人是我」。
+        # 最后一档是 §3.3「没有班主任也能跑 / 老师到位后只填数据即生效」的前提——
+        # op.batch.homeroom_teacher_id 存的是 res.users，而本仓 op.faculty 0 个在职行，
+        # 班主任完全可能没有教师档案；沿用老门槛会让最主要的使用者连队列都进不去。
+        if not leave_portal_approver():
             return request.redirect('/my/home')
         rec = self._scoped_record('edu.leave', leave_id)
         if not rec.exists():
@@ -1331,7 +1388,18 @@ class EduParentPortal(http.Controller):
         state_label = {
             'request': '已申请（待审批）', 'approved': '已批准',
             'refused': '已拒绝',
+            # §3.1：新增第四态必须给中文标签，否则详情页会直接吐出英文 code
+            'pending_second': '一级已通过（待二级审批）',
         }.get(rec.state, rec.state or '—')
+        # §4.4（S3 → S4 契约）：转交表单要的「当前审批级」与「合法转入人」。
+        # transfer_users 用 S2 冻结接口 transfer_candidates(stage)（已过滤自己/申请人）；
+        # 接口未就绪 ⇒ 空集 ⇒ S4 的 t-if 让表单隐藏（不 500、更不是「谁都能转」）。
+        # 只有**当前这一级的应批人**才看得到转交入口（§4.4：privileged_staff 可批但不可转）。
+        leave_stage = leave_stage_of_state(rec.state)
+        can_transfer = _leave_can_transfer(rec, request.env.user, leave_stage)
+        transfer_users = (leave_transfer_candidates(rec, leave_stage)
+                          if can_transfer
+                          else request.env['res.users'].sudo().browse())
         return request.render('edu_portal.edu_leave_detail', {
             'title': '请假审批详情',
             'page_name': 'leave_detail',
@@ -1339,6 +1407,13 @@ class EduParentPortal(http.Controller):
             'vals': self._leave_detail_vals(rec),
             'state_label': state_label,
             'steps': self._leave_steps(rec.state),
+            'leave_stage': leave_stage,
+            'transfer_users': transfer_users,
+            # §8.1/S4 契约：能否处置 / 能否转交（S4 的按钮守卫可用这两个布尔量；
+            # 不给的话，转交出去后的原审批人仍看得见详情页，会看到**按了没用**的
+            # 「同意/驳回」按钮 —— 后端的 fail-closed 不变，这里只是把话说在前面）。
+            'can_act': _leave_can_act(rec, request.env.user),
+            'can_transfer': can_transfer,
         })
 
 
@@ -2007,8 +2082,9 @@ class EduParentPortal(http.Controller):
         语义对齐飞书「只对符合条件的待处理任务批量同意或拒绝」：只处理
         state=request 的单，非待处理计入「跳过」；逐条 savepoint 独立成败。
         """
-        fac = current_faculty()
-        if not fac and not privileged_staff():
+        # §8.1 准入（S3 放宽，判据见 leave_portal_approver）：有教师档案 ∪
+        # 教务处/系统组 ∪「本级应批人是我」——理由与 leave_approvals 同。
+        if not leave_portal_approver():
             return request.redirect('/my/home')
         new_state = post.get('state', '')
         if new_state not in ('approved', 'refused'):
@@ -2030,19 +2106,21 @@ class EduParentPortal(http.Controller):
         pending = self._scoped_records(
             'edu.leave', posted, [('state', '=', 'request')])
         records = self._scoped_records('edu.leave', posted)
+        # §4.3(2)/§8.1（S3）：可处置 = 本级应批人本人（或 privileged_staff），
+        # 与单条路由**同判据** —— 否则「转交出去的单被原审批人批量批掉」会绕过
+        # §4.3(2)（批量只处理 state=request，故这里恒是一级）。
+        actionable = pending.filtered(
+            lambda r: _leave_can_act(r, request.env.user))
 
         def _apply(rec):
-            if new_state == 'refused':
-                rec.write({'reject_reason': reason})
-            # 课代表需求⑥：批量审批同样补写审批留痕（与单条同口径）
-            vals = {'state': new_state}
-            vals.update(rec._approver_vals())
-            rec.write(vals)
-            rec._notify_applicant(new_state)
+            # 课代表需求⑥ + §3.1：批量与单条**必须同一套分级动作** ——
+            # 否则「4 天的单批量通过 = 直接终审」会绕过 pending_second（静默走样）。
+            # was_pending=True：批量集合已按 state='request' 过滤。
+            _leave_flow_apply_state(rec, new_state, reason, was_pending=True)
             return True
 
-        ok, failures = self._bulk_loop(pending, _apply)
-        skipped = len(records) - len(pending)
+        ok, failures = self._bulk_loop(actionable, _apply)
+        skipped = len(records) - len(actionable)
         # t67：被作用域丢弃的 id（越权 + 不存在）聚合计数；只给总数、不拆原因
         ignored = max(0, len(set(posted)) - len(records))
         request.env['edu.audit.log'].sudo()._log(
@@ -2713,24 +2791,72 @@ def teacher_taught_batches(env, fac):
         [('faculty_id', '=', fac.id)]).mapped('batch_id').ids
 
 
-def approval_scope_domain(env):
-    """审批作用范围（t34 F3）：教师=任教班级的学生；教务处/管理员不限。"""
+def leave_scope_students(env, fac):
+    """§8.2 的 ③④：「我任教班级的学生」∪「我当班主任的班的学生」（去重 id）。
+
+    · ③ 任教班级 = op.session.faculty_id 口径（既有 t34 F3，teacher_taught_batches）；
+    · ④ 班主任班级 = op.batch.homeroom_teacher_id（S1 新增字段，可空）——
+      本仓今天 0 个班主任（字段全空）⇒ 这一项恒为空集，不影响既有可见域；
+    · **不看 op.faculty 是否存在**：班主任字段存的是 res.users，与 op.faculty
+      0 在职无关（设计稿 §5.1「老师到位后只填数据即生效」——填下拉框即生效）。
+    """
+    batch_ids = list(teacher_taught_batches(env, fac) if fac else [])
+    for bid in env['op.batch'].sudo().search(
+            [('homeroom_teacher_id', '=', env.uid)]).ids:
+        if bid not in batch_ids:
+            batch_ids.append(bid)
+    if not batch_ids:
+        return []
+    return env['op.student.course'].sudo().search(
+        [('batch_id', 'in', batch_ids)]).mapped('student_id').ids
+
+
+def approval_scope_domain(env, model_name='edu.leave'):
+    """审批作用范围（t34 F3 + §8.2 请假分级）：教务处/管理员不限。
+
+    请假（`model_name='edu.leave'`，默认）= 下面三项的**并集（OR）**：
+      ① 我是这一单**当前一级**应批人（first_approver_id = 我）；
+      ② 我是这一单**当前二级**应批人（second_approver_id = 我）；
+      ③ 我任教班级 ∪ 我当班主任的班的学生提的单（既有 t34 F3 口径 + §8.2 班主任项）。
+    **为什么必须并集**：§4.3(2) 把「我能不能批这一级」的判据从「是不是班主任」
+    换成「是不是本单当前这一级的 first_approver_id / second_approver_id」；
+    而列表 / 批量 / 单条**必须同域**（既有「看得见的 = 能处置的」，
+    见上游 `_approval_scope_domain` 的注释），否则会重现历史缺陷。
+    转交后原审批人 ① 落空 ⇒ 立刻看不见、也就批不了（§4.3(2)）。
+    ⚠ 例外不破：privileged_staff()（教务处组 / 系统组）**恒可批任何单**，
+      故这里第一行就返回「不限」（code-map §6 第 3 条铁律）。
+
+    ⚠ 申诉（model_name='edu.grievance'）**逐字保持 t34 F3 老域**：edu.grievance
+      没有这两个字段，把 OR 项拼进去 search 会直接 ValueError（申诉页 500）。
+      故本函数新增 `model_name` 形参做显式分流：scoped_record/scoped_records 已把
+      它们自己的 model_name 传进来，`_approval_scope_domain` 默认 'edu.leave'
+      （既有请假调用点一字不改），申诉调用点显式传 'edu.grievance'。
+    """
     if privileged_staff():
         return []
     fac = current_faculty()
-    if not fac:
-        return [('student_id', '=', 0)]
-    batches = teacher_taught_batches(env, fac)
-    if not batches:
-        return [('student_id', '=', 0)]
-    students = env['op.student.course'].sudo().search(
-        [('batch_id', 'in', batches)]).mapped('student_id')
-    return [('student_id', 'in', students.ids or [0])]
+    if model_name != 'edu.leave':
+        # 非请假模型：一字不改地保留 t34 F3 行为
+        if not fac:
+            return [('student_id', '=', 0)]
+        batches = teacher_taught_batches(env, fac)
+        if not batches:
+            return [('student_id', '=', 0)]
+        students = env['op.student.course'].sudo().search(
+            [('batch_id', 'in', batches)]).mapped('student_id')
+        return [('student_id', 'in', students.ids or [0])]
+    terms = [('first_approver_id', '=', env.uid),
+             ('second_approver_id', '=', env.uid)]
+    student_ids = leave_scope_students(env, fac)
+    if student_ids:
+        terms.append(('student_id', 'in', student_ids))
+    # OR 前缀（波兰式）：n 项 ⇒ n-1 个 '|'
+    return ['|'] * (len(terms) - 1) + terms
 
 
 def scoped_record(env, model_name, rec_id, extra_domain=None):
     """按审批作用域取单条记录；不存在/越权一律返回空集（按不存在处理）。"""
-    dom = approval_scope_domain(env)
+    dom = approval_scope_domain(env, model_name)
     if extra_domain:
         dom = dom + list(extra_domain)
     try:
@@ -2742,7 +2868,495 @@ def scoped_record(env, model_name, rec_id, extra_domain=None):
 
 def scoped_records(env, model_name, ids, extra_domain=None):
     """按审批作用域批量取记录（越权 id 不在返回集里）。"""
-    dom = approval_scope_domain(env)
+    dom = approval_scope_domain(env, model_name)
     if extra_domain:
         dom = dom + list(extra_domain)
     return env[model_name].sudo().search(dom + [('id', 'in', list(ids or []) + [0])])
+
+
+# ===========================================================================
+# S3 —— 请假拆分 + 分级审批 + 转交：门户动作面（**本段只追加**）
+#
+# 设计：docs/plans/leave-split-approval-design.md
+#   §3.3 空值行为（没有班主任也能跑）/ §4.3(1)(2)(3)(4) 转交四规则与四层留痕 /
+#   §4.4 转交动作面 / §7.1 销假（正交字段，不改 state）/ §7.5 事后补假硬拒（门户侧）/
+#   §8 权限矩阵（§8.1 谁能批/谁能转、§8.2 扩域）
+#
+# 本段对**既有函数**的改动只有下面这几处（其余一字不动）：
+#   1) approval_scope_domain(env)：§8.2 请假侧并集（first/second_approver_id）；
+#      caller（scoped_record / scoped_records / _approval_scope_domain）把
+#      自己的 model_name 传下来，申诉侧显式走 'edu.grievance' 老域。
+#   2) leave_approvals / leave_detail / leave_set_state / leave_set_state_bulk 的
+#      **准入行**：放宽为 leave_portal_approver()（多一档「本级应批人是我」）。
+#      依据 §3.3：op.batch.homeroom_teacher_id 存的是 res.users，而本仓
+#      op.faculty 0 个在职行 ⇒ 班主任可以没有教师档案；不放宽则
+#      「老师到位后只填数据即生效」跑不通（最主要的使用者进不来）。
+#   3) leave_set_state / leave_set_state_bulk 的**执行行**：交给 S2 的冻结动作
+#      （一级/二级按当前 state 自动分流，见 _leave_flow_apply_state）；
+#      leave_set_state 另接受 new_state=='send_back'（§3.1 二级退回一级）。
+#   4) _leave_steps：加 'pending_second' 一档（§3.1）。
+#   5) leave_detail：state_label 多一档 + 给模板传 transfer_users / leave_stage。
+#   6) child_leave_save：§7.5 门户侧硬拒（学生侧同判据，落在 batch3.py）。
+#
+# ⚠ 与 S2 的接口约定（**只调用，不实现**）：edu.leave 上的
+#   can_user_act / action_first_approve / action_second_approve / action_refuse /
+#   action_send_back / action_transfer / action_confirm_return / transfer_candidates
+#   （route_of 归模型内部使用，门户侧不需要）。一律经 leave_flow_action() 取用：
+#   拿到 ⇒ 走 S2；拿不到 ⇒ fail-closed（不写字段、不猜语义）。唯一例外是
+#   leave_set_state 的 approved/refused —— 那里回退到本文件原有的直写实现
+#   （逐字保留），保证 S2 落地前后既有功能零回归。
+#
+# ⚠ 留痕归属（队长 2026-09-25 裁决）：S2 的动作**内部已含**审计与通知
+#   （action_transfer = 转交行 + 改写应批人 + 「请假审批转交」审计 + 三方通知；
+#   action_first/second_approve / action_refuse = 状态 + 审批留痕 +
+#   「请假审批」审计 + 申请人通知）⇒ 控制器**一律不重复写**，只在回退路径补。
+#
+# ⚠ 命名不一致（留档，防联调扯皮）：设计稿 §10 写 transfer()、§3.2 写模块级
+#   route_of(leave)；队长清单写 action_transfer / edu.leave.route_of(self)。
+#   本段对转交**两个名字都兼容**（action_transfer 优先，transfer 兜底）。
+# ===========================================================================
+
+# 身份反查唯一口径：本段要用「档案 → 账号」的反向并集（§4.3(1)② 判「是不是
+# 申请人本人」、§7.1 判「是不是本人/家长」）。文件顶部那条 import 只带了正向
+# 反查，故在此**追加**一个 import，不改既有 import 行（# noqa: E402：本仓先例
+# main.py:338 也是非顶部 import）。
+from odoo.addons.edu_schedule.models.identity import users_of_profile  # noqa: E402
+
+
+# ---------------------------------------------------------------------------
+# 判据层（唯一事实源；路由与模板都从这里取）
+# ---------------------------------------------------------------------------
+def leave_applicant_kind(env=None):
+    """当前登录账号的请假身份（§5.3 唯一口径）：'student' / 'parent' / 'staff'。
+
+    判定只走 edu_schedule/models/identity.py 的**双向并集**反查：
+      · op.student 非空      ⇒ 'student'（学生在 /my/time_off 看到学生单）
+      · 否则 op.parent 非空  ⇒ 'parent'（家长为孩子请假，**不是**教职单）
+      · 两者皆空             ⇒ 'staff'（教职单）
+    **不依赖 op.faculty 存在**、**不看 share**：本仓 teacher@local 正是门户账号
+    且 share=True，用 share 判会把它错判成学生（§5.3 的显式反例）。
+    """
+    env = request.env if env is None else env
+    if profile_of_user(env, 'op.student'):
+        return 'student'
+    if profile_of_user(env, 'op.parent'):
+        return 'parent'
+    return 'staff'
+
+
+def leave_stage_of_state(state):
+    """单据当前处于哪一级（§3.1）：request → 一级；pending_second → 二级。
+
+    其它状态（approved/refused）**没有待批级** ⇒ 返回 None（转交与审批都按
+    「不在该级」处理）。这是「我能不能批这一级」的唯一入口。
+    """
+    return {'request': 'first', 'pending_second': 'second'}.get(state or '')
+
+
+def leave_portal_approver(env=None):
+    """教师侧请假页的准入判据（§8.1）：有教师档案 ∪ privileged_staff ∪ 有我的待批单。
+
+    最后一档是 §3.3 硬要求的落点：「没有班主任也能跑」「老师到位后只填数据即
+    生效」—— op.batch.homeroom_teacher_id 存的是 res.users，而本仓 op.faculty
+    0 个在职行，班主任完全可能没有教师档案。沿用「无教师档案 ⇒ 回 /my/home」
+    的老门槛，会让这批人连队列都进不去（功能对最主要的使用者静默失效）。
+    """
+    if privileged_staff():
+        return True
+    if current_faculty():
+        return True
+    env = request.env if env is None else env
+    return bool(env['edu.leave'].sudo().search_count(
+        ['|', ('first_approver_id', '=', env.uid),
+         ('second_approver_id', '=', env.uid)]))
+
+
+def leave_applicant_users(leave):
+    """本单申请人名下的登录账号（§4.3(1)② / §7.1 的判据；**不用 partner**）。
+
+    · 学生单：student_id → 账号（identity.py 的「档案 → 账号」三条来源并集）；
+    · 教职单：applicant_user_id 本身。
+    判「是不是申请人本人」必须用这个集合：同一 partner 可能挂多个账号，也可能
+    挂着程序化创建的账号，用 partner 判会漏（本仓身份反查踩过两次）。
+    """
+    users = leave.env['res.users'].sudo().browse()
+    if leave.student_id:
+        users |= users_of_profile(leave.student_id.sudo())
+    if leave.applicant_user_id:
+        users |= leave.applicant_user_id.sudo()
+    return users
+
+
+def leave_backdated_guard(raw_date):
+    """§7.5 门户侧硬拒判据：date_from < 提交日 ⇒ True。
+
+    边界（设计稿逐字）：**今天请假、今天提交**（date_from == today）允许 ——
+    只有严格早于今天才算「事后补假」。解析失败返回 False（交给既有日期解析
+    分支处理，不抢它的活）。
+    """
+    try:
+        day = fields.Date.to_date(raw_date) if raw_date else None
+    except Exception:
+        return False
+    return bool(day) and day < fields.Date.today()
+
+
+def leave_flow_action(rec, name):
+    """取 S2 在 edu.leave 上的冻结动作；**没有就返回 None**（调用方必须 fail-closed）。
+
+    为什么要这个薄壳：接口是**并行开发**的冻结契约，控制器不能假设它一定已经
+    落地（否则升级窗口里一按按钮就是 500）。取不到 = 功能不可用 = 什么字段都
+    不写（绝不猜语义、绝不自己实现一份模型逻辑）。
+    """
+    fn = getattr(rec, name, None)
+    return fn if callable(fn) else None
+
+
+def leave_transfer_candidates(rec, stage):
+    """§4.3(1)：这一级的**合法转入人**（res.users），S2 冻结接口的输出。
+
+    接口未就绪 / 抛错 ⇒ 空集（= 转交入口隐藏、POST 也会被挡）：绝不 fail-open
+    到「谁都能转」。再叠一层 §4.3(1)①② 的控制器侧过滤（自己、申请人本人）——
+    候选集合的口径在模型（唯一事实源），控制器只做**收窄**不做放大。
+    """
+    empty = rec.env['res.users'].sudo().browse()
+    if not stage:
+        return empty
+    fn = leave_flow_action(rec, 'transfer_candidates')
+    if not fn:
+        return empty
+    try:
+        users = fn(stage)
+    except Exception:
+        _logger.warning('edu_portal: transfer_candidates(%s) 调用失败，'
+                        '转交入口按不可用处理', stage, exc_info=True)
+        return empty
+    users = (users or empty).sudo()
+    banned = set(leave_applicant_users(rec).ids) | {rec.env.uid}
+    return users.filtered(lambda u: u.id not in banned)
+
+
+def _leave_can_act(rec, user, stage=None):
+    """§8.1：我能不能批这一单的**当前这一级**。
+
+    优先 S2 的冻结接口 can_user_act(user)（它内含 privileged_staff 恒可批的
+    既有例外）；接口缺席时退到 §8.1 的逐字判据
+    （user == 当前级 approver_id **or** privileged_staff()）。
+    两条路都 fail-closed：判不出来就是「不能」。
+    """
+    fn = leave_flow_action(rec, 'can_user_act')
+    if fn:
+        try:
+            return bool(fn(user))
+        except Exception:
+            _logger.warning('edu_portal: can_user_act 调用失败，按无权处理',
+                            exc_info=True)
+            return False
+    if privileged_staff():
+        return True
+    field = {'first': 'first_approver_id',
+             'second': 'second_approver_id'}.get(
+                 stage or leave_stage_of_state(rec.state) or '')
+    if not field:
+        return False
+    approver = rec[field]
+    return bool(approver and user and approver.id == user.id)
+
+
+def _leave_can_transfer(rec, user, stage):
+    """§4.4：谁能转交 —— **严格**是「本单当前这一级的应批人」本人。
+
+    ⚠ 刻意**不含** privileged_staff 例外：§8.1 把「转交」单列一行，判据是
+    user 属于 {first_approver_id, second_approver_id}。教务处/系统组「恒可批」，
+    但转交是把自己的待办让渡出去，不等于可以把别人的待办转走。
+
+    优先 S2 的冻结实现 can_user_transfer(user)（它还多查「该级是否已转过」）；
+    缺席时用本函数下方的逐字判据（fail-closed）。
+    """
+    fn = leave_flow_action(rec, 'can_user_transfer')
+    if fn:
+        try:
+            return bool(fn(user))
+        except Exception:
+            _logger.warning('edu_portal: can_user_transfer 调用失败，按不可转处理',
+                            exc_info=True)
+            return False
+    field = {'first': 'first_approver_id',
+             'second': 'second_approver_id'}.get(stage or '')
+    if not field or not user:
+        return False
+    approver = rec[field]
+    return bool(approver and approver.id == user.id)
+
+
+def leave_portal_context():
+    """门户自助提交标记（§7.5）：S2 的 _portal_submission() 优先看这个 context。
+
+    为什么必须带上：判据的兜底是「创建者不是特权账号」，而**教务/管理员本人**
+    在门户里提交时是特权账号 —— 不带这个标记，他的单会被模型当成「后台代录」
+    通道（backfilled=True），§7.5 的硬拒在他身上静默失效。
+    """
+    try:
+        from odoo.addons.edu_portal.models.leave_flow import CTX_PORTAL
+        return {CTX_PORTAL: True}
+    except Exception:
+        return {}
+
+
+def leave_proof_kind(post):
+    """§7.2 的证明方式（表单字段 → 模型 selection，非法值一律 'none'）。"""
+    kind = (post.get('proof_kind') or '').strip()
+    return kind if kind in ('file', 'oral', 'none') else 'none'
+
+
+def leave_proof_vals(post):
+    """§7.2：门户证明字段 → create 的 vals（S2 的 create 校验读的就是这三个）。"""
+    return {
+        'proof_kind': leave_proof_kind(post),
+        'oral_proof_by': (post.get('oral_proof_by') or '').strip()[:64] or False,
+        'oral_proof_relation': (post.get('oral_proof_relation') or '').strip()[:32]
+                               or False,
+    }
+
+
+def leave_attach_proof_file(leave, post):
+    """§7.2 文件证明：把门户上传的文件落成 ir.attachment(res_model/res_id)。
+
+    为什么只能在**建单后**落库：attachment_ids 是 o2m 到 ir.attachment 的
+    （res_id 指向已存在的单据）—— 建单那一刻必然还是空的。
+    """
+    import base64
+    upload = post.get('proof_file') or post.get('attachment')
+    if not upload or not getattr(upload, 'filename', None):
+        return None
+    try:
+        data = upload.read()
+    except Exception:
+        _logger.warning('edu_portal: 证明附件读取失败 leave=%s', leave.id,
+                        exc_info=True)
+        return None
+    if not data:
+        return None
+    return leave.env['ir.attachment'].sudo().create({
+        'name': upload.filename,
+        'datas': base64.b64encode(data),
+        'res_model': 'edu.leave',
+        'res_id': leave.id,
+    })
+
+
+def leave_check_proof(leave):
+    """调 S2 的附件复核（§7.2：proof_kind='file' 却一个附件都没有 ⇒ UserError）。
+
+    S2 的 docstring 明确「S3/S4 在上传完成后调用本方法」—— 动作缺席时跳过
+    （不 500；证明校验的最终责任仍在模型侧）。
+    """
+    check = leave_flow_action(leave, '_check_proof_attachments')
+    if check:
+        return check()
+    return None
+
+
+def _leave_flow_notice(text, back='/leave/approvals'):
+    """带用户可见提示的回跳（复用既有 ?bulk_msg= 回执位，模板已渲染）。"""
+    return '%s%cbulk_msg=%s' % (back, '&' if '?' in back else '?',
+                                quote(text[:200]))
+
+
+def _leave_flow_apply_state(rec, new_state, reason, was_pending=None):
+    """把门户的「同意 / 驳回 / 二级退回」落到 S2 的冻结动作上（§3.1 状态机）。
+
+    为什么必须有这一层（而不是在路由里直接 write state）：
+      · 一级通过后到底是 approved 还是 pending_second，由 need_second
+        （§3.2 route_of + §7.4 over_quota）决定 —— 那是**模型**的判定，
+        控制器复制一份必然走样（4 天的单会被直接终审）；
+      · 二级退回（pending_second → request）只有模型知道
+        second_sent_back_at / second_send_back_reason 与清空 second_approver_id。
+    动作内部守卫是 fail-loud（state 不匹配抛 UserError）⇒ 本函数不吞异常，
+    让错误如实暴露，而不是静默 no-op。
+
+    返回值：'action'（已由 S2 动作执行：状态 + 审批留痕 + 审计 + 通知都归它）/
+    'legacy'（回退既有直写，并在 was_pending 时补既有通知）/ 'noop'。
+    """
+    if new_state == 'send_back':
+        fn = leave_flow_action(rec, 'action_send_back')
+        if not fn:
+            return 'noop'            # 'send_back' 不是状态值 ⇒ 没有动作就绝不写
+        fn(reason)
+        return 'action'
+    if new_state == 'approved':
+        name = 'action_second_approve' if rec.state == 'pending_second' else 'action_first_approve'
+    else:
+        name = 'action_refuse'
+    fn = leave_flow_action(rec, name)
+    if fn:
+        if new_state == 'refused':
+            fn(reason)
+        else:
+            fn()
+        return 'action'
+    # —— S2 动作缺席：逐字沿用本文件既有实现，保证升级窗口内既有功能零回归 ——
+    if new_state == 'refused' and reason:
+        rec.write({'reject_reason': reason})
+    vals = {'state': new_state}
+    vals.update(rec._approver_vals())
+    rec.write(vals)
+    if was_pending:
+        rec._notify_applicant(new_state)
+    return 'legacy'
+
+
+# ---------------------------------------------------------------------------
+# 门户动作面（§4.4 转交 / §7.1 销假）
+# ---------------------------------------------------------------------------
+class EduLeaveFlowPortal(http.Controller):
+    """请假分级审批的两条新门户路由（S3）。
+
+    两条都是 POST + csrf=True（S4 的表单带 token），并各挂一个 GET 出口：
+      · 未登录 GET ⇒ Odoo 的 auth='user' 先接管 ⇒ 303 跳登录（既不是 500，
+        也不是 405 —— 探测/误点不会把页面打成错误码）；
+      · 已登录 GET ⇒ 303 回跳且**不写任何字段**（不做「GET 也能改状态」的坏事）。
+    """
+
+    @http.route('/leave/transfer', type='http', auth='user', website=True,
+                methods=['GET', 'POST'], csrf=True)
+    def leave_transfer(self, **post):
+        """转交审批（§4.3 四条规则 + §4.4 动作面）。
+
+        字段（S4 的表单已写死）：leave_id / stage / to_user_id / reason / next。
+        守卫顺序（**每一步都 fail-closed，任何一步不过都不写字段**）：
+          ① 越权/不存在 ⇒ 按不存在处理（沿用 scoped_record 的既有口径）；
+          ② 当前级由**单据 state** 决定，不信表单的 stage（防伪造）；
+          ③ 只有本级应批人**本人**能转（教务处可批但不可替人转，§4.4）；
+          ④ 只能转 1 次（入口预检；并发双转由 DB UNIQUE(leave_id, stage) 兜底）；
+          ⑤ 转入人必须存在、不是自己、不是申请人、且仍在候选集合内（二次校验）；
+          ⑥ 执行 S2 的 action_transfer —— 四层留痕（转交行 / 应批人改写 /
+             「请假审批转交」审计 / 三方通知）**全在动作内部**（队长裁决），
+             控制器**一律不重复写**；另做一次「转交行是否真落下」的自证。
+        """
+        back = post.get('next') or ''
+        if not back.startswith('/leave/'):
+            back = '/leave/approvals'
+        if request.httprequest.method != 'POST':
+            return request.redirect(back)
+        env = request.env
+        try:
+            lid = int(post.get('leave_id', 0))
+        except (TypeError, ValueError):
+            lid = 0
+        reason = (post.get('reason') or '').strip()[:500]
+        if not reason:
+            return request.redirect(_leave_flow_notice(
+                '转交必须填写原因（留痕三要素：谁转给谁、何时、为什么）'))
+        rec = scoped_record(env, 'edu.leave', lid)
+        if not rec.exists():
+            return request.redirect(back)
+        stage = leave_stage_of_state(rec.state)
+        posted_stage = (post.get('stage') or '').strip()
+        if not stage or (posted_stage and posted_stage != stage):
+            return request.redirect(_leave_flow_notice(
+                '该单据当前不在你提交的审批级上，页面已刷新'))
+        if not _leave_can_transfer(rec, env.user, stage):
+            return request.redirect(back)
+        Transfer = env['edu.leave.transfer'].sudo()
+        if Transfer.search_count([('leave_id', '=', rec.id),
+                                  ('stage', '=', stage)]):
+            return request.redirect(_leave_flow_notice(
+                '该单据该级已转交过 1 次，不能再次转交'))
+        raw_to = post.get('to_user_id')
+        Users = env['res.users'].sudo()
+        to_user = Users.browse(int(raw_to)) if str(raw_to or '').isdigit() else Users.browse()
+        if not to_user.exists() or to_user.id == env.user.id:
+            return request.redirect(_leave_flow_notice(
+                '不能转交给自己，请重新选择转入人'))
+        if to_user.id in leave_applicant_users(rec).ids:
+            return request.redirect(_leave_flow_notice('不能转交给申请人本人'))
+        candidates = leave_transfer_candidates(rec, stage)
+        if not candidates or to_user not in candidates:
+            return request.redirect(_leave_flow_notice(
+                '该账号不在本级合法转入人范围内，请重新选择'))
+        action = (leave_flow_action(rec, 'action_transfer')
+                  or leave_flow_action(rec, 'transfer'))
+        if not action:
+            _logger.warning(
+                'edu_portal: 转交动作未就绪（edu.leave.action_transfer 缺失），'
+                '已 fail-closed：leave=%s 未写任何字段', rec.id)
+            return request.redirect(_leave_flow_notice('转交功能尚未就绪，请稍后再试'))
+        rec_id, rec_name = rec.id, rec.name or ''
+        from_user = env.user
+        try:
+            action(to_user, reason)
+        except pg_errors.UniqueViolation:
+            # §4.3(3)：并发双转撞 UNIQUE(leave_id, stage) ⇒ 整事务回滚后再回队列
+            # （REPEATABLE READ 下必须结束当前事务，否则重查永远看不见对手；
+            #  本仓同款先例 edu_tg_bind/models/tg_claim.py）
+            env.cr.rollback()
+            env.invalidate_all(flush=False)
+            _logger.info('edu_portal: 转交并发冲突（leave=%s stage=%s），已回滚',
+                         rec_id, stage)
+            return request.redirect(_leave_flow_notice(
+                '该单据该级已转交过 1 次，不能再次转交'))
+        if not Transfer.search_count([('leave_id', '=', rec_id),
+                                      ('stage', '=', stage)]):
+            _logger.warning(
+                'edu_portal: action_transfer 未落下转交行（leave=%s stage=%s），'
+                '按未执行处理', rec_id, stage)
+            return request.redirect(_leave_flow_notice('转交未生效，请稍后重试'))
+        return request.redirect(back)
+
+    @http.route('/leave/<int:leave_id>/return_confirm', type='http',
+                auth='user', website=True, methods=['GET', 'POST'], csrf=True)
+    def leave_return_confirm(self, leave_id, **post):
+        """销假（§7.1）：学生/家长提交「行程及实践收获」→ 班主任/教务确认。
+
+        同一条路由两跳（S4 的表单）：
+          · 提交侧：return_note，判据 = **本人/家长**（不看审批权）；
+          · 确认侧：confirm=1，判据 = 本级应批人 or privileged_staff（§8.1），
+            执行 S2 的 action_confirm_return（return_confirmed_at/by 由它写）。
+        销假是**正交字段**、**不改 state** —— 做成第五个状态会打断既有三档筛选、
+        首页计数与 _leave_steps()（§7.1）。两跳都 fail-closed：判不出来就回门户，
+        不写任何字段。
+        """
+        if request.httprequest.method != 'POST':
+            return request.redirect('/my/home')
+        env = request.env
+        try:
+            rec = env['edu.leave'].sudo().browse(int(leave_id or 0))
+        except (TypeError, ValueError):
+            rec = env['edu.leave'].sudo().browse()
+        if not rec.exists():
+            return request.redirect('/my/home')
+        note = (post.get('return_note') or post.get('note') or '').strip()[:2000]
+        confirm = str(post.get('confirm') or '') in ('1', 'true', 'True',
+                                                     'on', 'yes')
+        user = env.user
+        is_applicant = user.id in leave_applicant_users(rec).ids
+        # 两跳的判据（§8.1）：确认侧 = 本级应批人 or privileged_staff；
+        # 提交侧 = 本人/家长。判不出来一律回门户、不写字段。
+        if confirm:
+            if not _leave_can_act(rec, user):
+                return request.redirect('/my/home')
+        elif not is_applicant:
+            return request.redirect('/my/home')
+        action = leave_flow_action(rec, 'action_confirm_return')
+        if action:
+            # S2 的动作**一个入口两种角色**（申请人写 return_note；审批人写
+            # return_confirmed_at/by），留痕、审计与「已到期才能销假」的校验都在
+            # 模型里（唯一事实源）⇒ 控制器不重复写任何字段、不重复写审计。
+            confirmed = action(note)
+            if confirm or confirmed:
+                return request.redirect('/leave/approvals')
+            return request.redirect('/my/time_off?box=return_submitted')
+        # —— 动作缺席（并行开发安全网）：只有「申请人提交说明」这一跳可以按
+        #    §7.1 直写 return_note 一个字段；审批人确认那一跳**绝不直写**
+        #    （return_confirmed_* 是裁决留痕，只能由模型动作落）——
+        if confirm or rec.state != 'approved':
+            _logger.warning('edu_portal: action_confirm_return 未就绪，'
+                            '销假 fail-closed：leave=%s 未写任何字段', rec.id)
+            return request.redirect(_leave_flow_notice(
+                '销假功能尚未就绪，请稍后再试', '/my/time_off'))
+        rec.write({'return_note': note})
+        env['edu.audit.log'].sudo()._log(
+            '请假销假', 'edu.leave', rec.id, rec.name or '',
+            '提交销假说明%s' % ('：%s' % note[:60] if note else ''))
+        return request.redirect('/my/time_off?box=return_submitted')
diff --git a/custom_addons/edu_portal/views/roles.xml b/custom_addons/edu_portal/views/roles.xml
index edefb54..d66224e 100644
--- a/custom_addons/edu_portal/views/roles.xml
+++ b/custom_addons/edu_portal/views/roles.xml
@@ -621,10 +621,10 @@
                                 </td>
                                 <td><a t-attf-href="/leave/approvals/#{lv.id}" class="text-decoration-none" t-out="lv.name or ('#' + str(lv.id))"/></td>
                                 <td t-out="lv.student_id.name"/>
-                                <td t-out="{'sick': '病假', 'legal': '法定假期', 'casual': '事假', 'other': '其他'}.get(lv.leave_type, lv.leave_type)"/>
+                                <td t-out="{'sick': '病假', 'legal': '法定假期', 'casual': '事假', 'other': '其他', 'marriage_funeral': '婚丧假', 'winter_summer': '寒暑假', 'practice_week': '实践周'}.get(lv.leave_type, lv.leave_type)"/>
                                 <td><t t-out="lv.date_from"/> ~ <t t-out="lv.date_to"/></td>
-                                <td><span t-att-class="'badge ' + {'request': 'text-bg-warning', 'approved': 'text-bg-success', 'refused': 'text-bg-danger'}.get(lv.state, 'text-bg-secondary')"
-                                          t-out="{'request': '待审批', 'approved': '已通过', 'refused': '已拒绝'}.get(lv.state, lv.state)"/></td>
+                                <td><span t-att-class="'badge ' + {'request': 'text-bg-warning', 'approved': 'text-bg-success', 'refused': 'text-bg-danger', 'pending_second': 'text-bg-info'}.get(lv.state, 'text-bg-secondary')"
+                                          t-out="{'request': '待审批', 'approved': '已通过', 'refused': '已拒绝', 'pending_second': '待二级审批'}.get(lv.state, lv.state)"/></td>
                                 <!-- 需求⑥：记录上必须显示「由课代表 X 审批」/「由任课老师 X 审批」 -->
                                 <td class="small text-muted" t-out="lv.approver_label()"/>
                                 <td class="text-end">
```

## 4.6.3 最终版本端到端实测（原始输出）：未登录 / csrf / §7.5 / 空日期 / 转交+A8 / 分级 / 分流 / 类型

```text
########## A. 未登录访问新路由（应 303/302 跳登录，不是 500）##########
GET  /leave/transfer              -> 303 http://localhost:8069/web/login?redirect=%2Fleave%2Ftransfer%3F
POST /leave/transfer              -> 303 http://localhost:8069/web/login?redirect=%2Fleave%2Ftransfer%3F
GET  /leave/100000/return_confirm -> 303 http://localhost:8069/web/login?redirect=%2Fleave%2F100000%2Freturn_confirm%3F

########## B. 缺 csrf token 的 POST（应拒绝，不是 500）##########
POST /leave/transfer 无 csrf         -> 400
POST /leave/1/return_confirm 无 csrf -> 400

########## C. §7.5 事后补假（应拒绝、不落库）##########
POST /my/time_off/save (date_from=2026-09-23) -> 422
   edu_leave 行数 before=30 after=30 ; 本次落库=0 ; 响应含条例原文=1

########## D. 空日期（修复前 500；现 303 回 error_date）##########
POST /my/time_off/save (空日期) -> 303 http://localhost:8069/my/time_off?box=error_date

########## E. 转交 + A8 + 分级状态机（临时夹具：op_batch(8).homeroom_teacher_id=11，跑完立刻还原）##########
POST /my/time_off/save (2 天) -> 303
-- E.1 提交后（一级应批人 = 班主任 11）--
449 | SLR000102 | request | first=11 | transfers=0
-- E.2 A7 转交：fac(11) -> bo(12) --
POST /leave/transfer -> 303 http://localhost:8069/leave/approvals/449
449 | request | first=12 | transfers=1
请假审批转交 | 一级：预备科导师【演示】 -> 教务专员；原因：S3-REPORT 转交给教务
transfer row: stage=first from=11 to=12 reason=S3-REPORT 转交给教务
-- E.3 A8 负向：原审批人 fac 再 POST /leave/set_state --
POST /leave/set_state (fac) -> 303 http://localhost:8069/leave/approvals/449
   state: request -> request ; audit 行数: 2 -> 2 ; approver_id=(空)
-- E.4 可见性 vs 处置权：fac 仍看得见（§8.2 可见域），但不能批（§4.3(2) 动作判据）--
   GET /leave/approvals (fac) -> 200 ; 列表含本单=
   GET /leave/approvals/449 (fac) -> 200
-- E.5 转入人 bo 现在可以批 --
POST /leave/set_state (bo) -> 303 http://localhost:8069/leave/approvals/449
449 | approved | approver=12 | kind=registrar
-- E.6 分级：4 天单 ⇒ 一级通过后 pending_second --
POST /my/time_off/save (4 天) -> 303
POST /leave/set_state 一级通过 (4 天) -> 303
450 | days=4 | pending_second | first=11 | second=2
   夹具已还原：op_batch(8).homeroom_teacher_id = NULL

########## F. 身份分流（§5.3/§8.1）##########
GET /my/time_off (stu) -> 200 
GET /my/time_off (bo) -> 200 
GET /my/time_off (fac) -> 200 
GET /my/time_off (par) -> 303 http://localhost:8069/my/child
   stu 正文: 学生表单=1 教职标题=0
   bo  正文: 学生表单=0 教职标题=1

########## G. §6 类型白名单 / 中文标签（新 code 不降级、不裸奔）##########
   marriage_funeral -> 落库 marriage_funeral
   winter_summer -> 落库 winter_summer
   practice_week -> 落库 practice_week
   bogus_code -> 落库 other
   3 待二级审批
   1 寒暑假
   2 婚丧假
   1 实践周
```
