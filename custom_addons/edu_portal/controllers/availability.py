# -*- coding: utf-8 -*-
"""教师自助：不可用时间 `/my/availability`（排课链路 §10.2 的教师侧入口）。

零新模型 / 零新表：数据实体就是 `resource.calendar.leaves` ——
    resource_id       = 该教师的资源（op.faculty.resource_id 由 S1 的 resource.mixin 提供）
    date_from/date_to = 不可用区间（库内 UTC 朴素 Datetime）
    time_type         = 'leave'
    name              = 原因（按周展开的还带批次标记前缀）

「按周重复」不是实体：保存时把一条录入**展开成多条 leaves**，
name 统一以「【批次 <14 位码>】」开头 ⇒ 整批可撤销（前缀约定，不新建模型）。

ⓘ 依赖 S1 可能尚未落盘（op.faculty 还没有 resource_id）——
这里**探测 `_fields` 优雅降级**：未接线时页面给说明、写路由一律拒绝、绝不 500。
"""
import re
from datetime import date, datetime, time, timedelta

from odoo import fields, http
from odoo.http import request

from .roles import current_faculty

LEAVES_MODEL = 'resource.calendar.leaves'
WEEKDAYS = [('0', '周一'), ('1', '周二'), ('2', '周三'), ('3', '周四'),
            ('4', '周五'), ('5', '周六'), ('6', '周日')]
WEEKDAY_LABEL = dict(WEEKDAYS)
# 批次标记：名称前缀约定（不是模型、不是字段）
BATCH_MARK = '【批次 %s】'
BATCH_RE = re.compile(r'^【批次 (\d{14})】')
# 单次「按周重复」最多展开的条数：防手滑写出天量记录（截止日期很远时）
MAX_EXPAND = 200
DEFAULT_REASON = '个人事务'

# 页面提示（box 查询参数 → 红/绿提示文案由模板按 key 分支，控制器不拼 HTML）
BOX_MSG = {
    'saved': '已登记：本条不可用时间已写入。',
    'updated': '已更新：本条不可用时间已修改。',
    'deleted': '已删除：该条不可用时间已移除。',
    'batch_deleted': '已撤销：该批按周重复的不可用时间已整批移除。',
    'nowire': '教师资源尚未接线，暂时无法登记（系统只做了只读展示）。',
    'noresource': '你的教师档案还没有关联资源，暂时无法登记；请联系教务处补建教师资源。',
    'badtime': '起止时刻不合法：结束时刻必须晚于开始时刻。',
    'baddate': '日期不合法：请按「年-月-日」填写，且不要早于今天。',
    'badweekday': '星期几不合法。',
    'toomany': '展开后的条数超过 %d 条，请把截止日期改近一些。' % MAX_EXPAND,
    'gone': '该记录已不存在或不属于你，未做任何修改。',
}
BOX_ERROR = ('nowire', 'noresource', 'badtime', 'baddate',
             'badweekday', 'toomany', 'gone')


# ---------------------------------------------------------------------------
# 小工具：身份 / 时区 / 解析
# ---------------------------------------------------------------------------
def _faculty_and_resource(env):
    """(教师档案, 教师资源, resource_id 字段是否已接线)。

    四态：无教师档案 / 字段未接线（S1 未落盘）/ 已接线但该教师资源为空
    （存量档案待迁移）/ 正常。写路由对前三种一律拒绝，绝不 500。
    """
    faculty = current_faculty()
    if not faculty:
        return None, None, False
    wired = 'resource_id' in env['op.faculty']._fields
    resource = faculty.resource_id if wired else None
    return faculty, (resource if resource else None), wired


def _to_utc(env, local_naive):
    """本地朴素时刻 → UTC 朴素时刻。

    不引 pytz/zoneinfo：用 context_timestamp 反推当前用户的时区偏移
    （偏移取「把本地值当 UTC」那一刻的偏移，跨夏令时切换日有秒级误差，
    对「某日某时段不可用」这类登记足够）。
    """
    if not local_naive:
        return None
    user = env['res.users'].browse(env.uid)
    probe = fields.Datetime.to_string(local_naive)
    seen = fields.Datetime.context_timestamp(
        user, fields.Datetime.to_datetime(probe))
    return local_naive - (seen.replace(tzinfo=None) - local_naive)


def _local(env, dt_utc):
    """库内 UTC 朴素时刻 → 当前用户本地朴素时刻（展示用）。"""
    if not dt_utc:
        return None
    user = env['res.users'].browse(env.uid)
    return fields.Datetime.context_timestamp(user, dt_utc).replace(tzinfo=None)


def _to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_hm(value):
    """'HH:MM' → datetime.time（容错 'H:MM' / 'HH:MM:SS'）。"""
    raw = (value or '').strip()
    parts = raw.split(':')
    if len(parts) < 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def _parse_day(value):
    raw = (value or '').strip()
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


def _batch_code(name):
    """名称 → 批次码（非批次名称返回 ''）。"""
    match = BATCH_RE.match(name or '')
    return match.group(1) if match else ''


def _reason_of(name):
    """名称 → 原因（剥掉批次标记前缀）。"""
    return BATCH_RE.sub('', name or '') or DEFAULT_REASON


def _leave_vals(env, resource, name, start_local, end_local):
    """一条 leaves 的字段值（区间是**本地**朴素时刻，写入前转 UTC）。"""
    return {
        'name': name,
        'resource_id': resource.id,
        'date_from': fields.Datetime.to_string(_to_utc(env, start_local)),
        'date_to': fields.Datetime.to_string(_to_utc(env, end_local)),
        'time_type': 'leave',
    }


def _my_leaves(env, resource):
    """本教师的不可用登记（读侧一份域，页内不再逐条查询）。"""
    return env[LEAVES_MODEL].sudo().search([
        ('resource_id', '=', resource.id),
        ('time_type', '=', 'leave'),
    ], order='date_from asc')


def _rows(env, leaves):
    """leaves → 页面行 + 批次摘要（一次遍历，模板只读 dict）。"""
    rows, batches = [], {}
    now = fields.Datetime.now()
    for lv in leaves:
        lo, hi = _local(env, lv.date_from), _local(env, lv.date_to)
        if not lo:
            continue
        code = _batch_code(lv.name)
        rows.append({
            'id': lv.id,
            'day_iso': lo.strftime('%Y-%m-%d'),
            'day': '%s %s' % (lo.strftime('%Y-%m-%d'),
                              WEEKDAY_LABEL.get(str(lo.weekday()), '')),
            'span': '%s–%s' % (lo.strftime('%H:%M'),
                               (hi or lo).strftime('%H:%M')),
            'start': lo.strftime('%H:%M'),
            'end': (hi or lo).strftime('%H:%M'),
            'reason': _reason_of(lv.name),
            'batch': code,
            'past': bool(lv.date_to and lv.date_to < now),
        })
        if code:
            batch = batches.setdefault(code, {
                'code': code, 'reason': _reason_of(lv.name), 'count': 0,
                'first': '', 'last': '', 'past': True})
            batch['count'] += 1
            day = lo.strftime('%Y-%m-%d')
            batch['first'] = min(batch['first'] or day, day)
            batch['last'] = max(batch['last'] or day, day)
            batch['past'] = batch['past'] and bool(lv.date_to
                                                   and lv.date_to < now)
    return rows, [batches[k] for k in sorted(batches)]


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
class EduAvailabilityPortal(http.Controller):
    """教师自助不可用时间：GET 列表 + 两个写路由（save / delete）。"""

    @http.route('/my/availability', type='http', auth='user', website=True)
    def my_availability(self, **kw):
        env = request.env
        faculty, resource, wired = _faculty_and_resource(env)
        if not faculty:
            # 本页是「教师本人」的功能页：非教师（学生 / 家长 / 无教师档案者）一律
            # 303 回门户，与全仓角色错配路由同口径（§13 V18）；不渲染说明页。
            # 闸门必须走 current_faculty()（双向并集）：教师档案可能只挂在链②
            # partner.user_id 上 —— 证据：user 11 的 partner 48 ≠ op_faculty 17 的 partner 32，
            # 只有 partner.user_id=11 → partner 32 才命中；改成只看 users.partner_id 会误 303 真教师。
            return request.redirect('/my/home', code=303)
        box = kw.get('box') or ''
        rows, batches = [], []
        if faculty and resource is not None:
            rows, batches = _rows(env, _my_leaves(env, resource))
        edit_id = _to_int(kw.get('edit'))
        edit_row = None
        if edit_id:
            edit_row = next((r for r in rows if r['id'] == edit_id), None)
        return request.render('edu_portal.edu_availability', {
            'title': '我的不可用时间',
            'page_name': 'availability',
            # 两态：已接线 / 未接线（未接线时页面只读 + 说明）；非教师已在更早处 303
            'wired': wired,
            # 已接线但本人资源为空（存量档案待迁移）——与「字段未接线」分开说明
            'resource_missing': bool(wired and faculty and resource is None),
            'ready': bool(wired and resource is not None),
            'faculty': faculty,
            'rows': rows,
            'rows_n': len(rows),
            'batches': batches,
            'batches_n': len(batches),
            'upcoming_n': len([r for r in rows if not r['past']]),
            'today': fields.Date.today().strftime('%Y-%m-%d'),
            'weekdays': WEEKDAYS,
            'edit_row': edit_row,
            'box': box,
            'box_msg': BOX_MSG.get(box, ''),
            'box_error': box in BOX_ERROR,
        })

    @http.route('/my/availability/save', type='http', methods=['POST'],
                auth='user', website=True, csrf=True)
    def my_availability_save(self, **post):
        """登记：单条（某日某时段）或按周重复（展开成多条 leaves）。"""
        env = request.env
        faculty, resource, wired = _faculty_and_resource(env)
        if not faculty:
            # 写路由同闸门：非教师直接 POST 也必须挡（§13 V18）
            return request.redirect('/my/home', code=303)
        if resource is None:
            # 未接线 / 资源为空：写侧一律拒绝（不猜资源、不 500）
            return request.redirect('/my/availability?box=%s'
                                    % (wired and 'noresource' or 'nowire'))
        Leaves = env[LEAVES_MODEL].sudo()
        reason = (post.get('reason') or '').strip()[:120] or DEFAULT_REASON
        start_hm = _parse_hm(post.get('start_time'))
        end_hm = _parse_hm(post.get('end_time'))
        if not start_hm or not end_hm or end_hm <= start_hm:
            return request.redirect('/my/availability?box=badtime')

        # 改：只认「自己的」那一条（域里带 resource_id，防越权改别人的登记）
        edit_id = _to_int(post.get('leave_id'))
        if edit_id:
            target = Leaves.search([('id', '=', edit_id),
                                    ('resource_id', '=', resource.id)], limit=1)
            if not target:
                return request.redirect('/my/availability?box=gone')
            day = _parse_day(post.get('date'))
            if not day:
                return request.redirect('/my/availability?box=baddate')
            target.write(_leave_vals(
                env, resource,
                '%s%s' % (BATCH_MARK % _batch_code(target.name), reason)
                if _batch_code(target.name) else reason,
                datetime.combine(day, start_hm),
                datetime.combine(day, end_hm)))
            return request.redirect('/my/availability?box=updated')

        if (post.get('mode') or 'single') == 'weekly':
            weekday = _to_int(post.get('weekday'))
            if weekday is None or not (0 <= weekday <= 6):
                return request.redirect('/my/availability?box=badweekday')
            until = _parse_day(post.get('until'))
            today = date.today()
            if not until or until < today:
                return request.redirect('/my/availability?box=baddate')
            code = fields.Datetime.now().strftime('%Y%m%d%H%M%S')
            first = today + timedelta(days=(weekday - today.weekday()) % 7)
            vals_list, day = [], first
            while day <= until:
                vals_list.append(_leave_vals(
                    env, resource, BATCH_MARK % code + reason,
                    datetime.combine(day, start_hm),
                    datetime.combine(day, end_hm)))
                day += timedelta(days=7)
            if len(vals_list) > MAX_EXPAND:
                return request.redirect('/my/availability?box=toomany')
            Leaves.create(vals_list)
            return request.redirect('/my/availability?box=saved&n=%d'
                                    % len(vals_list))

        day = _parse_day(post.get('date'))
        if not day or day < date.today():
            return request.redirect('/my/availability?box=baddate')
        Leaves.create(_leave_vals(env, resource, reason,
                                  datetime.combine(day, start_hm),
                                  datetime.combine(day, end_hm)))
        return request.redirect('/my/availability?box=saved&n=1')

    @http.route('/my/availability/delete', type='http', methods=['POST'],
                auth='user', website=True, csrf=True)
    def my_availability_delete(self, **post):
        """删：单条（leave_id）或整批（batch = 14 位批次码）。"""
        env = request.env
        faculty, resource, wired = _faculty_and_resource(env)
        if not faculty:
            # 写路由同闸门：非教师直接 POST 也必须挡（§13 V18）
            return request.redirect('/my/home', code=303)
        if resource is None:
            return request.redirect('/my/availability?box=%s'
                                    % (wired and 'noresource' or 'nowire'))
        Leaves = env[LEAVES_MODEL].sudo()
        batch = (post.get('batch') or '').strip()
        if batch:
            if not (batch.isdigit() and len(batch) == 14):
                return request.redirect('/my/availability?box=gone')
            leaves = Leaves.search([
                ('resource_id', '=', resource.id),
                ('time_type', '=', 'leave'),
                ('name', '=like', BATCH_MARK % batch + '%')])
            if not leaves:
                return request.redirect('/my/availability?box=gone')
            leaves.unlink()
            return request.redirect('/my/availability?box=batch_deleted')
        leave_id = _to_int(post.get('leave_id'))
        leaf = Leaves.search([('id', '=', leave_id),
                              ('resource_id', '=', resource.id)], limit=1)
        if not leaf:
            return request.redirect('/my/availability?box=gone')
        leaf.unlink()
        return request.redirect('/my/availability?box=deleted')
