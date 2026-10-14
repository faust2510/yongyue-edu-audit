#!/usr/bin/env bash
# docs/audit/migration/precheck_b6.sh — B6 课程导入前的**可执行前置断言**
#
# 为什么需要它：19.0.3.0.0 迁移（老 M2M 表 -> edu_course_subject）只在**版本号变化**时跑一次。
# 若顺序反了（先导入课程、后升级模块），新挂接会写进老表 op_course_op_subject_rel，
# 而迁移不会再跑 => edu_course_subject 永远少掉那一批行（历史口径：38 行 vs 应有 334 行）。
# 这条守卫把「迁移到底跑没跑」变成可机械判定，而不是靠人回忆。
#
# 用法：
#   bash docs/audit/migration/precheck_b6.sh                 # 正向：三条都成立 => exit 0
#   PRECHECK_NEGATIVE=1 bash docs/audit/migration/precheck_b6.sh   # 反向自证：故意期望一个不存在的版本 => exit 1
#
# 退出码：0=可以导入  1=断言失败（停手）  2=找不到数据/环境错
set -uo pipefail
HOST="${HOST:-prod-host}"
DB="${DB:-edu19}"
DBC="${DBC:-edu19-prod-db-1}"
MIN_VER="${MIN_VER:-19.0.3.0.0}"
MIN_ROWS="${MIN_ROWS:-14}"
[ "${PRECHECK_NEGATIVE:-0}" = "1" ] && MIN_VER="203.0.113.9"   # 反向注入：该版本在库里不存在

SQL=$(cat <<'EOSQL'
SELECT 'edu_portal', state, latest_version FROM ir_module_module WHERE name = 'edu_portal'
UNION ALL SELECT 'table_edu_course_subject', coalesce(to_regclass('edu_course_subject')::text,'NULL'), ''
UNION ALL SELECT 'rows_edu_course_subject', (SELECT count(*)::text FROM edu_course_subject), ''
UNION ALL SELECT 'rows_old_rel_table', (SELECT count(*)::text FROM op_course_op_subject_rel), '';
EOSQL
)

OUT=$(env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY ssh -o ConnectTimeout=25 "$HOST" \
  "docker exec -i $DBC psql -U odoo -d $DB -A -F'|' -t -f -" <<<"$SQL" 2>/dev/null) || { echo "PRECHECK ENV_ERR：连不上 $HOST / $DBC"; exit 2; }
echo "--- 实测读数（$HOST $DB）---"
echo "$OUT"

FAIL=0
VER=$(echo "$OUT" | awk -F'|' '$1=="edu_portal"{print $3}')
STATE=$(echo "$OUT" | awk -F'|' '$1=="edu_portal"{print $2}')
TBL=$(echo "$OUT" | awk -F'|' '$1=="table_edu_course_subject"{print $2}')
ROWS=$(echo "$OUT" | awk -F'|' '$1=="rows_edu_course_subject"{print $2}')
OLD=$(echo "$OUT" | awk -F'|' '$1=="rows_old_rel_table"{print $2}')

chk() { if [ "$2" = "1" ]; then echo "PASS  $1"; else echo "FAIL  $1"; FAIL=1; fi; }

chk "edu_portal state=installed（实测 '$STATE'）" "$([ "$STATE" = installed ] && echo 1 || echo 0)"
# 版本比较：按点分段逐段比大小
ver_ge() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" = "$2" ]; }
chk "edu_portal latest_version >= $MIN_VER（实测 '$VER'）" "$(ver_ge "$VER" "$MIN_VER" && echo 1 || echo 0)"
chk "to_regclass('edu_course_subject') 非空（实测 '$TBL'）" "$([ "$TBL" = edu_course_subject ] && echo 1 || echo 0)"
chk "edu_course_subject 行数 >= $MIN_ROWS（实测 '$ROWS'；老表 '$OLD' 行应已被搬过来）" "$([ "${ROWS:-0}" -ge "$MIN_ROWS" ] 2>/dev/null && echo 1 || echo 0)"

if [ "$FAIL" = "0" ]; then echo "PRECHECK PASS —— 19.0.3.0.0 迁移已生效，可以跑 B6 课程导入"; exit 0; fi
echo "PRECHECK FAIL —— 停手！先让 edu_portal 升级到 >= $MIN_VER（跑 -u edu_portal），再回来跑 B6"; exit 1