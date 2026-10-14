# -*- coding: utf-8 -*-
"""19.0.4.0.0 前置迁移：请假单拆分 + 分级审批 —— 第 1 步的「列就位 + 回填」与
第 4/5 步的**迁移前快照**。

设计：docs/plans/leave-split-approval-design.md
  · §9.1 迁移 7 步表（本文件负责「列就位」与「快照」，断言统一在 post-migrate 打）
  · §9.2 文件清单 / §10 的 S1 卡片

为什么必须在 pre 阶段做（而不是全放 post）
------------------------------------------
① `applicant_kind` 在模型里是 **required=True**（= DB 层 NOT NULL），而
   `_auto_init` 给「已存在的表」加 required 列时的顺序是
   「建列 → _init_column 填默认值 → post_init 里 SET NOT NULL」。
   本步先把列建好并**显式回填 'student'**，让任何数据形态下这一步都稳：
   即使 `_init_column` 因故没填（例如字段默认值被后人删掉），NOT NULL 也加得上。
   ⚠ 这一步**幂等**：列已存在就只回填 NULL 行，重复跑无副作用。
② `edu_leave.name`（单号）与既有行的 `state` 是 §9.1 步 4/5 的「**一个字节都不许动**」
   对象。要断言「逐字一致」，就必须先有迁移前的基线 —— 故在 pre 阶段快照进
   `edu_leave_1904_backup`（照 19.0.2.0.0 的 `edu_fee_bill_cat_backup` 先例），
   由 post-migrate 逐位对账后删除。

为什么断言放 post-migrate 而不是这里
------------------------------------
pre 阶段跑在 `registry.init_models()` **之前**：那时 `edu_leave_transfer` 表、
`op_batch.homeroom_teacher_id` 列**都还不存在**（它们由本次升级的 _auto_init 建），
在 pre 里断言「表/列存在」必然假红。故：**pre 做快照与回填，post 做 7 步断言**。
"""
import logging

_logger = logging.getLogger(__name__)

#: §9.1 步4/步5 的基线快照表（post-migrate 对账后删除）
BACKUP_TABLE = 'edu_leave_1904_backup'


def _table_exists(cr, table):
    cr.execute('SELECT to_regclass(%s)', (table,))
    return bool(cr.fetchone()[0])


def _column_exists(cr, table, column):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    # version 为 None = 首次安装（全新库）：还没有 edu_leave 数据，
    # _auto_init 会直接按新 schema 建表，无需任何回填/快照。
    if not version:
        _logger.info('[leave-split] 首次安装（version=None），无历史数据，跳过前置迁移')
        return

    if not _table_exists(cr, 'edu_leave'):
        _logger.info('[leave-split] 本地无 edu_leave 表（全新库），跳过前置迁移')
        return

    # ------------------------------------------------------------------
    # §9.1 步4/步5 的基线：把迁移前的 (id, name, state) 原样快照下来。
    #   name  = 单号（id=26 的 '001'、id=27 的 'SLR000001' 这类历史编号）
    #   state = 既有状态（不许被本次升级改动）
    # post-migrate 用「双向 EXCEPT」逐位对账 ⇒ 「逐字一致」是可复算的，不是口头承诺。
    # ------------------------------------------------------------------
    cr.execute('DROP TABLE IF EXISTS %s' % BACKUP_TABLE)
    cr.execute("""
        CREATE TABLE %s AS
        SELECT id, name, state FROM edu_leave
    """ % BACKUP_TABLE)
    cr.execute('SELECT count(*) FROM %s' % BACKUP_TABLE)
    snap_n = cr.fetchone()[0]
    cr.execute("SELECT count(*) FROM %s WHERE state = 'refused'" % BACKUP_TABLE)
    snap_refused = cr.fetchone()[0]
    _logger.info('[leave-split] 前置快照完成：%s 行（其中 state=refused %s 行）→ %s',
                 snap_n, snap_refused, BACKUP_TABLE)

    # ------------------------------------------------------------------
    # §9.1 步1：applicant_kind 新列 → 回填 'student'
    # ------------------------------------------------------------------
    if not _column_exists(cr, 'edu_leave', 'applicant_kind'):
        cr.execute('ALTER TABLE edu_leave ADD COLUMN applicant_kind varchar')
        _logger.info('[leave-split] 步1 建列 edu_leave.applicant_kind（varchar，先可空）')
    else:
        _logger.info('[leave-split] 步1 列 edu_leave.applicant_kind 已存在，只做幂等回填')

    # 历史单据一律是学生单（方案 A：既有表本来就是「学生请假」）。
    cr.execute("""
        UPDATE edu_leave SET applicant_kind = 'student'
        WHERE applicant_kind IS NULL
    """)
    filled = cr.rowcount
    cr.execute('SELECT count(*) FROM edu_leave WHERE applicant_kind IS NULL')
    left = cr.fetchone()[0]
    _logger.info('[leave-split] 步1 回填 student %s 行；剩余 NULL %s 行', filled, left)
    if left:
        # 前置阶段就把窟窿显式暴露（post 还会再断言一次；两处都不过就整体回滚）
        raise RuntimeError(
            '[leave-split] 步1 失败：edu_leave 仍有 %s 行 applicant_kind 为空，'
            '拒绝带着空值进入 NOT NULL 阶段' % left)

    _logger.info('[leave-split] 前置迁移结束（快照 %s 行 / 步1 回填 %s 行）',
                 snap_n, filled)
