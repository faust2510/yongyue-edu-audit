# 菜单收口执行器（宿主侧外壳，t2）
# 用法：
#   bash scripts/consolidate_menus.sh dry-run            # 预演：试算后回滚，绝不落库
#   bash scripts/consolidate_menus.sh apply              # 落库（会写出回滚依据 JSON）
# 环境：MENU_PLAN（计划文件，默认 docs/audit/menu-consolidation/menu-consolidation-plan.json）
set -euo pipefail

MODE="${1:-dry-run}"
case "$MODE" in dry-run|apply) ;; *) echo "[consolidate_menus] 未知模式: ${MODE}（只支持 dry-run / apply）" >&2; exit 2 ;; esac
PLAN="${MENU_PLAN:-docs/audit/menu-consolidation/menu-consolidation-plan.json}"
[ -f "$PLAN" ] || { echo "[consolidate_menus] 计划文件不存在: $PLAN" >&2; exit 2; }
[ -f scripts/consolidate_menus.py ] || { echo "[consolidate_menus] 缺少 scripts/consolidate_menus.py" >&2; exit 2; }

if ! docker compose exec -T web true 2>/dev/null; then echo "[consolidate_menus] web 容器不可用" >&2; exit 3; fi
# 升级锁口径（t9 统一，与 scripts/safe_upgrade.sh:60 同源）：EDU_UPGRADE_LOCK 覆盖 ＞
# TMPDIR（未设**或空** ⇒ /tmp）＞ 固定名；${TMP_BASE%/} 去 macOS 尾斜杠，与 python 侧一致。
TMP_BASE="${TMPDIR:-/tmp}"; TMP_BASE="${TMP_BASE%/}"
UPGRADE_LOCK="${EDU_UPGRADE_LOCK:-${TMP_BASE}/edu19_upgrade.lock}"
if [ -d "${UPGRADE_LOCK}" ]; then echo "[consolidate_menus] 有升级锁（${UPGRADE_LOCK}），停手" >&2; exit 3; fi

echo "[consolidate_menus] mode=$MODE plan=$PLAN"
RAW="$(mktemp "${TMPDIR:-/tmp}/menu_plan.XXXXXX")"
ERR="$(mktemp "${TMPDIR:-/tmp}/menu_plan_err.XXXXXX")"

set +e
docker compose exec -T \
  -e MENU_PLAN_MODE="$MODE" \
  -e MENU_PLAN_TEXT="$(cat "$PLAN")" \
  -e MENU_SELF_TEXT="$(cat scripts/consolidate_menus.py)" \
  web odoo shell -c /etc/odoo/odoo.conf --db_host=db -r odoo -w odoo -d edu19 --no-http \
  < scripts/consolidate_menus.py > "$RAW" 2>"$ERR"
RC="$?"
set -e
echo "[consolidate_menus] odoo shell 退出码 = $RC"

if grep -q 'MARKER::MENU_PLAN_JSON::' "$RAW"; then
  echo "[consolidate_menus] 已产出计划 JSON"
else
  echo "[consolidate_menus] 未产出计划 JSON，输出末尾：" >&2
  tail -25 "$RAW" >&2
  echo "[consolidate_menus] stderr 末尾：" >&2
  tail -15 "$ERR" >&2
  exit 4
fi

# 人读部分（去掉机器 JSON 那一行）
grep -v -e 'MARKER::MENU_PLAN_JSON::' -e 'MARKER::MENU_ROLLBACK_BASIS::' -e 'MARKER::FACULTY_REACHABILITY::' "$RAW"

# 机器部分落盘
mkdir -p docs/audit/menu-consolidation
if [ "$MODE" = "apply" ]; then
  OUT="docs/audit/menu-consolidation/applied-report.json"
else
  OUT="docs/audit/menu-consolidation/dryrun-report.json"
fi
grep 'MARKER::MENU_PLAN_JSON::' "$RAW" | sed 's/^MARKER::MENU_PLAN_JSON:://' > "$OUT"
grep 'MARKER::MENU_ROLLBACK_BASIS::' "$RAW" | sed 's/^MARKER::MENU_ROLLBACK_BASIS:://' > docs/audit/menu-consolidation/rollback-basis.json
grep 'MARKER::FACULTY_REACHABILITY::' "$RAW" | sed 's/^MARKER::FACULTY_REACHABILITY:://' > docs/audit/menu-consolidation/faculty-reachability.json
chmod 644 docs/audit/menu-consolidation/faculty-reachability.json
echo "[consolidate_menus] 教师侧可达性证据已写入 = docs/audit/menu-consolidation/faculty-reachability.json"
chmod 644 docs/audit/menu-consolidation/rollback-basis.json
echo "[consolidate_menus] 回滚依据已写入 = docs/audit/menu-consolidation/rollback-basis.json"
chmod 644 "$OUT"
rm -f "$RAW" "$ERR"
echo "[consolidate_menus] 计划 JSON 已写入 = $OUT"
