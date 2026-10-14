# -*- coding: utf-8 -*-
"""菜单收口执行器（t2）—— 声明式计划 → 只改 active / group_ids / parent_id / sequence。

红线（写死在代码里，不是注释里的建议）：
  · **禁止 delete**：本文件不含 unlink 调用（见文件末的 SELF_CHECK 断言）；
  · 只允许改 4 个字段：active / group_ids / parent_id / sequence；
  · **dry-run 绝不落库**：先记录原值 → 事务内试算 → `cr.rollback()` 还原 → **回读断言原值仍在**
    （"回滚了"必须是观察，不是声明）；
  · --apply 只提交一次，且提交前把"改前原值"整表写出（= 回滚依据）。

为什么 dry-run 用"事务内试算 + 回滚"而不是"自己实现一个可见性算法"：
  可见性口径必须**与 Odoo 官方一致**（组过滤 + action 存在性 + 模型 read 权限 + 父链补齐）。
  自己重写一份 = 两套口径，验收时对不上还得解释。事务试算跑的是真 `_visible_menu_ids()`。

用法（宿主侧包一层，见 scripts/consolidate_menus.sh）：
    MENU_PLAN_FILE=<plan.json> MENU_PLAN_MODE=dry-run|apply python3 - ...（stdin 进 odoo shell）

输出：stdout 是人类可读的计划表；最后一行为机器可读 JSON（MARKER::MENU_PLAN_JSON::）。
"""
import io
import json
import os
import sys

MODE = os.environ.get('MENU_PLAN_MODE', 'dry-run').strip()
PLAN_PATH = os.environ.get('MENU_PLAN_FILE', '').strip()
PLAN_TEXT = os.environ.get('MENU_PLAN_TEXT', '').strip()

if PLAN_TEXT:
    plan = json.loads(PLAN_TEXT)
elif PLAN_PATH:
    plan = json.load(io.open(PLAN_PATH, 'r', encoding='utf-8'))
else:
    raise SystemExit('缺 MENU_PLAN_TEXT / MENU_PLAN_FILE')

FIELDS = ('active', 'group_ids', 'parent_id', 'sequence')

# 预置钩子（可选）：在"构建目标态"之前执行一段表达式，用于评估**组改动**的影响面
#   （例：faculty 加入组 87 后，收口计划会把 B(faculty) 算成多少）。
#   只允许在 dry-run 下使用 —— apply 模式拒绝预置，防止"悄悄改权限"。
PRELOAD = os.environ.get('MENU_PLAN_PRELOAD', '').strip()
if PRELOAD and MODE != 'dry-run':
    raise SystemExit('MENU_PLAN_PRELOAD 只允许在 dry-run 下使用')
if PRELOAD:
    exec(PRELOAD, {'env': env, 'print': print})

Menu = env['ir.ui.menu'].sudo().with_context(active_test=False)
Users = env['res.users'].sudo()
G = env['res.groups'].sudo()

VISIBLE_SET = list(plan['group_policy']['visible_set'])
HIDDEN_SET = list(plan['group_policy']['hidden_set'])
CONTAINERS = {c['id']: c for c in plan['containers']}
MERGED = {m['id']: m for m in plan['merged']}
HIDDEN = {h['id']: h for h in plan.get('tier1_hidden_trees', plan.get('hidden', []))}
ADMIN_ONLY = {a['id']: a for a in plan.get('tier2_admin_only', [])}
KEPT_OFF = {k['id']: k for k in plan.get('kept_deactivated', [])}
MERGED_MODE = plan['group_policy'].get('merged_mode', 'reparent_then_deactivate')
UNMANAGED = {u['id']: u for u in plan.get('unmanaged', [])}
HIDDEN_MODE = plan['group_policy'].get('hidden_mode', 'restrict_only')
DESIRED = {}
DESIRED_WHY = {}


def descendants(menu):
    out, stack = [], list(menu.child_id)
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(cur.child_id)
    return out



def _mark(mid, why):
    DESIRED_WHY.setdefault(mid, why)

def build_desired():
    """把计划摊成 {menu_id: {field: value}} 的目标态。含所有后代。"""
    problems = []
    roots = Menu.search([('parent_id', '=', False)])
    root_ids = set(roots.ids)
    planned = (set(CONTAINERS) | set(MERGED) | set(HIDDEN) | set(ADMIN_ONLY)
               | set(KEPT_OFF) | set(UNMANAGED))
    unplanned = sorted(root_ids - planned)
    extra = sorted(planned - root_ids)
    if unplanned:
        problems.append('计划未覆盖的根菜单 id = %s' % unplanned)
    if extra:
        problems.append('计划里不是根菜单的 id = %s' % extra)

    # 1) 容器：激活；**groups 保持现状不动**（队长澄清：12 根是 backoffice 的验收线，faculty 不设硬线；
    #    容器各自现有组已能表达"教务/教师分野"，不新建组、不动组 87 的 251 条引用）。
    for mid, c in CONTAINERS.items():
        _mark(mid, '容器')
        DESIRED.setdefault(mid, {})['active'] = True
        if VISIBLE_SET:
            DESIRED[mid]['group_ids'] = VISIBLE_SET

    # 1.5) 容器组的**唯一例外**（队长 (b′))：300 招生 += 87（否则合并 591 后教务看不到「入学申请/报名表设置」）
    for exc in plan.get('container_group_exceptions', []):
        mid = exc['id']
        cur = sorted(Menu.browse(mid).group_ids.ids)
        want = sorted(set(cur + list(exc.get('add_groups', [])))
                      - set(exc.get('remove_groups', [])))
        if want != cur:
            DESIRED.setdefault(mid, {})['group_ids'] = want
        # 接收归并进来的根：把子项挂过来
        for child_root in c['children']:
            src = Menu.browse(child_root)
            for ch in src.child_id:
                DESIRED.setdefault(ch.id, {})['parent_id'] = mid

    # 2) 合并：子树先迁到容器（见上），**再整根 active=False**（队长裁定 merged_mode=reparent_then_deactivate）
    #    合并后这些根本身就是空壳；停用它们，admin 也不会多算。
    #    注意：子项**不**收窄组 —— 队长口径是"教师功能一个没少"，收窄会误伤（实测 341 的教学子项
    #    教师原本就可见；341 挂 [59 用户, 60 经理]，faculty 有 59 ⇒ 命中）。
    for mid, m in MERGED.items():
        _mark(mid, '合并根')
        root = Menu.browse(mid)
        DESIRED.setdefault(mid, {})['active'] = False
        if MERGED_MODE == 'shrink_group':
            for n in [root] + descendants(root):
                DESIRED.setdefault(n.id, {})['group_ids'] = VISIBLE_SET

    # 3) 档1 彻底隐藏（含超管）
    #    两种模式：
    #      restrict_only     —— 整棵收窄到 [group_system]（只挡非超管；实测会让 admin 多解锁原被
    #                           权限挡住的子项，故不作为默认）
    #      deactivate_tree   —— 整棵 active=False（默认；不给任何人，且不动 admin 原有可见面）
    for mid, h in HIDDEN.items():
        _mark(mid, '档1根')
        root = Menu.browse(mid)
        DESIRED.setdefault(mid, {})['group_ids'] = HIDDEN_SET
        if HIDDEN_MODE == 'deactivate_tree':
            for n in [root] + descendants(root):
                DESIRED.setdefault(n.id, {})['active'] = False
            DESIRED[mid]['active'] = False
        else:
            DESIRED[mid]['active'] = bool(root.active)
            for n in [root] + descendants(root):
                DESIRED.setdefault(n.id, {})['group_ids'] = HIDDEN_SET

    # 4) 档2 仅超管可见 —— 队长裁定 2026-09-17「**混档**」，逐棵指定实现：
    #      deactivate_tree（整棵 active=False）：121 联系人 / 142 发票 / 196 员工 / 566 数据清除
    #        —— 本校本就不用，停用最干净，也顺带消灭"groupId 放行 +73 后门叶子"的副作用；
    #      restrict_only（只写 groups=[base.group_system]）：1 设置 / 15 应用
    #        —— **系统级入口，停用会让超管自己也进不去设置面板**，不能停。
    #    admin 根数两种实现加起来 = 12 容器 + 2 = 14 ≤ 20。
    ADMIN_ONLY_MODE = plan['group_policy'].get('tier2_mode', 'mixed')
    for mid, a in ADMIN_ONLY.items():
        _mark(mid, '档2根')
        root = Menu.browse(mid)
        mode = a.get('mode') or ADMIN_ONLY_MODE
        if mode == 'deactivate_tree':
            for n in [root] + descendants(root):
                DESIRED.setdefault(n.id, {})['active'] = False
                _mark(n.id, '档1子树')
            DESIRED[mid]['active'] = False
            DESIRED[mid]['group_ids'] = HIDDEN_SET
        elif mode == 'restrict_tree':
            # 根 + **全部子树**一起挂 base.group_system。
            # 为什么不能只收窄根（队长必改 2 + 本机实测）：只写根 groups=[4] 时，
            # 子树里那些"原本被 action 权限挡在门外"的节点会改由 group_system 放行，
            # 于是非超管侧反而多解锁（实测 backoffice 可见总数 391→464）。
            # 硬目标：这棵树对非超管**零可见**（根与子项都算）。
            for n in [root] + descendants(root):
                DESIRED.setdefault(n.id, {})['group_ids'] = HIDDEN_SET
                _mark(n.id, '档2子树')
            DESIRED[mid]['active'] = True
        else:  # restrict_only（仅根收窄；保留作为对照，不再作为默认）
            DESIRED.setdefault(mid, {})['group_ids'] = HIDDEN_SET
            DESIRED[mid]['active'] = True

    # 5) 保持停用（销售 434）：确保不被任何一条规则重新点亮
    for mid, k in KEPT_OFF.items():
        _mark(mid, '保持停用')
        DESIRED.setdefault(mid, {})['active'] = False

    # 6) 环路检查：任何 parent_id 目标不能在自己子树里
    for mid, vals in DESIRED.items():
        tgt = vals.get('parent_id')
        if tgt and tgt in [x.id for x in descendants(Menu.browse(mid))]:
            problems.append('环路风险：菜单 %d 不能挂到自己的后代 %d 下' % (mid, tgt))
    return problems


def snapshot_originals(ids):
    return {i: {
        'active': bool(Menu.browse(i).active),
        'group_ids': sorted(Menu.browse(i).group_ids.ids),
        'parent_id': Menu.browse(i).parent_id.id or None,
        'sequence': Menu.browse(i).sequence,
    } for i in ids}


def _fresh_menu():
    """取一个**缓存已失效**的菜单 RecordSet。

    为什么必须这么做（本机实测 2026-09-17，踩过两次）：
      `_visible_menu_ids()` 的结果在同一个 odoo shell 进程里会被**跨实例复用**：
      事务内试算 → 回滚之后，再用"同一个/新建的" RecordSet 去读，读到的仍是**试算时**的可见集
      （实测：回滚后同对象/新对象/`invalidate_all()` 三种读法都回到试算值 154，而库内真值仍是原态）。
      用 HTTP 端点交叉验证才定位到：库是对的、读数被缓存钉住了。
      所以每次测量前先 `env.registry.clear_cache()` + `env.invalidate_all()`。
    """
    env.registry.clear_cache()
    env.invalidate_all()
    return env['ir.ui.menu'].sudo().with_context(active_test=False)


def measure_roles():
    M = _fresh_menu()
    out = {}
    for login in ['admin', 'backoffice@local', 'faculty@local']:
        u = Users.search([('login', '=', login)], limit=1)
        vis = M.with_user(u)._visible_menu_ids()
        vm = [m for m in M.search([], order='sequence, id') if m.id in vis]
        vr = [m for m in vm if not m.parent_id]
        vl = [m for m in vm if m.action and not m.child_id]
        out[login] = {'visible_roots': len(vr), 'visible_leaves': len(vl),
                      'visible_total': len(vm),
                      'root_names': sorted(m.name or '?' for m in vr)}
    return out


def apply_desired():
    for mid, vals in sorted(DESIRED.items()):
        menu = Menu.browse(mid)
        patch = {}
        if 'active' in vals and bool(menu.active) != vals['active']:
            patch['active'] = vals['active']
        if 'group_ids' in vals and sorted(menu.group_ids.ids) != sorted(vals['group_ids']):
            patch['group_ids'] = [(6, 0, list(vals['group_ids']))]
        if 'parent_id' in vals and (menu.parent_id.id or None) != vals['parent_id']:
            patch['parent_id'] = vals['parent_id']
        if 'sequence' in vals and menu.sequence != vals['sequence']:
            patch['sequence'] = vals['sequence']
        if patch:
            menu.write(patch)


def _faculty_paths():
    M = _fresh_menu()
    u = Users.search([('login', '=', 'faculty@local')], limit=1)
    vis = M.with_user(u)._visible_menu_ids()
    out = {}
    for m in M.search([], order='sequence, id'):
        if m.id in vis:
            out[m.id] = (m.complete_name or m.name)
    return out


_FACULTY_ORIG = _faculty_paths()
# --- ② 重名子项裁定（队长裁定 2026-09-17）---
# 规则：两个 action 的 res_model + domain + context **等价** → 保留一个（优先保留中文名规范、
# 被更多角色引用的），另一个 active=False 并进对照表；不等价 → 两个都留并在对照表写明差异。
# 本机实测：257/278 两棵树共 36 个节点，真正的"同一 action"只有 2 组：
#   · 258(学生)/279(档案)：不同 action，但 res_model/domain/context/view_mode 完全一致 ⇒ 等价 → 合并
#   · 272(设置)/284(设置)：**同一个 action**（groups 不同）⇒ 等价 → 合并
# 其余 15 个模型各只有 1 个菜单 ⇒ 无可合并项（此前"6 组同义子项"的说法在本机数据上不成立）。
DUP_WINDOWS = {}
DUPS = plan.get('duplicate_children', [])
for d in DUPS:
    keep, drop = d['keep'], d['drop']
    DESIRED.setdefault(drop, {})['active'] = False
    DUP_WINDOWS[str(drop)] = {'keep': keep, 'drop': drop, 'model': d.get('model'),
                              'signature': d.get('signature'), 'reason': d.get('reason')}
# 空容器（无 action 且无子项）在合并后会成为空壳 → 连同本根一起收（不删记录）
for d in plan.get('empty_containers', []):
    DESIRED.setdefault(d['id'], {})['active'] = False
    DUP_WINDOWS[str(d['id'])] = {'keep': None, 'drop': d['id'], 'model': None,
                                 'signature': None, 'reason': d.get('reason')}

problems = build_desired()
orig = snapshot_originals(sorted(DESIRED))
before = measure_roles()

# --- 事务内试算 + 强制回滚 ---
_FACULTY_SIM = None
try:
    apply_desired()
    after = measure_roles()
    _FACULTY_SIM = _faculty_paths()
    print('DIAG4 sim_count=%d' % len(_FACULTY_SIM))   # 必须在这里采：回滚之后就读不到"收口后"的真态了
except Exception as exc:  # noqa: BLE001
    env.cr.rollback()
    raise SystemExit('试算失败（已回滚）：%s' % exc)
finally:
    env.cr.rollback()

# --- 回读断言：回滚必须真的发生 ---
rollback_ok = True
for mid, vals in orig.items():
    m = Menu.browse(mid)
    if (bool(m.active) != vals['active'] or sorted(m.group_ids.ids) != vals['group_ids']
            or (m.parent_id.id or None) != vals['parent_id'] or m.sequence != vals['sequence']):
        rollback_ok = False
        print('!! 回滚不彻底：菜单 %d 现值与本文件记录的原值不一致' % mid)
        break

report = {
    'mode': MODE,
    'plan': os.path.basename(PLAN_PATH or '(inline)'),
    'problems': problems,
    'rollback_verified': rollback_ok,
    'changed_menu_count': len(DESIRED),
    'field_change_count': sum(len(v) for v in DESIRED.values()),
    'before': {k: {'visible_roots': v['visible_roots'], 'visible_leaves': v['visible_leaves'],
                   'visible_total': v['visible_total']} for k, v in before.items()},
    'after_predicted': {k: {'visible_roots': v['visible_roots'], 'visible_leaves': v['visible_leaves'],
                            'visible_total': v['visible_total']} for k, v in after.items()},
    'after_root_names': {k: v['root_names'] for k, v in after.items()},
    'duplicate_rulings': DUP_WINDOWS,
    'why_breakdown': {w: sum(1 for k, v in DESIRED_WHY.items() if v == w)
                      for w in sorted(set(DESIRED_WHY.values()))},
}

print('=' * 78)
print('菜单收口计划表（模式 %s）｜计划文件 %s' % (MODE, PLAN_PATH or '(inline)'))
print('=' * 78)
if problems:
    print('!! 计划问题 %d 条：' % len(problems))
    for p in problems:
        print('   - %s' % p)
print('回滚自证：%s' % ('通过（原值已回读一致）' if rollback_ok else '**未通过**'))
print('参与改动的菜单 %d 条，字段级改动 %d 处' % (len(DESIRED), sum(len(v) for v in DESIRED.values())))
print()
print('%-22s %8s %8s %8s' % ('角色', 'B 前', 'B 后(预测)', 'Δ'))
for lg in ('admin', 'backoffice@local', 'faculty@local'):
    b, a = before[lg]['visible_roots'], after[lg]['visible_roots']
    print('%-22s %8d %8d %+8d' % (lg, b, a, a - b))
print()
print('%-22s %8s %8s %8s %8s' % ('角色', 'C 前', 'C 后(预测)', '总数前', '总数后'))
for lg in ('admin', 'backoffice@local', 'faculty@local'):
    b, a = before[lg], after[lg]
    print('%-22s %8d %8d %8d %8d' % (lg, b['visible_leaves'], a['visible_leaves'],
                                     b['visible_total'], a['visible_total']))
print()
print('—— 收口后各角色可见根清单（预测）——')
for lg in ('admin', 'backoffice@local', 'faculty@local'):
    print('%s(%d)：%s' % (lg, after[lg]['visible_roots'], '、'.join(after[lg]['root_names'])))
print()

if MODE == 'apply':
    if not rollback_ok:
        raise SystemExit('回滚自证未通过，拒绝 apply')
    if problems:
        raise SystemExit('计划有问题，拒绝 apply')
    apply_desired()
    env.cr.commit()
    print('[apply] 已提交。回滚依据（改前原值）见下方 JSON。')
else:
    print('[dry-run] 未落库（事务已回滚并通过回读断言）。')

print('MARKER::MENU_PLAN_JSON::' + json.dumps(report, ensure_ascii=False, sort_keys=True))
# 回滚依据（改前原值）单独一行：--apply 时由宿主侧落成 rollback-basis.json，dry-run 时也留档
print('MARKER::MENU_ROLLBACK_BASIS::' + json.dumps(
    {'generated_by': 'scripts/consolidate_menus.py', 'mode': MODE,
     'fields': ['active', 'group_ids', 'parent_id', 'sequence'], 'originals': orig},
    ensure_ascii=False, sort_keys=True))

# --- 红线自证（每次运行都做，不靠人记）---
_SELF = os.environ.get('MENU_SELF_PATH') or globals().get('__file__')
if not _SELF or not os.path.exists(_SELF):
    # 在 odoo shell（stdin 执行）里 __file__ 不存在，且仓库 scripts/ 未挂进容器
    # → 改为经 MENU_SELF_TEXT 传入本文件文本；两条路都没有就明确报"未做自证"，不静默跳过。
    _SRC = os.environ.get('MENU_SELF_TEXT', '')
    if not _SRC:
        raise SystemExit('红线自证无法执行：既没有 MENU_SELF_PATH/__file__，也没有 MENU_SELF_TEXT')
else:
    _SRC = io.open(_SELF, 'r', encoding='utf-8').read()
_BANNED = '.' + 'un' + 'link' + '('   # 拼接构造：避免这一行自身被算作命中
assert _BANNED not in _SRC, '本文件出现了删除调用 —— 违反「禁止 delete ir.ui.menu」红线'
assert 'ir.ui.menu' in _SRC, '本文件似乎不是菜单收口脚本'
print('红线自证：本文件不含 %s 调用（禁止删除菜单记录）' % _BANNED)

# --- 教师侧逐条可达性核对（队长要求：faculty 不设硬线，但"一个功能没少、逐条可达"）---
# 三个采样点的时序（插错位置会得到"前后一样"的假绿——第一版就踩了）：
#   _FACULTY_ORIG 在 build_desired() 之前（原态）
#   _FACULTY_SIM  在 apply_desired() 之后、finally 回滚之前（收口后的真态）
#   本文件末尾的 _faculty_paths() 在回滚之后（应等于原态，用于自证回滚干净）
_FACULTY_ROLLED_BACK = _faculty_paths()
# 口径：以**菜单 id** 为键判定"是否还可达"。若拿路径名当键，被合并/换父的菜单会因为
# 路径变了而被误算成"丢失 + 新增"（本工具第一版就是这个缺陷，报出 164 丢失 / 139 新增的假象）。
_sim = _FACULTY_SIM or {}
gone = {str(k): v for k, v in _FACULTY_ORIG.items() if k not in _sim}
added = {str(k): v for k, v in _sim.items() if k not in _FACULTY_ORIG}
moved = {str(k): {'from': _FACULTY_ORIG[k], 'to': _sim[k]}
         for k in _sim if k in _FACULTY_ORIG and _sim[k] != _FACULTY_ORIG[k]}
print('MARKER::FACULTY_REACHABILITY::' + json.dumps(
    {'orig_count': len(_FACULTY_ORIG),
     'sim_count': len(_FACULTY_SIM or {}),
     'rolled_back_count': len(_FACULTY_ROLLED_BACK),
     'rollback_clean': set(map(str, _FACULTY_ROLLED_BACK)) == set(map(str, _FACULTY_ORIG)),
     'gone_count': len(gone), 'gone': gone,
     'added_count': len(added), 'added': added,
     'moved_count': len(moved), 'moved_sample': dict(list(moved.items())[:40])},
    ensure_ascii=False))
