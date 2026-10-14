# -*- coding: utf-8 -*-
"""从计划 JSON + 实况读数生成 edu_nav 的声明式菜单数据文件（t2，宿主侧）。

为什么要生成器而不是手写 XML：
  · 计划里 345 条菜单、420 处字段改动，手写必错；而且"计划改了但 XML 没跟着改"是最典型的
    双源漂移（两份口径）。生成器让 **计划 JSON 成为唯一声明源**，XML 是它的派生。
  · 生成时同时产出 `MENU_CONSOLIDATED_COUNT`（受影响菜单条数），由模块在装载期反查比对：
    届时若装载了漂移的 XML（计划改了没重新生成），装载日志会直接报 ERROR，而不是静默用旧态。

生成规则（与 scripts/consolidate_menus.py 的目标态计算完全一致 —— 同一套口径）：
  · 容器：active=True；group_ids=可见集；接收归并进来的根的子菜单（parent_id 改指容器）
  · 合并：根 active=False；整棵子树 group_ids=可见集（否则子菜单会把父链重新拉亮）
  · 隐藏：整棵 active=False + group_ids=仅超管
  · 只写**与实况不同**的字段（最小改动面；每处不同都带注释说明来源）

用法：python3 scripts/gen_menu_data.py [计划路径] [输出路径]
      默认：docs/audit/menu-consolidation/menu-consolidation-plan.json
            custom_addons/edu_nav/data/menu_consolidation_data.xml
依赖：需要一个能连库的 odoo shell 读数（由本脚本调 scripts/menu_plan_state.py 采集）。
"""
import io
import json
import os
import subprocess
import sys
import tempfile

ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
STATE_SRC = 'db'
for _a in sys.argv[1:]:
    if _a.startswith('--state='):
        STATE_SRC = _a.split('=', 1)[1]
BASELINE = 'docs/audit/menu-consolidation/menu-tree-before.json'
EMIT = 'live'
if '--inert' in sys.argv[1:]:
    EMIT = 'inert'
for _a in sys.argv[1:]:
    if _a.startswith('--emit='):
        EMIT = _a.split('=', 1)[1]
if EMIT not in ('live', 'inert'):
    raise SystemExit('--emit 只支持 live / inert')
PLAN = ARGS[0] if ARGS else 'docs/audit/menu-consolidation/menu-consolidation-plan.json'
OUT = ARGS[1] if len(ARGS) > 1 else 'custom_addons/edu_nav/data/menu_consolidation_data.xml'
MODELS = 'custom_addons/edu_nav/models/menu_consolidation.py'


def state_via_shell(plan):
    """把计划里的菜单 id 交给容器侧采集实况（active/parent/sequence/group_ids）。"""
    ids = []
    for c in plan['containers']:
        ids.append(c['id'])
    for m in plan['merged']:
        ids.append(m['id'])
    for h in plan.get('tier1_hidden_trees', plan.get('hidden', [])):
        ids.append(h['id'])
    for a in plan.get('tier2_admin_only', []):
        ids.append(a['id'])
    for k in plan.get('kept_deactivated', []):
        ids.append(k['id'])
    py = '''
import json
M = env['ir.ui.menu'].sudo().with_context(active_test=False)
IData = env['ir.model.data'].sudo()
ids = __IDS__


def _xid(mid):
    d = IData.search([('model', '=', 'ir.ui.menu'), ('res_id', '=', mid)], limit=1)
    return (d.module + '.' + d.name) if d else None


out = {}
for i in ids:
    m = M.browse(i)
    if not m.exists():
        continue
    out[str(i)] = {'name': m.name, 'active': bool(m.active),
                   'parent_id': m.parent_id.id or None, 'sequence': m.sequence,
                   'group_ids': sorted(m.group_ids.ids), 'xmlid': _xid(i)}
# 子树实况（用于隐藏类整棵停用 / 合并类整棵收窄）
def desc(mid):
    out_, st = [], list(M.browse(mid).child_id)
    while st:
        c = st.pop(); out_.append(c); st.extend(c.child_id)
    return out_
for i in list(ids):
    for c in desc(i):
        out[str(c.id)] = {'name': c.name, 'active': bool(c.active),
                          'parent_id': c.parent_id.id or None, 'sequence': c.sequence,
                          'group_ids': sorted(c.group_ids.ids), 'xmlid': _xid(c.id)}
print('MARKER::MENU_STATE::' + json.dumps(out, ensure_ascii=False, sort_keys=True))
'''.replace('__IDS__', json.dumps(ids))
    proc = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell', '-c', '/etc/odoo/odoo.conf',
         '--db_host=db', '-r', 'odoo', '-w', 'odoo', '-d', 'edu19', '--no-http'],
        input=py, text=True, capture_output=True)
    for line in proc.stdout.split('\n'):
        if line.startswith('MARKER::MENU_STATE::'):
            return json.loads(line[len('MARKER::MENU_STATE::'):])
    sys.stderr.write('采集实况失败：\n%s\n%s\n' % (proc.stdout[-2000:], proc.stderr[-2000:]))
    raise SystemExit(1)


def uninstalled_modules():
    """查库：哪些模块不是 installed。

    为什么必须有这一步（2026-10-02，edu_nav 长期升不动 EXIT=255 的根因）：
      数据文件用**目标菜单自己的规范 xmlid** 做记录键；若那个 xmlid 属于一个**未安装**的模块，
      Odoo 的 tools/convert.py:_test_xml_id 对「跨模块 xmlid 引用未安装模块」是**硬断言**
      ⇒ ParseError ⇒ 升级 exit 255 ⇒ **所有菜单类改动被结构性阻塞**。
      实测：本文件曾引用 account_payment / website_slides / website_slides_forum /
      hr_skills_slides / website_livechat 共 23 条，全部指向「计划里还留着、盘上已经没了」的菜单。
      取证：docs/audit/menu-consolidation/deploy-shipping-gap.md
    """
    py = '''
print('MARKER::MODS::' + ','.join(sorted(env['ir.module.module'].sudo()
      .search([('state', '!=', 'installed')]).mapped('name'))))
'''
    proc = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell', '-c', '/etc/odoo/odoo.conf',
         '--db_host=db', '-r', 'odoo', '-w', 'odoo', '-d', 'edu19', '--no-http'],
        input=py, text=True, capture_output=True)
    for line in proc.stdout.split('\n'):
        if line.startswith('MARKER::MODS::'):
            return set(x for x in line[len('MARKER::MODS::'):].split(',') if x)
    sys.stderr.write('查未安装模块失败：\n%s\n%s\n' % (proc.stdout[-2000:], proc.stderr[-2000:]))
    raise SystemExit(1)


def descendants(state, root_id):
    kids = {}
    for k, v in state.items():
        if v['parent_id']:
            kids.setdefault(v['parent_id'], []).append(int(k))
    out, st = [], list(kids.get(root_id, []))
    while st:
        cur = st.pop()
        out.append(cur)
        st.extend(kids.get(cur, []))
    return out


def declare_expected_count(n):
    """把"期望改写多少条"写进 ir.config_parameter，供装载期守卫核对。

    为什么需要：数据文件用**目标菜单自己的规范 xmlid** 做记录键，这些 xmlid 仍属各自模块
    （base/openeducat_*/mail/…），并不会在 ir.model.data 里留下 edu_nav 的行。
    所以守卫没法靠"数 edu_nav 的 ir.model.data"来判断数据是不是惰性 ——
    变成"无法核对"就会退化成"恒定报错"或"恒定通过"，两者都是坏信号。
    这里由生成器显式声明期望值：live 写实际条数、inert 写 0。
    """
    env_args = {
        'key': 'edu_nav.consolidated_count',
        'value': str(n),
    }
    py = '''
K = __KEY__
V = __VAL__
env['ir.config_parameter'].sudo().set_param(K, V)
env.cr.commit()
print('MARKER::PARAM_OK::' + env['ir.config_parameter'].sudo().get_param(K))
'''.replace('__KEY__', repr(env_args['key'])).replace('__VAL__', repr(env_args['value']))
    r = subprocess.run(['docker', 'compose', 'exec', '-T', 'web', 'odoo', 'shell',
                        '-c', '/etc/odoo/odoo.conf', '--db_host=db', '-r', 'odoo', '-w', 'odoo',
                        '-d', 'edu19', '--no-http'], input=py, text=True, capture_output=True)
    for line in r.stdout.split('\n'):
        if line.startswith('MARKER::PARAM_OK::'):
            return line.split('::', 2)[2]
    return None


def main():
    import json as _json
    plan = json.load(io.open(PLAN, encoding='utf-8')) 

    if STATE_SRC == 'baseline':
        # 用收口前基线当"现值"算目标态。
        # 为什么需要：本生成器默认只写"与库内现值不同"的字段，所以当库已等于目标态时会生成 0 条
        # ⇒ data 文件变空 ⇒ 「升级后仍生效」的保障就丢。要重建声明式数据必须回到基线起算。
        _t = io.open(BASELINE, encoding='utf-8').read()
        base = json.JSONDecoder().raw_decode(_t[_t.find('{'):])[0]
        _menus = {m['id']: m for m in base['menus']}
        _ids = set()
        for c in plan['containers']:
            _ids.add(c['id'])
        for m in plan['merged']:
            _ids.add(m['id'])
        for h in plan.get('tier1_hidden_trees', []):
            _ids.add(h['id'])
        for a in plan.get('tier2_admin_only', []):
            _ids.add(a['id'])
        for k in plan.get('kept_deactivated', []):
            _ids.add(k['id'])
        for x in plan.get('empty_containers', []):
            _ids.add(x['id'])
        for x in plan.get('duplicate_children', []):
            _ids.add(x['keep'])
            _ids.add(x['drop'])
        _kids = {}
        for m in base['menus']:
            if m['parent_id']:
                _kids.setdefault(m['parent_id'], []).append(m['id'])
        _stack = list(_ids)
        while _stack:
            cur = _stack.pop()
            for c2 in _kids.get(cur, []):
                if c2 not in _ids:
                    _ids.add(c2)
                    _stack.append(c2)
        state = {str(i): {'name': _menus[i]['name'], 'active': bool(_menus[i]['active']),
                          'parent_id': _menus[i]['parent_id'], 'sequence': _menus[i]['sequence'],
                          'group_ids': list(_menus[i]['group_ids']),
                          'xmlid': _menus[i]['xmlid']} for i in _ids if i in _menus}
        print('[state] 用收口前基线当现值：%d 条菜单进入计算' % len(state))
    else:
        state = state_via_shell(plan)
    visible = list(plan['group_policy']['visible_set'])
    hidden = list(plan['group_policy']['hidden_set'])
    mode = plan['group_policy'].get('hidden_mode', 'deactivate_tree')

    desired = {}   # id -> {field: (value, note)}

    def state_of(mid):
        return state.get(str(mid), {})

    def want(mid, field, value, note):
        cur = state.get(str(mid), {}).get(field)
        if field == 'group_ids':
            same = sorted(cur or []) == sorted(value)
        else:
            same = (cur == value) if field != 'active' else (bool(cur) == bool(value))
        if not same:
            desired.setdefault(mid, {})[field] = (value, note)


    # 容器
    #   ⚠ 关键：容器组**保持不动**；唯一例外由 container_group_exceptions 声明。
    #   例外必须按"库里现值 + add − remove"算**绝对目标**（写入 [(6,0,[...])] 而非增量），
    #   否则 -u 重放时增量会在原值上叠加成不可预期的结果。
    #   （此前残留的 visible 参数曾把 300 的组算成"清空"，已删除该参数。）
    exc_map = {e['id']: e for e in plan.get('container_group_exceptions', [])}
    for c in plan['containers']:
        want(c['id'], 'active', True, '容器：保持启用')
        if c['id'] in exc_map:
            e = exc_map[c['id']]
            cur = list(state_of(c['id']).get('group_ids') or [])
            tgt = sorted(set(cur + list(e.get('add_groups', []))) - set(e.get('remove_groups', [])))
            if not tgt:
                raise SystemExit('容器 %d 的例外算出空组，拒绝生成' % c['id'])
            want(c['id'], 'group_ids', tgt,
                 '容器例外（全计划唯一一条）：groups += %s → %s'
                 % (','.join(str(g) for g in e.get('add_groups', [])), tgt))
    # 归并：把源根的一级子菜单挂到容器下
    kids = {}
    for k, v in state.items():
        if v['parent_id']:
            kids.setdefault(v['parent_id'], []).append(int(k))
    for c in plan['containers']:
        for child_root in c['children']:
            for ch in kids.get(child_root, []):
                want(ch, 'parent_id', c['id'], '归并：%s(%d) → %s(%d)' % (
                    state_of(ch)['name'], ch, c['name'], c['id']))

    # 合并根
    for m in plan['merged']:
        root = m['id']
        want(root, 'active', False, '合并：本根停用，子树迁往 %s(%d)' % (m['name'], m['into']))
        # 队长裁定 merged_mode=reparent_then_deactivate —— **子项不收窄组**。
        # 旧草案的 shrink_group 分支已删：它把子项写成空组，而 visible_set 现为空，
        # 等于清空全员的组（曾把 279 档案 写成 [(5,0,0)]，是实打实的错改）。

    # 档1：彻底隐藏（含超管）
    for h in plan.get('tier1_hidden_trees', plan.get('hidden', [])):
        root = h['id']
        if mode == 'deactivate_tree':
            want(root, 'active', False, '档1 彻底隐藏：整棵停用（记录保留，可一键回滚）')
            for n in descendants(state, root):
                want(n, 'active', False, '档1 子树（来自 %s）' % h['name'])
        else:
            want(root, 'group_ids', hidden, '档1：仅超管')
            for n in descendants(state, root):
                want(n, 'group_ids', hidden, '档1 子树（来自 %s）' % h['name'])

    # 档2：队长最终口径 = **混档**，逐棵按 plan 里的 mode 执行：
    #   deactivate_tree（121 联系人 / 142 发票 / 196 员工 / 566 数据清除）：整棵 active=False；
    #   restrict_tree  （1 设置 / 15 应用）：根 + 全部子树挂 base.group_system（系统级入口不能停）。
    #   ⚠ 这里必须读**每棵的 mode**：此前只读了全局 tier2_mode，导致逐棵配置被忽略、
    #     生成出来的 XML 把 121/142/196/566 也写成"保留启用"，admin 因此停在 18 而非 14。
    tier2_default = plan['group_policy'].get('tier2_mode', 'restrict_tree')
    for a in plan.get('tier2_admin_only', []):
        root = a['id']
        mode = a.get('mode') or tier2_default
        if mode == 'deactivate_tree':
            want(root, 'active', False, '档2 整棵停用：本根停用（%s）' % a['name'])
            want(root, 'group_ids', hidden, '档2：组锚定为超管')
            for n in descendants(state, root):
                want(n, 'active', False, '档2 子树（来自 %s）' % a['name'])
        else:  # restrict_tree（默认）
            want(root, 'active', True, '档2 仅超管：保持启用（%s）' % a['name'])
            want(root, 'group_ids', hidden, '档2 仅超管：groups=[base.group_system]')
            for n in descendants(state, root):
                want(n, 'group_ids', hidden, '档2 子树（来自 %s）：根+子树一起挂超管组' % a['name'])

    # 保持停用（销售 434）
    for k in plan.get('kept_deactivated', []):
        want(k['id'], 'active', False, '保持停用（记录保留）')

    # ② 重名子项裁定（队长裁定）：等价 → 保留一个、另一个停用；空容器（无 action 无子项）随根停用。
    #   判据与依据见 plan.duplicate_children / plan.empty_containers（施工图 §3.6 有完整表）。
    for d in plan.get('duplicate_children', []):
        want(d['drop'], 'active', False,
             '重复入口合并：保留 %s，停用 %s（%s）' % (d['keep'], d['drop'], d.get('model')))
    # 导航侧例外（F7/t15）：按**规范 xmlid** 覆盖 website.menu 记录（改指有效页 / 中文化）
    #   注意：website.menu 没有 active 字段（实测字段表），停用只能 is_visible=False 或删除；
    #   本块只做'改指 + 属性校正'，删除孤儿由 scripts/fix_nav_duplicates.py 负责（那是宿主侧脚本、可备份可回滚）。
    for e in plan.get('website_menu_exceptions', []):
        want(e['id'], 'url', e['url'], '导航例外：%s → %s（%s）' % (e.get('xmlid'), e['url'], 'F7'))
        if e.get('name'):
            want(e['id'], 'name', e['name'], '导航例外：名称中文化（%s）' % e.get('xmlid'))
        if e.get('sequence') is not None:
            want(e['id'], 'sequence', e['sequence'], '导航例外：序列')
    for d in plan.get('empty_containers', []):
        want(d['id'], 'active', False, '空容器（无 action 且无子项）：%s' % d.get('reason', ''))

    def _guard_no_empty_groups():
        bad = [mid for mid, fv in desired.items()
               if 'group_ids' in fv and not fv['group_ids'][0]]
        if bad:
            raise SystemExit('拒绝生成：以下菜单被写成空组（会变成全员可见）：%s' % bad)

    _guard_no_empty_groups()

    # ---- 过滤：xmlid 属未安装模块的记录一律不写（否则 load 撞硬断言、升级 exit 255）----
    # 这些菜单在**盘上根本不存在**（模块卸载时菜单与 ir.model.data 行一起没了），
    # 所以它们不是「要收口的菜单」，而是「计划里还留着、盘上已经没了」的陈旧引用 —— 删之无损。
    _bad_mods = uninstalled_modules()
    _dropped = []
    for _mid in sorted(desired):
        _xid = state_of(_mid).get('xmlid')
        _mod = _xid.split('.')[0] if _xid else None
        if _mod and _mod in _bad_mods:
            _dropped.append((_mid, _xid))
    for _mid, _xid in _dropped:
        del desired[_mid]
    if _dropped:
        print('[filter] 跳过 %d 条：xmlid 属未安装模块（写了也会被 Odoo 硬断言拒）' % len(_dropped))
        for _mid, _xid in _dropped[:30]:
            print('         id=%s  %s' % (_mid, _xid))
    else:
        print('[filter] 无陈旧引用（0 条被跳过）')

    decl = chr(60) + chr(63) + 'xml version=' + chr(34) + '1.0' + chr(34) + \
           ' encoding=' + chr(34) + 'utf-8' + chr(34) + chr(63) + chr(62)
    lines = [decl, '<!--',
             '  菜单收口的声明式数据主体（edu_nav）——**本文件由脚本生成，不要手改**。',
             '  生成器：scripts/gen_menu_data.py（计划 JSON 为唯一声明源）',
             '  计划文件：%s' % PLAN,
             '  生成时间(UTC)：%s' % os.popen('date -u +%Y-%m-%dT%H:%M:%SZ').read().strip(),
             '  受影响菜单 %d 条 / 字段改动 %d 处' % (
                 len(desired), sum(len(v) for v in desired.values())),
             '  红线：只出现 active / group_ids / parent_id / sequence，绝不出现删除类操作。',
             '  为什么是普通 <record>：全部 605 条 ir.ui.menu 的 noupdate 都是 0，',
             '  普通 record 每次升级都会重放 ⇒ 天生满足「升级后仍生效」+「幂等」。',
             '-->',
             '<odoo>']
    LT_, GT_ = chr(60), chr(62)
    OPEN_C = LT_ + chr(33) + chr(45) + chr(45) + chr(32)
    CLOSE_C = chr(32) + chr(45) + chr(45) + GT_
    for mid in sorted(desired):
        fields = desired[mid]
        line_open = ('    ' + OPEN_C) if EMIT == 'inert' else '    '
        line_close = CLOSE_C if EMIT == 'inert' else ''
        note0 = '%s (id=%d)' % (state_of(mid)['name'], mid)
        lines.append('    ' + OPEN_C + note0 + CLOSE_C)
        # forcecreate="0" 是**必须的**：本文件只写"已存在记录的字段"，
        # 不带它时加载器会把 <field name="id" eval="N"/> 当成新记录去 INSERT
        # （实测报错：null value in column "name" of relation "ir_ui_menu"），必须走 write 路径。
        # 关键：用**目标菜单自己的规范 xmlid**（如 base.menu_administration）做记录键。
        #   为什么不能用自造 xmlid（menu_state_X）：那样库里不存在该 xmlid，加载器会走 INSERT
        #   分支，把 129 条改动变成 129 条新菜单（实测全库 605→734、根 40→133，已回滚）。
        #   用规范 xmlid 时加载器解析到的是**已存在的菜单记录**，走 write 路径 —— 且每次 -u 幂等。
        #   （探针阶段已验证：覆盖 base.menu_administration 后该 xmlid 仍唯一、仍属 base。）
        xmlid = state_of(mid).get('xmlid')
        module = (xmlid.split('.')[0] if xmlid else 'edu_nav')
        name_part = (xmlid.split('.', 1)[1] if xmlid else 'menu_%d' % mid)
        head = 'record id="%s.%s" model="ir.ui.menu" forcecreate="0"' % (module, name_part)
        lines.append(line_open + LT_ + head + GT_ + line_close)
        # 必须带"创建 ir.ui.menu 所需的最小字段集"：
        #   本文件的 xmlid（menu_state_X）在库里**不存在**，所以首次装载走的是 INSERT 分支；
        #   只给 id+目标字段会撞 `name` 的非空约束（实测报错）。
        #   带上 name（NOT NULL，菜单名不可空）+ active + sequence（NOT NULL，有 default 但显式给更稳），
        #   并用 <field name="id" eval="X"/> 指定记录 id，首次装载即为新 xmlid + 指定 id 的记录，
        #   之后每次升级都走 write（幂等）。
        for extra, expr in (('name', None), ('active', None), ('sequence', None)):
            pass
        nm = state_of(mid).get('name') or '(未命名)'
        idf = 'field name="id" eval="%d" /' % mid
        lines.append(line_open + LT_ + idf + GT_ + line_close)
        # XML 属性里的引号必须转义为 &quot;（json.dumps 会产出裸 " ，直接拼进属性会破坏 XML）
        nm_esc = nm.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        nmf = 'field name="name" eval="&quot;%s&quot;" /' % nm_esc
        lines.append(line_open + LT_ + nmf + GT_ + line_close)
        # active / sequence 必须写**目标值**（fields 里已经算好的那份），不能写库内现值 ——
        # 写现值等于把所有"停用/启用"改动静默丢掉（对账器抓到过一次，见 check_menu_data_sync.py）。
        act_tgt = fields['active'][0] if 'active' in fields else bool(state_of(mid).get('active'))
        # 若目标态里已经有 active 的显式声明（带归因注释那条），头部就不再重复写一次
        if 'active' not in fields:
            acf = 'field name="active" eval="%s" /' % ('True' if act_tgt else 'False')
            lines.append(line_open + LT_ + acf + GT_ + line_close)
        seq_tgt = fields['sequence'][0] if 'sequence' in fields else (
            state_of(mid).get('sequence') if state_of(mid).get('sequence') is not None else 10)
        sqf = 'field name="sequence" eval="%d" /' % seq_tgt
        lines.append(line_open + LT_ + sqf + GT_ + line_close)
        for f in ('active', 'group_ids', 'parent_id', 'sequence'):
            if f not in fields:
                continue
            value, note = fields[f]
            lines.append('        ' + OPEN_C + note + CLOSE_C)
            if f == 'group_ids':
                gpart = 'field name="group_ids" eval="[(5, 0, 0)]" /' if not value else (
                    'field name="group_ids" eval="[(6, 0, [%s])]" /' % ', '.join(str(g) for g in value))
            elif f == 'parent_id':
                # many2one 必须写整数（或 False），不能写 x2many 的 [(6,0,[N])] 语法 ——
                # 实测：写前者会 ParseError「Invalid field ... in eval」。
                gpart = ('field name="parent_id" eval="%d" /' % value) if value \
                    else 'field name="parent_id" eval="False" /'
            elif f == 'active':
                gpart = 'field name="active" eval="%s" /' % ('True' if value else 'False')
            else:
                gpart = 'field name="sequence" eval="%d" /' % value
            body = LT_ + gpart + GT_
            lines.append(('        ' + body) if EMIT != 'inert' else ('        ' + OPEN_C + body + CLOSE_C))
        endrec = LT_ + chr(47) + 'record' + GT_
        lines.append(('    ' + endrec) if EMIT != 'inert' else ('    ' + OPEN_C + endrec + CLOSE_C))
    lines.append('</odoo>')
    text = '\n'.join(lines) + '\n'
    # 模式行在最后插入（EMIT 是全局变量；写在 header 字面量里曾造成 NameError，已修）
    mode_note = ('发射模式：inert（惰性：业务记录全部被注释，装载等于零变化）'
                 if EMIT == 'inert' else '发射模式：live（生效）')
    text = text.replace('  红线：只出现', '  ' + mode_note + '\n  红线：只出现', 1)
    io.open(OUT, 'w', encoding='utf-8').write(text)
    got = declare_expected_count(len(desired) if EMIT == 'live' else 0)
    print('已声明 ir.config_parameter edu_nav.consolidated_count = %s（供装载期守卫核对）' % got)
    print('已生成 %s：受影响 %d 条 / 字段改动 %d 处' % (
        OUT, len(desired), sum(len(v) for v in desired.values())))
    # 同步模块里的期望条数常量：**必须与发射模式一致**，否则守卫会（正确地）报漂移。
    #   live  → 数据里有 N 条记录，常量写 N；
    #   inert → 数据里 0 条记录，常量写 0（守卫在 0 时只记录不校验）。
    want_count = len(desired) if EMIT == 'live' else 0
    if os.path.exists(MODELS):
        src = io.open(MODELS, encoding='utf-8').read()
        import re
        new_src = re.sub(r'MENU_CONSOLIDATED_COUNT = \d+',
                         'MENU_CONSOLIDATED_COUNT = %d' % want_count, src)
        if new_src != src:
            io.open(MODELS, 'w', encoding='utf-8').write(new_src)
            print('已同步 MENU_CONSOLIDATED_COUNT = %d（模式 %s）' % (want_count, EMIT))


if __name__ == '__main__':
    main()
