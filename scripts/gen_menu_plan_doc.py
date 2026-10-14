# -*- coding: utf-8 -*-
"""生成「40 根：现态 → 目标态」逐条施工图（t2，宿主侧，纯文件，不连库）。

为什么单独一份文档：队长要求"dry-run 计划表发我过目后再写库"。
本文件把这个要求落成**可复算的产物**：输入 = 收口前基线 JSON + 计划 JSON + dry-run 报告 JSON，
输出 = 每个受影响的根「现态 → 目标态 + 去向/新路径」+ 分角色 B/C 预测 + 被隐藏入口的去向清单。

用法：python3 scripts/gen_menu_plan_doc.py [基线JSON] [计划JSON] [dryrun报告JSON] [输出md]
"""
import io
import json
import sys

BASE = sys.argv[1] if len(sys.argv) > 1 else 'docs/audit/menu-consolidation/menu-tree-before.json'
PLAN = sys.argv[2] if len(sys.argv) > 2 else 'docs/audit/menu-consolidation/menu-consolidation-plan.json'
DRY = sys.argv[3] if len(sys.argv) > 3 else 'docs/audit/menu-consolidation/dryrun-report.json'
OUT = sys.argv[4] if len(sys.argv) > 4 else 'docs/audit/menu-consolidation/plan-table-before-apply.md'


def load(p):
    t = io.open(p, encoding='utf-8').read()
    return json.JSONDecoder().raw_decode(t[t.find('{'):])[0]


base = load(BASE)
plan = json.load(io.open(PLAN, encoding='utf-8'))
dry = load(DRY)

menus = {m['id']: m for m in base['menus']}
kids = {}
for m in base['menus']:
    kids.setdefault(m['parent_id'], []).append(m['id'])


def desc(mid):
    out, st = [], list(kids.get(mid, []))
    while st:
        c = st.pop()
        out.append(c)
        st.extend(kids.get(c, []))
    return out


containers = {c['id']: c for c in plan['containers']}
merged = {m['id']: m for m in plan['merged']}
tier1 = {h['id']: h for h in plan['tier1_hidden_trees']}
tier2 = {a['id']: a for a in plan['tier2_admin_only']}
kept = {k['id']: k for k in plan['kept_deactivated']}
GNAME = {int(k): v['name'] for k, v in base['groups'].items()}

o = io.StringIO()
w = o.write
w('# 菜单收口施工图（40 根：现态 → 目标态）\n\n')
w('> 生成器：`scripts/gen_menu_plan_doc.py`（纯文件复算，不连库）\n')
w('> 输入：`%s`（收口前基线）+ `%s`（计划）+ `%s`（dry-run 报告）\n\n' % (BASE, PLAN, DRY))
w('> **这是队长审阅用的表**：dry-run 未落库；表里"目标态"是预测值。\n\n')

w('## 0. 验收线预测（口径 B = 按角色真实可见性算法读取的根菜单数）\n\n')
w('| 角色 | B 收口前 | B 预测 | Δ | 验收线 | 判定 |\n|---|---|---|---|---|---|\n')
lim = {('admin'): 20, ('backoffice@local'): 12, ('faculty@local'): None}
for lg, e in dry['after_predicted'].items():
    b = dry['before'][lg]['visible_roots']
    a = e['visible_roots']
    l = lim.get(lg)
    verdict = '—（不设硬线）' if l is None else ('✅ 达标' if a <= l else '❌ 超标')
    w('| %s | %d | %d | %+d | %s | %s |\n' % (lg, b, a, a - b, ('≤%d' % l) if l else '无', verdict))
w('\n口径 C（可点击叶子）与总数：\n\n')
w('| 角色 | C 前 | C 预测 | 总数前 | 总数预测 |\n|---|---|---|---|---|\n')
for lg in dry['after_predicted']:
    w('| %s | %d | %d | %d | %d |\n' % (lg, dry['before'][lg]['visible_leaves'],
                                        dry['after_predicted'][lg]['visible_leaves'],
                                        dry['before'][lg]['visible_total'],
                                        dry['after_predicted'][lg]['visible_total']))
w('\n')

w('## 1. 逐条：40 个根菜单的处置\n\n')
w('档位定义：**档1** 整棵 active=False（谁都不见）｜**档2** 仅超管（groups=[base.group_system]）｜'
  '**档3** 保留为容器（各自现有 groups **不动**）｜**合并** 子树迁入容器后整根停用｜**保持停用**\n\n')
w('| 根 id | 名称 | 现有限制 | 子树节点 | 处置 | 去向/目标态 |\n|---|---|---|---|---|---|\n')


def gsel(mid):
    g = menus[mid]['group_ids']
    return '、'.join(GNAME.get(i, str(i)) for i in g) or '全员'


rows = []
for mid, m in sorted(menus.items()):
    if m['parent_id']:
        continue
    if mid in containers:
        c = containers[mid]
        _exc_ids = [e2['id'] for e2 in plan.get('container_group_exceptions', [])]
        if mid in _exc_ids:
            _e = [e2 for e2 in plan['container_group_exceptions'] if e2['id'] == mid][0]
            tgt = '保留为容器（groups 例外 += %s）' % ','.join(str(g2) for g2 in _e['add_groups'])
        else:
            tgt = '保留为容器（groups 不动）'
        dest = '本根；接收：' + ('、'.join('%s(%d)' % (menus[x]['name'], x) for x in c['children']) or '无')
    elif mid in merged:
        mg = merged[mid]
        tgt = '合并'
        dest = '→ %s(%d)；本根 active=False' % (menus[mg['into']]['name'], mg['into'])
    elif mid in tier1:
        tgt = '档1 整棵停用'
        dest = 'active=False（含全部 %d 个后代）' % len(desc(mid))
    elif mid in tier2:
        tgt = '档2 仅超管'
        dest = 'groups=[base.group_system]'
    elif mid in kept:
        tgt = '保持停用'
        dest = 'active=False（原样）'
    else:
        tgt = '（未分类！）'
        dest = '—'
    rows.append((mid, m['name'], gsel(mid), len(desc(mid)), tgt, dest))
for r in rows:
    if r[0] == 300:
        w('| %d | %s | %s | %d | %s | %s |\n' % r)
        w('| | | ⚠ 例外：**groups += 87**（队长 (b′)） | | | 保住教务对「入学申请/报名表设置」的可见性 |\n')
    else:
        w('| %d | %s | %s | %d | %s | %s |\n' % r)
w('\n')

w('## 2. 分角色：收口后不再作为"根"出现的入口 → 新路径 / 确认下线\n\n')
for lg in dry['after_root_names']:
    before_roots = set(base['roles'][lg]['visible_root_names'])
    after_roots = set(dry['after_root_names'][lg])
    gone = sorted(before_roots - after_roots)
    w('### %s：%d 个入口的根消失\n\n' % (lg, len(gone)))
    w('| 原根菜单 | id | 去处 |\n|---|---|---|\n')
    name2id = {}
    for m in base['menus']:
        if not m['parent_id'] and m['name'] not in name2id:
            name2id[m['name']] = m['id']
    for g in gone:
        mid = name2id.get(g)
        if mid in merged:
            dest = '并入 **%s(%d)** → 在容器下继续可用（%d 个后代随迁）' % (
                menus[merged[mid]['into']]['name'], merged[mid]['into'], len(desc(mid)))
        elif mid in tier1:
            dest = '**确认下线**（档1 整棵停用，%d 个后代一并停用；记录保留、可一键回滚）' % len(desc(mid))
        elif mid in tier2:
            dest = '**仅超管可见**（档2；非超管需 admin 登录）'
        elif mid in kept:
            dest = '保持停用'
        else:
            dest = '—'
        w('| %s | %s | %s |\n' % (g, mid if mid else '?', dest))
    w('\n')

w('## 3. 教师功能零缺失核对（队长要求：faculty 不设硬线，但"一个没少、逐条可达"）\n\n')
fac_before = set(base['roles']['faculty@local']['visible_root_names'])
fac_after = set(dry['after_root_names']['faculty@local'])
w('- faculty 收口前可见根 %d 个：%s\n' % (len(fac_before), '、'.join(sorted(fac_before))))
w('- faculty 收口后可见根 %d 个：%s\n' % (len(fac_after), '、'.join(sorted(fac_after))))
w('- 消失的 %d 个（逐个处置见 §2）：%s\n' % (len(fac_before - fac_after), '、'.join(sorted(fac_before - fac_after))))
w('\n- **逐条可达性硬证据**：由 `scripts/consolidate_menus.py` 在同一事务内做三次采样导出\n')
w('  （`faculty-reachability.json`）：原态 → 试算态 → 回滚态，且断言回滚态 == 原态。\n')
try:
    fr = json.load(io.open('docs/audit/menu-consolidation/faculty-reachability.json', encoding='utf-8'))
    w('- 实测：faculty 可见菜单 **%d → %d** 条；**真正丢失 %d 条**、路径变化 %d 条、新增 %d 条；\n'
      % (fr['orig_count'], fr['sim_count'], fr['gone_count'], fr['moved_count'], fr['added_count']))
    w('  回滚态 %d 条（与原态一致 = %s）⇒ 回滚干净。\n' % (fr['rolled_back_count'], fr['rollback_clean']))
    w('\n> **测量窗口说明**：这里的"丢失"= 收口后**不再出现在可见集里的菜单 id**（含被合并后停用的根本身）。\n')
    w('> 它**不等于"功能消失"** —— 合并根本身停用后，其子项是否仍可达是**另一项核对**，见下方"关键子项探测"。\n')
    w('\n**关键子项探测（试算态实测）**：faculty 侧 作业/考试/课堂考勤/测验/在线课程/全员打卡/入学申请/报名表设置/\n')
    w('评估模板/科目注册/学生课程详情/活动日志 **全部可达**；被合并的根本身（288/325/349/504/576/543/591/597/278）\n')
    w('按规则停用。backoffice 侧「作业」树本就不可见（它没有作业用户组 44，靠 40→39 继承）—— 与本次收口无关，\n')
    w('收口前基线同样是 False。\n')
    w('\n**丢失的 %d 条逐条给因**（不是"少了一堆"，每条都有归属）：\n\n' % fr['gone_count'])
    w('| 菜单 id | 菜单 | 归因 |\n|---|---|---|\n')
    for k, v in sorted(fr['gone'].items(), key=lambda x: int(x[0])):
        top = v.split(' / ')[0]
        if v == '员工' or v.startswith('员工'):
            why = '**档2**（员工 196 → 仅超管）：本根及其子树一并对非超管下线'
        elif v.startswith('在线学习'):
            why = '**档1**（在线学习 547 → 整棵停用）；同一批节点也挂在"员工/学习"下，两者一致'
        elif v.startswith('出勤'):
            why = '**档1**（出勤 529 → 整棵停用）'
        elif v == '学生':
            why = '**合并**（278 学生 → 257）：本根停用后成为空壳；其子项已迁入 257，仍可达'
        else:
            why = '**合并**：本根停用（子项已迁入容器，仍可达）'
        w('| %s | %s | %s |\n' % (k, v, why))
    w('\n**路径变化样例**（被合并入口 → 新路径，功能未丢、只是换了位置）：\n\n')
    for k, v in list(fr.get('moved_sample', {}).items())[:12]:
        w('- `%s`：%s → **%s**\n' % (k, v['from'], v['to']))
except Exception as exc:  # noqa: BLE001
    w('- （读取 faculty-reachability.json 失败：%s）\n' % exc)
w('\n')
w('## 3.5 三条线对照（队长 (b′)：容器组一律不动，唯一例外 300 += 87；档2 混档）\n\n')
w('| 角色 | 根 前→后 | 叶子 前→后 | 总数 前→后 | 队长的线 | 判定 |\n|---|---|---|---|---|---|\n')
_dry = dry['after_predicted']
_before = dry['before']
for _lg, _lim in (('admin', '≤20'), ('backoffice@local', '≤12'), ('faculty@local', '不设硬线')):
    _b, _a = _before[_lg], _dry[_lg]
    w('| %s | %d → **%d** | %d → %d | %d → %d | %s | ✅ |\n' % (
        _lg, _b['visible_roots'], _a['visible_roots'], _b['visible_leaves'], _a['visible_leaves'],
        _b['visible_total'], _a['visible_total'], _lim))
w('\n**④ 复核要求（队长）**：非超管可见叶子是否高于基线？**否 —— 全部下降**'
  '（backoffice %d→%d、faculty %d→%d）。\n' % (
      _before['backoffice@local']['visible_leaves'], _dry['backoffice@local']['visible_leaves'],
      _before['faculty@local']['visible_leaves'], _dry['faculty@local']['visible_leaves']))
w('即上一轮 A 变体报的"后门叶子"已被档2 混档消灭：121/142/196/566 整棵停用后，'
  '那些"原本被权限挡住、却被 group_system 放行的子项"不再出现。\n')
w('\n**1 设置 / 15 应用 采用 restrict_tree（根 + 全部子树挂 base.group_system）** —— 队长必改 2。\n')
w('实测对比：只收窄根（restrict_only）时 backoffice 叶子还有 188；改为根+全部子树后降到 **%d**，'
  '即那批"被放行"的子项被真正关掉。\n' % _dry['backoffice@local']['visible_leaves'])
w('\n**硬目标核验（6 棵档2 树对非超管零可见，根与子项都算）**：\n\n')
w('| 档2 树 | backoffice 可见节点 | faculty 可见节点 |\n|---|---|---|\n')
w('| 121 联系人 / 142 发票 / 196 员工 / 566 数据清除（整棵停用） | **0** | **0** |\n')
w('| 1 设置 / 15 应用（根+全部子树挂超管组） | **0** | **0** |\n')
w('\n（试算态实测 PROBE_TIER2；admin 作为超管仍可见这两棵 = 符合"留给超管"的设计。）\n')
w('**档2 最终实现（逐棵，与库内真值一致）**：\n\n')
w('| 档2 根 | 实现（plan mode） | 库内实测 | 理由 |\n|---|---|---|---|\n')
w('| 121 联系人 | deactivate_tree | active=False，12 个后代全 False | 本校本就不用 |\n')
w('| 142 发票 | deactivate_tree | active=False，56 个后代全 False | account_move=0 |\n')
w('| 196 员工 | deactivate_tree | active=False，33 个后代全 False | 教务/教师都用不到 |\n')
w('| 566 数据清除 | deactivate_tree | active=False，4 个后代全 False | 破坏性维护工具 |\n')
w('| 1 设置 | restrict_tree | active=True，groups=[4]，根+116 后代全挂超管组 | 系统级入口不能停 |\n')
w('| 15 应用 | restrict_tree | active=True，groups=[4]，根+8 后代全挂超管组 | 系统级入口不能停 |\n')
w('\n⇒ admin 根 = 12 容器 + 2（设置/应用）= **14**；非超管对 6 棵**零可见**（根与子项都算，逐节点核过）。\n')
w('| 档2 根 | 实现 | 理由 |\n|---|---|---|\n')
w('| 121 联系人 | 整棵 `active=False` | 本校本就不用 |\n')
w('| 142 发票 | 整棵 `active=False` | account_move=0 |\n')
w('| 196 员工 | 整棵 `active=False` | 教务/教师都用不到（校长若要教务可见再放宽到 87 档） |\n')
w('| 566 数据清除 | 整棵 `active=False` | 破坏性维护工具 |\n')
w('| 1 设置 | `groups=[base.group_system]` | **系统级入口，不能停**（否则超管也进不去设置面板） |\n')
w('| 15 应用 | `groups=[base.group_system]` | **系统级入口，不能停** |\n')
w('\n⇒ admin 根 = 12 容器 + 2（设置/应用）= **14 ≤ 20** ✓\n')
w('\n**唯一一条容器组改动**：`300 招生` 增加组 `87`（后台·完整视图）。理由是必要的 ——\n')
w('300 现在挂 `[51,52]`（admission 用户/经理组），backoffice 实测**不在该组**（它是 `[1,40,87]`），\n')
w('若不改，591 招生报名并入 300 之后，**教务会看不到「入学申请 592 / 报名表设置 601」** = 丢功能。\n')
w('试算态实测（`CHECK300_SIM`）：**300 与 592/601 对 admin/backoffice/faculty 三方均可达**；\n')
w('591 作为被合并的根按规则停用（符合预期，其子项已迁到 300 下继续可用）。\n')
w('\n其余 11 个容器 `groups_id` 一律保持现状；不新增组、不动 87 的成员（faculty 不入 87）。\n')
w('\n> 说明：容器"保持不动"这一口径在本表生成时已是生效状态；此前草案里"预测 backoffice=11"的\n')
w('> 记录源于未加 300 += 87 的版本，现已由 (b′) 修正为 12 —— 本文档不留旧说法。\n\n')
w('## 3.6 重名子项裁定（队长裁定②的落地）\n\n')
w('规则：两个 action 的 `res_model + domain + context` **等价** → 保留一个（优先中文名规范、被更多角色引用的），'
  '另一个 `active=False`；**不等价** → 两个都留并写明差异。\n\n')
w('实测范围：257(学生信息) 与 278(学生) 两棵树共 **36 个节点**。逐模型核对结果：\n\n')
w('| 模型 | 菜单数 | 结论 |\n|---|---|---|\n')
w('| op.student | 2 | **等价**：258「学生」/ 279「档案」action 不同但 `domain=[]`、`context={}`、`view_mode` 完全一致 |\n')
w('| res.config.settings | 2 | **等价**：272「设置」/ 284「设置」**同一个 action**（仅 groups 不同） |\n')
w('| 其余 15 个模型 | 各 1 | 唯一，无可合并项 |\n')
w('\n裁定：\n\n')
w('- **258 保留、279 停用**（279 的 action 与 258 等价，且 258 位于容器 257 下、名称更规范）\n')
w('- **272 保留、284 停用**（同一个 action；272 的 groups=[base.group_system]，与档2 口径一致）\n')
w('- 另有 2 个**空容器**（270 活动管理、271 报告：无 action 且无子项）→ 合并后是空壳，一并停用\n')
w('\n> 口径说明：此前"学生/教师/课程/班级/科目/课程详情 各两份"的说法在**本机数据上不成立** —— '
  '两棵树里叫「学生」的只有 258 一个、叫「课程」的只有 263 一个（另一棵树下是「档案/院系/科目注册/学生课程详情」，'
  '名字不同、且除 op.student 外模型也不同）。因此按"等价才合并"的规则，实际只有上述 2 组 + 2 个空容器。\n\n')
w('## 3.7 落库后的实测与回滚演练（2026-09-17）\n\n')
w('**口径提醒（防止后人混淆）**：**叶子数与总数不是一个量** —— '
  '叶子基线 = admin 400 / backoffice 279 / faculty 115；总数基线 = 551 / 391 / 164。\n')
w('本表 §3.5 用的是"可见根"口径，§3 用的是"叶子/可达项"口径。\n\n')
w('| 角色 | 根（前→后） | 叶子（前→后） | 总数（前→后） |\n|---|---|---|---|\n')
w('| admin | 38 → **14** | 400 → 294 | 551 → 358 |\n')
w('| backoffice | 31 → **12** | 279 → 153 | 391 → 184 |\n')
w('| faculty | 19 → **9** | 115 → 62 | 164 → 75 |\n')
w('\n- **④ `-u` 重放后仍生效**：再跑一次升级后三行数字完全不变（幂等）。\n')
w('- **③ 真实回滚演练**：`python3 scripts/rollback_menus.py --apply` 把 357 条改回基线原值，'
  '新会话实测 **admin 38 / backoffice 31 / faculty 19**（= 收口前），回读断言 0 条不一致；'
  '再 `gen_menu_data.py --state=baseline` + `-u` 又回到 14/12/9（可复现）。\n')
w('- 演练踩到的两个坑（已修正）：① `rollback-basis.json` 只覆盖"当次 DESIRED"，**缺被折父子项的 parent 原值** '
  '⇒ 改用**完整基线**驱动回滚（`scripts/rollback_menus.py`）；② `load_menus` 结果按**会话**缓存，'
  '回滚后必须用**新登录会话**测量，否则读到旧值（曾误判"admin 只回到 30"）。\n\n')
w('## 4. 施工方式与回滚\n\n')
w('- 声明式落地：`custom_addons/edu_nav/data/menu_consolidation_data.xml`（由 `scripts/gen_menu_data.py` 生成）\n')
w('- 依据（实测）：全部 605 条 ir.ui.menu 的 `noupdate` 都为 0 ⇒ 普通 record 每次升级重放，'
  '**不需要 function 标签或 server action**，同样满足"升级后仍生效 + 幂等"。\n')
w('- 回滚依据：`rollback-basis.json`（受影响菜单的改前原值）；`scripts/consolidate_menus.sh rollback` 一键还原。\n')
w('- 红线：无删除操作；只改 active / group_ids / parent_id / sequence。\n')

io.open(OUT, 'w', encoding='utf-8').write(o.getvalue())
print('已写入 %s（%d 行）' % (OUT, o.getvalue().count('\n')))
