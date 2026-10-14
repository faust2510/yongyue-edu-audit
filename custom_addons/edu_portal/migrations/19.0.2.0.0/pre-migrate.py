# -*- coding: utf-8 -*-
"""19.0.2.0.0 前置迁移：把旧的分类列快照下来。

为什么必须在 pre 阶段做：
新模型把 edu.fee.bill.category（Selection）换成 category_id（m2o），
Odoo 的 _auto_init 会在本次升级里**删掉旧的 category 列**；一旦删了，
就再也没有源数据可以做映射了。

本脚本只做一件事：把旧值原样复制到 edu_fee_bill_cat_backup，
真正的映射放到 post-migrate（那时分类档案已由 data/fee_categories.xml 建好）。
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'edu_fee_bill' AND column_name = 'category'
    """)
    if not cr.fetchone():
        _logger.info('[fee-categories] 旧 category 列不存在（全新库），跳过快照')
        return
    cr.execute('DROP TABLE IF EXISTS edu_fee_bill_cat_backup')
    cr.execute("""
        CREATE TABLE edu_fee_bill_cat_backup AS
        SELECT id, category FROM edu_fee_bill
    """)
    cr.execute('SELECT count(*) FROM edu_fee_bill_cat_backup')
    _logger.info('[fee-categories] 已快照 %s 行旧分类值', cr.fetchone()[0])
