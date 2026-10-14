#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评估定义的只读留档（第 1 期"备份"动作；**不删任何东西**）。

设计依据：docs/plans/evaluation-rebuild-design.md §7.2 方案 A（不写迁移脚本，
把 A 套的**定义**导出留档，教务在新引擎里按需重建）与 §7.1 的删除顺序。

⚠ **2026-09-29 起只留 A 套（edu.eval.*）+ 新引擎对照**：B 套
（edu.admin.eval.* / edu_eval 模块）**已被删除**（用户授权，证据
docs/audit/edu-eval-removal.md），三张表不复存在 ⇒ B 套的采集项已从本脚本移除。

⚠ **不要在本仓直接重跑本脚本**：产物
docs/audit/eval-rebuild/a-suite-eval-definitions.json 里存着**删除行政评估之前**
的留档（b_suite 三表 = 0/0/0，是"确无真实使用"这一判定的取证材料之一）。
重跑会**覆盖**它。脚本已加互锁：产物里一旦存在 b_suite，必须显式
EDU_ALLOW_OVERWRITE_EVIDENCE=1 才允许覆盖。

只读保证：本脚本只发 SELECT（psql -tAc），不写库、不改环境。
用法：python3 scripts/backup_a_eval_json.py
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB = os.environ.get('EDU_DB_NAME', 'edu19')
CONTAINER = os.environ.get('EDU_DB_CONTAINER', 'edu19-clone-db-1')
REPO = Path(__file__).resolve().parent.parent
OUT = REPO / 'docs' / 'audit' / 'eval-rebuild' / 'a-suite-eval-definitions.json'
CST = timezone(timedelta(hours=8))

TABLES = {
    'edu_eval_template': ['id', 'name', 'type_code', 'total', 'pass_line',
                          'excellent_line', 'visible_to_student'],
    'edu_eval_template_line': ['id', 'name', 'max_score', 'sequence',
                               'template_id'],
    'edu_eval_task': ['id', 'template_id', 'student_id', 'evaluator_type',
                      'period', 'state', 'total_score'],
    'edu_eval_score': ['id', 'task_id', 'template_line_id', 'score'],
}


def psql_json(sql):
    out = subprocess.run(
        ['docker', 'exec', CONTAINER, 'psql', '-U', 'odoo', '-d', DB, '-tAc',
         sql], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or '')[:300])
    return out.stdout.strip()


def dump(table, cols):
    rows = psql_json("select coalesce(json_agg(row_to_json(t)), '[]'::json) "
                     "from (select %s from %s order by id) t"
                     % (', '.join(cols), table))
    return json.loads(rows or '[]')


def main():
    data = {
        'collected_at': datetime.now(CST).isoformat(timespec='seconds'),
        'note': ('评估定义只读留档。A 套 = edu_portal 内的 edu.eval.*。'
                 'B 套（edu_eval 模块的 edu.admin.eval.*）已于 2026-09-29 '
                 '删除，其删除前留档保留在本文件的历史版本里'
                 '（见 docs/audit/edu-eval-removal.md）。'),
        'a_suite': {},
        'counts': {},
    }
    for table, cols in TABLES.items():
        try:
            rows = dump(table, cols)
        except Exception as exc:
            rows = []
            data.setdefault('errors', []).append('%s: %s' % (table, exc))
        data['a_suite'][table] = rows
        data['counts'][table] = len(rows)
    # 顺手留档新引擎的模板清单（对照用：并存期三套各自有多少定义）
    try:
        data['assess'] = {
            'edu_assess_template': json.loads(psql_json(
                "select coalesce(json_agg(row_to_json(t)), '[]'::json) from "
                "(select id, name, kind, target_kind from edu_assess_template "
                "order by id) t")),
        }
    except Exception as exc:
        data.setdefault('errors', []).append('edu_assess_template: %s' % exc)
    # 取证互锁：产物里若已有 b_suite（删除前的 0/0/0 留档），默认拒绝覆盖。
    if OUT.exists() and 'b_suite' in OUT.read_text(encoding='utf-8') \
            and os.environ.get('EDU_ALLOW_OVERWRITE_EVIDENCE') != '1':
        print('REFUSED: %s 含有 b_suite 留档（删除行政评估前的取证材料），'
              '重跑会覆盖它。确需覆盖请显式 EDU_ALLOW_OVERWRITE_EVIDENCE=1。'
              % OUT.name)
        return 3
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                   encoding='utf-8')
    print('BACKUP file=%s templates=%s lines=%s tasks=%s scores=%s'
          % (OUT.name,
             data['counts'].get('edu_eval_template'),
             data['counts'].get('edu_eval_template_line'),
             data['counts'].get('edu_eval_task'),
             data['counts'].get('edu_eval_score')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
