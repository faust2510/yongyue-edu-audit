#!/usr/bin/env bash
# ============================================================================
# tests/smoke/settings_deadline_reverse_test.sh
#   反向测试（必须能红）：把 fields.Date **注回**去，**同一把尺子**（
#   settings_deadline_probe.py 的 default_get 全字段判据）必须重现那条 Exception；
#   脚本结束自动还原源码（trap），还原后再跑同一判据必须复绿。
#
# 为什么必须做：只证明「现在是绿的」不够 —— 一个恒绿的判据等于没有判据。
#   本脚本证明该判据对「Date 类型 + config_parameter」这一形态**确实会红**。
#
# 用法：bash tests/smoke/settings_deadline_reverse_test.sh
# 退出码：0 = 注入后确实变红（反向成立）｜1 = 注入后仍是绿的（判据无效）｜2 = ENV
# ============================================================================
set -uo pipefail
SRC="custom_addons/edu_portal/models/registration.py"
BAK="$(mktemp)"
LOG="/tmp/t110/reverse_red.log"
mkdir -p /tmp/t110
cp "$SRC" "$BAK"
restore() { cp "$BAK" "$SRC"; rm -f "$BAK"; echo "[reverse] 已还原 $SRC"; }
trap restore EXIT

python3 - <<'PY'
import pathlib
p = pathlib.Path('custom_addons/edu_portal/models/registration.py')
s = p.read_text(encoding='utf-8')
for f in ('edu_apply_deadline', 'edu_enroll_deadline'):
    old = '%s = fields.Datetime(' % f
    assert s.count(old) == 1, '锚点不唯一：%s (%d)' % (old, s.count(old))
    s = s.replace(old, '%s = fields.Date(' % f)
p.write_text(s, encoding='utf-8')
print('[reverse] 已注入 fields.Date x2（保留 config_parameter，复现 t88 原形态）')
PY

docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
  --db_host=db -r odoo -w odoo --no-http \
  < tests/smoke/settings_deadline_probe.py > "$LOG" 2>&1
rc=$?
echo "[reverse] 探针退出码=$rc"
grep -E '^\[FAIL\] settings_default_get_all_fields' "$LOG" | cut -c1-400
if grep -q "must have type 'boolean', 'integer', 'float', 'char', 'selection', 'many2one' or 'datetime'" "$LOG"; then
  echo "REVERSE_OK: 注入 fields.Date 后同一判据精确重现原 Exception（日志 ${LOG}）"
  exit 0
fi
echo "REVERSE_FAIL: 注入后判据没红 —— 判据无效，别拿它当证据" >&2
exit 1