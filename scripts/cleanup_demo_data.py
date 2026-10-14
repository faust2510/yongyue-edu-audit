#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""样品账号与演示数据清理（v2.1-A10 工具化，生产门禁）。

两类目标：
  A. 样品账号（seed_* / 本地演示产生的账号）——输出邮箱清单；
     --deactivate 停用（active=False，安全，默认动作），
     --delete-users 硬删除（危险：op.student.user_id 为 ondelete=CASCADE，
     会连坐删除学生档案，非必要不要用）。
  B. 演示数据——按「名称标记 + 批量码」识别：
     · 名称标记：名称/正文含「演示」「【演示】」「冒烟」的记录
       （seed_* 全部演示数据统一使用这些标记，见 scripts/seed_*.py）；
     · 批量码：seed_demo 生成的班级码（--include-seed-codes 开启才纳入删除，
       默认只报告；注意 CRS-*/PRP-2026 已转为真实骨架，绝不按码删）；
     · 关联数据：演示学生/教师/家长（名称标记或挂接样品账号）的
       打卡/周记/评估分等（--include-linked-data 开启才纳入删除）；
     · 演示人档案（--delete-demo-persons 开启才删除 op_student/op_parent/
       op_faculty 行）。

  ★ 解绑先于删除（评审 F3 强制约定）：op_student.user_id 的外键是
    ON DELETE CASCADE——直接删 res_users 会级联删掉整个学生档案！
    因此 --execute 时先执行「解绑」阶段：把样品账号与待删人档案的
    user_id（op_student.user_id / op_parent.user_id / res_partner.user_id，
    教师经 partner 委托同列）全部置空，再删用户/档案/数据。
    （已在本库实测：op_student.user_id=CASCADE、op_parent.user_id=SET NULL、
    res_partner.user_id=SET NULL、res_users.partner_id=RESTRICT。）

默认 = --dry-run：只输出两份清单（账号邮箱 + 各模型记录明细），不动数据。
正式执行必须显式 --execute；逐模型在独立 savepoint 中删除，被外键挡住的
记录跳过并报告（绝不整体回滚）。

用法：
  python3 scripts/cleanup_demo_data.py --dry-run                  # 预览（默认）
  python3 scripts/cleanup_demo_data.py --execute                  # 正式执行
  python3 scripts/cleanup_demo_data.py --deactivate --execute     # 停用样品账号
  python3 scripts/cleanup_demo_data.py --only edu.lesson --execute
  连接参数：--db-host/--db-port/--db-name/--db-user/--db-password
  容器内执行：docker compose exec web python3 /tmp/cleanup_demo_data.py \\
      --db-host db --db-user odoo --db-password <pwd> --dry-run
退出码：0=成功；2=连接/参数错误；3=执行模式中存在被跳过项。
"""
import argparse
import sys

try:
    import psycopg2
except ImportError:
    psycopg2 = None

# ---------------------------------------------------------------------------
# 演示数据规格：(模型名, 表名, 名称列, 类别)
#   类别：marker=名称标记直删；marker-depend=父表命中后按外键归属；
#         linked=按演示人集（student_id/faculty_id/parent_id）归属。
# 依赖顺序：依赖者（子）在前，父表在后。
# ---------------------------------------------------------------------------
DEMO_MODELS = [
    # 子表（marker-depend：按父表命中集合归属）
    ('edu.fee.payment',       'edu_fee_payment',       [],           'marker-depend', 'bill_id'),
    ('edu.lesson.progress',   'edu_lesson_progress',   [],           'marker-depend', 'lesson_id'),
    # 关联数据（linked：按演示人集归属）
    ('edu.checkin.record',    'edu_checkin_record',    ['name'],     'linked',        'student_id'),
    ('edu.journal.entry',     'edu_journal_entry',     ['name'],     'linked',        'student_id'),
    # 父表（marker：名称/正文标记直删）
    ('edu.lesson',            'edu_lesson',            ['name'],     'marker',        None),
    ('edu.notice',            'edu_notice',            ['name'],     'marker',        None),
    ('edu.fee.bill',          'edu_fee_bill',          ['name'],     'marker',        None),
    ('edu.leave',             'edu_leave',             ['name', 'reason'], 'marker',  None),
    ('edu.grievance',         'edu_grievance',         ['name', 'reason'], 'marker',  None),
    ('op.media',              'op_media',              ['name'],     'marker',        None),
    ('op.subject',            'op_subject',            ['name', 'code'], 'marker',    None),
    ('op.course',             'op_course',             ['name', 'code'], 'marker',    None),
    ('op.batch',              'op_batch',              ['name', 'code'], 'marker',    None),
]

# 种子脚本批量码（仅收 seed_demo.py 的明确演示码）。
# 注意：seed_yongyue_data.py 的 CRS-* 课程与 PRP-2026 班级已转为真实骨架
# （预备科 · 2026级 等正式名称），绝不能按码删——故不列入。
SEED_CODES = {
    'op_batch': ['B2401'],
}

# 样品账号识别：登录名以 @local/@demo/@test 结尾，或名称含演示/冒烟标记
# （seed_* 与本地演示账号统一约定；@test 覆盖注册测试残留。
#  Odoo19 中 res_users 无 name/email 列，均经 partner_id 取自 res_partner；
#  本串经 Python %-插值嵌入外层 SQL，故用单 %（勿按 psycopg2 参数写成 %%））
SAMPLE_LOGIN_SUFFIXES = ('@local', '@demo', '@test')
SAMPLE_MARKER_SQL = "u.login ILIKE '%@local' OR u.login ILIKE '%@demo%' " \
                    "OR u.login ILIKE '%@test%' OR p.name ILIKE '%演示%' " \
                    "OR p.name ILIKE '%冒烟%'"

ALLOWED_MODELS = {m[0] for m in DEMO_MODELS}


def build_parser():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--db-host', default='127.0.0.1')
    p.add_argument('--db-port', type=int, default=5432)
    p.add_argument('--db-name', default='edu19')
    p.add_argument('--db-user', default='odoo')
    p.add_argument('--db-password', default='odoo')
    p.add_argument('--dry-run', action='store_true',
                   help='预览模式（默认即预览）：只输出清单，不改数据')
    p.add_argument('--execute', action='store_true',
                   help='正式执行：按清单删除演示数据（默认仅预览）')
    p.add_argument('--deactivate', action='store_true',
                   help='样品账号执行动作=停用(active=False)')
    p.add_argument('--delete-users', action='store_true',
                   help='样品账号执行动作=硬删除（危险，见文档）')
    p.add_argument('--include-seed-codes', action='store_true',
                   help='种子批量码（B2401/PRP-2026 等）纳入删除范围（默认仅报告）')
    p.add_argument('--include-linked-data', action='store_true',
                   help='演示人的打卡/周记/评估分等关联数据纳入删除范围（默认仅报告）')
    p.add_argument('--delete-demo-persons', action='store_true',
                   help='同时删除演示人档案（op_student/op_parent/op_faculty，'
                        '先解绑 user_id 再删）')
    p.add_argument('--only', metavar='MODEL', default='',
                   help='只处理指定模型（如 edu.lesson），其余仅预览计数')
    p.add_argument('--json', action='store_true', help='输出 JSON 报告')
    return p


def has_column(cur, table, column):
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=%s AND column_name=%s", (table, column))
    return cur.fetchone() is not None


def table_exists(cur, table):
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name=%s", (table,))
    return cur.fetchone() is not None


def qcol(cur, table, cols):
    """过滤出表中真实存在的列。"""
    return [c for c in cols if has_column(cur, table, c)]


def marker_where(cur, table, cols):
    """名称/正文标记条件；无可用列返回 (None, [])。"""
    real = qcol(cur, table, cols)
    if not real:
        return None, []
    conds = ' OR '.join(
        "(CAST(%s AS TEXT) ILIKE '%%演示%%' OR CAST(%s AS TEXT) ILIKE '%%冒烟%%')" % (c, c)
        for c in real)
    return conds, []


def pkey_exists(cur, table):
    cur.execute("""
        SELECT a.attname FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisprimary
    """, (table,))
    row = cur.fetchone()
    return row[0] if row else 'id'


def main():
    args = build_parser().parse_args()
    if psycopg2 is None:
        print('ERROR: 需要 psycopg2（python3 -m pip install psycopg2-binary）', file=sys.stderr)
        return 2
    args.dry_run = not args.execute  # --execute 显式覆盖默认预览
    if args.delete_users and args.deactivate:
        print('ERROR: --delete-users 与 --deactivate 互斥，只能选一个', file=sys.stderr)
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

    mode = 'EXECUTE' if args.execute else 'DRY-RUN'
    report = {'mode': mode, 'accounts': [], 'models': [], 'notes': []}
    skipped_any = False

    # ========================= A. 样品账号 =========================
    cur.execute(
        "SELECT u.id, u.login, p.name, p.email, u.active "
        "FROM res_users u JOIN res_partner p ON p.id = u.partner_id "
        "WHERE %s ORDER BY u.login" % SAMPLE_MARKER_SQL)
    account_rows = cur.fetchall()
    # 技术账号过滤：系统/OdooBot/公众/模板账号不当作样品（先取完账号行再查）
    cur.execute("SELECT id FROM res_users WHERE login IN "
                "('__system__','__oe__','OdooBot','public',"
                "'portaltemplate','parentportaltemplate')")
    tech = {r[0] for r in cur.fetchall()}
    accounts = [{'id': r[0], 'login': r[1], 'name': r[2], 'email': r[3] or '',
                 'active': bool(r[4])} for r in account_rows
                if r[0] not in tech]
    report['accounts'] = accounts
    sample_uids = [a['id'] for a in accounts]
    # 账号动作在 B2 ②（解绑之后）统一执行——见下方 B2 阶段
    act = ('delete' if args.delete_users
           else 'deactivate' if args.deactivate else 'report')
    for a in accounts:
        a['applied'] = 'pending-' + act
    report['notes'].append('账号动作: %s（在解绑后执行）' % act)

    # ========================== B. 演示数据 ==========================
    # B0. 演示人集合（linked 口径）：名称标记人 + 挂接样品账号的人
    demo_persons = {'op_student': set(), 'op_faculty': set(), 'op_parent': set()}
    cur.execute("""
        SELECT s.id FROM op_student s JOIN res_partner p ON p.id = s.partner_id
        WHERE p.name ILIKE '%%演示%%' OR p.name ILIKE '%%冒烟%%'""")
    demo_persons['op_student'] |= {r[0] for r in cur.fetchall()}
    cur.execute("""
        SELECT f.id FROM op_faculty f JOIN res_partner p ON p.id = f.partner_id
        WHERE p.name ILIKE '%%演示%%' OR p.name ILIKE '%%冒烟%%'""")
    demo_persons['op_faculty'] |= {r[0] for r in cur.fetchall()}
    cur.execute("""
        SELECT p.id FROM op_parent p JOIN res_partner rp ON rp.id = p.name
        WHERE rp.name ILIKE '%%演示%%' OR rp.name ILIKE '%%冒烟%%'""")
    demo_persons['op_parent'] |= {r[0] for r in cur.fetchall()}
    for tbl, col in (('op_student', 'user_id'), ('op_parent', 'user_id'),
                     ('op_faculty', 'user_id')):
        if not has_column(cur, tbl, col):
            continue
        uids = tuple(sample_uids)
        if not uids:
            continue
        cur.execute('SELECT id FROM %s WHERE %s IN %%s' % (tbl, col), (uids,))
        demo_persons[tbl] |= {r[0] for r in cur.fetchall()}
    person_table = {'edu.checkin.record': 'op_student',
                    'edu.journal.entry': 'op_student'}

    # B0b. 演示人档案（可删目标，--delete-demo-persons 才执行）：
    #     名称标记 + 挂接样品账号；教师另按 partner.user_id 归属样品账号
    if sample_uids:
        cur.execute("""
            SELECT f.id FROM op_faculty f JOIN res_partner p ON p.id = f.partner_id
            WHERE p.user_id IN %s""", (tuple(sample_uids),))
        demo_persons['op_faculty'] |= {r[0] for r in cur.fetchall()}

    # B1. 逐模型计算命中集（先父表算 marker，再依赖表/关联表）
    match = {}   # model -> id 集合
    detail = {}  # model -> [{id, label}]
    only = args.only and args.only.strip()
    for model, table, cols, kind, own_col in DEMO_MODELS:
        if only and model != only:
            continue
        if not table_exists(cur, table):
            report['notes'].append('表不存在，跳过: %s' % table)
            continue
        pk = pkey_exists(cur, table)
        ids = set()
        if kind == 'marker':
            w, params = marker_where(cur, table, cols)
            if w:
                if model in SEED_CODES and has_column(cur, table, 'code'):
                    cur.execute('SELECT %s FROM %s WHERE %s' % (pk, table, w),
                                params or None)
                    found = {r[0] for r in cur.fetchall()}
                    # 区分标记命中与码命中：标记命中必删；码命中视开关
                    ids |= found
                    if args.include_seed_codes:
                        codes = tuple(SEED_CODES[model])
                        cur.execute(
                            'SELECT %s FROM %s WHERE code IN %%s' % (pk, table),
                            (codes,))
                        found2 = {r[0] for r in cur.fetchall()}
                        ids |= found2
                        report['notes'].append(
                            '%s: 批量码纳入(%s)' % (model, ','.join(SEED_CODES[model])))
                    else:
                        hit_codes = []
                        for code in SEED_CODES[model]:
                            cur.execute(
                                'SELECT %s FROM %s WHERE code = %%s' % (pk, table),
                                (code,))
                            for (rid,) in cur.fetchall():
                                if rid in ids:
                                    continue
                                hit_codes.append(rid)
                        if hit_codes:
                            report['notes'].append(
                                '%s: 批量码命中 %d 条（未删，需 --include-seed-codes）'
                                % (model, len(hit_codes)))
                            report['models'].append({
                                'model': model, 'kind': 'seed-codes',
                                'dry_run_only': True, 'ids': hit_codes})
                else:
                    cur.execute('SELECT %s FROM %s WHERE %s' % (pk, table, w),
                                params or None)
                    ids = {r[0] for r in cur.fetchall()}
            # marker 且有关联码标的父表（op.course/op.batch）在无码时也列出
            if not ids and model in SEED_CODES and not args.include_seed_codes:
                pass  # 码命中但未开启，已在上方 note 报告
        elif kind == 'marker-depend':
            # 依赖表经父表外键归属（own_col → 父模型）
            parent_map = {'bill_id': 'edu.fee.bill',
                          'lesson_id': 'edu.lesson'}
            pm = parent_map.get(own_col)
            pids = set(match.get(pm, []))
            if pids and has_column(cur, table, own_col):
                cur.execute('SELECT %s FROM %s WHERE %s IN %%s' % (pk, table, own_col),
                            (tuple(sorted(pids)),))
                ids = {r[0] for r in cur.fetchall()}
        elif kind == 'linked':
            if not args.include_linked_data:
                report['notes'].append('%s: 关联数据未纳入（需 --include-linked-data）' % model)
                continue
            ptbl = person_table.get(model, 'op_student')
            pids = demo_persons.get(ptbl)
            if pids and has_column(cur, table, own_col):
                cur.execute('SELECT %s FROM %s WHERE %s IN %%s' % (pk, table, own_col),
                            (tuple(sorted(pids)),))
                ids = {r[0] for r in cur.fetchall()}
        else:
            continue
        if not ids:
            continue
        # 取可读标签（名称列或主键）
        if has_column(cur, table, 'name'):
            cur.execute('SELECT %s, name FROM %s WHERE %s IN %%s ORDER BY %s'
                        % (pk, table, pk, pk), (tuple(sorted(ids)),))
            detail[model] = [{'id': r[0], 'label': r[1] or ''} for r in cur.fetchall()]
        else:
            detail[model] = [{'id': i, 'label': ''} for i in sorted(ids)]
        match[model] = ids
        report['models'].append({'model': model, 'kind': kind,
                                 'dry_run_only': False,
                                 'ids': sorted(ids)})

    # B2. 执行（--execute）——顺序铁律（评审 F3）：
    #    ① 解绑（unlink user_id → NULL，防止 op_student.user_id CASCADE 连坐）
    #    ② 账号（停用/删除）  ③ 演示人档案（--delete-demo-persons）
    #    ④ 演示数据（按 DEMO_MODELS 顺序，先子后父）
    if args.execute:
        # ---------- ① 解绑 ----------
        # 需解绑的账号 = 样品账号 ∪ 待删人档案当前挂接的账号
        unlink_uids = set(sample_uids)
        person_rows = demo_persons  # {op_student:[...], op_parent:[...], op_faculty:[...]}
        if has_column(cur, 'op_student', 'user_id'):
            cur.execute('SELECT user_id FROM op_student WHERE id IN %s AND user_id IS NOT NULL',
                        (tuple(sorted(demo_persons['op_student'])) or (0,),))
            unlink_uids |= {r[0] for r in cur.fetchall()}
        if has_column(cur, 'op_parent', 'user_id'):
            cur.execute('SELECT user_id FROM op_parent WHERE id IN %s AND user_id IS NOT NULL',
                        (tuple(sorted(demo_persons['op_parent'])) or (0,),))
            unlink_uids |= {r[0] for r in cur.fetchall()}
        # 教师档案无 user_id 列（委托 res_partner.user_id），无需单独解绑
        # 教师/家长/学生的 partner.user_id 一并置空：
        if not unlink_uids:
            unlink_uids = {0}
        unlink_sql = [
            ('op_student', 'user_id'), ('op_parent', 'user_id'),
            ('res_partner', 'user_id'),
        ]
        unlink_applied = {}
        for tbl, col in unlink_sql:
            if not has_column(cur, tbl, col):
                continue
            cur.execute('UPDATE %s SET %s=NULL WHERE %s IN %%s' % (tbl, col, col),
                        (tuple(sorted(unlink_uids)),))
            unlink_applied[tbl + '.' + col] = cur.rowcount
        report['notes'].append(
            '① 解绑: ' + ', '.join('%s=%d' % (k, v) for k, v in unlink_applied.items())
            if unlink_applied else '① 解绑: 无可解绑列')
        report['unlink'] = unlink_applied

        # ---------- ② 账号 ----------
        if args.delete_users:
            n_del = n_block = 0
            for a in accounts:
                cur.execute('SAVEPOINT sp_user_%s' % a['id'])
                try:
                    cur.execute('DELETE FROM res_users WHERE id=%s', (a['id'],))
                    n_del += cur.rowcount
                    a['applied'] = 'deleted'
                except Exception as e:
                    cur.execute('ROLLBACK TO SAVEPOINT sp_user_%s' % a['id'])
                    n_block += 1
                    a['applied'] = 'blocked: %s' % str(e).strip()[:40]
                    skipped_any = True
                finally:
                    cur.execute('RELEASE SAVEPOINT sp_user_%s' % a['id'])
            report['notes'].append('② 账号: 删除 %d / 跳过 %d（硬删除被引用账号会跳过，'
                                   '建议优先 --deactivate）' % (n_del, n_block))
        elif args.deactivate:
            for a in accounts:
                cur.execute('UPDATE res_users SET active=False WHERE id=%s', (a['id'],))
                a['applied'] = 'deactivated'
            report['notes'].append('② 账号: 停用 %d 个' % len(accounts))

        # ---------- ③ 演示人档案（先解绑后删，见①） ----------
        if args.delete_demo_persons:
            for tbl, label in (('op_student', 'op_student'),
                               ('op_parent', 'op_parent'),
                               ('op_faculty', 'op_faculty')):
                ids = demo_persons.get(tbl)
                if not ids:
                    continue
                pk = pkey_exists(cur, tbl)
                deleted, blocked = 0, []
                cur.execute('SAVEPOINT sp_person_%s' % tbl)
                try:
                    cur.execute('DELETE FROM %s WHERE %s IN %%s' % (tbl, pk),
                                (tuple(sorted(ids)),))
                    deleted = cur.rowcount
                except Exception as e:
                    cur.execute('ROLLBACK TO SAVEPOINT sp_person_%s' % tbl)
                    blocked = list(ids)
                    skipped_any = True
                    report['notes'].append(
                        '③ %s: 删除被外键拦截（%s），跳过 %d 条'
                        % (label, str(e).strip()[:80], len(blocked)))
                finally:
                    cur.execute('RELEASE SAVEPOINT sp_person_%s' % tbl)
                report['notes'].append('③ %s: 删除 %d / 跳过 %d' % (label, deleted, len(blocked)))

        # ---------- ④ 演示数据 ----------
        for model, table, _cols, _kind, _oc in DEMO_MODELS:
            if only and model != only:
                continue
            ids = match.get(model)
            if not ids:
                continue
            deleted, blocked = 0, []
            cur.execute('SAVEPOINT sp_%s' % model.replace('.', '_'))
            try:
                cur.execute('DELETE FROM %s WHERE %s IN %%s' % (table, pkey_exists(cur, table)),
                            (tuple(sorted(ids)),))
                deleted = cur.rowcount
            except Exception as e:
                cur.execute('ROLLBACK TO SAVEPOINT sp_%s' % model.replace('.', '_'))
                blocked = list(ids)
                report['notes'].append('%s: 删除被外键拦截（%s），已跳过 %d 条'
                                       % (model, str(e).strip()[:80], len(blocked)))
                skipped_any = True
            finally:
                cur.execute('RELEASE SAVEPOINT sp_%s' % model.replace('.', '_'))
            report['notes'].append('%s: 删除 %d / 跳过 %d' % (model, deleted, len(blocked)))

    if args.execute:
        try:
            conn.commit()
        except Exception as e:
            print('ERROR: 提交失败: %s' % e, file=sys.stderr)
            return 2

    # ========================= C. 输出报告 =========================
    if args.json:
        import json
        print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
        return 3 if (args.execute and skipped_any) else 0

    print('=' * 78)
    print('样品与演示数据清理  db=%s  模式=%s' % (args.db_name, mode))
    print('=' * 78)
    print('【A. 样品账号】共 %d 个（动作=%s）' % (len(accounts), act))
    print('  邮箱清单：' + (', '.join(a['email'] or a['login'] for a in accounts)
                            if accounts else '（无）'))
    for a in accounts:
        print('  - %-28s %-16s %s active=%s [%s]' % (
            a['email'] or a['login'], a['login'], a['name'] or '',
            a['active'], a['applied']))
    print()
    print('【B. 演示数据】')
    for model, table, cols, kind, oc in DEMO_MODELS:
        if only and model != only:
            continue
        d = detail.get(model)
        if d is None:
            continue
        in_exe = bool(args.execute and match.get(model))
        print('  [%s] %-24s 命中 %-4d 条  %s'
              % (kind, model, len(d), ('已删除' if in_exe else '')))
        shown = d[:5]
        for r in shown:
            print('      - %s  %s' % (r['id'], r['label'] or ''))
        if len(d) > 5:
            print('      … 其余 %d 条略' % (len(d) - 5))
    if not any(m['model'] for m in report['models']) and not accounts:
        print('  （未发现样品账号或演示数据）')
    print()
    print('【说明】')
    for n in report['notes']:
        print('  * ' + n)
    if not args.execute:
        print('  * 当前为 DRY-RUN：未改动任何数据。确认后加 --execute 正式执行；')
        print('    账号停用加 --deactivate，关联数据(打卡/周记/评估分)加 --include-linked-data，')
        print('    种子批量码加 --include-seed-codes。')
    if skipped_any:
        print('  * 存在被外键拦截的跳过项（见上），请人工复核。')
    return 3 if (args.execute and skipped_any) else 0


if __name__ == '__main__':
    sys.exit(main())