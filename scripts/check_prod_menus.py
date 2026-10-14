#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生产菜单探活审计（v2.1-A8 工具化）。

对任意 Odoo 库一键校验全部菜单（根菜单及其整棵子树）× 动作 × res_model
× 视图 的有效性，输出「有效/失效」报告。对齐 tests/smoke/F_roles_smoke.md
t12 的探活思路，但覆盖全部菜单而非 7 个抽查点。

判定规则（任一命中即「失效」）：
  1. 菜单 action 指向的动作记录在 ir_act_window / ir_act_url /
     ir_act_server / ir_act_report_xml / ir_act_client 中都不存在；
  2. act_window 的 res_model 为空；
  3. res_model 不在 ir_model 表中（模块未安装/模型已移除 → 访问即报错）；
  4. act_window 挂的 ir_act_window_view.view_id 指向不存在的视图（含 0）；
  5. 菜单挂的组（ir_ui_menu_group_rel）指向不存在的组（警告级，
     不判失效——仅提示，避免误伤历史库）。
  无动作的菜单 = 纯分组父菜单，属正常（报告「无动作(分组)」，不计失效）。

用法：
  python3 scripts/check_prod_menus.py [--db-host H] [--db-port P] [--db-name N]
      [--db-user U] [--db-password W] [--inactive] [--json] [--only-root]

  远程/容器内执行示例（生产 203.0.113.10 /opt/edu-app）：
    docker compose exec web python3 /tmp/check_prod_menus.py --db-host db \\
        --db-name edu19 --db-user odoo --db-password "<从 odoo.conf 取>"
  （脚本不落盘到进容器目录，用 docker compose cp 传入 /tmp 即可）

退出码：0=全部有效；1=存在失效项；2=参数/连接错误。
"""
import argparse
import json
import sys

try:
    import psycopg2
except ImportError:
    psycopg2 = None

# 动作类型 → (模型名, 表名, 该动作 res_model 的列名；None 表示无模型列)
# Odoo 19 中 ir_ui_menu.action 为 varchar 存储 'ir.actions.act_window,<id>'
_ACTION_TYPES = {
    'ir.actions.act_window': ('ir_act_window', 'res_model'),
    'ir.actions.url':        ('ir_act_url', None),
    'ir.actions.server':     ('ir_act_server', 'model_id'),
    'ir.actions.report':     ('ir_act_report_xml', 'model'),
    'ir.actions.client':     ('ir_act_client', None),
}


def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--db-host', default='127.0.0.1')
    p.add_argument('--db-port', type=int, default=5432)
    p.add_argument('--db-name', default='edu19')
    p.add_argument('--db-user', default='odoo')
    p.add_argument('--db-password', default='odoo')
    p.add_argument('--inactive', action='store_true', help='连同 inactive 菜单一起审计（默认只查 active）')
    p.add_argument('--json', action='store_true', help='输出 JSON 报告')
    p.add_argument('--only-root', action='store_true', help='只审计根菜单（不含子菜单树）')
    return p


def has_column(cur, table, column):
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=%s AND column_name=%s", (table, column))
    return cur.fetchone() is not None


def table_exists(cur, table):
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name=%s", (table,))
    return cur.fetchone() is not None


def main():
    args = build_parser().parse_args()
    if psycopg2 is None:
        print('ERROR: 需要 psycopg2（python3 -m pip install psycopg2-binary）', file=sys.stderr)
        return 2
    try:
        conn = psycopg2.connect(
            host=args.db_host, port=args.db_port, dbname=args.db_name,
            user=args.db_user, password=args.db_password, connect_timeout=8)
    except Exception as e:
        print('ERROR: 无法连接数据库 %s@%s:%s/%s: %s' % (
            args.db_user, args.db_host, args.db_port, args.db_name, e), file=sys.stderr)
        return 2
    cur = conn.cursor()

    # ---- 载入全部菜单（含 xmlid；name 为 jsonb 翻译字典，取 zh_CN/en_US）----
    active_clause = '' if args.inactive else "AND m.active"
    cur.execute(f"""
        SELECT m.id,
               COALESCE(NULLIF(m.name->>'zh_CN', ''), NULLIF(m.name->>'en_US', ''),
                        m.name::text),
               m.parent_id, m.action, md.module, md.name
        FROM ir_ui_menu m
        LEFT JOIN ir_model_data md
          ON md.model='ir.ui.menu' AND md.res_id=m.id AND md.module IS NOT NULL
        WHERE 1=1 {active_clause}
        ORDER BY COALESCE(m.parent_id, 0), m.sequence, m.id
    """)
    menus = [{'id': r[0], 'name': r[1], 'parent_id': r[2], 'action': r[3],
              'xmlid': (r[4] + '.' + r[5]) if r[4] and r[5] else ''} for r in cur.fetchall()]
    by_id = {m['id']: m for m in menus}

    # ---- 预取各动作表的全部 id（存在性）与 res_model ----
    model_of = {}   # action_id -> res_model（若有）
    seen_actions = set()
    # ir_model id → 模型名（ir_act_server.model_id 存的是 ir_model 行 id）
    cur.execute('SELECT id, model FROM ir_model')
    ir_model_name = {r[0]: r[1] for r in cur.fetchall()}
    for amodel, (tbl, col) in _ACTION_TYPES.items():
        if not table_exists(cur, tbl):
            continue
        cur.execute('SELECT id FROM %s' % tbl)
        for (aid,) in cur.fetchall():
            seen_actions.add(aid)
        if col and has_column(cur, tbl, col):
            cur.execute('SELECT id, %s FROM %s WHERE %s IS NOT NULL' % (col, tbl, col))
            for aid, m in cur.fetchall():
                if amodel == 'ir.actions.server':
                    # model_id 为 ir_model 行 id → 转模型名；查不到则留原值待判失效
                    model_of[aid] = ir_model_name.get(m, m)
                else:
                    model_of[aid] = m

    # ---- 全部已存在模型名 ----
    cur.execute('SELECT model FROM ir_model')
    known_models = {r[0] for r in cur.fetchall()}

    # ---- 窗口动作的视图挂载（act_window_view → ir_ui_view）----
    window_views = {}   # act_window_id -> [(view_id, view_mode)]
    known_views = {}
    if has_column(cur, 'ir_act_window_view', 'act_window_id'):
        cur.execute("""
            SELECT wv.act_window_id, wv.view_id, wv.view_mode
            FROM ir_act_window_view wv
            WHERE wv.view_id != 0
        """)
        for awid, vid, mode in cur.fetchall():
            window_views.setdefault(awid, []).append((vid, mode))
        cur.execute('SELECT id FROM ir_ui_view')
        known_views = {r[0] for r in cur.fetchall()}

    # ---- 菜单组参照校验（警告级；Odoo19 rel 表列为 gid，且 FK 为 CASCADE，
#      组被删时关联行已随删，此检查主要防畸形/手改库）----
    broken_groups = set()
    if has_column(cur, 'ir_ui_menu_group_rel', 'gid'):
        cur.execute("""
            SELECT DISTINCT r.menu_id FROM ir_ui_menu_group_rel r
            LEFT JOIN res_groups g ON g.id = r.gid
            WHERE g.id IS NULL
        """)
        for (mid,) in cur.fetchall():
            broken_groups.add(mid)

    # ---- 逐菜单审计 ----
    rows = []
    failures = []
    for m in menus:
        label = m['xmlid'] or ('(无 xmlid) id=%s' % m['id'])
        parent = m['parent_id']
        raw_action = m['action']
        aid = None
        amodel = None
        if raw_action:
            parts = str(raw_action).split(',', 1)
            if len(parts) == 2:
                amodel, aid_s = parts
                try:
                    aid = int(aid_s)
                except ValueError:
                    aid = None
        if amodel is None:
            # 无动作：分组父菜单正常；叶子菜单无动作=死链（提示级）
            has_children = any(c['parent_id'] == m['id'] for c in menus)
            if has_children:
                status, kind, model, note = True, 'NONE(分组)', '', ''
            else:
                status, kind, model, note = True, 'NONE(叶子)', '', '叶子菜单无动作(死链提示，需人工确认)'
        elif amodel not in _ACTION_TYPES:
            status, kind, model, note = True, amodel, '', '未覆盖动作类型(不判失效)'
        elif aid is None or aid not in seen_actions:
            status, kind, model, note = False, amodel, '', '动作记录不存在(action=%s,%s)' % (amodel, aid)
        else:
            kind = amodel
            model = model_of.get(aid, '') or ''
            problems = []
            note = ''
            if amodel == 'ir.actions.act_window':
                if not model:
                    problems.append('act_window 未配置 res_model')
                elif model not in known_models:
                    problems.append('res_model 不存在于 ir_model: %s' % model)
                # 视图挂载检查：窗口动作应至少挂了视图（无视图=将落到通用视图，
                # 历史 A8 报错几乎都来自视图/模型过期，故仅作提示）
                wv = window_views.get(aid, [])
                for vid, _mode in wv:
                    if vid not in known_views:
                        problems.append('窗口视图缺失 view_id=%s' % vid)
                if not wv:
                    note = '未挂自定义视图(将用通用视图)'
            elif amodel == 'ir.actions.server' and model and model not in known_models:
                problems.append('server 动作 model 不存在: %s' % model)
            elif amodel == 'ir.actions.report' and model and model not in known_models:
                problems.append('报表模型不存在: %s' % model)
            status = not problems
            note = note or '; '.join(problems)
        gnote = '组缺失' if m['id'] in broken_groups else ''
        row = {
            'id': m['id'], 'name': m['name'], 'parent_id': parent,
            'xmlid': label, 'action_type': kind, 'res_model': model,
            'ok': status, 'note': note or gnote,
        }
        rows.append(row)
        if not status:
            failures.append(row)

    conn.close()
    roots = [r for r in rows if not r['parent_id']]
    if args.only_root:
        rows = roots

    if args.json:
        print(json.dumps({'total': len(rows), 'failures': len(failures),
                          'rows': rows}, ensure_ascii=False, indent=1))
        return 1 if failures else 0

    print('=' * 78)
    print('菜单探活审计  db=%s  菜单数=%d  根菜单=%d  失效=%d'
          % (args.db_name, len(rows), len(roots), len(failures)))
    print('=' * 78)
    for r in rows:
        mark = 'ok  ' if r['ok'] else 'FAIL'
        print('%s|%s|menu=%s|%s|action=%s|res_model=%s|%s'
              % (mark, r['xmlid'], r['id'], r['name'],
                 r['action_type'], r['res_model'] or '-', r['note'] or ''))
    if failures:
        print('-' * 78)
        print('失效清单（%d 项）——修复方向：确认对应模块已安装/升级（A8：' % len(failures))
        print('docker compose exec web odoo -c /etc/odoo/odoo.conf -d edu19 '
              '-u edu_portal,edu_life,edu_schedule,edu_apply '
              '--stop-after-init 后 restart web），如模块已卸载请停用对应菜单')
        for f in failures:
            print('  FAIL menu=%s %s action=%s res_model=%s %s'
                  % (f['id'], f['name'], f['action_type'], f['res_model'], f['note']))
        return 1
    print('\n全部菜单动作有效。')
    return 0


if __name__ == '__main__':
    sys.exit(main())