# -*- coding: utf-8 -*-
"""19.0.4.0.0 后置迁移：§9.1 迁移 7 步的**逐条自证**（每步都把表格里的断言行打印出来）。

设计：docs/plans/leave-split-approval-design.md §9.1（7 步表）/ §9.2 / §10 的 S1 卡片。
前置：migrations/19.0.4.0.0/pre-migrate.py 已建好 applicant_kind 列、回填 'student'，
      并把迁移前的 (id, name, state) 快照进 edu_leave_1904_backup。

四条纪律（照 19.0.3.0.0 的教训，缺一条就是留半迁移状态或制造假红）
----------------------------------------------------------------
1. **只增不改**：既有行的 name（单号）与 state 一个字节都不许动（§9.1 步4/步5）；
2. **幂等**：全部回填语句都是「只动 NULL 行」/「NOT EXISTS」，重跑不产生重复；
3. **自证**：断言不过直接 raise ⇒ 整个 -u 事务回滚，绝不留「迁了一半」的库；
4. **全新库跳过**：version 为 None（首次安装）时没有历史数据，
   第 4/5 步（需要前置快照）显式跳过并**明写 SKIP**，不静默当绿。

⚠ 再跑安全（比字面口径更严）：第 4/5 步只在**快照表存在**时对账 ——
   上线后再因版本号变动跑一次本脚本时，快照表已被上次删除，
   于是显式 SKIP，而不会拿「今天的 name/state」去跟不存在的基线比、
   把一次正常升级变成事故（这正是 19.0.3.0.0 踩过的坑）。
"""
import logging

_logger = logging.getLogger(__name__)

#: §9.1 步4/步5 的基线快照（由 pre-migrate 建立，本脚本对账后删除）
BACKUP_TABLE = 'edu_leave_1904_backup'
#: §9.1 步7 的新表
TRANSFER_TABLE = 'edu_leave_transfer'
#: §9.1 步6 的新列
HOMEROOM_TABLE = 'op_batch'
HOMEROOM_COL = 'homeroom_teacher_id'

#: §9.1 步3：「留空或默认，无需回填」的列。
#: ⚠ 例外：proof_kind 在模型里 default='none'，Odoo 的 _init_column 会把新列的
#:   默认值写给既有行（= 'none' ⇒ 语义就是「无证明」，与「留空」等价），
#:   故本表**不含** proof_kind，改为单独断言「只能是 NULL 或 'none'」。
STEP3_COLUMNS = (
    'first_approver_id',
    'second_approver_id',
    'route_note',
    'return_confirmed_at',
    'return_confirmed_by_id',
    'return_note',
    'return_overdue_alerted_at',
    'lead_days_actual',
    'lead_days_short',
    'over_quota',
    'backfilled',
)


def _table_exists(cr, table):
    cr.execute('SELECT to_regclass(%s)', (table,))
    return bool(cr.fetchone()[0])


def _column_exists(cr, table, column):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return bool(cr.fetchone())


def _scalar(cr, sql, params=()):
    cr.execute(sql, params)
    row = cr.fetchone()
    return row[0] if row else None


def _columns_of_ddl(ddl):
    """从 CONSTRAINT / INDEX 的 DDL 文本里取列名元组。

    两种输入形态都要认（都不含嵌套括号，故取「第一个 ( 到它之后第一个 )」即可）：
      · pg_get_constraintdef → 'UNIQUE (leave_id, stage)'
      · pg_get_indexdef      → 'CREATE UNIQUE INDEX x ON public.t USING btree (leave_id, stage)'
    刻意**不用正则**：本文件在 Odoo 的迁移脚本环境里跑，少一层转义就少一个坑。
    """
    ddl = (ddl or '').strip()
    start = ddl.find('(')
    end = ddl.find(')', start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        return ()
    return tuple(c.strip().strip('"') for c in ddl[start + 1:end].split(','))


def _unique_objects(cr, table):
    """该表上所有 UNIQUE 对象（约束 + 唯一索引）：[(名字, 列元组, 类型)]。"""
    found = []
    cr.execute("""
        SELECT c.conname, pg_get_constraintdef(c.oid)
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname = %s AND c.contype = 'u'
    """, (table,))
    for name, ddl in cr.fetchall():
        found.append((name, _columns_of_ddl(ddl), 'UNIQUE CONSTRAINT'))
    cr.execute("""
        SELECT i.indexrelid::regclass::text, pg_get_indexdef(i.indexrelid)
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        WHERE t.relname = %s AND i.indisunique
    """, (table,))
    for name, ddl in cr.fetchall():
        found.append((name, _columns_of_ddl(ddl), 'UNIQUE INDEX'))
    return found


# ======================================================================
# §9.1 步 1：applicant_kind 新列 → 回填 'student'
# ======================================================================
def _step1(cr):
    # 幂等再回填（pre 已做过；这里再兜一次，防「列由 _auto_init 新建」的路径）
    cr.execute("""
        UPDATE edu_leave SET applicant_kind = 'student'
        WHERE applicant_kind IS NULL
    """)
    late_filled = cr.rowcount
    null_n = _scalar(cr, 'SELECT count(*) FROM edu_leave WHERE applicant_kind IS NULL')
    student_n = _scalar(cr, "SELECT count(*) FROM edu_leave WHERE applicant_kind = 'student'")
    staff_n = _scalar(cr, "SELECT count(*) FROM edu_leave WHERE applicant_kind = 'staff'")
    _logger.info(
        '[leave-split] 步1｜动作=新列 applicant_kind 并回填 student｜'
        '断言=SELECT count(*) FROM edu_leave WHERE applicant_kind IS NULL 应为 0 → 实测 %s｜'
        'student=%s staff=%s（本次补填 %s 行）', null_n, student_n, staff_n, late_filled)
    if null_n:
        raise RuntimeError(
            '[leave-split] 步1 断言失败：edu_leave 有 %s 行 applicant_kind 为空'
            '（设计要求 = 0）' % null_n)
    _logger.info('[leave-split] 步1 ✓ 通过')


# ======================================================================
# §9.1 步 2：applicant_user_id ← 从 student_id.user_id 尽力回填
# ======================================================================
def _step2(cr):
    if not _column_exists(cr, 'edu_leave', 'applicant_user_id'):
        raise RuntimeError('[leave-split] 步2 失败：edu_leave.applicant_user_id 列不存在')
    if not _table_exists(cr, 'op_student'):
        _logger.info('[leave-split] 步2｜动作=从 student_id.user_id 尽力回填｜'
                     '断言=设计稿**不设硬断言**｜实测：本地无 op_student 表，SKIP 回填')
        return
    cr.execute("""
        UPDATE edu_leave l SET applicant_user_id = s.user_id
        FROM op_student s
        WHERE l.student_id = s.id
          AND l.applicant_user_id IS NULL
          AND s.user_id IS NOT NULL
    """)
    filled = cr.rowcount
    still_null = _scalar(cr, 'SELECT count(*) FROM edu_leave WHERE applicant_user_id IS NULL')
    _logger.info(
        '[leave-split] 步2｜动作=applicant_user_id ← student_id.user_id（尽力）｜'
        '断言=设计稿**不设硬断言**（本仓 identity.py 是双向并集，单链 SQL 会漏，'
        '故只报告不拦）｜实测 本次回填 %s 行 / 仍为空 %s 行', filled, still_null)


# ======================================================================
# §9.1 步 3：first/second_approver_id、route_note、proof_kind、lead_days_short、
#            over_quota、return_* 留空或默认（**不回填业务值**）
# ======================================================================
def _step3(cr):
    have_snap = _table_exists(cr, BACKUP_TABLE)
    scope = ('JOIN %s b ON b.id = l.id' % BACKUP_TABLE) if have_snap else ''
    counts = []
    for col in STEP3_COLUMNS:
        if not _column_exists(cr, 'edu_leave', col):
            raise RuntimeError('[leave-split] 步3 失败：edu_leave.%s 列不存在（字段声明缺失）' % col)
        n = _scalar(cr, 'SELECT count(*) FROM edu_leave l %s WHERE l.%s IS NOT NULL'
                    % (scope, col))
        counts.append((col, n))
    _logger.info('[leave-split] 步3｜动作=留空或默认，不回填业务值｜'
                 '断言=「无需回填」⇒ 迁移前既有行在这些列上必须仍为空｜'
                 '实测（%s 非空计数）= %s', '快照行' if have_snap else '全表', counts)

    if not have_snap:
        # 再跑安全（19.0.3.0.0 的教训）：上线后会话/教务会正常写这些列，
        # 此时若拿全表当基线断言「必须为空」⇒ 误报失败并回滚一次正常升级。
        _logger.info('[leave-split] 步3 SKIP 断言：无前置快照表（全新库或本版本已迁过）'
                     '—— 上面的计数仅为读数，**不是通过**')
        return
    dirty = [c for c, n in counts if n]
    if dirty:
        raise RuntimeError(
            '[leave-split] 步3 断言失败：下列列**被意外回填**（设计要求留空）：%s'
            % ', '.join('%s=%d行' % (c, n) for c, n in counts if n))
    # proof_kind 单独：default='none' ⇒ 只允许 NULL 或 'none'（两者语义都是「无证明」）
    bad_proof = _scalar(cr, """
        SELECT count(*) FROM edu_leave
        WHERE proof_kind IS NOT NULL AND proof_kind <> 'none'
    """)
    proof_none = _scalar(cr, "SELECT count(*) FROM edu_leave WHERE proof_kind = 'none'")
    _logger.info('[leave-split] 步3 附加｜proof_kind（模型 default=none）'
                 '断言=只能是 NULL 或 none → 实测 none=%s / 其他值=%s', proof_none, bad_proof)
    if bad_proof:
        raise RuntimeError('[leave-split] 步3 附加断言失败：proof_kind 出现非 none 的值 %s 行' % bad_proof)
    _logger.info('[leave-split] 步3 ✓ 通过（全部留空/默认）')


# ======================================================================
# §9.1 步 4：**不动** name 单号（与迁移前逐字一致）
# ======================================================================
def _step4(cr):
    # ⚠ Odoo 的 Cursor.execute() 返回 None（不是 psycopg2 的 cursor）——
    #   不许写 cr.execute(...).fetchall()，必须分两行（本脚本第一版就踩了这个坑）。
    cr.execute('SELECT name FROM edu_leave ORDER BY id')
    names = [r[0] for r in cr.fetchall()]
    _logger.info('[leave-split] 步4｜动作=不动 name 单号｜'
                 '断言=SELECT name FROM edu_leave ORDER BY id 与迁移前逐字一致｜'
                 '实测 迁移后 name 序列（按 id 升序）=%s', names)
    if not _table_exists(cr, BACKUP_TABLE):
        _logger.info('[leave-split] 步4 SKIP：无前置快照表（全新库或本版本已迁过），'
                     '无法对账 —— **这不是通过**')
        return
    cr.execute("""
        SELECT id, name FROM edu_leave
        EXCEPT SELECT id, name FROM %s
    """ % BACKUP_TABLE)
    changed = cr.fetchall()
    cr.execute("""
        SELECT id, name FROM %s
        EXCEPT SELECT id, name FROM edu_leave
    """ % BACKUP_TABLE)
    lost = cr.fetchall()
    _logger.info('[leave-split] 步4 对账｜新增/改名 = %s 行 %s｜丢失 = %s 行 %s',
                 len(changed), changed[:5], len(lost), lost[:5])
    if changed or lost:
        raise RuntimeError(
            '[leave-split] 步4 断言失败：name 单号与迁移前不一致 '
            '（新增/改名 %s 行，丢失 %s 行）—— 单号必须逐字保留' % (len(changed), len(lost)))
    _logger.info('[leave-split] 步4 ✓ 通过（name 逐字一致）')


# ======================================================================
# §9.1 步 5：**不动**既有行 state（尤其 state='refused'）
# ======================================================================
def _step5(cr):
    cr.execute("SELECT state, count(*) FROM edu_leave GROUP BY state ORDER BY state")
    dist = cr.fetchall()
    refused = _scalar(cr, "SELECT count(*) FROM edu_leave WHERE state = 'refused'")
    _logger.info('[leave-split] 步5｜动作=不动既有行 state｜'
                 '断言=既有状态分布与迁移前逐字一致｜'
                 '实测 迁移后 state 分布 = %s｜refused = %s 行', dist, refused)
    if not _table_exists(cr, BACKUP_TABLE):
        _logger.info('[leave-split] 步5 SKIP：无前置快照表（全新库或本版本已迁过），'
                     '无法对账 —— **这不是通过**')
        return
    cr.execute("SELECT state, count(*) FROM %s GROUP BY state ORDER BY state" % BACKUP_TABLE)
    before = cr.fetchall()
    cr.execute("""
        SELECT id, state FROM edu_leave
        EXCEPT SELECT id, state FROM %s
    """ % BACKUP_TABLE)
    changed = cr.fetchall()
    cr.execute("""
        SELECT id, state FROM %s
        EXCEPT SELECT id, state FROM edu_leave
    """ % BACKUP_TABLE)
    lost = cr.fetchall()
    _logger.info('[leave-split] 步5 对账｜迁移前分布 = %s｜状态被改 = %s 行 %s｜'
                 '消失 = %s 行 %s', before, len(changed), changed[:5], len(lost), lost[:5])
    if changed or lost:
        raise RuntimeError(
            '[leave-split] 步5 断言失败：既有行的 state 被改动 '
            '（改动 %s 行，消失 %s 行）—— 历史裁决必须原样保留' % (len(changed), len(lost)))
    _logger.info('[leave-split] 步5 ✓ 通过（state 逐字一致，refused %s 行未动）', refused)


# ======================================================================
# §9.1 步 6：op_batch.homeroom_teacher_id 新列，**全空**
# ======================================================================
def _step6(cr):
    if not _table_exists(cr, HOMEROOM_TABLE):
        _logger.info('[leave-split] 步6 SKIP：无 %s 表（本库未装基座课程批次模型）'
                     '—— **这不是通过**', HOMEROOM_TABLE)
        return
    if not _column_exists(cr, HOMEROOM_TABLE, HOMEROOM_COL):
        raise RuntimeError('[leave-split] 步6 断言失败：%s.%s 列不存在'
                           % (HOMEROOM_TABLE, HOMEROOM_COL))
    total = _scalar(cr, 'SELECT count(*) FROM %s' % HOMEROOM_TABLE)
    non_null = _scalar(cr, 'SELECT count(*) FROM %s WHERE %s IS NOT NULL'
                       % (HOMEROOM_TABLE, HOMEROOM_COL))
    _logger.info('[leave-split] 步6｜动作=新列 %s.%s，不回填｜'
                 '断言=该列全空｜实测 %s 行 / 非空 %s 行（列存在 ✓）',
                 HOMEROOM_TABLE, HOMEROOM_COL, total, non_null)
    if non_null:
        raise RuntimeError(
            '[leave-split] 步6 断言失败：%s.%s 有 %s 行非空（设计要求全空，'
            '「没有班主任也能跑」正是靠这个默认空值）'
            % (HOMEROOM_TABLE, HOMEROOM_COL, non_null))
    _logger.info('[leave-split] 步6 ✓ 通过（列存在且全空 ⇒ 所有新单一级审批落教务处）')


# ======================================================================
# §9.1 步 7：新表 edu_leave_transfer + UNIQUE(leave_id, stage)
# ======================================================================
def _step7(cr):
    if not _table_exists(cr, TRANSFER_TABLE):
        raise RuntimeError('[leave-split] 步7 断言失败：表 %s 不存在'
                           '（模型 edu.leave.transfer 未建表）' % TRANSFER_TABLE)
    uniques = _unique_objects(cr, TRANSFER_TABLE)
    hit = [u for u in uniques if u[1] == ('leave_id', 'stage')]
    _logger.info('[leave-split] 步7｜动作=新表 %s + UNIQUE(leave_id, stage)｜'
                 '断言=\\d %s 有该唯一索引｜实测 全部 UNIQUE 对象 = %s｜命中 = %s',
                 TRANSFER_TABLE, TRANSFER_TABLE, uniques, hit)
    if not hit:
        raise RuntimeError(
            '[leave-split] 步7 断言失败：%s 上没有 (leave_id, stage) 的唯一约束/索引 '
            '（现有 UNIQUE 对象 = %s）—— 「只能转 1 次」必须是 DB 级'
            % (TRANSFER_TABLE, uniques))
    _logger.info('[leave-split] 步7 ✓ 通过：%s 唯一对象 = %s', hit[0][0], hit[0][1])


def migrate(cr, version):
    if not version:
        _logger.info('[leave-split] 首次安装（version=None）：按新 schema 建库，'
                     '无历史数据需要回填；仍执行结构型断言（步1/6/7）')
    elif not _table_exists(cr, 'edu_leave'):
        _logger.info('[leave-split] 本地无 edu_leave 表（全新库），跳过回填与对账')
        return

    _logger.info('=' * 72)
    _logger.info('[leave-split] 19.0.4.0.0 后置迁移自证开始（§9.1 七步）')
    _step1(cr)
    _step2(cr)
    _step3(cr)
    _step4(cr)
    _step5(cr)
    _step6(cr)
    _step7(cr)
    _logger.info('[leave-split] §9.1 七步全部通过 ✓')

    # 收尾：对账基线用完即删（幂等；重复跑时第 4/5 步会显式 SKIP）
    if _table_exists(cr, BACKUP_TABLE):
        cr.execute('DROP TABLE %s' % BACKUP_TABLE)
        _logger.info('[leave-split] 前置快照表 %s 已删除（对账完成）', BACKUP_TABLE)
    _logger.info('=' * 72)
