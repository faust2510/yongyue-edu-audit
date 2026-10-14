# -*- coding: utf-8 -*-
"""19.0.2.0.0 后置迁移：旧分类 → edu.fee.category 回填。

顺序保证：pre-migrate 已把旧值存进 edu_fee_bill_cat_backup；
本脚本运行时，data/fee_categories.xml 已建好分类档案（按 code 反查 id）。

映射（docs/plans/fee-categories-design.md §4）：
    tuition 统筹费 → tongchou 统筹（改名）
    textbook 教材  → jiaocai 教材
    activity 活动  → huodong 活动
    transport 交通 → jiaotong 交通
    printing 打印  → dayin 打印
    fine 罚款      → qita 其他（校长 2026-09-16：罚款不存在，不设该分类）
    other 其他     → qita 其他
映射表外的任何旧值 → 归入「其他」并**打印告警**（不静默丢）。
结束时断言：无分类账单数必须为 0。
"""
import logging

_logger = logging.getLogger(__name__)

MAPPING = {
    'tuition': 'tongchou',
    'textbook': 'jiaocai',
    'activity': 'huodong',
    'transport': 'jiaotong',
    'printing': 'dayin',
    'fine': 'qita',
    'other': 'qita',
}


def migrate(cr, version):
    if not version:
        return
    cr.execute("SELECT to_regclass('edu_fee_bill_cat_backup')")
    if not cr.fetchone()[0]:
        _logger.info('[fee-categories] 无快照表（全新库或已在上一版迁过），跳过回填')
        return

    total_mapped = 0
    for old_code, new_code in MAPPING.items():
        cr.execute("""
            UPDATE edu_fee_bill b SET category_id = c.id
            FROM edu_fee_bill_cat_backup k, edu_fee_category c
            WHERE k.id = b.id AND k.category = %s AND c.code = %s
        """, (old_code, new_code))
        if cr.rowcount:
            _logger.info('[fee-categories] %s → %s：%s 行',
                         old_code, new_code, cr.rowcount)
            total_mapped += cr.rowcount

    # 映射表外的旧值 → 其他（并点名，绝不静默）
    cr.execute("""
        SELECT DISTINCT k.category FROM edu_fee_bill_cat_backup k
        JOIN edu_fee_bill b ON b.id = k.id
        WHERE b.category_id IS NULL AND k.category IS NOT NULL
    """)
    unknown = [r[0] for r in cr.fetchall()]
    if unknown:
        _logger.warning('[fee-categories] 映射表外旧值 %s → 归入「其他」', unknown)
    cr.execute("""
        UPDATE edu_fee_bill b SET category_id = c.id
        FROM edu_fee_category c
        WHERE b.category_id IS NULL AND c.code = 'qita'
    """)

    cr.execute("SELECT count(*) FROM edu_fee_bill WHERE category_id IS NULL")
    left = cr.fetchone()[0]
    _logger.info('[fee-categories] 回填完成：映射 %s 行，仍无分类 %s 行',
                 total_mapped, left)
    if left:
        # 有账单没分类 ⇒ 让它显式失败，别把窟窿带进生产
        raise Exception('[fee-categories] 仍有 %s 行账单没有分类，迁移中止'
                        % left)

    cr.execute('DROP TABLE edu_fee_bill_cat_backup')
    _logger.info('[fee-categories] 快照表已删除')
