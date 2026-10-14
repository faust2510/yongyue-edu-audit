# -*- coding: utf-8 -*-
"""菜单收口「前后对照」基线工具（在 odoo shell 内运行，只读，绝不写库）。

为什么要有它（t2 的交付纪律）：
  · 菜单收口只允许改 active / groups / parent_id / sequence，且必须可一键回滚；
    **回滚的目标态与验收的判据都必须是"改之前那一刻的真实状态"**，
    而"真实状态"不能靠人眼记 —— 必须落成可 diff 的基线文件（本脚本产出）。
  · 同一个脚本同时负责"收口后"的快照与"前后对照表"（diff 模式），
    避免"记录的口径"与"验证的口径"是两套代码（dev-workflow 铁律：同一个汇总行不能有两套口径）。

口径定义（写死在输出里，防止读的人猜）：
  A 原始根菜单数 = ir.ui.menu 里 parent_id IS NULL 的行数（含 inactive），
    并列 active 数；本仓 active 与 inactive 分开给，绝不混报一个数。
  B 可见根菜单数 = 以**该角色用户身份**调 ir.ui.menu._visible_menu_ids()（Odoo 官方可见性算法：
    组过滤 + action 存在性 + 模型 read 权限 + 父链补齐）后，落在根层级的菜单数。
  C 可见叶子数 = 可见集合里"有 action 且无子菜单"的项数（= 真正能点开干活的口径）。
  三者在输出里都带定义文本；**同一份 JSON 里不给"根菜单总数"这类无口径数字。**

角色：默认取 admin / backoffice@local / faculty@local（队长裁定②的三个账号锚点），
      可用 MENU_BASELINE_ROLES 覆盖（逗号分隔的登录名）。

覆盖范围声明（本工具的盲区，必须显式列出）：
  · 只覆盖 ir.ui.menu 记录本身（active/父/序/组/动作/xmlid）与**ORM 层可见性**；
  · **不覆盖**：前端 JS 再过滤（如 debug 模式隐藏 group_no_one）、门户侧导航、网站菜单
    （website.menu 是另一张表）、点击 action 后的业务可见性；
  · **不覆盖**：组继承链的"为什么" —— implied_ids 结论单独放在 snapshot.implied 里，
    那只是"谁隐含 base.group_system"的一跳/多跳结论，不替代权限审计。

用法（本机克隆，web 容器在跑）：
    # ① 收口前基线（写入 docs/audit/menu-consolidation/）
    bash scripts/menu_baseline.sh snapshot --tag before
    # ② 收口后快照
    bash scripts/menu_baseline.sh snapshot --tag after
    # ③ 前后对照表（stdout，Markdown）
    bash scripts/menu_baseline.sh diff \
        --before docs/audit/menu-consolidation/menu-tree-before.json \
        --after  docs/audit/menu-consolidation/menu-tree-after.json
    # ④ 环境冒烟（不写文件）
    bash scripts/menu_baseline.sh --dry-run snapshot

环境变量（脚本内部读取；由 menu_baseline.sh 设置）：
    MENU_BASELINE_MODE   snapshot | diff
    MENU_BASELINE_ROLES  逗号分隔登录名
    MENU_BASELINE_BEFORE / _AFTER   diff 模式的两份 JSON 路径（脚本按路径自行读取）

本脚本不写任何文件、不改任何记录；文件落盘由 menu_baseline.sh 在宿主侧完成。
"""
import io
import json
import os
import sys

from odoo import fields

MODE = os.environ.get('MENU_BASELINE_MODE', 'snapshot').strip()
ROLES = [x.strip() for x in os.environ.get(
    'MENU_BASELINE_ROLES', 'admin,backoffice@local,faculty@local').split(',') if x.strip()]

Menu = env['ir.ui.menu'].sudo().with_context(active_test=False)
IData = env['ir.model.data'].sudo()
Users = env['res.users'].sudo()
Groups = env['res.groups'].sudo()
SYS_GID = env.ref('base.group_system').id


def xmlid_of(menu_id):
    d = IData.search([('model', '=', 'ir.ui.menu'), ('res_id', '=', menu_id)], limit=1)
    return '%s.%s' % (d.module, d.name) if d else None


def full_path(menu):
    """根→本节点的名称串（'/' 连接）；父链缺环不影响本函数（只读父链）。"""
    names, cur, guard = [], menu, 0
    while cur and guard < 20:
        names.append(cur.name or ('#%d' % cur.id))
        cur = cur.parent_id
        guard += 1
    return ' / '.join(reversed(names))


def group_rows(menu):
    out = []
    for g in menu.group_ids:
        d = IData.search([('model', '=', 'res.groups'), ('res_id', '=', g.id)], limit=1)
        out.append({
            'id': g.id,
            'xmlid': '%s.%s' % (d.module, d.name) if d else None,
            'name': g.name,
            'user_count': len(g.all_user_ids),
            'is_group_system': g.id == SYS_GID,
        })
    return sorted(out, key=lambda r: r['id'])


def group_closure(root_id, max_depth=12):
    """谁隐含 root_id（多跳）。Odoo 组继承是 DAG，这里用 BFS + 访问集去环。"""
    seen, level, frontier = set(), 0, [root_id]
    while frontier and level < max_depth:
        nxt = []
        for gid in frontier:
            for g in Groups.search([('implied_ids', 'in', gid)]):
                if g.id in seen or g.id == root_id:
                    continue
                seen.add(g.id)
                nxt.append(g.id)
        frontier = nxt
        level += 1
    out = []
    for gid in sorted(seen):
        g = Groups.browse(gid)
        d = IData.search([('model', '=', 'res.groups'), ('res_id', '=', gid)], limit=1)
        out.append({'id': gid, 'xmlid': '%s.%s' % (d.module, d.name) if d else None,
                    'name': g.name, 'user_count': len(g.all_user_ids)})
    return out


def snapshot():
    all_menus = Menu.search([], order='sequence, id')
    root_all = all_menus.filtered(lambda m: not m.parent_id)
    root_act = root_all.filtered('active')
    root_inact = root_all - root_act

    # 组 id -> 名称/成员（全库一次，避免逐菜单 N+1 查询）
    group_meta = {}
    for g in Groups.search([]):
        d = IData.search([('model', '=', 'res.groups'), ('res_id', '=', g.id)], limit=1)
        group_meta[g.id] = {
            'xmlid': '%s.%s' % (d.module, d.name) if d else None,
            'name': g.name,
            'user_count': len(g.all_user_ids),
        }

    menus_out = []
    for m in all_menus:
        gids = sorted(m.group_ids.ids)
        menus_out.append({
            'id': m.id,
            'xmlid': xmlid_of(m.id),
            'name': m.name,
            'parent_id': m.parent_id.id or None,
            'parent_xmlid': xmlid_of(m.parent_id.id) if m.parent_id else None,
            'sequence': m.sequence,
            'active': bool(m.active),
            'is_root': not m.parent_id,
            'group_ids': gids,
            'group_xmlids': [group_meta.get(i, {}).get('xmlid') for i in gids],
            'group_system_only': gids == [SYS_GID],
            'action': ('%s,%s' % (m.action._name, m.action.id)) if m.action else None,
            'action_model': getattr(m.action, 'res_model', None) if m.action else None,
            'child_count': len(m.child_id),
        })

    by_id = {r['id']: r for r in menus_out}

    roles_out = {}
    for login in ROLES:
        u = Users.search([('login', '=', login)], limit=1)
        entry = {'login': login, 'found': bool(u), 'user_id': u.id if u else None}
        if not u:
            roles_out[login] = entry
            continue
        vis = Menu.with_user(u)._visible_menu_ids()
        vis_menus = [m for m in all_menus if m.id in vis]
        vis_roots = [m for m in vis_menus if not m.parent_id]
        vis_leaves = [m for m in vis_menus if m.action and not m.child_id]
        deepest, deepest_len = None, -1
        for m in vis_menus:
            p = full_path(m)
            if p.count(' / ') > deepest_len:
                deepest, deepest_len = p, p.count(' / ')
        entry.update({
            'visible_total': len(vis_menus),
            'visible_roots': len(vis_roots),
            'visible_leaves': len(vis_leaves),
            'visible_root_list': [{
                'id': m.id, 'name': m.name, 'xmlid': xmlid_of(m.id),
                'sequence': m.sequence, 'child_count': len(m.child_id),
                'has_action': bool(m.action),
                'group_ids': sorted(m.group_ids.ids),
            } for m in vis_roots],
            'visible_root_names': [m.name for m in vis_roots],
            'visible_ids_digest_count': len(vis),
            'deepest_visible_path_len': deepest_len + 1,
            'deepest_visible_path': deepest,
            'visible_leaf_paths': sorted(full_path(m) for m in vis_leaves),
        })
        roles_out[login] = entry

    gs_users = Groups.browse(SYS_GID).all_user_ids
    return {
        'meta': {
            'generated_at_utc': fields.Datetime.to_string(fields.Datetime.now()),
            'tool': 'scripts/menu_baseline.py',
            'purpose': '菜单收口前后对照基线（只读快照；供回滚与验证方共用）',
            'database': env.cr.dbname,
            'odoo_version': env['ir.module.module'].sudo().search(
                [('name', '=', 'base')], limit=1).latest_version,
            'roles': ROLES,
            'base_group_system_id': SYS_GID,
            'coverage_note': (
                '仅 ir.ui.menu 记录 + ORM 层可见性（_visible_menu_ids）。不覆盖：前端 JS 二次过滤、'
                'website.menu、门户导航、action 目标页的业务可见性。'
            ),
        },
        'definitions': {
            'A_raw_roots': 'ir.ui.menu 中 parent_id IS NULL 的行数（含 inactive；active/inactive 分列）',
            'B_visible_roots': '以该角色用户身份调 ir.ui.menu._visible_menu_ids() 后落在根层级的菜单数',
            'C_visible_leaves': '可见集合中「有 action 且无子菜单」的项数（真正可点击干活的口径）',
        },
        'counts': {
            'A_raw_roots_total': len(root_all),
            'A_raw_roots_active': len(root_act),
            'A_raw_roots_inactive': len(root_inact),
            'menus_total_incl_inactive': len(all_menus),
            'menus_active': len(all_menus.filtered('active')),
        },
        'root_menus': [by_id[m.id] for m in root_all],
        'root_menus_active': [by_id[m.id] for m in root_act],
        'root_menus_inactive': [by_id[m.id] for m in root_inact],
        'menus': menus_out,
        'roles': roles_out,
        'groups': {'%d' % gid: meta for gid, meta in sorted(group_meta.items())},
        'implied': {
            'who_implies_group_system': group_closure(SYS_GID),
            'group_system_users': [{'id': u.id, 'login': u.login, 'name': u.name,
                                    'active': bool(u.active)} for u in gs_users],
        },
    }


def build_tree(payload):
    """文本树（人眼核对用）。按 (sequence, id) 排序；★=active，✗=inactive，⛔=仅 group_system。"""
    rows = payload['menus']
    kids = {}
    for r in rows:
        kids.setdefault(r['parent_id'], []).append(r)
    for k in kids:
        kids[k].sort(key=lambda r: (r['sequence'], r['id']))
    lines = []

    def walk(node, depth):
        mark = '★' if node['active'] else '✗'
        gs = '⛔' if node['group_system_only'] else ''
        gids = node['group_ids']
        gt = (' 组=%s' % (','.join(str(i) for i in gids))) if gids else ' 组=全员'
        lines.append('%s%s %s%s [%d] seq=%s%s%s' % (
            '    ' * depth, mark, gs, node['name'] or '?', node['id'], node['sequence'],
            gt, ('  →' + node['xmlid']) if node['xmlid'] else ''))
        for c in kids.get(node['id'], []):
            walk(c, depth + 1)

    for r in sorted(kids.get(None, []), key=lambda r: (r['sequence'], r['id'])):
        walk(r, 0)
    return '\n'.join(lines)


def do_snapshot(stream):
    payload = snapshot()
    stream.write(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))
    stream.write('\n')
    stream.write('# --- 文本树（供人工核对，机器读上面 JSON）---\n')
    stream.write(build_tree(payload))
    stream.write('\n')
    stream.write('# A 原始根菜单(含 inactive)=%d（active=%d / inactive=%d）｜全库菜单 %d（active %d）\n' % (
        payload['counts']['A_raw_roots_total'], payload['counts']['A_raw_roots_active'],
        payload['counts']['A_raw_roots_inactive'], payload['counts']['menus_total_incl_inactive'],
        payload['counts']['menus_active']))
    for login, e in payload['roles'].items():
        if not e['found']:
            stream.write('# B %s：账号不存在（跳过）\n' % login)
            continue
        stream.write('# B %s 可见根=%d ｜ C 可见叶子=%d ｜ 可见菜单总数=%d ｜ 最深路径层级=%d\n' % (
            login, e['visible_roots'], e['visible_leaves'], e['visible_total'],
            e['deepest_visible_path_len']))
    return 0


def _load(path):
    """读基线 JSON。文件里 JSON 之后还有人工可读的文本树，因此用 raw_decode
    只吃掉**第一个完整 JSON 对象**（json.loads 全量读会把后面的树算成 Extra data）。"""
    with io.open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    return json.JSONDecoder().raw_decode(text[text.find('{'):])[0]


def do_diff(stream):
    before_path = os.environ.get('MENU_BASELINE_BEFORE', '').strip()
    after_path = os.environ.get('MENU_BASELINE_AFTER', '').strip()
    if not before_path or not after_path:
        sys.stderr.write('diff 模式需要 MENU_BASELINE_BEFORE / MENU_BASELINE_AFTER\n')
        return 2
    before, after = _load(before_path), _load(after_path)

    def idx(p):
        return {m['id']: m for m in p['menus']}

    b, a = idx(before), idx(after)
    rows = []
    for mid in sorted(set(b) | set(a)):
        B, A = b.get(mid), a.get(mid)
        if B is None or A is None:
            rows.append((mid, '新增' if B is None else '消失', B or A, B, A))
            continue
        for field in ('active', 'parent_id', 'sequence', 'group_ids', 'name'):
            if B.get(field) != A.get(field):
                rows.append((mid, field, A, B, A))
                break

    stream.write('# 菜单收口前后对照表（%s → %s）\n\n' % (before_path, after_path))
    stream.write('## 0. 口径数字\n\n')
    bc, ac = before['counts'], after['counts']
    stream.write('| 口径 | 收口前 | 收口后 | 变化 |\n|---|---|---|---|\n')
    for key, label in (('A_raw_roots_total', 'A 原始根菜单（parent_id IS NULL，含 inactive）'),
                       ('A_raw_roots_active', 'A 其中 active'),
                       ('A_raw_roots_inactive', 'A 其中 inactive'),
                       ('menus_total_incl_inactive', '全库菜单数（含 inactive）'),
                       ('menus_active', '全库 active 菜单数')):
        stream.write('| %s | %s | %s | %+d |\n' % (label, bc[key], ac[key], ac[key] - bc[key]))
    stream.write('\n## 1. 分角色可见口径（B 可见根 / C 可见叶子 / 可见总数）\n\n')
    stream.write('| 角色 | B 前 | B 后 | ΔB | C 前 | C 后 | ΔC | 可见总数前 | 可见总数后 |\n|---|---|---|---|---|---|---|---|---|\n')
    for login in sorted(set(list(before['roles'].keys()) + list(after['roles'].keys()))):
        eb, ea = before['roles'].get(login, {}), after['roles'].get(login, {})
        if not eb.get('found') or not ea.get('found'):
            stream.write('| %s | - | - | - | - | - | - | - | - |\n' % login)
            continue
        stream.write('| %s | %d | %d | %+d | %d | %d | %+d | %d | %d |\n' % (
            login, eb['visible_roots'], ea['visible_roots'],
            ea['visible_roots'] - eb['visible_roots'],
            eb['visible_leaves'], ea['visible_leaves'],
            ea['visible_leaves'] - eb['visible_leaves'],
            eb['visible_total'], ea['visible_total']))

    for login in sorted(set(list(before['roles'].keys()) + list(after['roles'].keys()))):
        eb, ea = before['roles'].get(login, {}), after['roles'].get(login, {})
        if not eb.get('found') or not ea.get('found'):
            continue
        gone = [x for x in eb.get('visible_root_names', []) if x not in ea.get('visible_root_names', [])]
        new = [x for x in ea.get('visible_root_names', []) if x not in eb.get('visible_root_names', [])]
        stream.write('\n### 1.%s %s：不再可见的根菜单（%d）\n\n' % (
            login, login, len(gone)))
        for x in gone:
            stream.write('- %s → **已下线（本角色）**：需要时用 admin 登录\n' % x)
        if new:
            stream.write('\n新增可见（%d）：%s\n' % (len(new), '、'.join(new)))

    stream.write('\n## 2. 逐条菜单改动（field 级）\n\n')
    stream.write('| menu id | 菜单 | 改动字段 | 前 | 后 |\n|---|---|---|---|---|\n')
    for mid, field, node, B, A in rows:
        stream.write('| %d | %s | %s | %s | %s |\n' % (
            mid, (node or {}).get('name') or '?', field,
            json.dumps(None if B is None else B.get(field), ensure_ascii=False),
            json.dumps(None if A is None else A.get(field), ensure_ascii=False)))
    if not rows:
        stream.write('| - | （无改动） | - | - | - |\n')
    stream.write('\n# 汇总：改动菜单 %d 条；B(教务/管理员) 见上表\n' % len(rows))
    return 0


def do_plan(stream):
    """施工图数据源：把根菜单摊平成"决策表"（每个根一行，带角色可见性与子树规模）。

    为什么不是让人去看 JSON：t1 的施工图要按**批次（保留/隐藏/合并/降级）**决策，
    它需要的是"每行一个候选、列齐全"的表；这张表由本函数产出，避免手抄错行。
    本模式同样**只读**。
    """
    payload = snapshot()
    b = {r['id']: r for r in payload['menus']}
    kids = {}
    for r in payload['menus']:
        kids.setdefault(r['parent_id'], []).append(r['id'])

    def descendants(mid):
        out, stack = [], list(kids.get(mid, []))
        while stack:
            cur = stack.pop()
            out.append(cur)
            stack.extend(kids.get(cur, []))
        return out

    gname = {int(k): v['name'] for k, v in payload['groups'].items()}
    stream.write('# 根菜单施工图数据源（口径 A 全部 %d 行，含 inactive %d）\n' % (
        payload['counts']['A_raw_roots_total'], payload['counts']['A_raw_roots_inactive']))
    stream.write('# 生成工具：scripts/menu_baseline.py（plan 模式，只读）｜生成时间(UTC)：%s\n' % payload['meta']['generated_at_utc'])
    stream.write('# 口径 A=parent_id IS NULL 行数；口径 B=该角色 _visible_menu_ids() 后落在根层的数\n')
    stream.write('# 「可见角色」列 = 三锚点里谁看得见本根（A=admin ／ B=backoffice ／ F=faculty）\n')
    stream.write('# 「组」列 = 本根的 group_ids 名称（空=全员可见）\n\n')
    stream.write('| 序 | id | xmlid | 名称 | 启用 | A | B | F | 组 | 子树节点 | 有action | 备注 |\n')
    stream.write('|---|---|---|---|---|---|---|---|---|---|---|---|\n')
    for r in payload['root_menus']:
        roles_vis = []
        for short, login in (('A', 'admin'), ('B', 'backoffice@local'), ('F', 'faculty@local')):
            e = payload['roles'].get(login, {})
            if e.get('found') and r['name'] in e.get('visible_root_names', []):
                roles_vis.append(short)
        gs = '、'.join(gname.get(i, str(i)) for i in r['group_ids']) or '全员'
        desc = descendants(r['id'])
        note = []
        if not r['active']:
            note.append('已停用')
        if r['group_system_only']:
            note.append('仅超管')
        if not roles_vis:
            note.append('三锚点皆不可见')
        if r['xmlid'] and not r['xmlid'].split('.')[0].startswith('edu_'):
            note.append('基座/原生')
        else:
            note.append('自研')
        stream.write('| %s | %d | %s | %s | %s | %s | %s | %s | %s | %d | %s | %s |\n' % (
            r['sequence'], r['id'], r['xmlid'] or '-', r['name'] or '?',
            '是' if r['active'] else '否',
            '✓' if 'A' in roles_vis else '·', '✓' if 'B' in roles_vis else '·',
            '✓' if 'F' in roles_vis else '·', gs, len(desc),
            '是' if r['action'] else '否', '；'.join(note)))
    stream.write('\n# 口径数字\n')
    stream.write('# A 原始根菜单=%d（active %d / inactive %d）｜全库菜单 %d（active %d）\n' % (
        payload['counts']['A_raw_roots_total'], payload['counts']['A_raw_roots_active'],
        payload['counts']['A_raw_roots_inactive'], payload['counts']['menus_total_incl_inactive'],
        payload['counts']['menus_active']))
    for login, e in payload['roles'].items():
        if e.get('found'):
            stream.write('# B %s 可见根=%d（C 可见叶子=%d，可见总数=%d）\n' % (
                login, e['visible_roots'], e['visible_leaves'], e['visible_total']))
    return 0


_buf = io.StringIO()
if MODE == 'diff':
    rc = do_diff(_buf)
elif MODE == 'plan':
    rc = do_plan(_buf)
else:
    rc = do_snapshot(_buf)
sys.stdout.write(_buf.getvalue())
sys.stdout.flush()
print('MENU_BASELINE_OK mode=%s rc=%d' % (MODE, rc))
