#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A9 公开站死链导航接线（幂等，--dry-run 预览，Q6 A 方案）。

把公开站导航里的 8 个 '#' 占位菜单映射到真页面或删除：

    活动 / Events ............ → /my/calendar     （一体化校历，B10）
    入场 / Admission ......... → /apply            （已有报名真页）
    工作机会 / 工作 / 校友     → 合并进「校友与就业」 → /alumni/jobs
                                  （edu_public 新公开页，复用 edu.alumni.job）
    论坛 / 博客 / 展示位置     → 删除（含子菜单）

特性：
- 幂等：已映射/已删除/已建的菜单二次运行零改动；
- 名称匹配兼容 website_menu.name 的 jsonb 翻译格式（{"en_US":..,"zh_CN":..}）
  与纯文本两种形态，中英文名均可命中；
- 删除「工作机会/工作/校友」时连子菜单整棵移除，随后确保唯一的
  「校友与就业」菜单存在（不重复创建）；
- 只操作 --website 指定站点的菜单（默认 1），不动其他站点。

用法（本地/生产均为 docker 部署，走容器内 psql，无需 psycopg2）：

    预览：
        python3 scripts/nav_fix.py --dry-run
        python3 scripts/nav_fix.py --list
    执行（生产）：
        python3 scripts/nav_fix.py \
            --container prod-host --db edu19 --website 1
    环境变量兜底：EDU_DB_CONTAINER / EDU_DB_NAME（tests/smoke 同款约定）。
"""
import argparse
import json
import subprocess
import sys

DEFAULT_CONTAINER = 'edu19-clone-db-1'
DEFAULT_DB = 'edu19'

# 目标站点固定为学校站点（生产 edu.example.org 的 website.id）
TARGET_WEBSITE = 1

# ---- 8 个占位菜单的分类规则 --------------------------------------------
# 每类：(名称匹配片段[中+英小写], 动作)
# 动作：('url', 目标url) 重映射；('merge',) 合并删除（并入校友与就业）；
#       ('delete',) 直接删除。
RULES = [
    ('events',    ('活动',), ('event',),          ('url', '/my/calendar')),
    ('admission', ('入场',), ('admission',),      ('url', '/apply')),
    ('alumni',    ('校友',), ('alumni',),         ('merge',)),
    ('jobs',      ('工作机会', '工作', '校园工作'),
                  ('job', 'career', 'recruit'),   ('merge',)),
    ('forum',     ('论坛',), ('forum',),          ('delete',)),
    ('blog',      ('博客',), ('blog',),           ('delete',)),
    ('locations', ('展示位置', '地点'), ('location',), ('delete',)),
]

DEST_MENU = ('/alumni/jobs', '校友与就业', 'Alumni & Careers')


def _run_psql(sql, container, db, dbuser):
    """容器内执行 psql，返回 (returncode, stdout)。"""
    proc = subprocess.run(
        ['docker', 'exec', '-i', container, 'psql', '-U', dbuser, '-d', db,
         '-tA', '-v', 'ON_ERROR_STOP=1', '-c', sql],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError('psql failed: %s' % proc.stderr.strip()[:500])
    return proc.stdout.strip()


def _select_menus(container, db, dbuser):
    rows = _run_psql(
        'SELECT id, parent_id, name, url, website_id, sequence, parent_path '
        'FROM website_menu ORDER BY id', container, db, dbuser)
    menus = []
    for line in rows.splitlines():
        if not line.strip():
            continue
        parts = line.split('|')
        menus.append({
            'id': int(parts[0]),
            'parent_id': int(parts[1]) if parts[1] else None,
            'name': parts[2],
            'url': parts[3],
            'website_id': int(parts[4]) if parts[4] else None,
            'sequence': int(parts[5]) if len(parts) > 5 and parts[5] else 0,
            'parent_path': parts[6] if len(parts) > 6 else None,
        })
    return menus


def _name_texts(raw):
    """website_menu.name 可能是 jsonb 翻译 dict 或纯文本。"""
    if not raw:
        return []
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            return [str(v) for v in d.values() if v]
    except (ValueError, TypeError):
        pass
    return [raw]


def _classify(row):
    """返回类别 key 或 None；「校友与就业」目标菜单优先于一切分类；
    已指向目标 url 的菜单视为「已完成」返回 None。"""
    texts = [t.lower() for t in _name_texts(row['name'])]
    url = (row['url'] or '').lower()
    # 目标菜单（url 已是 /alumni/jobs，或名字即「校友与就业」）：
    # 必须比「校友」合并规则更先判定，否则二次运行会把自家菜单删掉重建
    if url.endswith(DEST_MENU[0]) or any(
            '校友与就业' in t or 'alumni & career' in t for t in texts):
        return 'dest'
    for key, zh, en, _action in RULES:
        if not any(x in t for t in texts for x in zh) \
                and not any(x in t for t in texts for x in en):
            continue
        if key == 'events' and url.endswith('/my/calendar'):
            return None            # 已映射，跳过
        if key == 'admission' and url.endswith('/apply'):
            return None            # 已映射，跳过
        return key
    return None


def _descendants(menus, ids):
    """收集 ids 的所有子孙菜单 id（按 parent_id 递归）。"""
    by_parent = {}
    for m in menus:
        by_parent.setdefault(m['parent_id'], []).append(m['id'])
    out = set(ids)
    stack = list(ids)
    while stack:
        cur = stack.pop()
        for child in by_parent.get(cur, []):
            if child not in out:
                out.add(child)
                stack.append(child)
    return sorted(out)


def build_plan(menus, website):
    """分类菜单并生成操作计划。返回 (ops, summary)。

    ops: [('update', id, name, url, 新url, 原因), ('delete', id, name, url, 原因),
          ('create', jsonname, url, sequence, parent_id, pp_base, 原因)]
    """
    ops = []
    merged = []          # 待合并删除（jobs/alumni 类）
    deleted = []         # 待直接删除（forum/blog/locations 类）
    retargets = []       # (row, 新url, 原因)
    dest_exists = False
    dest_row = None

    for m in menus:
        if website is not None and m['website_id'] != website:
            continue
        key = _classify(m)
        if key is None:
            continue
        if key == 'dest':
            dest_exists = True
            dest_row = m
        elif key in ('forum', 'blog', 'locations'):
            deleted.append(m)
        elif key in ('jobs', 'alumni'):
            merged.append(m)
        elif key == 'events':
            retargets.append((m, '/my/calendar', '活动 -> 校历页'))
        elif key == 'admission':
            retargets.append((m, '/apply', '入场 -> 报名页'))

    for m in merged:
        ops.append(('delete', m['id'], m['name'], m['url'],
                    '并入「校友与就业」'))
    del_ids = set(m['id'] for m in merged)
    # 合并删除时整棵子树移除（工作机会的子菜单等）
    for child in _descendants(menus, sorted(del_ids)):
        row = next((mm for mm in menus if mm['id'] == child), None)
        if row and child not in del_ids:
            ops.append(('delete', child, row['name'], row['url'],
                        '「校友与就业」合并（子菜单）'))

    for m in deleted:
        ops.append(('delete', m['id'], m['name'], m['url'], '死链删除'))

    for row, new_url, reason in retargets:
        if row['url'] == new_url:
            continue
        ops.append(('update', row['id'], row['name'], row['url'],
                    new_url, reason))

    # 确保「校友与就业」目标菜单存在（最多一条）；挂在站点主菜单树下
    # 才能进入导航栏渲染（website.menu_id = 第一个根菜单的子树）
    site_rows = [m for m in menus if m['website_id'] == website]
    roots = sorted([m for m in site_rows if m['parent_id'] is None],
                   key=lambda m: m['id'])
    root = roots[0] if roots else None
    if not dest_exists:
        seq = 60
        if root is not None:
            child_seqs = [m['sequence'] for m in site_rows
                          if m['parent_id'] == root['id']]
            seq = (max(child_seqs) + 10) if child_seqs else 10
        pp_base = (root['parent_path'] or ('%d/' % root['id'])) if root \
            else None
        ops.append(('create', json.dumps(
            {'en_US': DEST_MENU[2], 'zh_CN': DEST_MENU[1]},
            ensure_ascii=False), DEST_MENU[0], seq,
            root['id'] if root else None, pp_base,
            '新建「校友与就业」菜单'))
    elif dest_row and dest_row['url'] != DEST_MENU[0]:
        ops.append(('update', dest_row['id'], dest_row['name'],
                    dest_row['url'], DEST_MENU[0], '「校友与就业」改指新页'))

    summary = {
        'update': sum(1 for o in ops if o[0] == 'update'),
        'delete': sum(1 for o in ops if o[0] == 'delete'),
        'create': sum(1 for o in ops if o[0] == 'create'),
    }
    return ops, summary


def _render_ops(ops):
    lines = []
    for op in ops:
        if op[0] == 'update':
            _, mid, name, old, new, reason = op
            lines.append('UPDATE menu#%s %r  %s -> %s  (%s)' % (
                mid, name, old, new, reason))
        elif op[0] == 'delete':
            _, mid, name, url, reason = op
            lines.append('DELETE  menu#%s %r  url=%s  (%s)' % (
                mid, name, url, reason))
        else:
            _, name, url, seq, parent_id, _pp, reason = op
            lines.append('CREATE  menu %s  url=%s seq=%s parent=%s  (%s)' % (
                name, url, seq, parent_id or 'root', reason))
    return lines


def apply_plan(ops, container, db, dbuser, website):
    """以单个 psql -c 事务执行全部操作；返回受影响说明。"""
    statements = ['BEGIN']
    for op in ops:
        if op[0] == 'update':
            _, mid, _n, _o, new, _r = op
            statements.append(
                "UPDATE website_menu SET url = '%s', write_date = now() "
                "WHERE id = %s;" % (new.replace("'", "''"), mid))
        elif op[0] == 'delete':
            _, mid, _n, _u, _r = op
            statements.append('DELETE FROM website_menu WHERE id = %s;' % mid)
        else:
            _, name_json, url, seq, parent_id, pp_base, _r = op
            parent_sql = 'NULL'
            if parent_id:
                parent_sql = str(parent_id)
            # 两步同事务：INSERT 后立即用 currval 补 parent_path
            # （数据修改 CTE 的主 UPDATE 看不到刚插入的行，勿用 WITH 写法）
            statements.append(
                "INSERT INTO website_menu "
                "(name, url, website_id, sequence, parent_id, "
                "create_uid, write_uid, create_date, write_date) VALUES "
                "('%s'::jsonb, '%s', %s, %s, %s, 1, 1, now(), now());"
                "UPDATE website_menu SET parent_path = '%s' || id || '/' "
                "WHERE id = currval('website_menu_id_seq');"
                % (name_json.replace("'", "''"), url, website, seq,
                   parent_sql, (pp_base or '').replace("'", "''")))
    statements.append('COMMIT')
    _run_psql('; '.join(statements), container, db, dbuser)
    return len(ops)


def main():
    ap = argparse.ArgumentParser(
        description='A9 公开站死链导航接线：8 个占位菜单映射/删除（幂等）。')
    ap.add_argument('--dry-run', action='store_true',
                    help='只打印将要执行的操作，不写库')
    ap.add_argument('--list', action='store_true',
                    help='列出目标站全部菜单及其 A9 分类')
    ap.add_argument('--container', default=None,
                    help='psql 所在容器（默认 EDU_DB_CONTAINER 或 %s）'
                         % DEFAULT_CONTAINER)
    ap.add_argument('--db', default=None,
                    help='数据库名（默认 EDU_DB_NAME 或 %s）' % DEFAULT_DB)
    ap.add_argument('--dbuser', default='odoo', help='数据库用户（默认 odoo）')
    ap.add_argument('--website', type=int, default=TARGET_WEBSITE,
                    help='目标站点 website.id（默认 1）')
    args = ap.parse_args()

    container = args.container or DEFAULT_CONTAINER
    db = args.db or DEFAULT_DB

    menus = _select_menus(container, db, args.dbuser)

    if args.list:
        for m in menus:
            cls = _classify(m)
            print('%-4s parent=%-4s website=%s %-10s url=%-16s %r' % (
                m['id'], m['parent_id'], m['website_id'],
                cls or '-', m['url'] or '', m['name']))
        return 0

    ops, summary = build_plan(menus, args.website)
    lines = _render_ops(ops)
    if args.dry_run:
        print('--- A9 导航接线 · dry-run（不写库）---')
        print('\n'.join(lines) if lines else '（无待办操作：导航已就绪）')
        print('--- 计划汇总: update=%d delete=%d create=%d ---' % (
            summary['update'], summary['delete'], summary['create']))
        return 0

    if not ops:
        print('无待办操作：导航已就绪（幂等）。')
        return 0
    n = apply_plan(ops, container, db, args.dbuser, args.website)
    print('--- A9 导航接线完成：共 %d 个操作（事务提交）---' % n)
    for line in lines:
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())