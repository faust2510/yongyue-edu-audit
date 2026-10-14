# -*- coding: utf-8 -*-
"""XML（edu_nav 的声明式数据）与 dry-run 执行器目标态的对账器（t2，宿主侧，纯文件）。

为什么需要（这条是"落库前最后一道自检"）：
  菜单改动有**两个执行通道**：① `scripts/consolidate_menus.sh dry-run`（事务试算，用来看预测）；
  ② `custom_addons/edu_nav/data/menu_consolidation_data.xml`（真正落库的那份，由 gen_menu_data.py 生成）。
  两者都从同一份 plan.json 派生，但**派生路径不同**（一个在 odoo shell 里算，一个在宿主侧生成）。
  只要有一条路径漏了/多了一步，就会出现"dry-run 说 352 条改动、XML 只写 181 条"这类**通道漂移** ——
  而落库用的是 XML，所以漂移会让"预测"与"实际"脱钩。本工具把两者逐条对账。

对账口径：
  · 期望终态 = rollback-basis.json（改前原值） + dryrun-report.json（哪条菜单动了）+ plan.json（目标值规则）；
    实际直接取 dryrun 报告里记录的 after（根清单）无法覆盖全部菜单，所以这里用**逐条字段比对**：
    期望：对每条"参与改动的菜单 id"，其终态应满足 plan 的规则（档1/档2/合并/容器/例外）；
    实际：XML 里该 id 声明的字段值。
  · 只比 XML **声明了的**字段；XML 未声明的字段表示"保持原值"，因此若 plan 规则要求改动而 XML 没声明 → 报漂移。

用法：python3 scripts/check_menu_data_sync.py [plan.json] [xml] [dryrun-report.json] [rollback-basis.json]
退出码：0 无漂移；1 有漂移（逐条打印）。
"""
import io
import json
import re
import sys

PLAN = sys.argv[1] if len(sys.argv) > 1 else 'docs/audit/menu-consolidation/menu-consolidation-plan.json'
XML = sys.argv[2] if len(sys.argv) > 2 else 'custom_addons/edu_nav/data/menu_consolidation_data.xml'
DRY = sys.argv[3] if len(sys.argv) > 3 else 'docs/audit/menu-consolidation/dryrun-report.json'
BASIS = sys.argv[4] if len(sys.argv) > 4 else 'docs/audit/menu-consolidation/rollback-basis.json'


def load(p):
    t = io.open(p, encoding='utf-8').read()
    return json.JSONDecoder().raw_decode(t[t.find('{'):])[0]


plan = json.load(io.open(PLAN, encoding='utf-8'))
dry = load(DRY)
basis = load(BASIS)['originals']
xml_text = io.open(XML, encoding='utf-8').read()

# 解析 XML 里"生效的"记录（未注释的）
rec = {}
# 记录标签可带额外属性（如 forcecreate="0"），正则必须容忍 —— 否则"读不到记录"会被误报成"通道漂移"
# 记录键现在是**目标菜单自己的规范 xmlid**（如 base.menu_administration），菜单 id 由 <field name="id"/> 给出
for m in re.finditer(r'^\s*<record id="[^"]+" model="ir\.ui\.menu"[^>]*>(.*?)^\s*</record>',
                     xml_text, re.S | re.M):
    body = m.group(1)
    fi = re.search(r'field name="id" eval="(\d+)"', body)
    if not fi:
        continue
    mid = int(fi.group(1))
    fields = {}
    f = re.search(r'field name="active" eval="(True|False)"', body)
    if f:
        fields['active'] = f.group(1) == 'True'
    f = re.search(r'field name="group_ids" eval="\[\(6, 0, \[([0-9, ]*)\]\)\]"', body)
    if f:
        fields['group_ids'] = sorted(int(x) for x in f.group(1).replace(' ', '').split(',') if x)
    f = re.search(r'field name="parent_id" eval="(\d+)"', body)
    if f:
        fields['parent_id'] = int(f.group(1))
    elif re.search(r'field name="parent_id" eval="False"', body):
        fields['parent_id'] = None
    f = re.search(r'field name="sequence" eval="(\d+)"', body)
    if f:
        fields['sequence'] = int(f.group(1))
    rec[mid] = fields

print('XML 生效记录 %d 条；dry-run 参与改动 %d 条' % (len(rec), dry['changed_menu_count']))
if not rec:
    print('FAIL | XML 里一条生效记录都没解析到 —— 先查 XML 或本工具的解析正则，不要当成"无改动"')
    sys.exit(1)

containers = {c['id']: c for c in plan['containers']}
merged = {m['id']: m for m in plan['merged']}
t1 = {h['id']: h for h in plan['tier1_hidden_trees']}
t2 = {a['id']: a for a in plan['tier2_admin_only']}
kept = {k['id']: k for k in plan.get('kept_deactivated', [])}
exc = {e['id']: e for e in plan.get('container_group_exceptions', [])}
hidden_set = list(plan['group_policy']['hidden_set'])

problems = []


def need(mid, field, want_value, why):
    """plan 规则要求 mid 的 field 应等于 want_value；核对 XML 是否声明且一致。"""
    got = rec.get(mid, {}).get(field)
    if got is None:
        # XML 没声明 ⇒ 保持原值；若原值就等于目标值则不算漂移
        if basis.get(str(mid), {}).get(field) == want_value:
            return
        problems.append('菜单 %d 的 %s 应为 %r（%s），但 XML 未声明且原值不是 ⇒ 通道漂移'
                        % (mid, field, want_value, why))
    elif got != want_value:
        problems.append('菜单 %d 的 %s：XML 写 %r，plan 要求 %r（%s）'
                        % (mid, field, got, want_value, why))


# 容器：active=True；组保持原值（例外除外）
for mid, c in containers.items():
    need(mid, 'active', True, '容器保持启用')
    if mid in exc:
        cur = list(basis.get(str(mid), {}).get('group_ids') or [])
        tgt = sorted(set(cur + list(exc[mid]['add_groups'])) - set(exc[mid].get('remove_groups', [])))
        need(mid, 'group_ids', tgt, '容器例外（全计划唯一一条）')
    else:
        if mid in rec and 'group_ids' in rec[mid]:
            problems.append('菜单 %d 是容器，plan 要求 groups 不动，但 XML 声明了 group_ids=%s'
                            % (mid, rec[mid]['group_ids']))
# 合并根：active=False
for mid in merged:
    need(mid, 'active', False, '合并后整根停用')
# 档1 / 档2：整棵 active=False? 由 mode 决定
for mid, h in t1.items():
    need(mid, 'active', False, '档1 彻底隐藏')
# 档2 是**混档**：逐棵按 mode 判定（deactivate_tree = 整棵停用；restrict_tree = 保留 + 根与子树挂超管组）
tier2_default = plan['group_policy'].get('tier2_mode', 'restrict_tree')
for mid, a in t2.items():
    mode = a.get('mode') or tier2_default
    if mode == 'deactivate_tree':
        need(mid, 'active', False, '档2 整棵停用（%s）' % mode)
    else:
        need(mid, 'active', True, '档2 仅超管（%s）：保留启用' % mode)
    need(mid, 'group_ids', hidden_set, '档2 = 仅 base.group_system')
for mid in kept:
    need(mid, 'active', False, '保持停用')

if problems:
    for p in problems:
        print('FAIL | %s' % p)
else:
    print('PASS | XML 与 dry-run 目标态一致：容器/例外/合并/档1/档2/保持停用 逐条核对无漂移')
print('%s | 对账完成（%d 条问题）' % ('FAIL' if problems else 'PASS', len(problems)))
sys.exit(1 if problems else 0)
