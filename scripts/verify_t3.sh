#!/usr/bin/env bash
# t3 交付自证 —— 一条命令核对全部验收项 + 版本指纹
# 用法: bash scripts/verify_t3.sh
# 退出码 0 = 全部通过；非 0 = 有项不符（会逐条打印）
set -u
F=custom_addons/edu_brand/static/src/scss/brand_tokens.scss
C=custom_addons/edu_portal/static/src/css/custom_home.css
fail=0
md5of(){ if command -v md5 >/dev/null 2>&1; then md5 -q "$1"; else md5sum "$1" | cut -d' ' -f1; fi; }
ok(){ printf '  [OK]   %s\n' "$1"; }
ng(){ printf '  [FAIL] %s\n' "$1"; fail=1; }
chk(){ # chk <描述> <期望值> <实际值>
  if [ "$2" = "$3" ]; then ok "$1 ($3)"; else ng "$1 (期望 $2, 实际 $3)"; fi
}

echo "=== 版本指纹（对不上就是读到了旧视图） ==="
echo "  brand_tokens.scss  md5 $(md5of "$F")  $(wc -l < "$F" | tr -d ' ') 行  mtime $(ls -l "$F" | awk '{print $7,$8}')"
echo

echo "=== 1. 通道令牌：逗号分隔 ==="
chk "空格形态通道（应 0）" 0 "$(grep -cE -- '--[a-z0-9-]+-rgb: *#\{red\([^)]*\)\} #\{green' "$F" || true)"
chk "逗号派生通道（应 9）" 9 "$(grep -cE -- '--[a-z0-9-]+-rgb: *#\{red\([^)]*\)\}, #\{green' "$F" || true)"
chk "--white-rgb 逗号"    1 "$(grep -c -- '--white-rgb: 255, 255, 255;' "$F" || true)"
chk "--black-rgb 逗号"    1 "$(grep -c -- '--black-rgb: 0, 0, 0;' "$F" || true)"

echo "=== 2. 阴影族：--shadow / --shadow-rgb，消费逗号式 ==="
chk "--shadow 基色"          1 "$(grep -cE -- '^  --shadow: #\{\$shadow\};' "$F" || true)"
chk "--shadow-rgb 派生通道"  1 "$(grep -cE -- '^  --shadow-rgb: +#\{red\(\$shadow\)\}' "$F" || true)"
chk "shadow-sm/md/lg 逗号消费" 3 "$(grep -cE -- '--shadow-(sm|md|lg): .*rgba\(var\(--shadow-rgb\)' "$F" || true)"
chk "-ink 残留（应 0）"      0 "$(grep -o 'shadow-ink' "$F" | wc -l | tr -d ' ')"

echo "=== 3. accent / gold / neutral-rgb ==="
chk "--accent = teal-600"    1 "$(grep -cE -- '^  --accent: +var\(--teal-600\);' "$F" || true)"
chk "\$accent = \$teal-600"   1 "$(grep -cE -- '^\$accent: +\$teal-600;' "$F" || true)"
chk "--gold-100 存在"        1 "$(grep -cE -- '^  --gold-100: #\{\$gold-100\};' "$F" || true)"
chk "gold-200 旧名（应 0）"   0 "$(grep -c 'gold-200' "$F" || true)"
chk "--neutral-rgb 由 \$neutral 派生" 1 "$(grep -cE -- '^  --neutral-rgb: +#\{red\(\$neutral\)\}' "$F" || true)"

echo "=== 4. 自定义属性值插值纪律 ==="
chk "裸变量赋自定义属性（应 0）" 0 "$(grep -cE -- '^  --[A-Za-z0-9_-]+: +\$' "$F" || true)"

echo "=== 5. 旧阴影墨 #172B4D 全仓清零 ==="
chk "全仓命中（应 0）" 0 "$(grep -rli '172b4d' custom_addons --include='*.css' --include='*.scss' 2>/dev/null | wc -l | tr -d ' ')"
chk "custom_home.css 用 --shadow-rgb" 1 "$(grep -c -- 'rgba(var(--shadow-rgb), .06)' "$C" || true)"

echo "=== 6. 网站色板 8 项（\$o-user-color-palette） ==="
chk "palette map-merge 存在" 1 "$(grep -c 'o-user-color-palette: map-merge' "$F" || true)"
chk "映射键数（应 8）" 8 "$(sed -n '/o-user-color-palette: map-merge/,/));/p' "$F" | grep -cE "^  'o-" || true)"

echo "=== 7. 头部注释含 A/B/C 三例 ==="
chk "A 例" 1 "$(grep -c 'A 普通属性写斜杠式' "$F" || true)"
chk "B 例" 1 "$(grep -c 'B 空格通道 + 逗号引用' "$F" || true)"
chk "C 例" 1 "$(grep -c 'C 逗号通道 + 逗号引用' "$F" || true)"

echo "=== 8. 门禁 ==="
if python3 scripts/color_tokens.py --check >/tmp/verify_t3_gate.out 2>&1; then
  ok "color_tokens.py --check  $(tail -1 /tmp/verify_t3_gate.out)"
else
  ng "$(grep -m1 'FAIL' /tmp/verify_t3_gate.out)"
fi

echo
if [ "$fail" = 0 ]; then echo "=== 全部通过：t3 交付与规范一致 ==="; else echo "=== 有项不符（见上 [FAIL]） ==="; fi
exit "$fail"
