# -*- coding: utf-8 -*-
"""19.0.3.0.0 后置迁移：把 M2M 关系表搬进 through 模型 edu_course_subject。

设计：docs/plans/major-track-elective-design.md §6.4

为什么必须搬（而不是留着老表用）
--------------------------------
op.course.subject_ids 换成非存储 computed + inverse + search 之后，
单一事实源就是 edu_course_subject（老表不再被读写）。搬过来时
**subject_type 显式留 NULL** = 「继承科目自身的必修/选修」⇒ 教务**零重配**，
行为与改造前逐条一致（§6.4.4「零数据迁移」的准确表述）。

四条纪律（缺一条就是不满足本仓红线 / 会留半迁移状态）
------------------------------------------------------
1. **只增不改**：老表 op_course_op_subject_rel **一行不删、不 DROP、不改**；
2. **幂等**：NOT EXISTS + 新表的 unique(course_id, subject_id) ⇒ 重跑不产生重复行；
3. **自证**：断言不过直接 raise ⇒ 整个 -u 事务回滚，绝不留「搬了一半」的库；
4. **全新库跳过**：version 为 None（首次安装）时老表根本不存在。

⚠ 自证口径的**再跑安全**（实施时发现的判据缺陷，比设计 §6.4.2 更严）
-------------------------------------------------------------------
设计写的自证①是「count(新) == count(老)」、③是「新表 subject_type 全为 NULL」。
这两条只在**首次**搬迁成立：上线之后教务会继续在专业上配科目（新表行数变大），
也会给搬来的行填必修/选修 —— 那时若因版本号变动再跑一次本脚本，
按字面口径会**误报失败并回滚整个升级**（把一次正常升级变成事故）。
故改为「**只对本次搬迁涉及的行**做逐位自证」：
  ① 本次应搬未搬的行数 == 实际 INSERT 行数，且新表增量 == 该行数；
     若新表本来为空（首次搬迁）再额外要求 count(新) == count(老)（= 设计原口径）；
  ② 老表 ⊆ 新表（老→新差集必须为空 = 一条不丢；新→老允许更大 = 教务后来新配的行）；
  ③ 本次搬来的那些行 subject_type 必须全为 NULL；④ 老表行数不变。
"""
import logging

_logger = logging.getLogger(__name__)

OLD_REL = 'op_course_op_subject_rel'
NEW_REL = 'edu_course_subject'


def migrate(cr, version):
    if not version:
        _logger.info('[major-track] 首次安装（version=None），无需搬迁')
        return

    cr.execute('SELECT to_regclass(%s), to_regclass(%s)', (OLD_REL, NEW_REL))
    old_rel, new_rel = cr.fetchone()
    if not old_rel:
        _logger.info('[major-track] 本地无旧关系表 %s，跳过搬迁', OLD_REL)
        return
    if not new_rel:
        raise RuntimeError(
            '[major-track] 新关系表 %s 不存在 —— 模型 edu.course.subject 未建表，'
            '拒绝留下列结构不一致的库' % NEW_REL)

    # 老表行数（搬迁前后必须逐位相等：只增不改的自证基线）
    cr.execute('SELECT count(*) FROM %s' % OLD_REL)
    old_count = cr.fetchone()[0]
    cr.execute('SELECT count(*) FROM %s' % NEW_REL)
    new_before = cr.fetchone()[0]

    # 本次「应搬未搬」的行（= 老表有、新表还没有的 (course, subject)）
    cr.execute("""
        SELECT r.op_course_id, r.op_subject_id
        FROM %(old)s r
        WHERE NOT EXISTS (
            SELECT 1 FROM %(new)s t
            WHERE t.course_id = r.op_course_id
              AND t.subject_id = r.op_subject_id
        )
    """ % {'old': OLD_REL, 'new': NEW_REL})
    missing = cr.fetchall()

    # ------------------------------------------------------------------
    # 搬迁：老表里「新表还没有」的行 → 新表一行；subject_type 显式 NULL、sequence=10
    # 幂等：靠新表的 unique(course_id, subject_id) + NOT EXISTS
    # ------------------------------------------------------------------
    cr.execute("""
        INSERT INTO %(new)s
            (course_id, subject_id, subject_type, sequence,
             create_uid, create_date, write_uid, write_date)
        SELECT r.op_course_id, r.op_subject_id, NULL, 10, 1, now(), 1, now()
        FROM %(old)s r
        WHERE NOT EXISTS (
            SELECT 1 FROM %(new)s t
            WHERE t.course_id = r.op_course_id
              AND t.subject_id = r.op_subject_id
        )
    """ % {'old': OLD_REL, 'new': NEW_REL})
    inserted = cr.rowcount
    _logger.info('[major-track] 搬迁关系行 %s 条（老表共 %s 条；新表原有 %s 条）',
                 inserted, old_count, new_before)

    # ------------------------------------------------------------------
    # 自证（任一不过 ⇒ raise ⇒ 整个 -u 回滚）
    # ------------------------------------------------------------------
    cr.execute('SELECT count(*) FROM %s' % NEW_REL)
    new_after = cr.fetchone()[0]

    # ① 应搬的都搬到了，且新表增量 == 本次插入数
    if inserted != len(missing) or new_after != new_before + inserted:
        raise RuntimeError(
            '[major-track] 自证① 失败：应搬 %d 行 / 实插 %d 行，'
            '新表 %d → %d 行' % (len(missing), inserted, new_before, new_after))
    # ①b 首次搬迁（新表原本为空）时，按设计口径要求与老表逐位相等
    if new_before == 0 and new_after != old_count:
        raise RuntimeError(
            '[major-track] 自证①b 失败（首次搬迁）：老表 %d 行 / 新表 %d 行，不相等'
            % (old_count, new_after))

    # ② 老表 ⊆ 新表（老→新差集必须为空 = 一条不丢）
    cr.execute("""
        SELECT op_course_id, op_subject_id FROM %(old)s
        EXCEPT
        SELECT course_id, subject_id FROM %(new)s
    """ % {'old': OLD_REL, 'new': NEW_REL})
    lost = cr.fetchall()
    if lost:
        raise RuntimeError(
            '[major-track] 自证② 失败：老表有 %d 行在新表里找不到（样例 %s）'
            % (len(lost), lost[:5]))
    cr.execute("""
        SELECT course_id, subject_id FROM %(new)s
        EXCEPT
        SELECT op_course_id, op_subject_id FROM %(old)s
    """ % {'old': OLD_REL, 'new': NEW_REL})
    extra = cr.fetchall()
    if extra:
        _logger.info('[major-track] 新表另有 %d 行不在老表内（改造后教务新配的科目，'
                     '属正常增量，不判失败）', len(extra))

    # ③ 本次搬来的行 subject_type 必须全为 NULL（= 继承科目全局值）
    if missing:
        pairs = ','.join('(%d,%d)' % (int(c), int(s)) for c, s in missing)
        cr.execute("""
            SELECT count(*) FROM %(new)s t
            WHERE (t.course_id, t.subject_id) IN (%(pairs)s)
              AND t.subject_type IS NOT NULL
        """ % {'new': NEW_REL, 'pairs': pairs})
        typed = cr.fetchone()[0]
        if typed:
            raise RuntimeError(
                '[major-track] 自证③ 失败：本次搬来的行里有 %d 行 subject_type 非空，'
                '搬迁必须全部留 NULL（空 = 继承科目全局值）' % typed)

    # ④ 老表未被动过（只增不改）
    cr.execute('SELECT count(*) FROM %s' % OLD_REL)
    old_after = cr.fetchone()[0]
    if old_after != old_count:
        raise RuntimeError(
            '[major-track] 自证④ 失败：老表 %s 行数发生变化（%d → %d）'
            % (OLD_REL, old_count, old_after))

    _logger.info('[major-track] 自证通过：老表 %d 行未动 / 本次搬 %d 行 / '
                 '新表 %d 行 / 搬来的行分类全空 ✓',
                 old_count, inserted, new_after)
