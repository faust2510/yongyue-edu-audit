#!/usr/bin/env bash
# scripts/backup_daily.sh — 在生产机本机跑（由 systemd timer 调用）：
#   全量 pg_dump + filestore tar + 本机还原彩排 + 推异地 + 保留策略 + manifest
#
# 为什么要在生产机本机彩排：『备份能还原』必须在产生它的那一刻被证明，而不是等要恢复的时候。
# （2026-10-01 事故：9-17 那批转储谁都没试过能不能还原，机器一没就全没了。）
# 彩排用的是同一个 PG 16 容器，还原进 scratch 库，断言通过才推异地。
#
# 依赖：bash / docker / tar / sha256sum（Ubuntu 自带）——不需要 pip，不需要 python 包。
# 配置优先级：脚本默认值 < /etc/edu19-backup.env < 命令行参数。
# 用法：backup_daily.sh [--check] [--drill] [--dry-run] [--keep N] [--offsite-kind K] [--offsite-target T] [--env-file F]
# 退出码：0=全链路通过  1=失败  2=用法/环境错  3=落盘但不完整或未验证（filestore 空 / 异地未配 / 未彩排）
set -uo pipefail

PROG="$(basename "$0")"
ENV_FILE="${ENV_FILE:-/etc/edu19-backup.env}"
PROJECT_DIR="${PROJECT_DIR:-/opt/edu-app}"
STAGE_DIR="${STAGE_DIR:-$PROJECT_DIR/backup}"
DB_CONTAINER="${DB_CONTAINER:-edu19-prod-db-1}"
WEB_CONTAINER="${WEB_CONTAINER:-edu19-prod-web-1}"
DB_NAME="${DB_NAME:-edu19}"
DB_USER="${DB_USER:-odoo}"
SCRATCH_DB="${SCRATCH_DB:-edu19_rehearsal}"
FILESTORE_PARENT="${FILESTORE_PARENT:-/var/lib/odoo/filestore}"
KEEP="${KEEP:-7}"
KEEP_MONTHLY="${KEEP_MONTHLY:-12}"
REHEARSE="${REHEARSE:-1}"
OFFSITE_KIND="${OFFSITE_KIND:-none}"
OFFSITE_TARGET="${OFFSITE_TARGET:-}"
OFFSITE_SSH_KEY="${OFFSITE_SSH_KEY:-}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"
MODE=backup
DRYRUN=0

if [ -r "$ENV_FILE" ]; then . "$ENV_FILE"; fi

while [ $# -gt 0 ]; do
  case "$1" in
    --check) MODE=check; shift;;
    --drill) MODE=drill; shift;;
    --dry-run) DRYRUN=1; shift;;
    --keep) KEEP="$2"; shift 2;;
    --keep-monthly) KEEP_MONTHLY="$2"; shift 2;;
    --no-rehearse) REHEARSE=0; shift;;
    --offsite-kind) OFFSITE_KIND="$2"; shift 2;;
    --offsite-target) OFFSITE_TARGET="$2"; shift 2;;
    --env-file) ENV_FILE="$2"; [ -r "$ENV_FILE" ] && . "$ENV_FILE"; shift 2;;
    -h|--help) sed -n '2,14p' "$0"; exit 0;;
    *) echo "$PROG: 未知选项 $1" >&2; exit 2;;
  esac
done

FAILS=0
INCOMPLETE=0
ok()   { printf '  [ok]   %s\n' "$1"; }
warn() { printf '  [WARN] %s\n' "$1"; INCOMPLETE=1; }
bad()  { printf '  [FAIL] %s\n' "$1"; FAILS=$((FAILS + 1)); }
note() { printf '%s\n' "$1"; }
die()  { printf '%s: %s\n' "$PROG" "$1" >&2; exit 2; }


note "== 前置检查 =="
command -v docker >/dev/null 2>&1 || die "没有 docker"
command -v tar >/dev/null 2>&1 || die "没有 tar"
command -v sha256sum >/dev/null 2>&1 || die "没有 sha256sum"
ok "docker/tar/sha256sum 都在（不需要 pip / python 包）"
for c in "$DB_CONTAINER" "$WEB_CONTAINER"; do
  r="$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)"
  [ "$r" = true ] || { bad "容器 $c 没在跑（inspect 得到 '$r'）"; }
done
[ "$FAILS" = 0 ] || { note '容器没起就不备份：先 docker compose up -d'; exit 1; }
ok "容器 $DB_CONTAINER / $WEB_CONTAINER 都在跑"
docker exec "$DB_CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 || { bad "容器里 $DB_NAME pg_isready 不通过"; exit 1; }
ok "$DB_NAME pg_isready 通过"
docker exec "$WEB_CONTAINER" test -d "$FILESTORE_PARENT/$DB_NAME" 2>/dev/null || { bad "容器 $WEB_CONTAINER 里 $FILESTORE_PARENT/$DB_NAME 不存在（filestore 卷挂了？）"; exit 1; }
ok "容器里 filestore 路径存在：$FILESTORE_PARENT/$DB_NAME"
DF_TARGET="$STAGE_DIR"; [ -d "$DF_TARGET" ] || DF_TARGET="$PROJECT_DIR"
FREE_KB="$(df -Pk "$DF_TARGET" 2>/dev/null | awk 'NR==2{print $4}')"
if [ -z "$FREE_KB" ]; then
  if [ "$MODE" = check ]; then warn "测不到 $DF_TARGET 的磁盘余量（路径还不存在）"; else die "$DF_TARGET 不存在或 df 失败 —— 备份没地方写"; fi
elif [ "$FREE_KB" -lt 524288 ]; then die "$DF_TARGET 剩余空间不足 512MB（当前 ${FREE_KB}KB）—— 备份会写爆磁盘"; fi
ok "磁盘余量 ${FREE_KB}KB"
case "$OFFSITE_KIND" in
  none) warn "OFFSITE_KIND=none：这次备份只落在本机 $STAGE_DIR —— 和生产机同一个故障域，不算有效备份";;
  rsync) command -v rsync >/dev/null 2>&1 || die "OFFSITE_KIND=rsync 但本机没有 rsync"
         [ -n "$OFFSITE_TARGET" ] || die "OFFSITE_KIND=rsync 但 OFFSITE_TARGET 为空"
         ok "异地=rsync:$OFFSITE_TARGET"
         if [ -d "$STAGE_DIR" ]; then
           # 2026-10-01 修（F1，假红）：原先这行是**裸 rsync -n**，不带 -e ⇒ 用 OFFSITE_SSH_KEY
           #   的部署会**永久假红**（真机实测 CHECK_EXIT=1 + rsync 255 Permission denied；同一秒
           #   手工加 -e "ssh -i <key>" 就 exit 0）。照手册做的人每个都会踩 ⇒ 复用 push_offsite 那套。
           CK_EXTRA=""
           [ -n "$OFFSITE_SSH_KEY" ] && CK_EXTRA="ssh -i $OFFSITE_SSH_KEY -o StrictHostKeyChecking=accept-new"
           if rsync -n ${CK_EXTRA:+-e "$CK_EXTRA"} "$STAGE_DIR/" "$OFFSITE_TARGET/" >/dev/null 2>&1; then ok "异地目标可达（rsync -n 干跑通过，含密钥）"; else bad "异地目标不可达/权限不足：$OFFSITE_TARGET"; fi
         fi;;
  rclone) command -v rclone >/dev/null 2>&1 || die "OFFSITE_KIND=rclone 但本机没有 rclone（apt-get install rclone）"; [ -n "$RCLONE_REMOTE" ] || die "OFFSITE_KIND=rclone 但 RCLONE_REMOTE 为空"; ok "异地=rclone:$RCLONE_REMOTE";;
  *) die "OFFSITE_KIND 只认 none|rsync|rclone，收到 $OFFSITE_KIND";;
esac

if [ "$MODE" = check ]; then
  note ''
  note '== --check：只检查，什么都没写 =='
  if [ "$FAILS" = 0 ] && [ "$INCOMPLETE" = 0 ]; then note 'RESULT: OK（前置条件满足）'; exit 0; else note 'RESULT: 有问题（见上）'; exit 1; fi
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/edu19-backup.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

# ---------------- 还原彩排（在 db 容器里做）----------------
rehearse() {
  local dump="$1" tag="$2" toc="$WORK/toc" filt="$WORK/toc.filtered" errf="$WORK/restore.err" ext rc errs t n
  local before="$FAILS"
  note "== 还原彩排（${tag}）：$dump =="
  docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -q -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\"" >/dev/null 2>&1
  docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -q -c "CREATE DATABASE \"$SCRATCH_DB\" TEMPLATE template0" >/dev/null 2>&1 || { bad "建 scratch 库 $SCRATCH_DB 失败"; return 1; }
  if ! docker exec -i "$DB_CONTAINER" pg_restore -l < "$dump" > "$toc" 2>/dev/null; then
    bad "$dump 解析不了（损坏/截断/不是 pg_dump 档案）—— 这份备份不可用"
    docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -q -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\"" >/dev/null 2>&1
    return 1
  fi
  grep -v ' EXTENSION - ' "$toc" > "$filt"
  for ext in $(awk '$4=="EXTENSION" {print $6}' "$toc"); do
    case "$ext" in plpgsql) continue;; esac
    if docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$SCRATCH_DB" -q -c "CREATE EXTENSION IF NOT EXISTS \"$ext\"" >/dev/null 2>&1; then
      ok "扩展 $ext 已预建（归档内同名条目已剔除，避免重复创建报错）"
    else
      warn "扩展 $ext 在本机容器不可用 —— 已剔除该条目；数据表照常还原，依赖它的功能在库内不可用"
    fi
  done
  docker exec -i "$DB_CONTAINER" sh -c 'cat > /tmp/edu19_rehearsal.toc' < "$filt"
  docker exec -i "$DB_CONTAINER" pg_restore -U "$DB_USER" -d "$SCRATCH_DB" --no-owner --no-privileges -L /tmp/edu19_rehearsal.toc < "$dump" > /dev/null 2> "$errf"
  rc=$?
  errs="$(grep -c -i 'error' "$errf" 2>/dev/null || true)"
  [ -n "$errs" ] || errs=0
  note "  pg_restore 退出码=$rc  stderr 中 error 行数=$errs"
  if [ "$rc" != 0 ] || [ "$errs" != 0 ]; then
    bad "还原进 $SCRATCH_DB 失败（退出码 ${rc}，error $errs 条）"
    head -20 "$errf" | sed 's/^/         /'
  else
    ok "还原进 $SCRATCH_DB 成功（0 error）"
  fi
  for t in res_company res_users res_partner ir_module_module ir_model_data ir_ui_menu ir_config_parameter mail_message ir_attachment op_course op_batch op_student edu_application edu_notice edu_alumni_job; do
    n="$(psql_at "$SCRATCH_DB" "select count(*) from public.$t")"
    if [ -z "$n" ]; then bad "关键表 $t 不存在（空库/拿错档案）"; elif [ "$n" -lt 1 ]; then bad "关键表 $t 行数为 0"; else ok "$t = $n 行"; fi
  done
  n="$(psql_at "$SCRATCH_DB" "select count(*) from ir_module_module where state='installed'")"
  if [ -z "$n" ] || [ "$n" -lt 1 ]; then bad "已装模块数为 0 或读不到"; else ok "ir_module_module installed = $n"; fi
  n="$(psql_at "$SCRATCH_DB" "select value from ir_config_parameter where key='web.base.url'")"
  if [ -z "$n" ]; then bad "ir_config_parameter.web.base.url 为空"; else ok "web.base.url = $n"; fi
  docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -q -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\"" >/dev/null 2>&1
  docker exec "$DB_CONTAINER" rm -f /tmp/edu19_rehearsal.toc >/dev/null 2>&1
  [ "$FAILS" = "$before" ]
}

# ---------------- 推异地 ----------------
push_offsite() {
  local f out
  case "$OFFSITE_KIND" in
    none) warn "异地未配置（OFFSITE_KIND=none）：文件只在 ${STAGE_DIR}，不算异地备份"; return 1;;
    rsync)
      RSYNC_MKPATH=""
      if rsync --help 2>&1 | grep -q -- --mkpath; then RSYNC_MKPATH=--mkpath; else note "  注：本机 rsync 不支持 --mkpath，异地目标目录必须预先存在"; fi
      local -a extra=()
      if [ -n "$OFFSITE_SSH_KEY" ]; then extra=(-e "ssh -i $OFFSITE_SSH_KEY -o StrictHostKeyChecking=accept-new"); fi
      for f in "$@"; do
        rsync -a $RSYNC_MKPATH ${extra[@]+"${extra[@]}"} "$f" "$OFFSITE_TARGET/" || { bad "rsync 推 $(basename "$f") 失败"; return 1; }
      done
      for f in "$@"; do
        out="$(rsync -ni --checksum ${extra[@]+"${extra[@]}"} "$f" "$OFFSITE_TARGET/" 2>&1)"
        if [ -n "$out" ]; then bad "异地校验不一致（$(basename "$f")）：$out"; return 1; fi
      done
      ok "已推异地并经 --checksum 复核：$OFFSITE_TARGET";;
    rclone)
      for f in "$@"; do rclone copy --checksum "$f" "$RCLONE_REMOTE" || { bad "rclone 推 $(basename "$f") 失败"; return 1; }; done
      ok "已推异地：$RCLONE_REMOTE";;
  esac
}

# 2026-10-01 新增（F2）：删一份备份时异地也要删**同一份的全部伴生文件**。
#   绝不对异地目录整体 --delete —— 那目录里还可能有别人的东西，只删自己命名的这几个。
purge_offsite() {
  local base="$1" stem userhost dir
  [ "$OFFSITE_KIND" = rsync ] || return 0
  [ -n "$OFFSITE_TARGET" ] || return 0
  case "$OFFSITE_TARGET" in
    *:*) userhost="${OFFSITE_TARGET%%:*}"; dir="${OFFSITE_TARGET#*:}";;
    *) return 0;;
  esac
  stem="${base%.dump}"
  local -a e=()
  [ -n "$OFFSITE_SSH_KEY" ] && e=(-i "$OFFSITE_SSH_KEY" -o StrictHostKeyChecking=accept-new)
  # 远端命令用**单引号**包住每个路径（本行整体是本地双引号串），避免本地/远端两重解析打架。
  # ⚠ 这行第一次写错过：把转义的双引号直接嵌进双引号串会让远端收到断开的命令，
  #    而 rm -f 断错路径是**危险**的 —— 所以下面加了「打印远端命令」的测试。
  local q="'"
  if ssh ${e[@]+"${e[@]}"} "$userhost" "rm -f ${q}$dir/$base${q} ${q}$dir/$base.sha256${q} ${q}$dir/${stem}_filestore.tar.gz${q} ${q}$dir/${stem}_filestore.tar.gz.sha256${q}" 2>/dev/null; then
    note "  异地同步删除：${base}（含 filestore 伴生文件）"
  else
    warn "  异地删除失败（本机已删）：$base —— 异地会残留，请人工清理"
  fi
}

# ---------------- 保留策略（只删自己命名的档案）----------------
retention() {
  local f base ts ym idx=0 seen="" kept=0 keep ismonth
  local -a files=()
  while IFS= read -r f; do files+=("$f"); done < <(ls -1t "$STAGE_DIR"/edu19_*Z.dump 2>/dev/null || true)
  for f in ${files[@]+"${files[@]}"}; do
    idx=$((idx + 1))
    base="$(basename "$f")"
    keep=0
    [ "$idx" -le "$KEEP" ] && keep=1
    ts="$(printf '%s' "${base%.dump}" | tr -cd '0-9')"
    ym="${ts:0:6}"
    ismonth=0
    case " $seen " in *" $ym "*) ;; *) ismonth=1; seen="$seen $ym";; esac
    if [ "$ismonth" = 1 ] && [ "$kept" -lt "$KEEP_MONTHLY" ]; then kept=$((kept + 1)); keep=1; fi
    [ "$base" = "$NEWDUMP" ] && keep=1
    if [ "$keep" = 0 ]; then
      # 2026-10-01 修（F2，无上限堆积）：原先只删 .dump 与 .dump.sha256，而 _filestore.tar.gz 与其
      #   .sha256 **永不清理**（本机与异地都累积，异地 rsync 也没有删除逻辑）。真机实证：--keep 1
      #   真跑 → 删了 dump、filestore 档仍在。量级 2.5MB/份·天 ≈ 0.9GB/年无上限，而异地只剩 3.8GB。
      stem="${f%.dump}"
      if [ "$DRYRUN" = 1 ]; then
        note "  [dry-run] 该删: $base 及其 filestore 伴生文件（本机与异地）"
      else
        note "  删旧档: ${base}（含 filestore 伴生文件）"
        rm -f "$f" "$f.sha256" "${stem}_filestore.tar.gz" "${stem}_filestore.tar.gz.sha256"
        purge_offsite "$base"
      fi
    fi
  done
}

dexec() { docker exec -i "$DB_CONTAINER" "$@"; }
psql_at() { docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$1" -Atc "$2" 2>/dev/null; }

# ---------------- --drill：只彩排最老的那份（月度演练）----------------
if [ "$MODE" = drill ]; then
  # 2026-10-01 修（F3，假绿）：原先用 ls -1tr（按 **mtime**）挑「最老」。
  #   而截断/损坏档案的手段会刷新 mtime ⇒ 把最老那份弄坏后，这里会**静默挑到另一份健康的**
  #   并报 PASS —— 「坏档演练」因此可以是绿的 = 门禁不能变红 = 假门禁（装机时已骗过一个人）。
  #   改为按**文件名里的时间戳**排序：档案名形如 edu19_<host>_<YYYYMMDD>T<HHMMSS>Z.dump，
  #   定宽零填充 ⇒ 字典序即时间序，与 mtime 彻底解耦。
  OLDEST="$(ls -1 "$STAGE_DIR"/edu19_*Z.dump 2>/dev/null | LC_ALL=C sort | head -1)"
  [ -n "$OLDEST" ] || die "$STAGE_DIR 里没有可演练的档案（edu19_*Z.dump）"
  note "月度演练：挑最老的一份重放彩排 -> $OLDEST"
  rehearse "$OLDEST" drill || true
  note ''
  if [ "$FAILS" = 0 ]; then note 'RESULT: PASS（保留期内最老的那份仍可还原）'; exit 0; else note 'RESULT: FAIL（老备份已不可还原，立刻人工介入）'; exit 1; fi
fi

# ---------------- 备份主流程 ----------------
TS="$(date -u +%Y%m%dT%H%M%SZ)"
NEWDUMP="edu19_${TS}.dump"
DUMP="$STAGE_DIR/$NEWDUMP"
FSFILE="$STAGE_DIR/edu19_${TS}_filestore.tar.gz"
FS_FILES=0
FS_STATE=NOTPULLED

note "== 1/5 数据库全量转储 =="
docker exec -i "$DB_CONTAINER" pg_dump -U "$DB_USER" -Fc -d "$DB_NAME" > "$DUMP.part" 2> "$WORK/pgdump.err"
RC=$?
if [ "$RC" != 0 ] || [ ! -s "$DUMP.part" ]; then bad "pg_dump 失败（退出码 ${RC}）"; head -10 "$WORK/pgdump.err" | sed 's/^/         /'; rm -f "$DUMP.part"; note 'RESULT: FAIL'; exit 1; fi
SZ="$(wc -c < "$DUMP.part" | tr -d ' ')"
if [ "$SZ" -lt 100000 ]; then bad "转储只有 $SZ 字节，太小"; rm -f "$DUMP.part"; note 'RESULT: FAIL'; exit 1; fi
mv "$DUMP.part" "$DUMP"
ok "${DUMP}（$SZ 字节）"

note "== 2/5 filestore 归档 =="
docker exec "$WEB_CONTAINER" tar -czf - -C "$(dirname "$FILESTORE_PARENT")" "$(basename "$FILESTORE_PARENT")/$DB_NAME" > "$FSFILE.part" 2> "$WORK/fs.err"
RC=$?
if [ "$RC" != 0 ]; then bad "filestore tar 失败（退出码 ${RC}）"; rm -f "$FSFILE.part"; note 'RESULT: FAIL'; exit 1; fi
if ! tar -tzf "$FSFILE.part" >/dev/null 2>&1; then bad "filestore 归档校验失败（tar -tzf 读不出来）"; rm -f "$FSFILE.part"; note 'RESULT: FAIL'; exit 1; fi
FS_FILES="$(tar -tzf "$FSFILE.part" 2>/dev/null | grep -v '/$' | grep -c . || true)"
[ -n "$FS_FILES" ] || FS_FILES=0
mv "$FSFILE.part" "$FSFILE"
if [ "$FS_FILES" -eq 0 ]; then
  FS_STATE=EMPTY
  warn "filestore 一个文件都没有 —— 这不叫备份成功：附件实体文件不在这次备份里（生产确实没附件，还是卷挂错了？要人看一眼）"
else
  FS_STATE=OK
  ok "${FSFILE}（$FS_FILES 个文件）"
fi
sha256sum "$DUMP" > "$DUMP.sha256"
sha256sum "$FSFILE" > "$FSFILE.sha256"
ok "sha256 已落"

note "== 3/5 还原彩排（本机容器内，scratch 库）=="
DBV=PASS
if [ "$REHEARSE" = 1 ]; then
  rehearse "$DUMP" "$TS" || DBV=FAIL
else
  warn "REHEARSE=0：这份备份没经过还原彩排，按本仓铁律不算有效备份"
  DBV=SKIPPED
fi

note "== 4/5 推异地 =="
PUSHED=0
if [ "$DRYRUN" = 1 ]; then
  warn "--dry-run：不推异地、不删旧档"
elif push_offsite "$DUMP" "$FSFILE" "$DUMP.sha256" "$FSFILE.sha256"; then
  PUSHED=1
fi

note "== 5/5 manifest + 保留策略 =="
if [ "$DBV" = FAIL ]; then VERDICT=FAIL
elif [ "$DBV" != PASS ]; then VERDICT=UNVERIFIED
elif [ "$FS_STATE" != OK ]; then VERDICT=INCOMPLETE
elif [ "$PUSHED" != 1 ]; then VERDICT=INCOMPLETE
else VERDICT=PASS; fi
if [ ! -f "$STAGE_DIR/MANIFEST.tsv" ]; then printf '# ts\thost\tdb\tdump\tbytes\tsha256\tfilestore\tsha256\tverdict\tfs_state\tfs_files\toffsite\n' >> "$STAGE_DIR/MANIFEST.tsv"; fi
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
  "$TS" "$(hostname -s 2>/dev/null || echo unknown)" "$DB_NAME" "$NEWDUMP" "$SZ" "$(cut -d' ' -f1 "$DUMP.sha256")" "$(basename "$FSFILE")" "$(cut -d' ' -f1 "$FSFILE.sha256")" "$VERDICT" "$FS_STATE" "$FS_FILES" "$OFFSITE_KIND" >> "$STAGE_DIR/MANIFEST.tsv"
retention

echo ''
echo '================ 备份结论 ================'
echo "档案: $DUMP"
echo "filestore: $FSFILE  [$FS_STATE, $FS_FILES 个文件]"
echo "本机彩排: $DBV"
echo "异地: $OFFSITE_KIND ${OFFSITE_TARGET:-${RCLONE_REMOTE:-}} (pushed=$PUSHED)"
echo "总判定: $VERDICT"
case "$VERDICT" in
  PASS) echo 'RESULT: PASS —— 转储+附件已推异地，且本机彩排还原成功'; exit 0;;
  FAIL) echo 'RESULT: FAIL —— 彩排没通过或还原报错，立刻人工介入'; exit 1;;
  UNVERIFIED) echo 'RESULT: UNVERIFIED —— 文件在，但没经过还原彩排，不算有效备份'; exit 3;;
  INCOMPLETE) echo 'RESULT: INCOMPLETE —— 文件在，但缺附件/缺异地（见上面 WARN），不算完整有效备份'; exit 3;;
  *) echo "RESULT: $VERDICT"; exit 3;;
esac