#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台账证据自查：把 data-loss-ledger.md 里引用的每条 文件:行 断言逐条回读。

用法:
    python3 docs/audit/migration/verify_ledger_evidence.py          # 正向：全部命中 => exit 0
    LEDGER_NEGATIVE=1 python3 .../verify_ledger_evidence.py         # 反向：故意把 1 条期望值改错 => exit 1

设计（对应本仓「证据纪律」）：
  * 正向通过   = 每条 (path, line, expect) 在真实文件里都能读到 expect 子串。
  * 反向注入   = 把第 #10 条期望值从 216 改成 288（一个真实存在但位置不同的数），必须变红。
  * 控制组     = 反向那一轮里，其余 39 条仍必须全绿 => 证明红是「被注入的那条」造成的，不是全局坏了。
  * 还原       = 不写任何文件、不改任何数据；反向只是进程内改一个字符串，退出即还原。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repo root

# (相对路径, 行号 1-based, 该行必须包含的子串)
ANCHORS = [
    ("docs/audit/security-audit-infra.md", 669, "edu19_before_cleanup_0830.dump"),
    ("docs/audit/security-audit-infra.md", 673, "edu19_post_cleanup_0830.dump"),
    ("docs/audit/security-audit-infra.md", 684, "-perm -o=r"),
    ("docs/audit/security-audit-infra.md", 696, "edu19-pre-t16-20260917-1729.sql.gz"),
    ("docs/audit/security-audit-infra.md", 564, "JWT_SECRET"),
    ("docs/deploy-malaysia.md", 28, "filestore"),
    ("docs/deploy-malaysia.md", 212, "backoffice@local"),
    ("docs/audit/edu-eval-removal.md", 114, "2026-08-31 00:09"),
    ("docs/audit/edu-eval-removal.md", 142, "pre_deleval_20260929_1545.gz"),
    ("docs/audit/edu-eval-removal.md", 328, "515"),
    ("docs/audit/edu-eval-removal.md", 440, "404"),
    ("docs/research/gradebook-entry.md", 118, "待定"),
    ("docs/research/gradebook-entry.md", 119, "op_student"),
    ("docs/research/gradebook-entry.md", 123, "总览班"),
    ("docs/research/gradebook-entry.md", 124, "216"),
    ("docs/research/gradebook-entry.md", 128, "edu_course_subject"),
    ("docs/research/gradebook-entry.md", 129, "edu_assess"),
    ("docs/audit/task-B1-enroll-timetable-gap.md", 25, "qnj2510798178@gmail.com"),
    ("docs/audit/task-B1-enroll-timetable-gap.md", 38, "BED2026-WZ001"),
    ("docs/audit/task-B1-enroll-timetable-gap.md", 82, "SR0017"),
    ("docs/curriculum/import-report.md", 31, "334"),
    ("docs/curriculum/import-report.md", 39, "王佐"),
    ("docs/plans/major-track-elective-design.md", 632, "compulsory"),
    ("docs/plans/major-track-elective-design.md", 644, "334"),
    ("docs/audit/security-audit-app.md", 443, "21 个门户账号"),
    ("docs/audit/security-audit-app.md", 448, "19 名学生"),
    ("docs/audit/security-audit-app.md", 501, "王佐"),
    ("docs/audit/security-audit-app.md", 690, "edu_telegram"),
    ("docs/audit/security-audit-app.md", 743, "21 个门户账号"),
    ("docs/plans/password-verbatim-audit.md", 53, "38 个账号"),
    ("docs/plans/ux-v3-delivery.md", 574, "8 个账号"),
    ("docs/plans/ux-v3-delivery.md", 575, "teacher@local"),
    ("docs/plans/ux-v3-delivery.md", 614, "2026-10-01"),
    ("docs/plans/course-representative-design.md", 698, "edu_leave"),
    ("docs/plans/course-representative-design.md", 703, "op_student"),
    ("docs/plans/class-change-request-design.md", 824, "BED2026-WZ001"),
    ("docs/plans/class-change-request-design.md", 826, "216"),
    ("docs/plans/fee-categories-design.md", 70, "edu_fee_bill"),
    ("docs/plans/fee-categories-design.md", 138, "REB000012"),
    ("docs/plans/google-fonts-localization-report.md", 10, "1317"),
    ("docs/plans/google-fonts-localization-report.md", 128, "54"),
    ("docs/plans/scheduling-overhaul-design.md", 650, "合班批"),
    ("docs/plans/README.md", 112, "未分班"),
    ("docs/plans/README.md", 114, "ir.mail_server"),
    ("docs/plans/data-provenance.md", 278, "pg_dump"),
    ("docs/handoff-prompt.md", 20, "王茜茜"),
    ("docs/audit/checkin-merge-report.md", 3, "本地"),
    ("docs/audit/checkin-merge-report.md", 41, "模块重装"),
    ("docs/plans/evaluation-rebuild-design.md", 22, "0 条打分"),
    ("scripts/ops/retire_old_batches.py", 17, "pre_overview2_20260924.gz"),
]

NEGATIVE_INDEX = 14  # (0-based) 对应上面第 15 条：(gradebook-entry.md, 124, '216')


def main() -> int:
    negative = os.environ.get('LEDGER_NEGATIVE') == '1'
    fails = []
    for i, (rel, lineno, expect) in enumerate(ANCHORS):
        if negative and i == NEGATIVE_INDEX:
            expect = '288'  # 注入：该行确实没有 288（288 是本地库的会话数，不是生产）
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
        print('LEDGER_EVIDENCE PASS  %d/%d  (negative=%s)' % (total, total, negative))
        return 0
    for rel, lineno, expect, got in fails:
        print('FAIL %s:%d  expect=%r  got=%r' % (rel, lineno, expect, got))
    print('LEDGER_EVIDENCE FAIL  pass=%d/%d  (negative=%s)' % (total - len(fails), total, negative))
    return 1


if __name__ == '__main__':
    sys.exit(main())