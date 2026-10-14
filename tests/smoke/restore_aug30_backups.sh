#!/usr/bin/env bash
# tests/smoke/restore_aug30_backups.sh — 对开发机现存的两份 2026-08-30 dump 跑还原彩排。
# 这是 restore_rehearsal.sh 的第一份真实用例：两份都必须 PASS 并打印关键表行数。
# 用法：bash tests/smoke/restore_aug30_backups.sh [--pgbin DIR] [--port P] [--dir 备份目录]
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
GATE="$REPO/scripts/restore_rehearsal.sh"
PGBIN=""
PORT="55432"
DIR="$HOME/Documents/edu19-backups"
while [ $# -gt 0 ]; do
  case "$1" in
    --pgbin) PGBIN="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --dir) DIR="$2"; shift 2;;
    -h|--help) echo "用法: $0 [--pgbin DIR] [--port P] [--dir 备份目录]"; exit 0;;
    *) echo "未知选项 $1" >&2; exit 2;;
  esac
done
RC=0
for f in "$DIR/edu19_post_cleanup_0830.dump" "$DIR/edu19_local_dev_0830.dump"; do
  echo ''
  echo "########## $f"
  if [ ! -f "$f" ]; then echo "缺档案: $f" >&2; RC=1; continue; fi
  if bash "$GATE" --pgbin "$PGBIN" --port "$PORT" "$f"; then
    echo "结论: PASS $f"
  else
    echo "结论: FAIL $f"
    RC=1
  fi
done
echo ''
if [ "$RC" = 0 ]; then echo 'RESULT: PASS —— 两份 Aug30 备份都通过彩排'; else echo 'RESULT: FAIL —— 有备份没通过彩排'; fi
exit $RC
