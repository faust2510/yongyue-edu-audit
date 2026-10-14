#!/usr/bin/env bash
# 冒烟一键回归：匿名公开面(项1-7) + 学生面(项8-15) + 报告汇总
# 用法：bash tests/smoke/run_smoke.sh
set -u
cd "$(dirname "$0")/../.."

export NO_PROXY=localhost,127.0.0.1
export no_proxy=localhost,127.0.0.1

PY="${PYTHON:-python3}"

echo "== [1/3] 匿名公开面 =="
"$PY" tests/smoke/smoke_anon.py || true

echo
echo "== [2/3] 学生面 stu@local =="
"$PY" tests/smoke/smoke_student.py || true

echo
echo "== [3/3] 汇总报告 =="
"$PY" tests/smoke/make_report.py
