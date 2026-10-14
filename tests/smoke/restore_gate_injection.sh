#!/usr/bin/env bash
# tests/smoke/restore_gate_injection.sh — 给「还原彩排门禁」做反向注入自检。
#
# 本仓铁律：不能变红的门禁是假门禁。所以这个脚本不测业务，只测门禁自己：
#   A 好档案        -> 期望 退出码 0
#   B 截断档案      -> 期望 非 0
#   C 垃圾文件      -> 期望 非 0
#   D 空库的转储    -> 期望 非 0
#   E 空库（--check-db）-> 期望 非 0
#   F 控制组：再跑一次 A -> 期望 0（证明门禁不是「永远红」）
# 任何一条期望不成立（尤其是「坏输入还绿」）=> 本脚本非 0 退出。
#
# 用法：bash tests/smoke/restore_gate_injection.sh [--pgbin DIR] [--port P] [--dump FILE]
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
GATE="$REPO/scripts/restore_rehearsal.sh"
PGBIN=""
PORT="55432"
GOOD="$HOME/Documents/edu19-backups/edu19_post_cleanup_0830.dump"

while [ $# -gt 0 ]; do
  case "$1" in
    --pgbin) PGBIN="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --dump) GOOD="$2"; shift 2;;
    -h|--help) echo "用法: $0 [--pgbin DIR] [--port P] [--dump FILE]"; exit 0;;
    *) echo "未知选项 $1" >&2; exit 2;;
  esac
done

if [ -z "$PGBIN" ]; then
  for d in /opt/homebrew/opt/postgresql@16/bin /opt/homebrew/bin /usr/local/opt/postgresql@16/bin /usr/lib/postgresql/16/bin; do
    [ -x "$d/pg_restore" ] && PGBIN="$d" && break
  done
  [ -n "$PGBIN" ] || PGBIN="$(dirname "$(command -v pg_restore)")"
fi
PSQL="$PGBIN/psql"; CREATEDB="$PGBIN/createdb"; DROPDB="$PGBIN/dropdb"; PGDUMP="$PGBIN/pg_dump"
[ -f "$GOOD" ] || { echo "找不到好档案: ${GOOD}（用 --dump 指定）" >&2; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/gate-injection.XXXXXX")"
BAD="$WORK/truncated.dump"
JUNK="$WORK/junk.dump"
EMPTYDUMP="$WORK/empty_db.dump"
EMPTYDB="edu19_gate_injection_empty"
scratch_of() { printf 'edu19_rehearsal_%s' "$(basename "$1" | tr -c 'A-Za-z0-9' '_' | cut -c1-40)"; }
BADDB="$(scratch_of "$BAD")"
SCRATCH_MAIN="$(scratch_of "$GOOD")"

cleanup() {
  "$DROPDB" -h 127.0.0.1 -p "$PORT" -U odoo --if-exists "$BADDB" >/dev/null 2>&1
  "$DROPDB" -h 127.0.0.1 -p "$PORT" -U odoo --if-exists "$EMPTYDB" >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT

BAD_EXPECT=0
RESULTS=()
run_case() {
  local name="$1" want="$2"; shift 2
  local log="$WORK/$name.log"
  echo ''
  echo '--- 用例 '$name' --------------------------------------------------'
  echo '命令: bash scripts/restore_rehearsal.sh '"$*"
  ( cd "$REPO" && bash "$GATE" "$@" ) > "$log" 2>&1
  local rc=$?
  echo "退出码: $rc"
  grep -E '^  \[FAIL\]|^RESULT:|表不存在|低于下限|无法解析|不可能是完整转储' "$log" | head -8 | sed 's/^/    /'
  local ok=0
  if [ "$want" = zero ]; then [ "$rc" -eq 0 ] && ok=1; else [ "$rc" -ne 0 ] && ok=1; fi
  if [ "$ok" = 1 ]; then
    echo "  期望[$want] 成立 -> 用例通过"
    RESULTS+=("$name: ok (rc=$rc, 期望 $want)")
  else
    echo "  期望[$want] 不成立 -> 门禁失效，本自检非 0 退出"
    RESULTS+=("$name: GATE-BROKEN (rc=$rc, 期望 $want)")
    BAD_EXPECT=1
  fi
}

echo '还原彩排门禁 · 反向注入自检'
echo "门禁: $GATE"
echo "好档案: $GOOD"

SZ=$(wc -c < "$GOOD" | tr -d ' ')
head -c $((SZ * 40 / 100)) "$GOOD" > "$BAD"
printf 'this is not a pg_dump archive, it is junk %s\n' "$(date)" > "$JUNK"
for i in $(seq 1 20000); do printf 'padding-%s\n' "$i"; done >> "$JUNK"

"$DROPDB" -h 127.0.0.1 -p "$PORT" -U odoo --if-exists "$EMPTYDB" >/dev/null 2>&1
"$CREATEDB" -h 127.0.0.1 -p "$PORT" -U odoo -O odoo "$EMPTYDB" >/dev/null 2>&1 || { echo "建空库失败（postgres 没起？）" >&2; exit 2; }
"$PGDUMP" -h 127.0.0.1 -p "$PORT" -U odoo -Fc -d "$EMPTYDB" -f "$EMPTYDUMP" || { echo "空库转储失败" >&2; exit 2; }

run_case A-good       zero    --pgbin "$PGBIN" --port "$PORT" "$GOOD"
run_case B-truncated  nonzero --pgbin "$PGBIN" --port "$PORT" "$BAD"
run_case C-junk       nonzero --pgbin "$PGBIN" --port "$PORT" "$JUNK"
run_case D-empty-dump nonzero --pgbin "$PGBIN" --port "$PORT" "$EMPTYDUMP"
run_case E-empty-db   nonzero --pgbin "$PGBIN" --port "$PORT" --check-db "$EMPTYDB"
run_case F-control    zero    --pgbin "$PGBIN" --port "$PORT" "$GOOD"

echo ''
echo '================ 注入自检结论 ================'
for r in "${RESULTS[@]}"; do echo "  $r"; done
if [ "$BAD_EXPECT" = 1 ]; then
  echo 'RESULT: FAIL —— 门禁在某个坏输入上没有变红（假门禁），必须修门禁'
  exit 1
fi
echo 'RESULT: PASS —— 6/6 期望成立：好档案绿、坏档案/空库红、控制组复绿'
exit 0
