#!/usr/bin/env bash
# 菜单收口基线（宿主侧外壳）—— 只读：不改记录、不升级、不碰生产。
# 用法：bash scripts/menu_baseline.sh snapshot --tag before [--dry-run]
set -euo pipefail
MODE=""; TAG="snapshot"; DRY=0
OUT_DIR="docs/audit/menu-consolidation"
ROLES="${MENU_BASELINE_ROLES:-admin,backoffice@local,faculty@local}"

usage() { sed -n '2,3p' "$0"; }

while [ $# -gt 0 ]; do
  case "$1" in
    snapshot|plan) MODE="$1" ;;
    --tag) TAG="${2:?--tag 后面要跟名字}"; shift ;;
    --out-dir) OUT_DIR="${2:?}"; shift ;;
    --roles) ROLES="${2:?}"; shift ;;
    --dry-run) DRY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[menu_baseline] 未知参数: $1" >&2; exit 2 ;;
  esac
  shift
done
if [ -z "$MODE" ]; then
  echo "[menu_baseline] 支持 snapshot / plan；前后对照表用 scripts/menu_baseline_diff.py" >&2
  exit 2
fi

# --- 前置探活（docs/code-map.md：跑前先探活）---
if ! docker compose exec -T web true 2>/dev/null; then
  echo "[menu_baseline] web 容器不可用" >&2
  exit 3
fi
# 升级锁口径（t9 统一，与 scripts/safe_upgrade.sh:60 同源）：
#   EDU_UPGRADE_LOCK 覆盖 ＞ TMPDIR（未设**或空** ⇒ /tmp）＞ 固定名 edu19_upgrade.lock。
#   ${TMP_BASE%/} 去掉 macOS TMPDIR 自带的尾斜杠，与 python 侧 os.path.join 形态一致
#   （否则拼出 ".../T//edu19_upgrade.lock"：文件系统等价，但字符串对拍对不上）。
TMP_BASE="${TMPDIR:-/tmp}"; TMP_BASE="${TMP_BASE%/}"
UPGRADE_LOCK="${EDU_UPGRADE_LOCK:-${TMP_BASE}/edu19_upgrade.lock}"
if [ -d "${UPGRADE_LOCK}" ]; then
  echo "[menu_baseline] 检测到升级锁（${UPGRADE_LOCK}）——有人正在升级，读到的菜单可能是中间态，停手" >&2
  exit 3
fi

echo "[menu_baseline] mode=$MODE tag=$TAG dry_run=$DRY roles=$ROLES"
RAW="$(mktemp "${TMPDIR:-/tmp}/menu_baseline.XXXXXX")"
ERR="$(mktemp "${TMPDIR:-/tmp}/menu_baseline_err.XXXXXX")"

set +e
docker compose exec -T -e MENU_BASELINE_MODE="$MODE" -e MENU_BASELINE_ROLES="$ROLES" web odoo shell -c /etc/odoo/odoo.conf --db_host=db -r odoo -w odoo -d edu19 --no-http < scripts/menu_baseline.py > "$RAW" 2>"$ERR"
RC="$?"
set -e
echo "[menu_baseline] odoo shell 退出码=$RC"

if grep -q 'MENU_BASELINE_OK' "$RAW"; then
  echo "[menu_baseline] 容器侧成功标记：已发现"
else
  echo "[menu_baseline] 容器侧未报告成功标记，输出末尾：" >&2
  tail -20 "$RAW" >&2
  echo "[menu_baseline] 容器 stderr 尾部（诊断用，文件保留在）$ERR" >&2
  tail -10 "$ERR" >&2
  exit 4
fi

if [ "$MODE" = "plan" ]; then
  # plan 产物是 Markdown 表（人读），校验方式不同：必须有表头 + 数据行数 == 口径 A
  ROWS="$(grep -c '^| [0-9]' "$RAW" || true)"
  ROOTS="$(grep -c '^# ' "$RAW" || true)"
  if ! grep -q '^| 序 | id | xmlid |' "$RAW"; then
    echo "[menu_baseline] plan 产物缺表头，不落盘" >&2
    exit 4
  fi
  if [ "$ROWS" -lt 1 ]; then
    echo "[menu_baseline] plan 产物没有数据行，不落盘" >&2
    exit 4
  fi
  echo "[menu_baseline] 施工图数据源数据行 = $ROWS"
else
  python3 scripts/menu_baseline_check.py "$RAW"
  CHECK_RC="$?"
  if [ "$CHECK_RC" != "0" ]; then
    echo "[menu_baseline] 基线校验未通过，不落盘，exit = $CHECK_RC" >&2
    exit 4
  fi
fi

if [ "$MODE" = "plan" ]; then
  TARGET="$OUT_DIR/root-menu-plan-$TAG.md"
else
  TARGET="$OUT_DIR/menu-tree-$TAG.json"
fi

if [ "$DRY" = "1" ]; then
  echo "[menu_baseline] 干跑不落盘，目标文件 = $TARGET"
  rm -f "$RAW" "$ERR"
  exit 0
fi

mkdir -p "$OUT_DIR"
if [ -f "$TARGET" ]; then
  BAK="$TARGET.bak"
  cp "$TARGET" "$BAK"
  echo "[menu_baseline] 旧基线已备份 = $BAK"
fi
mv "$RAW" "$TARGET"
chmod 644 "$TARGET"
rm -f "$ERR"
echo "[menu_baseline] 已写入 = $TARGET"
