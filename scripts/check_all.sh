#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 一键跑全套验证：静态门禁 + 站点门禁 + 探针 + 端到端 E2E。
#
# 为什么要有一个「全都跑一遍」的入口（2026-10-04 第 64 轮立）：
#   `scripts/` 下已经攒了 **20+ 个门禁/探针** 与 **4 份 E2E**，但**没有一个地方把它们串起来**。
#   后果是实测出来的：第 62/63 轮我随手跑了两份 E2E，才发现
#     · `test_checkin_journal.py` 自称「可重复执行」，实际重复执行必红（判据太松）；
#     · `test_submit_flows.py` 写死过去的日期 + 漏填必填字段，必然 FAIL。
#   两份都**红着没人知道**。门禁再多，不跑就等于没有。
#
# 用法：
#   bash scripts/check_all.sh            全跑（含浏览器/E2E，约几分钟）
#   bash scripts/check_all.sh --no-e2e   跳过 4 份 E2E（只跑门禁与探针）
#   bash scripts/check_all.sh --list     只列出会跑哪些
# 退出码：0=全绿 ｜ 1=有红 ｜ 2=环境未就绪（站点/容器没起）
set -u
cd "$(dirname "$0")/.." || exit 2

NO_PROXY="env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy no_proxy=127.0.0.1,localhost"
PY=/opt/homebrew/bin/python3
[ -x "$PY" ] || PY=python3
E2E=1
FRESH=0
case "${1:-}" in
  --no-e2e) E2E=0 ;;
  # 2026-10-04（第 68 轮）：全新库安装演练是**独立脚本**（它会建库/删库，有副作用），
  #   所以不默认跑；要跑用 `bash scripts/check_fresh_install.sh` 或本脚本的 --fresh-install。
  --fresh-install) FRESH=1 ;;
  --list)
    # 2026-10-04（第 100 轮）：原先这里只打一行分类（「静态门禁 + 站点门禁 + 探针 + E2E」），
    #   **没有真的列出会跑哪些** —— 与它自己的用法说明「只列出会跑哪些」不符（第 100 轮审计时发现）。
    #   改成从下面的 `run "名字"` 调用里抽出来，清单永远与实况一致（不会各写一份）。
    # ⚠ 名字里可能有**大写与空格**（E2E 那几项叫 "E2E submit_flows"）——
    #   第一版正则写成 [a-z_0-9]+ ⇒ 只列出 15 项，而实际跑 33 项。
    # ⚠ 两处易漏（都实测踩过）：① 名字里有大写与空格（"E2E submit_flows"）⇒ 正则不能用 [a-z_]+；
    #   ② E2E 与全新库演练的 run 是**缩进**的（在 if 里）⇒ 不能锚 ^run。
    echo "会跑的检查："
    grep -oE '^[[:space:]]*run "[^"]+"' "$0" | sed 's/^[[:space:]]*run "/  · /; s/"$//'
    # 静态门禁是**循环注册**的（`for g in …`），不出现 run 调用 ⇒ 单独列出来，别让它从清单里消失。
    echo "  （另有静态门禁由 for 循环注册）："
    sed -n '/^for g in /,/; do/p' "$0" | tr -d "\\" | tr '\n' ' ' | sed 's/^for g in //; s/; do//' | tr ' ' '\n' | grep -v "^$" | sed 's/^/  · /'
    # 还有一项是**内联特判**的（undefined_classes 带 UNKNOWN_KNOWN 阈值），不在这两种形式里。
    # ⚠ 别在这里引用 $UNKNOWN_KNOWN —— 它定义在**下面**（第 92 行附近），而本脚本开了 set -u，
    #   引用未定义变量会直接报 "unbound variable"（第 100 轮我自己就这么把 --list 弄挂过一次）。
    echo "  · undefined_classes（内联特判：超过登记的已知数才判红，阈值见脚本内 UNKNOWN_KNOWN）"
    [ "$E2E" = 0 ] && echo "（--no-e2e：已关掉 E2E）"
    [ "$FRESH" = 1 ] && echo "（--fresh-install：会加跑全新库安装演练）"
    exit 0 ;;
esac

pass=0; fail=0; red=""
run() {                       # run <名字> <命令…>
  local name="$1"; shift
  local out rc
  out=$("$@" 2>&1); rc=$?
  if [ $rc -eq 0 ]; then
    pass=$((pass+1)); printf "  ✅ %-28s\n" "$name"
  else
    fail=$((fail+1)); red="$red\n     · $name (exit $rc)"
    printf "  ❌ %-28s exit=%s  %s\n" "$name" "$rc" "$(echo "$out" | tail -1 | cut -c1-64)"
  fi
}

echo "=== 一、静态门禁（不连站点）==="
# ⚠ 2026-10-04（第 65 轮）：这份清单**漏了 check_shell_exitcode** —— 我自己新写的 check_all.sh 里
#   就有一处 shell 变量写法不合规（变量引用后面紧接全角括号、且没加花括号），而这门禁不在清单里 ⇒ 我的「一键全跑」
#   报「22/22 全绿」时它是红的，直到 safe_upgrade.sh 拒绝升级才暴露。**清单漏项 = 假绿**，已补。
for g in check_md_tables check_docs_index check_view_xpath check_po_sanity \
         check_manifest_tracking check_alias_not_extended check_recordset_none \
         check_ui_surface check_qweb_dict_foreach check_manifest_order \
         check_shell_exitcode check_live_registry check_doc_module_count; do
  [ -f "scripts/$g.py" ] && run "$g" python3 "scripts/$g.py"
done
run "asset_freshness" python3 scripts/check_asset_freshness.py

echo "=== 二、站点门禁（需要本地 edu19 在跑）==="
if ! curl -sS -m 5 -o /dev/null http://127.0.0.1:8069/web/login 2>/dev/null; then
  echo "  ⚠ 本地站点不可达 ⇒ 环境型跳过（不是通过）"
  echo; echo "结论：INCOMPLETE（站点没起，只跑了静态部分）"; exit 2
fi
run "accessibility" $NO_PROXY "$PY" scripts/check_accessibility.py --quiet
run "english" $NO_PROXY "$PY" scripts/check_english.py --quiet
run "nav_reachable" $NO_PROXY "$PY" scripts/check_nav_reachable.py
run "odoo_trace" $NO_PROXY "$PY" scripts/check_odoo_trace.py
run "ui_usability" $NO_PROXY "$PY" scripts/check_ui_usability.py
run "squeezed_tables" $NO_PROXY "$PY" scripts/find_squeezed_tables.py

# ⚠ 2026-10-04（本轮我自己踩到并修掉的坑）：`find_undefined_classes` 是**报告型工具**，
#   它自己的 docstring 写着「只报告、不判死；退出码 1=有命中（报告，不等于不合格）」，
#   而命中的 35 个类名**早已登记在案**（docs/audit/deprecated-inventory.md 的 C-13：
#   照旧站 DOM 抄来的类名、旧站样式表从未进本仓，实测页面并不难看 ⇒ 登记不删）。
#   把它当**判死**项塞进来，这份「一键全跑」就会**永远红** ——
#   而一条永远红的检查等于死检查（本仓纪律）。⇒ 改成只读数，且只在一个方向报警：
#   **数量超过登记值**（说明出现了没登记过的新类名）。
UNKNOWN_KNOWN=35               # ← 与 deprecated-inventory C-13 登记的数字一致
_uc=$($NO_PROXY "$PY" scripts/find_undefined_classes.py 2>&1 | grep -o "FOUND（[0-9]*" | grep -o "[0-9]*" | tail -1)
_uc=${_uc:-0}
if [ "$_uc" -gt "$UNKNOWN_KNOWN" ]; then
  fail=$((fail+1)); red="$red\n     · undefined_classes 新增未登记类名（${_uc} > 登记的 ${UNKNOWN_KNOWN}）"
  printf "  ❌ %-28s %s 个（登记 %s）—— 有新增，请看一眼\n" "undefined_classes" "$_uc" "$UNKNOWN_KNOWN"
elif [ "$_uc" -lt "$UNKNOWN_KNOWN" ]; then
  pass=$((pass+1)); printf "  ✅ %-28s %s 个（少于登记的 %s，说明有清理）\n" "undefined_classes" "$_uc" "$UNKNOWN_KNOWN"
else
  pass=$((pass+1)); printf "  ✅ %-28s %s 个（与 C-13 登记一致；报告型，不判死）\n" "undefined_classes" "$_uc"
fi

echo "=== 三、探针 ==="
run "mobile_layout" $NO_PROXY "$PY" scripts/probe_mobile_layout.py
run "metric_consistency" $NO_PROXY "$PY" scripts/probe_metric_consistency.py
run "write_error_paths" $NO_PROXY "$PY" scripts/probe_write_error_paths.py
run "privilege_boundaries" $NO_PROXY "$PY" scripts/probe_privilege_boundaries.py
run "nav_deadlinks" $NO_PROXY "$PY" scripts/probe_nav_deadlinks.py
run "home_cards" $NO_PROXY "$PY" scripts/probe_home_cards.py
run "exports" $NO_PROXY "$PY" scripts/probe_exports.py
run "mobile_flow" $NO_PROXY "$PY" scripts/probe_mobile_flow.py

if [ "$E2E" = "1" ]; then
  echo "=== 四、端到端 E2E ==="
  run "E2E life_eval" $NO_PROXY "$PY" scripts/test_life_eval.py
  run "E2E checkin_journal" $NO_PROXY "$PY" scripts/test_checkin_journal.py
  run "E2E submit_flows" $NO_PROXY "$PY" scripts/test_submit_flows.py
  # 2026-10-03（第 108 轮）补登记：这两个探针此前**不在门禁名单里**（作者与独立验证方都点了这条）——
  #   本仓原话「门禁再多，不跑就等于没有」。它们正是「教务录了分、学生看不见」那条断层的守卫。
  run "grade_entry_probe" $NO_PROXY "$PY" scripts/../tests/smoke/grade_entry_probe.py
  run "gradebook_registrar" $NO_PROXY "$PY" scripts/../tests/smoke/gradebook_registrar_entry.py
  if docker ps --format "{{.Names}}" 2>/dev/null | grep -q edu19-clone-web-1; then
    docker cp scripts/test_timetable_conflict.py edu19-clone-web-1:/tmp/tt_all.py >/dev/null 2>&1
    docker exec -u 0 edu19-clone-web-1 chmod 644 /tmp/tt_all.py >/dev/null 2>&1
    run "E2E timetable_conflict" docker exec -i -u 0 edu19-clone-web-1 sh -c \
        "cd /mnt && odoo shell -d edu19 --db_host=db --db_user=odoo --db_password=odoo --no-http --log-level=error < /tmp/tt_all.py"

    # 2026-10-08（W3）：F4 按钮回填 + F5 @提醒。探针 tests/smoke/tg_assist_mention_probe.py。
    # ⚠ 与上面那条不同：本探针**用自己的退出码**判成败（上面那个只打印 PASS/FAIL ⇒ 永远不会红）。
    #   反向自证过：注入「跨群清」缺陷 ⇒ RESULT=FAIL 16/22 且 exit 1；还原后 22/22 exit 0。
    docker cp tests/smoke/tg_assist_mention_probe.py edu19-clone-web-1:/tmp/w3probe.py >/dev/null 2>&1
    docker exec -u 0 edu19-clone-web-1 chmod 644 /tmp/w3probe.py >/dev/null 2>&1
    run "E2E tg_assist_mention" docker exec -i -u 0 edu19-clone-web-1 sh -c \
        "cd /mnt && odoo shell -d edu19 --db_host=db --db_user=odoo --db_password=odoo --no-http --log-level=error < /tmp/w3probe.py"

    # 2026-10-12：学号登录失败限速（edu.portal.login.throttle）。探针 tests/smoke/login_throttle_probe.py。
    # 守的是一条**生产探针实测到过的回归**：封禁中再失败会把 blocked_until 覆盖成 0 = 自己解锁。
    docker cp tests/smoke/login_throttle_probe.py edu19-clone-web-1:/tmp/throttle_probe.py >/dev/null 2>&1
    docker exec -u 0 edu19-clone-web-1 chmod 644 /tmp/throttle_probe.py >/dev/null 2>&1
    run "E2E login_throttle" docker exec -i -u 0 edu19-clone-web-1 sh -c \
        "cd /mnt && odoo shell -d edu19 --db_host=db --db_user=odoo --db_password=odoo --no-http --log-level=error < /tmp/throttle_probe.py"
  else
    echo "  ⚠ 没找到 edu19-clone-web-1 ⇒ 跳过 conflict / tg_assist_mention / login_throttle E2E（不是通过）"
  fi
fi

if [ "${FRESH:-0}" = "1" ]; then
  echo "=== 五、全新库安装演练（会建/删 edu19_rehearsal）==="
  run "fresh_install" bash scripts/check_fresh_install.sh
fi

echo
echo "================ 汇总 ================"
echo "  通过 $pass ／ 失败 $fail"
[ -n "$red" ] && { echo "  红的项："; echo -e "$red"; }
if [ $fail -eq 0 ]; then
  echo "结论：全绿 ✅"
  exit 0
fi
echo "结论：有红 ❌"
exit 1