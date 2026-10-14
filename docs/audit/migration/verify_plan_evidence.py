#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建预案证据自查：把 docs/audit/migration/rebuild-plan.md 引用的每个 文件:行 逐条回读。

用法:
    python3 docs/audit/migration/verify_plan_evidence.py        # 正向：50/50 => exit 0
    LEDGER_NEGATIVE=1 python3 .../verify_plan_evidence.py       # 反向：注入 1 条错期望 => exit 1

与前一份 verify_ledger_evidence.py 同构（正向 / 反向注入 / 控制组三件套）。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

ANCHORS = [
    ("scripts/import_curriculum.py", 2, "幂等"),
    ("scripts/import_curriculum.py", 11, "DRY_RUN 1 = 只报不写"),
    ("scripts/import_curriculum.py", 111, "subject_ids.ids"),
    ("scripts/import_curriculum.py", 136, "env.cr.commit()"),
    ("docs/curriculum/yongyue-curriculum.csv", 1, "课程,学分"),
    ("timetable_import/import_sessions.py", 18, "幂等重跑"),
    ("timetable_import/import_sessions.py", 39, "幂等：以"),
    ("timetable_import/import_sessions.py", 584, "edu.audit.log"),
    ("timetable_import/import_sessions.py", 661, "--dry-run"),
    ("timetable_import/PRODUCTION_CHECKLIST.md", 47, "created=0/skipped=216"),
    ("timetable_import/PRODUCTION_CHECKLIST.md", 71, "216 op.session"),
    ("scripts/ops/retire_old_batches.py", 2, "一次性数据迁移"),
    ("scripts/ops/retire_old_batches.py", 17, "pre_overview2_20260924.gz"),
    ("custom_addons/edu_portal/migrations/19.0.3.0.0/post-migrate.py", 2, "edu_course_subject"),
    ("custom_addons/edu_portal/migrations/19.0.2.0.0/post-migrate.py", 2, "edu.fee.category"),
    ("custom_addons/edu_portal/migrations/19.0.4.0.0/pre-migrate.py", 2, "请假单拆分"),
    ("custom_addons/edu_portal/models/major_track.py", 95, "subject_ids = fields.Many2many"),
    ("custom_addons/edu_portal/models/major_track.py", 98, "inverse"),
    ("openeducat_erp/openeducat_core/models/course.py", 37, "subject_ids"),
    ("scripts/merge_checkins.py", 20, "模块重装"),
    ("scripts/merge_checkins.py", 27, "--dry-run"),
    ("custom_addons/edu_life/data/demo_life.xml", 35, "_load_demo_records"),
    ("docs/audit/finding-F5-edulife-demo-injection.md", 1, "注入"),
    ("scripts/switch_currency_cny.py", 4, "幂等"),
    ("scripts/setup_brand_yongyue.py", 2, "品牌数据初始化"),
    ("scripts/seed_d1_nav.py", 132, "env.cr.commit()"),
    ("docs/plans/ux-v3-delivery.md", 585, "seed_d1_nav.py"),
    ("scripts/create_teacher_account.py", 5, "幂等"),
    ("scripts/create_teacher_account.py", 16, "res.partner.user_id"),
    ("custom_addons/edu_portal/models/invite_code.py", 685, "action_generate"),
    ("custom_addons/edu_portal/models/invite_code.py", 13, "批量生成"),
    ("custom_addons/edu_portal/data/fee_categories.xml", 2, "odoo"),
    ("docs/plans/password-verbatim-audit.md", 53, "38 个账号"),
    ("docs/audit/security-audit-app.md", 501, "王佐"),
    ("docs/plans/ux-v3-delivery.md", 574, "8 个账号"),
    ("scripts/deploy_myedu.sh", 183, "edu_nav"),
    ("docs/plans/data-provenance.md", 18, "演示数据必须带【演示】"),
    ("docs/plans/README.md", 68, "两段式导入"),
    ("docs/code-map.md", 59, "gr_no"),
    ("docs/audit/task-B1-enroll-timetable-gap.md", 82, "SR0017"),
    ("docs/plans/fee-categories-design.md", 138, "REB000012"),
    ("docs/plans/major-track-elective-design.md", 641, "334"),
    ("docs/research/gradebook-entry.md", 128, "edu_course_subject"),
    ("docs/audit/checkin-merge-report.md", 21, "edu_daily_checkin"),
    ("docs/audit/migration/data-loss-ledger.md", 24, "最痛"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 22, "edu_eval||uninstalled"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 25, "edu_portal|19.0.4.0.0|installed"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 50, "op_subject|14"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 52, "edu_course_subject(new)|14"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 72, "12|backoffice@local|f|f"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 74, "19|qnj2510798178@gmail.com|t|t"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 88, "USD|t"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 89, "CNY|f"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 100, "610|409"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 110, "971|709"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 138, "3|op.subject.registration|SR|1"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 148, "4|到堂打卡|daily|t"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 953, "op_subject|14"),
    ("docs/audit/migration/evidence/2026-10-01-newserver-readings.txt", 954, "edu_course_subject|14"),
    ("docs/audit/migration/evidence/2026-10-01-import-dryruns.txt", 8, "= 216"),
    ("docs/audit/migration/evidence/2026-10-01-import-dryruns.txt", 89, "新建 = 122"),
    ("docs/audit/migration/evidence/2026-10-01-filestore-recovery.txt", 40, "all= 710"),
    ("docs/audit/migration/evidence/2026-10-01-filestore-recovery.txt", 55, "rows_present=157"),
    ("docs/audit/migration/evidence/2026-10-01-filestore-recovery.txt", 56, "unique_present=91"),
    ("docs/audit/migration/evidence/2026-10-01-filestore-recovery.txt", 58, "set_diff_vs_leader=0"),
    ("docs/audit/migration/evidence/2026-10-01-filestore-recovery.txt", 73, "filestore_files=265"),
    ("docs/audit/migration/evidence/2026-10-01-filestore-recovery.txt", 77, "rows_whose_file_present=186"),
    ("docs/audit/migration/evidence/2026-10-01-filestore-recovery.txt", 79, "payment.method	0	462"),
    ("docs/audit/migration/evidence/2026-10-01-filestore-recovery.txt", 119, "乌鸦.jpeg"),
    ("docs/audit/migration/evidence/2026-10-01-b5-execution.txt", 110, "PRECHECK_NEGATIVE=1 -> NEG_EXIT=1"),
    ("docs/audit/migration/evidence/2026-10-01-b5-execution.txt", 116, "新增挂接 = 306"),
    ("docs/audit/migration/evidence/2026-10-01-b5-execution.txt", 121, "op_subject 147 | edu_course_subject 320"),
    ("docs/audit/migration/evidence/2026-10-01-b5-execution.txt", 144, "新建 0 | 已存在 124"),
    ("docs/audit/migration/evidence/2026-10-01-b5-execution.txt", 159, "既有科目 = 147 行 / 146 个唯一名"),
    ("docs/audit/migration/evidence/2026-10-01-b5-execution.txt", 163, "PRP-C02"),
]

NEGATIVE_INDEX = 45  # (0-based) 第 46 条：evidence/…newserver-readings.txt:22 (edu_eval||uninstalled)


def main() -> int:
    negative = os.environ.get('LEDGER_NEGATIVE') == '1'
    fails = []
    for i, (rel, lineno, expect) in enumerate(ANCHORS):
        if negative and i == NEGATIVE_INDEX:
            expect = 'installed_v2'  # 注入：该行没有这个串
        p = ROOT / rel
        try:
            lines = p.read_text(encoding='utf-8').splitlines()
        except OSError as e:
            fails.append((rel, lineno, expect, 'READ_ERR %s' % e))
            continue
        if lineno > len(lines):
            fails.append((rel, lineno, expect, 'LINE_OUT_OF_RANGE(%d)' % len(lines)))
            continue
        got = lines[lineno - 1]
        if expect not in got:
            fails.append((rel, lineno, expect, got.strip()[:120]))
    total = len(ANCHORS)
    if not fails:
        print('PLAN_EVIDENCE PASS  %d/%d  (negative=%s)' % (total, total, negative))
        return 0
    for rel, lineno, expect, got in fails:
        print('FAIL %s:%d  expect=%r  got=%r' % (rel, lineno, expect, got))
    print('PLAN_EVIDENCE FAIL  pass=%d/%d  (negative=%s)' % (total - len(fails), total, negative))
    return 1


if __name__ == '__main__':
    sys.exit(main())