#!/usr/bin/env bash
# scripts/restore_rehearsal.sh — 还原彩排门禁
#
# 铁律：备份没被真的还原过一次，就不算备份。本脚本把一份 pg_dump 档案真的还原进
# 一个 scratch 库，然后逐条断言；任何一条不成立 => 打印人话 + 非 0 退出。
#
# 它必须能变红（本仓铁律：不能变红的门禁是假门禁），因此：
#   · 没有 --allow-fail / --skip / 白名单开关；
#   · 不吞 pg_restore 的 stderr（归档里的任何一条 error 都算 FAIL）；
#   · 关键表缺失或行数低于下限都算 FAIL。
#
# 用法：
#   bash scripts/restore_rehearsal.sh [选项] <dump 文件> [...]
#   bash scripts/restore_rehearsal.sh [选项] --check-db <已存在的库名>
#
# 退出码：0 = 全部 PASS；1 = 有 FAIL；2 = 用法/环境错误
set -uo pipefail

PROG="$(basename "$0")"
HOST="${PGHOST:-127.0.0.1}"
PORT="${PGPORT:-55432}"
DBUSER="${PGUSER:-odoo}"
PGBIN_OPT=""
KEEP=0
QUIET=0
PROFILE=project
CHECK_DB=""
EXTRA_MIN_LIST=()
DUMPFILES=()

# 关键表口径（project = 本项目；core = 只查 Odoo 核心表）。
# 下限不是拍脑袋：见 docs/ops/backup-policy.md 附录 A（2026-08-30 两份真实 dump 的实测读数）。
REQ_PROJECT="res_company:1 res_users:1 res_partner:1 res_groups:1 ir_module_module:1 ir_model_fields:500 ir_model_data:1000 ir_ui_menu:100 ir_config_parameter:1 mail_message:1 ir_attachment:1 op_course:1 op_batch:1 op_student:1 edu_application:1 edu_notice:1 edu_alumni_job:1"
REQ_CORE="res_company:1 res_users:1 res_partner:1 ir_module_module:1 ir_model_data:100"

usage() {
  cat <<'EOU'
usage: restore_rehearsal.sh [选项] <dump 文件> [...]
  --host H         postgres 主机（默认 127.0.0.1，可用 PGHOST）
  --port P         端口（默认 55432，可用 PGPORT）
  --user U         用户（默认 odoo，可用 PGUSER）
  --pgbin DIR      postgres 客户端 bin 目录（默认自动探测 pg_restore/psql）
  --profile NAME   project（默认，本项目口径）| core（只查 Odoo 核心表）
  --min TABLE=N    追加/覆盖单表下限，可重复
  --check-db NAME  不还原，直接检查一个已存在的库（用于「空库」反例）
  --keep           成功也保留 scratch 库
  --quiet          只打结论行
  -h, --help
退出码：0=PASS 1=FAIL 2=用法或环境错误
EOU
}

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:?--host 需要值}"; shift 2;;
    --port) PORT="${2:?--port 需要值}"; shift 2;;
    --user) DBUSER="${2:?--user 需要值}"; shift 2;;
    --pgbin) PGBIN_OPT="${2:?--pgbin 需要值}"; shift 2;;
    --profile) PROFILE="${2:?--profile 需要值}"; shift 2;;
    --min) EXTRA_MIN_LIST+=("${2:?--min 需要值}"); shift 2;;
    --check-db) CHECK_DB="${2:?--check-db 需要值}"; shift 2;;
    --keep) KEEP=1; shift;;
    --quiet) QUIET=1; shift;;
    -h|--help) usage; exit 0;;
    --) shift; while [ $# -gt 0 ]; do DUMPFILES+=("$1"); shift; done;;
    -*) echo "$PROG: 未知选项 $1" >&2; usage >&2; exit 2;;
    *) DUMPFILES+=("$1"); shift;;
  esac
done

case "$PROFILE" in
  project) REQ_SPEC="$REQ_PROJECT";;
  core) REQ_SPEC="$REQ_CORE";;
  *) echo "$PROG: --profile 只认 project|core，收到 $PROFILE" >&2; exit 2;;
esac

# --min 覆盖：把 spec 里的下限换掉，或追加新表
for m in ${EXTRA_MIN_LIST[@]+${EXTRA_MIN_LIST[@]}}; do
  key="${m%%=*}"; val="${m##*=}"
  case "$key" in ''|*[!A-Za-z0-9_]*) echo "$PROG: --min 的表名不合法：$key" >&2; exit 2;; esac
  case "$val" in ''|*[!0-9]*) echo "$PROG: --min 格式应为 TABLE=N，收到 $m" >&2; exit 2;; esac
  if printf '%s' " $REQ_SPEC " | grep -q " $key:"; then
    new=""
    for spec in $REQ_SPEC; do
      if [ "${spec%%:*}" = "$key" ]; then new="$new $key:$val"; else new="$new $spec"; fi
    done
    REQ_SPEC="${new# }"
  else
    REQ_SPEC="$REQ_SPEC $key:$val"
  fi
done

resolve_pgbin() {
  if [ -n "$PGBIN_OPT" ]; then printf '%s' "$PGBIN_OPT"; return; fi
  for d in /opt/homebrew/opt/postgresql@16/bin /opt/homebrew/bin /usr/local/opt/postgresql@16/bin /usr/lib/postgresql/16/bin /usr/pgsql-16/bin; do
    if [ -x "$d/pg_restore" ] && [ -x "$d/psql" ]; then printf '%s' "$d"; return; fi
  done
  if command -v pg_restore >/dev/null 2>&1; then dirname "$(command -v pg_restore)"; return; fi
  printf '%s' ''
}
PGBIN="$(resolve_pgbin)"
if [ -z "$PGBIN" ]; then
  echo "$PROG: 找不到 pg_restore/psql —— 装 postgresql 客户端，或用 --pgbin 指路" >&2
  exit 2
fi

FAILS=()
WARNS=()
fail() { FAILS+=("$1"); printf '  [FAIL] %s\n' "$1"; }
warn() { WARNS+=("$1"); printf '  [WARN] %s\n' "$1"; }
say()  { [ "$QUIET" = 1 ] || printf '%s\n' "$1"; }

sha_of() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else sha256sum "$1" | awk '{print $1}'; fi
}

psql_at() { "$PGBIN/psql" -h "$HOST" -p "$PORT" -U "$DBUSER" -d "$1" -v ON_ERROR_STOP=1 -Atc "$2" 2>/dev/null; }

check_db() {
  local db="$1" spec t floor n status bad=0
  say "  表                         行数       下限  判定"
  for spec in $REQ_SPEC; do
    t="${spec%%:*}"
    floor="${spec##*:}"
    n="$("$PGBIN/psql" -h "$HOST" -p "$PORT" -U "$DBUSER" -d "$db" -Atc "select count(*) from public.$t" 2>/dev/null)"
    if [ -z "$n" ]; then
      status="表不存在"
      fail "库 $db 里没有关键表 $t —— 这是空库，或根本不是本项目的库"
      bad=1
      n="MISSING"
    elif [ "$n" -lt "$floor" ]; then
      status="低于下限"
      fail "库 $db 的关键表 $t 只有 $n 行（下限 ${floor}）—— 数据没进来或不完整"
      bad=1
    else
      status="ok"
    fi
    printf '  %-26s %10s %8s  %s\n' "$t" "$n" "$floor" "$status"
  done
  local installed url
  installed="$(psql_at "$db" "select count(*) from ir_module_module where state='installed'")"
  if [ -z "$installed" ]; then
    fail "库 $db 读不到 ir_module_module.state=installed —— 不是可用的 Odoo 库"
    bad=1
  elif [ "$installed" -lt 1 ]; then
    fail "库 $db 已装模块数为 0 —— 库是空的"
    bad=1
  else
    printf '  %-26s %10s %8s  %s\n' "ir_module_module(installed)" "$installed" "1" "ok"
  fi
  url="$(psql_at "$db" "select value from ir_config_parameter where key='web.base.url'")"
  if [ -z "$url" ]; then
    fail "库 $db 的 ir_config_parameter.web.base.url 为空 —— 不是可用的 Odoo 库"
    bad=1
  else
    say "  web.base.url = $url"
  fi
  return $bad
}

rehearse_dump() {
  local f="$1" rc errs size sha toc filtered db ext size_h
  echo ''
  echo '=============================================================='
  echo "彩排档案: $f"
  if [ ! -f "$f" ]; then fail "档案不存在：$f"; return 1; fi
  size=$(wc -c < "$f" | tr -d ' ')
  sha=$(sha_of "$f")
  echo "  大小: $size 字节    sha256: $sha"
  if [ "$size" -lt 512 ]; then
    fail "档案只有 $size 字节，不可能是完整转储（空文件/被截断）"
    return 1
  fi
  toc="$WORK/$(basename "$f").toc"
  if ! "$PGBIN/pg_restore" -l "$f" > "$toc" 2> "$WORK/toc.err"; then
    fail "档案无法解析成 pg_dump 档案（损坏 / 被截断 / 格式不对）—— 备份不可用"
    head -5 "$WORK/toc.err" | sed 's/^/         /'
    return 1
  fi
  # 关键表必须出现在归档目录里（TOC 层就能抓「拿错档案」）
  local missing_toc='' spec t
  for spec in $REQ_SPEC; do
    t="${spec%%:*}"
    if ! awk -v tb="$t" '$4=="TABLE" && $6==tb {found=1} END{exit !found}' "$toc"; then
      missing_toc="$missing_toc $t"
    fi
  done
  if [ -n "$missing_toc" ]; then
    fail "归档目录里没有这些关键表：$missing_toc —— 这份档案不是本项目的库"
    return 1
  fi
  db="edu19_rehearsal_$(basename "$f" | tr -c 'A-Za-z0-9' '_' | cut -c1-40)"
  "$PGBIN/dropdb" -h "$HOST" -p "$PORT" -U "$DBUSER" --if-exists "$db" >/dev/null 2>&1
  if ! "$PGBIN/createdb" -h "$HOST" -p "$PORT" -U "$DBUSER" -O "$DBUSER" -T template0 -E UTF8 "$db" >/dev/null 2>&1; then
    fail "建 scratch 库 $db 失败（目标 Postgres 不可用？）"
    return 1
  fi
  # 扩展显式处理：能建的先建（并从清单剔除，免得重复建报错）；建不了的如实报 WARN
  filtered="$WORK/$(basename "$f").toc.filtered"
  grep -v ' EXTENSION - ' "$toc" > "$filtered"
  for ext in $(awk '$4=="EXTENSION" {print $6}' "$toc"); do
    case "$ext" in plpgsql) continue;; esac
    if "$PGBIN/psql" -h "$HOST" -p "$PORT" -U "$DBUSER" -d "$db" -q -c "CREATE EXTENSION IF NOT EXISTS \"$ext\"" >/dev/null 2>&1; then
      say "  扩展 ${ext}：已在 scratch 库预建（档案内同名条目从还原清单剔除，避免重复创建报错）"
    else
      warn "扩展 $ext 在目标集群不可用（未安装 / 未 shared_preload_libraries）—— 已从还原清单剔除；数据表照常还原，但依赖该扩展的功能在库内不可用"
    fi
  done
  "$PGBIN/pg_restore" -h "$HOST" -p "$PORT" -U "$DBUSER" -d "$db" --no-owner --no-privileges -j 4 -L "$filtered" "$f" > "$WORK/restore.out" 2> "$WORK/restore.err"
  rc=$?
  errs=$(grep -c -i 'error' "$WORK/restore.err" 2>/dev/null || true)
  [ -n "$errs" ] || errs=0
  echo "  pg_restore 退出码=$rc   stderr 中 error 行数=$errs"
  if [ "$rc" -ne 0 ] || [ "$errs" -ne 0 ]; then
    fail "还原进 $db 失败（退出码 ${rc}，error $errs 条）—— 这份备份还原不出来"
    head -20 "$WORK/restore.err" | sed 's/^/         /'
    [ "$KEEP" = 1 ] || say "  （scratch 库 $db 已保留，供人工排查：$PGBIN/psql -h $HOST -p $PORT -U $DBUSER -d ${db}）"
    return 1
  fi
  if check_db "$db"; then
    if [ "$KEEP" = 1 ]; then
      echo "  scratch 库保留：$db"
    else
      "$PGBIN/dropdb" -h "$HOST" -p "$PORT" -U "$DBUSER" --if-exists "$db" >/dev/null 2>&1
    fi
    echo "  结论: PASS  ($f)"
    return 0
  else
    echo "  scratch 库保留供排查：$db"
    echo "  结论: FAIL  ($f)"
    return 1
  fi
}

# ---- 前置检查 ----
if ! "$PGBIN/pg_isready" -h "$HOST" -p "$PORT" -U "$DBUSER" >/dev/null 2>&1; then
  echo "$PROG: 连不上 postgres $HOST:${PORT}（用户 ${DBUSER}）—— 先起库，或用 --host/--port 指定" >&2
  exit 2
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/rehearsal.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

echo "还原彩排门禁  host=$HOST port=$PORT user=$DBUSER profile=$PROFILE"
echo "关键表口径: $REQ_SPEC"

if [ -n "$CHECK_DB" ]; then
  if [ ${#DUMPFILES[@]} -gt 0 ]; then echo "$PROG: --check-db 与 dump 文件不能同时给" >&2; exit 2; fi
  echo "检查已存在的库: $CHECK_DB"
  if ! psql_at "$CHECK_DB" 'select 1' >/dev/null || [ -z "$(psql_at "$CHECK_DB" 'select 1')" ]; then
    fail "库 $CHECK_DB 打不开（不存在？）"
  else
    check_db "$CHECK_DB" || true
  fi
else
  if [ ${#DUMPFILES[@]} -eq 0 ]; then echo "$PROG: 没给 dump 文件。用法见 --help" >&2; exit 2; fi
  for f in "${DUMPFILES[@]}"; do rehearse_dump "$f" || true; done
fi

echo ''
echo '================ 彩排结论 ================'
if [ ${#WARNS[@]} -gt 0 ]; then
  echo "WARN ${#WARNS[@]} 条（不阻断，已逐条打印）"
fi
if [ ${#FAILS[@]} -gt 0 ]; then
  echo "RESULT: FAIL —— ${#FAILS[@]} 条断言未通过，这份备份不能算有效备份"
  exit 1
fi
echo 'RESULT: PASS —— 档案可解析、已真的还原进库、关键表行数达标'
exit 0