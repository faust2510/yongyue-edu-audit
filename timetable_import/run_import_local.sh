#!/usr/bin/env bash
# 真实导入入口（本地 edu19 克隆库）：把 sessions.csv 经环境变量送进容器，
# 在 odoo shell 内执行 import_sessions.py；随后把容器内导出的比对 CSV 拉回仓库。
# 幂等：重复执行不会产生重复 session（先查后建）。
# 用法：bash timetable_import/run_import_local.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 准备 SESSIONS_CSV 环境变量（$(wc -l < timetable_import/sessions.csv) 行）"
SESSIONS_CSV_VALUE="$(cat timetable_import/sessions.csv)"

echo "==> odoo shell 执行 import_sessions.py"
docker compose exec -T \
    -e "SESSIONS_CSV=${SESSIONS_CSV_VALUE}" \
    web \
    odoo shell -c /etc/odoo/odoo.conf --db_host=db -r odoo -w odoo -d edu19 --no-http \
    < timetable_import/import_sessions.py \
    | tee /tmp/import_sessions_run.log

echo "==> 拉回比对 CSV"
docker compose cp web:/tmp/session_import_plan.csv timetable_import/session_import_plan_local.csv || true
docker compose cp web:/tmp/sessions_imported_local.csv timetable_import/sessions_imported_local.csv || true
echo "==> 完成；明细见 timetable_import/sessions_imported_local.csv"
