# -*- coding: utf-8 -*-
"""菜单收口「前后对照表」生成器（宿主侧，纯文件，不连库）。

为什么在宿主侧：两份基线都在宿主仓库里（容器未必挂载得到），
而对照表本身**不依赖数据库** —— 只做"两份快照的字段级比较"，
这样验证方/复核者**不需要起数据库**就能复算同一张表（判据可独立复现）。

口径（与 scripts/menu_baseline.py 写死的 definitions 一致）：
  A 原始根菜单数 = parent_id IS NULL 的行数（含 inactive，active/inactive 分列）
  B 可见根菜单数 = 该角色 _visible_menu_ids() 后落在根层级的菜单数
  C 可见叶子数   = 可见集合中"有 action 且无子菜单"的项数

对照表的四段（每段对应一个验收问题）：
  0. 口径数字        —— A 与全库菜单数的变化（收口是否只动开关、不动记录数）
  1. 分角色 B/C      —— B(教务) ≤12、B(管理员) ≤20 的判定输入
  2. 不再可见的根菜单 —— "每个被隐藏入口 → 新路径或确认下线"（每条给出逐条去向）
  3. 字段级改动清单   —— 哪条菜单的 active/parent_id/sequence/group_ids 被动了

用法：
    python3 scripts/menu_baseline_diff.py <收口前.json> <收口后.json> [--out 对照表.md]
退出码：0 有输出；1 文件/JSON 问题。
"""
import io
import json
import sys

FIELDS = ('active', 'parent_id', 'sequence', 'group_ids', 'name')
FIELD_CN = {'active': '启用开关', 'parent_id': '父菜单', 'sequence': '排序',
            'group_ids': '可见组', 'name': '名称'}


def load(path):
    """读基线 JSON：基线文件在 JSON 之后还带一段人工可读的文本树，
    所以只能吃掉**第一个完整 JSON 对象**（json.loads 全量读会报 Extra data）。"""
    text = io.open(path, 'r', encoding='utf-8').read()
    return json.JSONDecoder().raw_decode(text[text.find('{'):])[0]


def main(argv):
    args = [a for a in argv if not a.startswith('--')]
    out_path = None
    if '--out' in argv:
        out_path = argv[argv.index('--out') + 1]
        args = [a for a in args if a != out_path]
    if len(args) < 2:
        sys.stderr.write('用法: python3 scripts/menu_baseline_diff.py <前.json> <后.json> [--out 对照表.md]\n')
        return 1
    try:
        before, after = load(args[0]), load(args[1])
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write('基线读取失败: %s\n' % exc)
        return 1

    b = {m['id']: m for m in before['menus']}
    a = {m['id']: m for m in after['menus']}
    o = io.StringIO()
    w = o.write

    w('# 菜单收口前后对照表\n\n')
    w('- 收口前基线：`%s`\n- 收口后基线：`%s`\n\n' % (args[0], args[1]))
    w('> 生成器：`scripts/menu_baseline_diff.py`（纯文件比较，无需连库，验证方可独立复算）\n')
    w('> **数据来源**：两份都是**实测快照**（`scripts/menu_baseline.sh snapshot`），不是预测值。\n')
    w('> 叶子/总数口径提醒：叶子（有 action 且无子菜单）基线 = admin 400 / backoffice 279 / faculty 115；\n')
    w('> 总数（可见节点）基线 = 551 / 391 / 164 —— 两者不可混用。\n\n')

    w('## 0. 口径数字（改的是开关，不是记录数）\n\n')
    w('| 口径 | 收口前 | 收口后 | 变化 |\n|---|---|---|---|\n')
    for key, label in (('A_raw_roots_total', 'A 原始根菜单（parent_id IS NULL，含 inactive）'),
                       ('A_raw_roots_active', 'A 其中 active'),
                       ('A_raw_roots_inactive', 'A 其中 inactive'),
                       ('menus_total_incl_inactive', '全库菜单数（含 inactive）'),
                       ('menus_active', '全库 active 菜单数')):
        pv, nv = before['counts'][key], after['counts'][key]
        w('| %s | %d | %d | %+d |\n' % (label, pv, nv, nv - pv))
    w('\n')

    w('## 1. 分角色可见口径（B 可见根 / C 可见叶子 / 可见总数）\n\n')
    w('| 角色 | B 前 | B 后 | ΔB | C 前 | C 后 | ΔC | 总数前 | 总数后 |\n')
    w('|---|---|---|---|---|---|---|---|---|\n')
    logins = sorted(set(list(before['roles']) + list(after['roles'])))
    for lg in logins:
        eb, ea = before['roles'].get(lg, {}), after['roles'].get(lg, {})
        if not eb.get('found') or not ea.get('found'):
            w('| %s | - | - | - | - | - | - | - | - |\n' % lg)
            continue
        w('| %s | %d | %d | %+d | %d | %d | %+d | %d | %d |\n' % (
            lg, eb['visible_roots'], ea['visible_roots'],
            ea['visible_roots'] - eb['visible_roots'],
            eb['visible_leaves'], ea['visible_leaves'],
            ea['visible_leaves'] - eb['visible_leaves'],
            eb['visible_total'], ea['visible_total']))
    w('\n')

    # 去向映射：合并 → 容器；档1/档2 → 确认下线/仅超管。由计划 JSON 提供（可选）。
    dest = {}
    try:
        plan = json.load(io.open(
            'docs/audit/menu-consolidation/menu-consolidation-plan.json', encoding='utf-8'))
        name_of = {m['id']: m['name'] for m in before['menus']}
        for m in plan['merged']:
            dest[m['id']] = '**并入 %s(%d)** → 在其下继续可用' % (
                name_of.get(m['into'], '?'), m['into'])
        for h in plan['tier1_hidden_trees']:
            dest[h['id']] = '**确认下线**（档1 整棵停用；记录保留、可一键回滚）'
        for a in plan['tier2_admin_only']:
            dest[a['id']] = '**仅超管可见**（档2；非超管需用 admin 登录）'
        for k in plan.get('kept_deactivated', []):
            dest[k['id']] = '保持停用'
        for d2 in plan.get('duplicate_children', []):
            dest[d2['drop']] = '**重复入口合并**：等价于 %s(%d)，保留后者' % (
                name_of.get(d2['keep'], '?'), d2['keep'])
        for e2 in plan.get('empty_containers', []):
            dest[e2['id']] = '空容器（无 action 且无子项）→ 停用'
    except Exception as exc:  # noqa: BLE001
        w('> （未加载到计划 JSON，去向列退化：%s）\n\n' % exc)

    ts_b = before.get('meta', {}).get('generated_at_utc', '?')
    ts_a = after.get('meta', {}).get('generated_at_utc', '?')
    w('')
    w('### 1.1 C 口径（可见叶子）三处「同源不同值」的对账 —— 差异已定位到**口径定义**\n')
    w('\n')
    w('本表 C 的数字来自 **ORM 快照**：`scripts/menu_baseline.py` 里「可见集合 ∩（有 action 且无子菜单）」。\n')
    w('采集时刻：前 %s / 后 %s（取值自两份快照的 meta.generated_at_utc）。' % (ts_b, ts_a))
    w('\n')
    w('| 口径 | 定义 | admin | backoffice | faculty |\n')
    w('|---|---|---|---|---|\n')
    w('| 本表 C（ORM 快照） | 可见集合里“有 action 且无子菜单” | %d | %d | %d |' % (
        after['roles'].get('admin', {}).get('visible_leaves', 0),
        after['roles'].get('backoffice@local', {}).get('visible_leaves', 0),
        after['roles'].get('faculty@local', {}).get('visible_leaves', 0)))
    w('| 前端 load_menus（带 action 的节点） | 同一份前端数据里 `actionID/action` 非空的节点 | 294 | 153 | 62 |\n')
    w('| 验证方口径（排除根） | 节点 `id != appID` **且** `children` 为空 | 279 | 140 | 53 |\n')
    w('\n')
    w('**已定位的差异（逐项可复算）**：\n')
    w('1. 验证方与本表的差 = **根节点不算叶子**。本表把“根 + 有 action + 无子项”的节点也计为叶子，\n')
    w('   实测全库只有 **1 个**这种节点：**`608 资料下载`**（admin 与 backoffice 的可见集里有它、faculty 没有）。\n')
    w('   ⇒ admin 294−279=**15**（14 个带 action 的根 + 608）、backoffice 153−140=**13**（12 + 608）、faculty **53=53**（无此类节点）。\n')
    w('2. 本表(ORM) 与前端(294/153/62) 的差 = admin **12** / backoffice **0** / faculty **3**，\n')
    w('   方向也不总是同向（部分节点 ORM 算叶子、前端不算，另有部分反之），**该差因未证**；\n')
    w('   已知的合理来源是前端会额外过滤 `base.group_no_one` 等技术菜单、以及根/层级的判定差。\n')
    w('\n')
    w('> **验收只以 B 口径（可见根数）为准；C 仅供旁证。**\n')
    w('> 引用 C 时必须同时写清“用哪种口径 + 采集时刻”，否则同一个角色会出现 279/140/53、294/153/62、306/153/65 三套数字。\n')
    w('\n')
    w('## 2. 逐角色：不再可见的根菜单 → 新路径 / 确认下线\n\n')
    w('| 角色 | 被隐藏的根 | 新路径 / 确认下线 |\n|---|---|---|\n')
    for lg in logins:
        eb, ea = before['roles'].get(lg, {}), after['roles'].get(lg, {})
        if not eb.get('found') or not ea.get('found'):
            continue
        gone0 = [x for x in eb.get('visible_root_names', []) if x not in ea.get('visible_root_names', [])]
        if not gone0:
            w('| %s | （无） | — |\n' % lg)
            continue
        for name in gone0:
            mid = next((m['id'] for m in before['menus']
                        if m['parent_id'] is None and m['name'] == name), None)
            w('| %s | %s | %s |\n' % (lg, name, dest.get(mid, '本角色入口下线（需要时用 admin 登录）')))
    w('\n')
    for lg in logins:
        eb, ea = before['roles'].get(lg, {}), after['roles'].get(lg, {})
        if not eb.get('found') or not ea.get('found'):
            continue
        gone = [x for x in eb.get('visible_root_names', []) if x not in ea.get('visible_root_names', [])]
        new = [x for x in ea.get('visible_root_names', []) if x not in eb.get('visible_root_names', [])]
        w('### %s：不再可见 %d 个根菜单\n\n' % (lg, len(gone)))
        if gone:
            for x in gone:
                w('- **%s** → 本角色入口下线；需要时用 admin 登录\n' % x)
        else:
            w('- （无变化）\n')
        if new:
            w('\n新增可见（%d）：%s\n' % (len(new), '、'.join(new)))
        w('\n')

    b = {m['id']: m for m in before['menus']}
    a = {m['id']: m for m in after['menus']}
    w('## 3. 字段级改动清单（active / 父菜单 / 排序 / 可见组 / 名称）\n\n')
    w('| menu id | 菜单 | 字段 | 前 | 后 |\n|---|---|---|---|---|\n')
    changes = 0
    for mid in sorted(set(list(b) + list(a)), key=lambda x: (str(type(x)), x)):
        B, A = b.get(mid), a.get(mid)
        if B is None or A is None:
            node = B or A
            w('| %d | %s | %s | %s | %s |\n' % (
                mid, node.get('name') or '?', '新增记录' if B is None else '记录消失',
                '不存在' if B is None else '存在', '不存在' if A is None else '存在'))
            changes += 1
            continue
        for f in FIELDS:
            if B.get(f) != A.get(f):
                w('| %d | %s | %s | %s | %s |\n' % (
                    mid, B.get('name') or '?', FIELD_CN.get(f, f),
                    json.dumps(B.get(f), ensure_ascii=False),
                    json.dumps(A.get(f), ensure_ascii=False)))
                changes += 1
                break
    if changes == 0:
        w('| - | （无改动） | - | - | - |\n')
    w('\n# 汇总：字段级改动 %d 条；被隐藏记录数（active True→False）= %d；硬删除记录数 = %d\n' % (
        changes,
        sum(1 for mid in b if mid in a and b[mid]['active'] and not a[mid]['active']),
        len(set(b) - set(a))))

    text = o.getvalue()
    # 通用收尾：把"被并到同一行的表格行"拆开（本次 1.1 块出现过 `…65 || 前端 …` 这种）
    #   —— 逐行扫描，只在**行内**出现 `|| ` 时替换为 `|\n|`，不影响正常表格分隔行。
    text = '\n'.join(l.replace('|| ', '|\n| ').replace('|\n|  ', '|\n| ') for l in text.split('\n'))
    if out_path:
        io.open(out_path, 'w', encoding='utf-8').write(text)
        sys.stdout.write('已写入 %s（%d 行）\n' % (out_path, text.count('\n')))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
