#!/usr/bin/env bash
# scripts/backup_pull.sh — 把生产机的全量备份拉到「异地」，并强制它通过还原彩排。
#
# 为什么要有这个脚本（2026-10-01 事故）:
#   生产机（Hostinger 203.0.113.10，/opt/edu-app + /root/edu19-backup）欠费关机且不可达，
#   而所有转储都躺在同一台机器上 —— 机器没了，备份一起没了，只能退回到本机 2026-08-30 的两份。
#   所以本脚本有两条硬原则：
#     1) 落盘位置必须与生产机不同（--out 指向本机其它盘/外置盘/另一台机器）；
#     2) 没通过 restore_rehearsal.sh 的备份不算备份（默认强制彩排，失败即非 0 退出）。
#
# 退出码：0=全链路通过（数据库转储+filestore+彩排）  1=任何一步失败  2=用法错误  3=落盘但不完整/未验证
#
set -uo pipefail

PROG="$(basename "$0")"
HOST="prod-host"
RDIR="/opt/edu-app"
OUT="$HOME/Documents/edu19-backups"
DBNAME="edu19"
DBUSER="odoo"
DBCONTAINER=""
WEBCONTAINER=""
FORMAT="custom"
KEEP=7
KEEP_MONTHLY=12
FILESTORE=1
REHEARSE=1
DRYRUN=0
PGPORT="55432"
PGBIN=""
SSH_TIMEOUT=15

usage() {
  cat <<'EOU'
usage: backup_pull.sh [选项]
  --host H           ssh 目标（默认 prod-host；马上要换新服务器，一定用这个覆盖）
  --dir D            远端项目目录（默认 /opt/edu-app）
  --out O            本地/异地落盘目录（默认 ~/Documents/edu19-backups）
  --db NAME          数据库名（默认 edu19）
  --db-user U        postgres 用户（默认 odoo）
  --db-container C   db 容器名（默认自动探测含 db 的容器）
  --web-container C  web 容器名（默认自动探测含 web 的容器）
  --format F         custom（默认，pg_dump -Fc）| plain（pg_dump | gzip -9）
  --keep N           保留最近 N 份（默认 7）
  --keep-monthly M   另外每月保留 1 份，保留 M 个月（默认 12）
  --no-filestore     不拉 filestore（这份备份记为不完整 => 退出码 3）
  --skip-rehearsal   拉了但不彩排 => 退出码 3，这份备份记为未验证
  --dry-run          只演示保留策略要删什么，不真删
  --port P           本地 scratch postgres 端口（彩排用，默认 55432）
  --pgbin DIR        本地 postgres 客户端目录（彩排用，默认自动探测）
  -h, --help
EOU
}

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:?}"; shift 2;;
    --dir) RDIR="${2:?}"; shift 2;;
    --out) OUT="${2:?}"; shift 2;;
    --db) DBNAME="${2:?}"; shift 2;;
    --db-user) DBUSER="${2:?}"; shift 2;;
    --db-container) DBCONTAINER="${2:?}"; shift 2;;
    --web-container) WEBCONTAINER="${2:?}"; shift 2;;
    --format) FORMAT="${2:?}"; shift 2;;
    --keep) KEEP="${2:?}"; shift 2;;
    --keep-monthly) KEEP_MONTHLY="${2:?}"; shift 2;;
    --no-filestore) FILESTORE=0; shift;;
    --skip-rehearsal) REHEARSE=0; shift;;
    --dry-run) DRYRUN=1; shift;;
    --port) PGPORT="${2:?}"; shift 2;;
    --pgbin) PGBIN="${2:?}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "$PROG: 未知选项 $1" >&2; usage >&2; exit 2;;
  esac
done

die() { printf '%s: %s\n' "$PROG" "$1" >&2; exit 1; }
note() { printf '%s\n' "$1"; }

case "$FORMAT" in custom|plain) ;; *) die "--format 只认 custom|plain，收到 $FORMAT";; esac
case "$KEEP" in ''|*[!0-9]*) die "--keep 要是正整数";; esac
case "$KEEP_MONTHLY" in ''|*[!0-9]*) die "--keep-monthly 要是正整数";; esac

# 硬保险：异地备份不许落在生产机的备份目录里
case "$OUT" in
  /opt/edu-app/*|/root/*|/opt/edu-app|/root)
    die "--out=$OUT 落在生产机的目录里 —— 异地备份的第一原则就是不要和生产机同归于尽";;
esac

# ssh 一律绕开本机系统代理（本机代理 127.0.0.1:12450 会把 ssh 带沟里）
ssh_run() {
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
    ssh -o BatchMode=yes -o ConnectTimeout="$SSH_TIMEOUT" -o StrictHostKeyChecking=accept-new "$HOST" "$1"
}

sha_of() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else sha256sum "$1" | awk '{print $1}'; fi
}
size_of() { wc -c < "$1" | tr -d ' '; }

note "== 0/6 前置检查 =="
ssh_run 'true' >/dev/null 2>&1 || die "ssh $HOST 不通（先确认别名/密钥；代理已绕开）"
note "  ssh $HOST 通"
ssh_run "test -d '$RDIR'" || die "远端 $HOST:$RDIR 不存在"
note "  远端目录 $RDIR 存在"

running="$(ssh_run 'docker ps --format {{.Names}}' 2>/dev/null || true)"
if [ -z "$DBCONTAINER" ]; then
  DBCONTAINER="$(printf '%s\n' "$running" | grep -i db | head -1)"
fi
if [ -z "$WEBCONTAINER" ]; then
  WEBCONTAINER="$(printf '%s\n' "$running" | grep -i -e web -e odoo | head -1)"
fi
[ -n "$DBCONTAINER" ] || die "探测不到 db 容器（远端 docker ps 为空？）—— 用 --db-container 指定"
note "  db 容器=$DBCONTAINER  web 容器=${WEBCONTAINER:-未探测到}"
ssh_run "docker exec $DBCONTAINER pg_isready -U $DBUSER -d $DBNAME" >/dev/null 2>&1 \
  || die "远端 $DBCONTAINER 里 $DBNAME 不健康（pg_isready 未通过）"
note "  远端 $DBNAME pg_isready 通过"

mkdir -p "$OUT" || die "建不了落盘目录 $OUT"
[ -w "$OUT" ] || die "落盘目录 $OUT 不可写"
note "  异地落盘目录 ${OUT}（确认它与生产机不是同一台机器/同一块盘！）"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
HOSTSAN="$(printf '%s' "$HOST" | tr -c 'A-Za-z0-9' '-')"
PFX="edu19_${HOSTSAN}_${TS}"

note "== 1/6 拉数据库全量转储 =="
case "$FORMAT" in
  custom) NEWFILE="$OUT/$PFX.dump"; TMPFILE="$OUT/.$PFX.dump.part"
          ssh_run "docker exec -i $DBCONTAINER pg_dump -U $DBUSER -Fc -d $DBNAME" > "$TMPFILE" ;;
  plain)  NEWFILE="$OUT/$PFX.sql.gz"; TMPFILE="$OUT/.$PFX.sql.gz.part"
          ssh_run "docker exec -i $DBCONTAINER pg_dump -U $DBUSER -d $DBNAME | gzip -9" > "$TMPFILE" ;;
esac
RC=$?
[ "$RC" = 0 ] || { rm -f "$TMPFILE"; die "远端 pg_dump 失败（ssh/docker 退出码 ${RC}）"; }
[ -f "$TMPFILE" ] || die "没拿到转储文件"
SZ="$(size_of "$TMPFILE")"
[ "$SZ" -gt 100000 ] || { rm -f "$TMPFILE"; die "转储只有 $SZ 字节，太小，判定失败"; }
mv "$TMPFILE" "$NEWFILE" || die "落盘失败 $NEWFILE"
note "  $NEWFILE  ($SZ 字节)"

note "== 2/6 本地结构自检（脏档案不落进备份目录）=="
if [ "$FORMAT" = custom ]; then
  if [ -n "$PGBIN" ]; then RS="$PGBIN/pg_restore"; elif command -v pg_restore >/dev/null 2>&1; then RS="$(command -v pg_restore)"; elif [ -x /opt/homebrew/opt/postgresql@16/bin/pg_restore ]; then RS=/opt/homebrew/opt/postgresql@16/bin/pg_restore; else RS=""; fi
  [ -n "$RS" ] || die "本机没有 pg_restore，无法自检/彩排 —— 装 postgresql 客户端或用 --pgbin"
  "$RS" -l "$NEWFILE" >/dev/null 2>&1 || die "拉下来的档案 pg_restore 解析不了（传输损坏？）"
  note "  pg_restore -l 解析通过"
else
  gzip -t "$NEWFILE" 2>/dev/null || die "拉下来的 .sql.gz 解压校验失败（传输损坏？）"
  note "  gzip -t 校验通过"
fi

FSFILE=""
FS_FILES=0
FS_STATE=NOTPULLED
if [ "$FILESTORE" = 1 ]; then
  note "== 3/6 拉 filestore（附件实体文件；只拉 DB 不拉它 = 库能开、附件全断）=="
  [ -n "$WEBCONTAINER" ] || die "没探测到 web 容器，拉不了 filestore —— 用 --web-container 指定，或显式 --no-filestore"
  FSFILE="$OUT/${PFX}_filestore.tar.gz"
  FSTMP="$OUT/.${PFX}_filestore.tar.gz.part"
  ssh_run "docker exec $WEBCONTAINER tar -czf - -C /var/lib/odoo filestore/$DBNAME" > "$FSTMP"
  RC=$?
  if [ "$RC" != 0 ]; then
    rm -f "$FSTMP"
    die "拉 filestore 失败（退出码 ${RC}）—— 远端 /var/lib/odoo/filestore/$DBNAME 不存在或读不了；确认 --web-container 与容器内路径"
  fi
  tar -tzf "$FSTMP" >/dev/null 2>&1 || { rm -f "$FSTMP"; die "filestore 归档校验失败（tar -tzf 读不出来）"; }
  tar -tzf "$FSTMP" 2>/dev/null | grep -q '^filestore/' || { rm -f "$FSTMP"; die "filestore 归档里没有 filestore/ 目录 —— 远端路径拉错了"; }
  FS_FILES="$(tar -tzf "$FSTMP" 2>/dev/null | grep -v '/$' | grep -c . || true)"
  [ -n "$FS_FILES" ] || FS_FILES=0
  FSSZ="$(size_of "$FSTMP")"
  mv "$FSTMP" "$FSFILE"
  note "  $FSFILE  ($FSSZ 字节, $FS_FILES 个文件)"
  if [ "$FS_FILES" -eq 0 ]; then
    FS_STATE=EMPTY
    echo "  [WARN] 远端 filestore 里一个文件都没有（0 个）—— 这不叫「备份成功」：附件实体文件不在这次备份里。"
    echo "  [WARN] 要么生产确实还没有任何附件，要么 filestore 没恢复/挂了错的数据卷；两种都要人看一眼。"
    echo "  [WARN] manifest 记为 INCOMPLETE，退出码 3（不是 0）。"
  else
    FS_STATE=OK
  fi
else
  FS_STATE=SKIPPED
  note "== 3/6 filestore 被 --no-filestore 显式跳过（这份备份不完整：附件实体文件缺失，退出码 3）=="
fi

note "== 4/6 落 sha256 =="
DBSHA="$(sha_of "$NEWFILE")"
printf '%s  %s\n' "$DBSHA" "$(basename "$NEWFILE")" > "$NEWFILE.sha256"
note "  $(basename "$NEWFILE")  $DBSHA"
FSSHA=""
if [ -n "$FSFILE" ]; then
  FSSHA="$(sha_of "$FSFILE")"
  printf '%s  %s\n' "$FSSHA" "$(basename "$FSFILE")" > "$FSFILE.sha256"
  note "  $(basename "$FSFILE")  $FSSHA"
fi

DBV=""
if [ "$REHEARSE" = 1 ]; then
  note "== 5/6 还原彩排（没通过就不算备份）=="
  RS_DIR="$(cd "$(dirname "$0")" && pwd)"
  if bash "$RS_DIR/restore_rehearsal.sh" --pgbin "$PGBIN" --port "$PGPORT" "$NEWFILE"; then
    DBV=PASS
  else
    DBV=FAIL
  fi
else
  note "== 5/6 彩排被 --skip-rehearsal 跳过（这份备份记为「未验证」）=="
  DBV=SKIPPED
fi
if [ "$DBV" = FAIL ]; then
  VERDICT=FAIL
elif [ "$DBV" = SKIPPED ]; then
  VERDICT=UNVERIFIED
elif [ "$FS_STATE" != OK ]; then
  VERDICT=INCOMPLETE
else
  VERDICT=PASS
fi

note "== 6/6 记 manifest + 保留策略 =="
if [ ! -f "$OUT/MANIFEST.tsv" ]; then
  printf '# ts\thost\tdb\tdump\tbytes\tsha256\tfilestore\tsha256\tverdict\tfs_state\tfs_files\n' >> "$OUT/MANIFEST.tsv"
fi
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
  "$TS" "$HOST" "$DBNAME" "$(basename "$NEWFILE")" "$(size_of "$NEWFILE")" "$DBSHA" "${FSFILE:+$(basename "$FSFILE")}" "$FSSHA" "$VERDICT" "$FS_STATE" "$FS_FILES" >> "$OUT/MANIFEST.tsv"
note "  manifest: $OUT/MANIFEST.tsv"

files=()
while IFS= read -r f; do files+=("$f"); done < <(ls -1t "$OUT"/edu19_*_*Z.dump "$OUT"/edu19_*_*Z.sql.gz 2>/dev/null || true)
idx=0
MONTHS_SEEN=""
MONTHS_KEPT=0
for f in ${files[@]+${files[@]}}; do
  idx=$((idx + 1))
  base="$(basename "$f")"
  keep=0
  if [ "$idx" -le "$KEEP" ]; then keep=1; fi
  ts="${base%.dump}"; ts="${ts%.sql.gz}"; ts="${ts##*_}"
  ts="$(printf '%s' "$ts" | tr -cd '0-9')"
  ym="${ts:0:6}"
  ismonth=0
  case " $MONTHS_SEEN " in *" $ym "*) ;; *) ismonth=1; MONTHS_SEEN="$MONTHS_SEEN $ym";; esac
  if [ "$ismonth" = 1 ] && [ "$MONTHS_KEPT" -lt "$KEEP_MONTHLY" ]; then MONTHS_KEPT=$((MONTHS_KEPT + 1)); keep=1; fi
  if [ "$base" = "$(basename "$NEWFILE")" ]; then keep=1; fi
  if [ "$keep" = 0 ]; then
    if [ "$DRYRUN" = 1 ]; then
      note "  [dry-run] 该删: ${base}（不在最近 $KEEP 份内，也不是保留月的首份）"
    else
      note "  删旧档: $base"
      rm -f "$f" "$f.sha256"
    fi
  fi
done

echo ''
echo '================ 备份结论 ================'
echo "档案: $NEWFILE"
echo "filestore: ${FSFILE:-（未拉）}  [$FS_STATE, $FS_FILES 个文件]"
echo "数据库彩排: $DBV"
echo "总判定: $VERDICT"
case "$VERDICT" in
  PASS) echo 'RESULT: PASS —— 已拉到异地，附件实体文件也在，且数据库真的还原成功'; exit 0;;
  FAIL) echo 'RESULT: FAIL —— 备份已落盘但还原彩排失败，立刻人工介入'; exit 1;;
  UNVERIFIED) echo 'RESULT: UNVERIFIED —— 档案在异地，但没经过还原彩排，按本仓铁律不算有效备份'; exit 3;;
  INCOMPLETE) echo 'RESULT: INCOMPLETE —— 数据库那份可用，但附件实体文件没进这次备份（见上面 WARN），不算完整有效备份'; exit 3;;
  *) echo "RESULT: $VERDICT"; exit 3;;
esac