#!/bin/bash
# 马来西亚 prod-host（203.0.113.10）部署同步脚本
# 用法：在仓库根目录执行  bash scripts/deploy_myedu.sh [模块名列表]
#   不带参数 = 同步全部常变模块并升级
#   带模块名 = 只升级指定模块，如: bash scripts/deploy_myedu.sh edu_life,edu_assess
# 注意：若改了公开页模板（homepage/about/programs等），先本地跑
#       scripts/setup_brand_yongyue.py 验证无误后再部署，并在远端重跑远端版 setup。
# 环境变量：UPGRADE_TIMEOUT（升级最长等待秒数，默认 1800）
#           READY_TIMEOUT（重启后就绪探活上限秒数，默认 180）
#           EDU_CHECK_LOGIN / EDU_CHECK_PASSWORD（可选：给门禁一个会话，即可连带核对字段级；
#           不给时门禁只做模型级，并在输出里明写「字段级未验证」）
#
# 2026-09-24 重写 —— 起因是「课代表 / 专业·学制」两个功能在生产**暗了三天**
# ---------------------------------------------------------------------------
# 事故：09-21 上线 custom_addons/edu_portal/models/course_rep.py、09-22 上线
#   models/major_track.py；两次都是 rsync + 在**独立的一次性容器**里
#   `docker compose run … odoo -u edu_portal` 升级，**没有重启 web 进程**。
#   症状：菜单点得开、模型不存在（POST /web/dataset/call_kw model=edu.course.rep → 404，
#   werkzeug.exceptions.NotFound），op.course 上也没有新字段 edu_level_id；
#   每天 01:43 的 cron「edu_portal: 课代表到期收口（实时判定结果落库）」连续三天
#   `KeyError: 'edu.course.rep'`（09-22 01:43:26 / 09-23 01:43:48 / 09-24 01:43:05）。
# 铁律（本脚本从此照它执行）：
#   **Odoo 不会把「已被导入模块里的新文件」带进一个已经在跑的进程。**
#   注册表重载（模块升级）只更新数据库与执行升级的那个进程；活体 web 进程仍是旧注册表。
#   ⇒ 模块代码变了（尤其**新增 .py 文件 / 新增模型字段**）就**必须重启 web 进程**：
#     ① 升级放独立的一次性容器里跑（web 全程照常服务 —— 低停机）；
#     ② 升级结束后**一律** `docker compose restart web`（约 15-20s）；
#     ③ 有界轮询 /web/login 直到 200|302（就绪），超时**硬失败**；
#     ④ 跑活体注册表门禁 scripts/check_live_registry.py（库里有、活体进程认不认识），有 DARK 即失败。
#   历史沿革：更早的版本是「停 web → 升级 → 起 web」（停机数分钟）；后来的"零停机"变体
#   删掉了重启 —— 那正是本次事故的成因。现在两件事都要：**低停机 且 注册表正确**。
#
# 2026-09-29 再修 —— 起因是**同一天被咬两次**：本机 SSH 一断（出口代理干扰，当天断了十几次），
#   脚本就停在第 3 步（或静默退出），**第 4 步「重启 web」永远没跑**。于是生产停在
#   「数据库升了、盘上文件是新的、活体进程还是旧的」—— 正是上面 09-24 那段警告的事故形态，
#   而脚本既不报错也不告诉你（人只能手工读 /tmp/upg.exit、再补一条 docker compose restart web）。
# 现在的硬判据 = **升级 → 重启必须配对**（两条同时成立才算绿）：
#   ① /tmp/upg.exit = 0（升级容器退出码）
#   ② web 容器的 StartedAt **晚于** /tmp/upg.done（升级完成时刻）
#   ⚠ 两个读数都取自**服务器自己的时钟**（本机与服务器的时钟偏移不进判据）。
#   升级成功但 web 未重启 ⇒ 打印「升级成功但 web 未重启，活体注册表仍是旧的，
#   请执行 docker compose restart web」并 **exit 10**（第 4 步内的自证）。
# 配套的三条改动（都为了「跑完没做完」不再静默）：
#   · 第 3 步的 SSH 轮询不再把「通道断了」当成「升级还在跑」：通道异常计数并打印；
#     轮询超时前**最后确认一次** —— 标记文件已在（升级其实跑完了）就继续走第 4 步，
#     而不是像以前那样丢掉后半个流程；
#   · 第 4 步重启命令的 SSH 失败**不再让脚本静默退出**：改为警告 + 交给自证判定
#     （有没有真的重启只由 StartedAt 说话 —— 命令通道抖动不该造成假红/假绿）；
#   · 所有 ssh / rsync 调用统一加 ConnectTimeout + ServerAlive*（链路挂死时会无限等）。
# 排障入口：bash scripts/deploy_myedu.sh --verify —— **只跑自证、不做任何部署**
#   （替代「手工读 /tmp/upg.exit 猜状态」）。
# 退出码：0 成功 ｜ 7 升级等待超时（未能确认）｜ 8 重启后未就绪 ｜ 9 总账未过
#         ｜ **10 升级与重启未配对 / 无法自证**（含 --verify 判红）
set -e
# 2026-10-04：改成可覆盖。原因：本脚本头注释写明它是给**马来西亚 203.0.113.10** 写的，
#   但 `prod-host` 这个别名在换机后被改指到 203.0.113.11 ⇒ 想给 187 部署就无路可走。
#   现在：`REMOTE=prod-a bash scripts/deploy_myedu.sh` 即可部署到旧机；默认仍是现役 prod-host。
REMOTE="${REMOTE:-prod-host}"
DIR=/opt/edu-app
# 2026-09-29：SSH 传输加固（今天事故的入口就是"SSH 断了"）
#   本机出口有代理干扰，ssh 会**断**也会**挂**；默认的 ssh 在链路挂死时会无限等下去
#   （脚本既不报错也不退出 = 最坏的那种失败：人以为它还在干活）。
#   · ConnectTimeout=15   连不上 15s 内报错，不挂死；
#   · ServerAliveInterval / ServerAliveCountMax   链路死了约 45s 内被判死。
#   全部 ssh / rsync 调用统一用这两个变量，避免"只有新代码加了超时"。
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
RSYNC_SSH="ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=3"
# ---------------------------------------------------------------------------
# 升级 → 重启 的**配对自证**（2026-09-29）。只读、幂等、可单独调用。
#   返回 0 = 绿（两条判据都成立）｜非 0 = 红（原因已打印，VERIFY_REASON 给调用方复用）
# ---------------------------------------------------------------------------
VERIFY_REASON=""
verify_web_restarted() {
  local probe status UPG_RC DONE_NS DONE_ISO SISO SNS
  VERIFY_REASON=""
  # 一次 ssh 取齐 4 个读数；全部在**服务器上**读（时钟同源、docker 同源）
  probe=$(ssh "${SSH_OPTS[@]}" "$REMOTE" 'cd /opt/edu-app && bash -s' <<'EOS'
if [ ! -f /tmp/upg.exit ] || [ ! -f /tmp/upg.done ]; then echo "PROBE=NO_MARKERS"; exit 0; fi
read -r DONE_NS DONE_ISO < /tmp/upg.done || true
echo "UPG_RC=$(cat /tmp/upg.exit)"
echo "UPG_DONE_NS=${DONE_NS:-}"
echo "UPG_DONE_ISO=${DONE_ISO:-}"
CID=$(docker compose ps -q web 2>/dev/null | head -1)
if [ -z "$CID" ]; then echo "PROBE=NO_WEB_CONTAINER"; exit 0; fi
SISO=$(docker inspect -f '{{.State.StartedAt}}' "$CID" 2>/dev/null || true)
SNS=$(date -u -d "$SISO" +%s%N 2>/dev/null || true)
echo "WEB_STARTED_ISO=$SISO"
echo "WEB_STARTED_NS=$SNS"
echo "PROBE=OK"
EOS
) || probe="PROBE=SSH_FAIL"
  status=$(printf '%s\n' "$probe" | sed -n 's/^PROBE=//p')
  UPG_RC=$(printf '%s\n' "$probe" | sed -n 's/^UPG_RC=//p')
  DONE_NS=$(printf '%s\n' "$probe" | sed -n 's/^UPG_DONE_NS=//p')
  DONE_ISO=$(printf '%s\n' "$probe" | sed -n 's/^UPG_DONE_ISO=//p')
  SISO=$(printf '%s\n' "$probe" | sed -n 's/^WEB_STARTED_ISO=//p')
  SNS=$(printf '%s\n' "$probe" | sed -n 's/^WEB_STARTED_NS=//p')
  echo "  [自证] 升级容器退出码（远端 /tmp/upg.exit）：${UPG_RC:-<未读到>}"
  echo "  [自证] 升级完成时刻（远端 /tmp/upg.done）  ：${DONE_ISO:-<未读到>}  epoch_ns=${DONE_NS:-?}"
  echo "  [自证] web 容器 StartedAt（docker inspect）：${SISO:-<未读到>}  epoch_ns=${SNS:-?}"
  case "$status" in
    OK) : ;;
    NO_MARKERS)
      echo "  ✗ 远端没有 /tmp/upg.exit + /tmp/upg.done —— **无法自证**（本轮升级的标记不存在，或刚被清掉）。"
      echo "    ⇒ 不许当绿：先看 /tmp/upg.log 确认升级到底跑过没有。"
      VERIFY_REASON=UNPROVEN; return 1 ;;
    NO_WEB_CONTAINER)
      echo "  ✗ 远端取不到 web 容器（docker compose ps -q web 为空）—— **无法自证**。"
      VERIFY_REASON=UNPROVEN; return 1 ;;
    *)
      echo "  ✗ 远端自证探针失败（SSH 通道异常 / docker 不可用）—— **无法自证**，本读数无效（不是绿）。"
      VERIFY_REASON=UNPROVEN; return 1 ;;
  esac
  if [ "$UPG_RC" != "0" ]; then
    echo "  ✗ 升级容器退出码 ${UPG_RC:-<未读到>} ≠ 0 —— 升级本身没成功（与「重启没跑」是两回事）。"
    VERIFY_REASON=UPGRADE_FAILED; return 1
  fi
  case "$DONE_NS" in ''|*[!0-9]*)
    echo "  ✗ 升级完成时刻读数不可用（${DONE_NS}）—— **无法自证**。"
    VERIFY_REASON=UNPROVEN; return 1 ;;
  esac
  case "$SNS" in ''|*[!0-9]*)
    echo "  ✗ web 容器 StartedAt 不可读/不可解析（原文：${SISO:-空}）—— **无法自证**。"
    VERIFY_REASON=UNPROVEN; return 1 ;;
  esac
  if [ "$SNS" -le "$DONE_NS" ]; then
    echo "  ✗ StartedAt（${SISO}）**不晚于**升级完成时刻（${DONE_ISO}）⇒ 活体注册表仍是旧的。"
    VERIFY_REASON=NOT_RESTARTED; return 1
  fi
  echo "  ✓ 自证成立：web 在升级完成之后启动过（StartedAt ${SISO} > 升级完成 ${DONE_ISO}）。"
  return 0
}

# --verify：只跑自证（排障用；不 rsync / 不升级 / 不重启）
if [ "${1:-}" = "--verify" ]; then
  echo "== 自证模式（--verify）：只核对「最近一次升级之后 web 真的重启过」，不做任何部署 =="
  if verify_web_restarted; then
    echo "自证通过（升级与重启已配对）。"
    exit 0
  fi
  echo
  if [ "$VERIFY_REASON" = "NOT_RESTARTED" ]; then
    echo "⛔ 升级成功但 web 未重启，活体注册表仍是旧的，请执行 docker compose restart web"
    echo '   （本机：ssh $REMOTE "cd $DIR && docker compose restart web"）'
  else
    echo "⛔ 未通过自证（原因见上）—— 不要在未复核的情况下宣布部署成功。"
  fi
  exit 10
fi

# 未知的 --参数 一律拒绝：**绝不能**把参数当成模块名去跑一次真部署
# （先例：探针/人手写错 flag 时，`MODULES=--verify2` 会直接进 rsync + -u 全流程）
case "${1:-}" in
  --*)
    echo "未知参数：$1（本脚本目前只支持 --verify）—— 拒绝执行，避免把参数当模块名去部署。" >&2
    exit 2 ;;
esac

# 2026-10-08：ACTION 可覆盖。理由：本脚本从头到尾写死 -u，而 -u 对**尚未安装**的模块
#   **什么也不做**（Odoo 只升级 state='installed' 的模块）⇒ 新模块（如 edu_tg_assist）首装
#   会被静默跳过：rsync 到了、文件是新的、库和活体注册表里都没有 —— 又一次「部署成功但没变化」。
#   首装用法：ACTION=-i bash scripts/deploy_myedu.sh edu_tg_assist
#   之后照常：bash scripts/deploy_myedu.sh edu_tg_assist
#   ⚠ 只有**首次安装新模块**才用 -i；已装模块必须 -u（-i 对已装模块不重载 data/view）。
ACTION=${ACTION:--u}
case "$ACTION" in
  -u|-i) ;;
  *) echo "ACTION 只接受 -u 或 -i（收到：${ACTION}）—— 拒绝执行。" >&2; exit 2 ;;
esac
MODULES=${1:-edu_life,edu_schedule,edu_apply,edu_portal,edu_brand,edu_tg_bind,edu_tg_gate,edu_assess}
# 2026-10-14：把 rsync 清单提成变量 + 加**硬守卫**。当天真实事故：`deploy_myedu.sh edu_admit_invite`
#   跑完「部署通过」（升级无失败特征 / 冒烟全绿 / 活体注册表 117/117），但生产上
#   `/opt/edu-app/custom_addons/edu_admit_invite` **根本不存在**、`application_id` 列 0、视图 0 ——
#   因为模块名不在下面那行 rsync 清单里，`-u` 又对未安装模块什么也不做，于是**静默什么都没发生**。
#   这就是脚本自己在 :159 记过的那类「部署成功但没变化」；这次把它变成**跑之前就拒绝**：
#   只要 MODULES 里有一个模块不在同步清单里，直接 exit 2，不再假装成功。
#   ⚠ 另外两条硬约束（与 edu_nav 同源，判据见 :181-190 convert.py:242 `_test_xml_id`）：
#     ① **新模块首次必须 `ACTION=-i`**（`-u` 对 state!='installed' 的模块什么都不做）；
#     ② `edu_admit_invite` 的视图 `ref` 了 `edu_apply.view_edu_application_form` ⇒
#        **绝不能与 edu_apply 放进同一个 -u 批次**（那一刻 edu_apply 是 'to upgrade'，断言会失败）。
SYNC_MODULES='edu_life edu_schedule edu_apply edu_portal edu_brand edu_quiz edu_public edu_zh edu_tg_bind edu_assess edu_nav edu_tg_assist edu_tg_gate edu_admit_invite'
for _m in $(echo "$MODULES" | tr ',' ' '); do
  case " $SYNC_MODULES " in
    *" $_m "*) ;;
    *) echo "⛔ 模块 $_m 不在 rsync 同步清单（SYNC_MODULES）里 —— 它会「部署成功但生产上根本没有文件」。请先把它加进清单。" >&2; exit 2 ;;
  esac
  [ -d "custom_addons/$_m" ] || { echo "⛔ 本机没有 custom_addons/$_m 目录 —— 模块名写错了？" >&2; exit 2; }
done
UPGRADE_TIMEOUT=${UPGRADE_TIMEOUT:-1800}
READY_TIMEOUT=${READY_TIMEOUT:-180}

echo "== 1/6 rsync 模块 + 门禁脚本 =="
cd custom_addons
# 2026-09-14：补上 edu_zh 与 edu_public —— 原先漏同步（生产上 `ls custom_addons` 里根本没有 edu_zh 目录），
# 导致 14 条菜单改名（t117）与术语覆盖无法上线；edu_zh 是**新模块**，远端首次要 `-i`（不是 -u）。
# 2026-09-29：补上 edu_nav —— 同理漏同步 ⇒ data/menu_consolidation_data.xml 的任何改动
#   **永远上不了生产**（菜单收口这类工作是「静默失效」：本地改了、生产没变、谁都不报错）。
#   ⚠ edu_nav **不能与别的模块放进同一个 -u 列表，必须单独跑一趟（见第 3 步的第二趟）**。
#     根因已从「实测现象」追到**源码级判据**（2026-10-02 读 odoo/tools/convert.py:242 `_test_xml_id`）：
#       if module != self.module:
#           modcnt = env['ir.module.module'].search_count(
#               [('name','=',module), ('state','=','installed')])   # ← 只认 installed
#           assert modcnt == 1, 'The ID "%s" refers to an uninstalled module'
#     ⇒ **被引用模块必须恰好是 `state='installed'`**；`to upgrade` 不算！
#       而同一个 -u 列表里的模块全都会先被置成 `to upgrade` ⇒ 只要 edu_nav 的数据引用了
#       任一**同批升级模块**的 xmlid，就**必然断言失败**（与 forcecreate 无关，断言在写入之前）。
#       实测：`-u edu_portal,edu_nav` → 崩在 data:2666 的 edu_portal.menu_edu_invite_code_root
#       （edu_portal 那一刻是 to upgrade，不是 installed）。
#     ① **已修**（2026-10-02）：数据文件曾引用 5 个**已卸载**模块（account_payment /
#        website_slides / website_slides_forum / hr_skills_slides / website_livechat）共 **23 条**，
#        现已由生成器新增的 uninstalled_modules() 过滤掉（353→330 条，常量与库内参数同步为 330）。
#        反向自证：塞回 1 条 ⇒ 升级立刻 255；删掉 ⇒ 0。
#     ② F1（根菜单被重新点亮）**本轮未能复现**：本地先 `-u edu_portal` 再查，542/543/576/606
#        四棵根菜单**仍是 active=f**（诚实记：这是对 2026-09-29 那份预测的反例，不再当已知事实用）；
#        但「单独跑一趟」仍然是对的做法 —— 它让 edu_nav 成为最后写者，且规避上面那条硬断言。
rsync -az --exclude='__pycache__' -e "$RSYNC_SSH" \
  $SYNC_MODULES "$REMOTE:$DIR/custom_addons/"
cd ..
# 活体注册表门禁是部署闭环里的一步（不是可选附件），脚本本身也要上远端
# 2026-09-24：探活脚本一并同步（宿主 systemd timer 每 5 分钟跑，失败推 Telegram；
# 见 docs/deploy-malaysia.md「站点探活与告警」）
rsync -az -e "$RSYNC_SSH" scripts/check_live_registry.py \
  scripts/health_check_alert.py "$REMOTE:$DIR/scripts/"

echo "== 2/6 权限修复（容器内 odoo 用户需可读写数据文件）=="
# 2026-09-14：容器内 odoo 用户读不到权限不对的文件（静默表现为"模块没变化"）。
# 2026-10-01：原先是**手写的 chmod 列表**，必须与上面 rsync 列表逐字对齐 —— 一旦漏写、或
#   rsync 列表新增模块而这里没同步加，就会以「PermissionError: 读不到 xxx.py」炸掉升级。
#   当天真实事故：重建新服务器时 rsync 从 macOS 带过来 12 个 600 的文件，
#   `-u all` 在 Loading module edu_brand 处 exit 255（CRITICAL Couldn't load module edu_brand）。
#   改为对整个同步树兜底 a+rX —— rsync 列表新增模块时**不再需要同步改这里**，
#   消灭了「两份列表必须一致」这个只能靠人记住的不变量。
ssh "${SSH_OPTS[@]}" "$REMOTE" "chmod -R a+rX $DIR/custom_addons $DIR/openeducat_erp $DIR/scripts"

echo "== 3/6 升级（独立的一次性容器，后台跑；web 不停机）=="
ssh "${SSH_OPTS[@]}" "$REMOTE" "MODULES=$MODULES ACTION=$ACTION bash -s" <<'EOS'
set -e
cd /opt/edu-app
rm -f /tmp/upg.log /tmp/upg.exit /tmp/upg.done /tmp/upg_run.sh
cat > /tmp/upg_run.sh <<EOF2
docker compose run --rm --name deploy-upg web odoo -c /etc/odoo/odoo.conf -d edu19 $ACTION $MODULES \
  --db_host=db -r odoo -w odoo --stop-after-init --http-port=8099 > /tmp/upg.log 2>&1
RC=\$?
# ---- 第二趟：edu_nav 必须**单独一趟**（理由见脚本第 1 步的长注释）----
#   同一个 -u 列表里它的数据会引用到「to upgrade」的模块 xmlid，而 Odoo 只认「installed」
#   ⇒ 硬断言 255。单独跑时上一趟已把依赖模块全部落回 installed，断言才成立。
#   失败不让第一趟的成功被吞掉：记录合并退出码，交由第 4 步的失败特征扫描如实报红。
if [ \$RC -eq 0 ]; then
  echo '---- 第二趟：edu_nav（单独）----' >> /tmp/upg.log
  docker compose run --rm --name deploy-upg-nav web odoo -c /etc/odoo/odoo.conf -d edu19 -u edu_nav \
    --db_host=db -r odoo -w odoo --stop-after-init --http-port=8099 >> /tmp/upg.log 2>&1
  RC=\$?
fi
echo \$RC > /tmp/upg.exit
# 2026-09-29：升级完成时刻（**服务器自己的时钟**：纳秒 + 人类可读），供第 4 步自证比对。
#   写在 exit 之后 ⇒ /tmp/upg.done 存在就代表升级容器已经结束、退出码已落盘。
echo "\$(date -u +%s%N) \$(date -u +%Y-%m-%dT%H:%M:%SZ)" > /tmp/upg.done
EOF2
nohup bash /tmp/upg_run.sh >/dev/null 2>&1 &
echo "升级容器已后台启动（模块 ${MODULES}），web 继续对外服务"
EOS
# 2026-09-29：轮询改成「等两个标记 + 把 SSH 通道异常与升级未完成区分开」。
#   旧写法 `while ! ssh ... test -f /tmp/upg.exit` 有两个坑：
#     ① 通道断了（255）时 `! ssh` 为真 ⇒ 与「升级还在跑」无法区分，只能干等到超时；
#     ② 超时那一刻**直接 exit 7** —— 哪怕升级其实早在远端跑完了，第 4 步重启也不会再跑
#        （今天两次事故正是这个形态：库升了、文件新了、活体进程还是旧的）。
WAITED=0
POLL_ERR=0
while :; do
  POLL=$(ssh "${SSH_OPTS[@]}" "$REMOTE" 'if [ -f /tmp/upg.exit ] && [ -f /tmp/upg.done ]; then echo YES; else echo NO; fi' 2>/dev/null) || POLL=""
  if [ "$POLL" = "YES" ]; then
    break
  fi
  if [ -z "$POLL" ]; then
    POLL_ERR=$((POLL_ERR + 1))
    if [ $((POLL_ERR % 6)) -eq 1 ]; then
      echo "  …$WAITED 秒：SSH 轮询通道异常第 $POLL_ERR 次（升级容器仍在远端后台跑，继续等）"
    fi
  fi
  if [ "$WAITED" -ge "$UPGRADE_TIMEOUT" ]; then
    # 超时 ≠ 升级没跑完：通道断了但升级其实已完成，是今天的常态 ⇒ 先做最后一次确认
    if ssh "${SSH_OPTS[@]}" "$REMOTE" 'test -f /tmp/upg.exit && test -f /tmp/upg.done' 2>/dev/null; then
      echo "  …已等 $UPGRADE_TIMEOUT 秒，但检测到升级其实已结束（/tmp/upg.exit + /tmp/upg.done 都在）"
      echo "    ⇒ 不在这里退出，继续走第 4 步（重启 web）+ 自证（这才是「配对」的关键那一半）。"
      break
    fi
    echo "⚠ 升级容器已等 $UPGRADE_TIMEOUT 秒仍未结束（SSH 通道异常 $POLL_ERR 次）—— 硬失败，日志尾部："
    ssh "${SSH_OPTS[@]}" "$REMOTE" "tail -20 /tmp/upg.log" || true
    echo "  ⚠ 现在**无法确认**升级是否已完成；若稍后确认已完成，请补上那一半并复核："
    echo "     ssh $REMOTE 'cd $DIR && docker compose restart web'   # 不重启=活体注册表仍是旧的"
    echo "     bash scripts/deploy_myedu.sh --verify                # 复核升级与重启是否配对"
    exit 7
  fi
  sleep 5
  WAITED=$((WAITED + 5))
done
# 读退出码：SSH 抖动不该在这里静默退出（也不该伪造一个读数）—— 读数失败就写明失败，
# 真正的判据在第 4 步自证（它自己会重读一次，并且区分「读不到」与「非 0」）。
UPG_RC=$(ssh "${SSH_OPTS[@]}" "$REMOTE" "cat /tmp/upg.exit" 2>/dev/null) || UPG_RC="<读取失败：SSH 通道异常>"
echo "升级容器退出码：${UPG_RC}（等待 $WAITED 秒）"
UPG_FAIL=0
# 升级阶段的失败特征（口径抄自 safe_upgrade.sh）：退出码 + 成功标记 + 失败特征，三条都要过
if ! ssh "${SSH_OPTS[@]}" "$REMOTE" 'bash -s' <<'EOS'
LOG=/tmp/upg.log
RC=$(cat /tmp/upg.exit)
[ "$RC" = "0" ] || { echo "✗ 升级容器退出码 $RC"; exit 1; }
grep -qE 'Modules loaded' "$LOG" || { echo "✗ 日志里没有 'Modules loaded' —— 装载未走完"; exit 1; }
if grep -qE 'Traceback \(most recent call last\)|CRITICAL|manifest not found|not installable, skipped|inconsistent states' "$LOG"; then
  echo "✗ 日志里出现失败特征："
  grep -nE 'Traceback \(most recent call last\)|CRITICAL|manifest not found|not installable, skipped|inconsistent states' "$LOG" | head -10
  exit 1
fi
echo "升级日志：无失败特征；ERROR 行 $(grep -c ERROR "$LOG" || true) 条（下列前 5 条供人判读，本脚本"
echo "  不拿它们当失败判据 —— 注册表有没有真的进活体进程，由第 6 步门禁判定）："
grep -nE 'ERROR' "$LOG" | head -5 || true
exit 0
EOS
then
  echo "⚠ 升级阶段有失败特征 —— **不在这里退出**：不重启=活体注册表是旧的（本次事故就是这么来的），"
  echo "  所以下面照常重启 + 探活 + 跑门禁，最后由总账决定成败。"
  UPG_FAIL=1
fi

echo "== 4/6 重启 web（**必须**：注册表重载不会 import 新文件；约 15-20s）=="
# 2026-09-29：重启命令的 SSH 失败**不再让脚本静默退出**（旧写法在 `set -e` 下会当场退出，
#   于是第 5/6 步与自证全都不跑 —— 那正是两次事故的落地形态）。但这里也**不判成败**：
#   重启有没有真的发生，只由紧跟着的自证（StartedAt vs 升级完成时刻）说话 ——
#   命令通道抖动不该造成假红（远端已重启但通道先断），也不该造成假绿（命令返回 0 但没重启）。
if ssh "${SSH_OPTS[@]}" "$REMOTE" "cd $DIR && docker compose restart web >/dev/null 2>&1 && echo 'web 已重启'"; then
  :
else
  echo "⚠ 重启命令的 SSH 调用失败/中断 —— 不在这里下结论，交给下一步自证（以远端 StartedAt 为准）。"
fi
echo "-- 重启自证（升级 → 重启必须配对；不通过即硬失败 exit 10）--"
if ! verify_web_restarted; then
  echo
  if [ "$VERIFY_REASON" = "NOT_RESTARTED" ]; then
    echo "⛔ 升级成功但 web 未重启，活体注册表仍是旧的，请执行 docker compose restart web"
    echo "   （本机：ssh $REMOTE 'cd $DIR && docker compose restart web'）"
    echo "   重启后复核：bash scripts/deploy_myedu.sh --verify"
  else
    echo "⛔ 部署未通过「升级→重启配对」自证（原因见上；VERIFY_REASON=${VERIFY_REASON}）——"
    echo "   不要在未复核的情况下宣布部署成功。"
  fi
  exit 10
fi

echo "== 5/6 就绪探活（有界轮询 /web/login，等到 200|302；超时硬失败）=="
READY=0
CODE=000
for i in $(seq 1 $((READY_TIMEOUT / 3))); do
  CODE=$(ssh "${SSH_OPTS[@]}" "$REMOTE" "curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8069/web/login" 2>/dev/null || echo 000)
  case "$CODE" in
    200|302) READY=1; echo "就绪：约 $((i * 3)) 秒后 /web/login → $CODE"; break ;;
  esac
  sleep 3
done
if [ "$READY" != "1" ]; then
  echo "⚠ 重启后 $READY_TIMEOUT 秒内 /web/login 没到 200/302（最后读数 ${CODE}）—— 硬失败，现场如下："
  ssh "${SSH_OPTS[@]}" "$REMOTE" "cd $DIR && docker compose ps web; docker compose logs --tail=20 web" || true
  exit 8
fi

echo "== 6/6 冒烟 + 活体注册表门禁（**都在远端执行** —— 测的是生产站，不是本机克隆）=="
# 2026-09-14 修：原冒烟 curl 的是本机 127.0.0.1:8069（= 本地克隆），**从来没有测过生产** ——
# 生产缺 study.py、/my/study 静默 404 就是这么漏掉的。现改为 ssh 到远端跑同一组断言。
SMOKE_RC=0
# 2026-10-01（换机事故）：本段原先只冒烟**匿名**路由，而匿名门户页返回 303（跳登录），
#   于是「登录后全站 404」这种致命状态可以**一路全绿**。当晚真实发生：生产 config 缺
#   db_name ⇒ 匿名 / 200（看着完全正常），登录后 /my/home、/my/study、/student/timetable 全 404。
#   故新增强制断言（不需要口令就能红）：生产 config 必须有 db_name；
#   并在提供了 EDU_CHECK_LOGIN/PASSWORD 时**再验一遍登录态路由**。
if [ -n "${EDU_CHECK_LOGIN:-}" ] && [ -n "${EDU_CHECK_PASSWORD:-}" ]; then AUTH_VERIFIED=1; else AUTH_VERIFIED=0; fi
# ⚠ 2026-10-04 修：这一段 heredoc 里用了 DIR 这个变量，但它只在**本地**第 56 行定义过、从没传进来 ⇒
#   断言 A 实际查的是 "/config/odoo.conf"（不存在）⇒ grep 失败 ⇒ **永远报「缺 db_name」**。
#   而这条断言正是 2026-10-01 换机事故（匿名全绿、登录后全站 404）之后加的守卫 ——
#   守卫本身坏了 = 那个灾难再来一次也不会有人知道。故把 DIR 一并传进去，并把两种失败分开报。
if ssh "${SSH_OPTS[@]}" "$REMOTE" "DIR='${DIR:-}' EDU_CHECK_LOGIN='${EDU_CHECK_LOGIN:-}' EDU_CHECK_PASSWORD='${EDU_CHECK_PASSWORD:-}' bash -s" <<'EOS'
FAIL=0
# ---- 断言 A：生产配置必须有 db_name（换机事故的根因守卫，无需口令即可变红）----
CONF="${DIR:-/opt/edu-app}/config/odoo.conf"
if [ ! -f "$CONF" ]; then
  # 分两种情况报：**文件都找不到** 与 **文件在但缺 db_name** 是两回事，
  # 混为一谈会把人指向错误的方向（本断言 2026-10-03 就因此空转了一整天）。
  echo "  ⛔ 找不到配置文件：${CONF}（DIR='${DIR:-}'）—— 检查 deploy 脚本传参，别急着改 odoo.conf。"
  FAIL=1
elif grep -qE "^[[:space:]]*db_name[[:space:]]*=" "$CONF" 2>/dev/null; then
  echo "db_name 已配置（${CONF}）：$(grep -E "^[[:space:]]*db_name" "$CONF" | tail -1)"
else
  echo "  ⛔ $CONF 缺 db_name —— list_db=False 且无默认库时，匿名页正常但**登录后全站 404**。"
  echo "     修法：加 db_name = edu19 后 docker compose restart web（见 docs/code-map.md §2）。"
  FAIL=1
fi
echo "-- 公开页：期望 200（/web/login 允 302：生产会跳到带 db 参数的登录页）--"
for u in / /programs /apply /contactus; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 http://127.0.0.1:8069$u)
  echo "$u $code"
  [ "$code" = "200" ] || { echo "  ⚠ 期望 200"; FAIL=1; }
done
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 http://127.0.0.1:8069/web/login)
echo "/web/login $code"
case "$code" in 200|302) ;; *) echo "  ⚠ 期望 200 或 302"; FAIL=1 ;; esac
echo "-- 门户页：期望 303/200；404 = 路由文件没上 --"
for u in /my/home /my/study /my/apps /subject/enroll /student/timetable; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 http://127.0.0.1:8069$u)
  echo "$u $code"
  case "$code" in
    200|303) ;;
    404) echo "  ⚠ 404 = 路由不存在（先查 rsync 是否漏了文件，例如 edu_portal/controllers/study.py）"; FAIL=1 ;;
    *) echo "  ⚠ 非预期状态码"; FAIL=1 ;;
  esac
done
# ---- 断言 B：登录态路由（匿名 303 会掩盖登录后 404，必须带会话再验一遍）----
AUTH_NOTE="未验证登录态（未提供 EDU_CHECK_LOGIN/EDU_CHECK_PASSWORD）"
if [ -n "$EDU_CHECK_LOGIN" ] && [ -n "$EDU_CHECK_PASSWORD" ]; then
  JAR=$(mktemp)
  AUTH=$(curl -sS --max-time 20 -c "$JAR" -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"login\":\"$EDU_CHECK_LOGIN\",\"password\":\"$EDU_CHECK_PASSWORD\"}}" \
    http://127.0.0.1:8069/web/session/authenticate)
  case "$AUTH" in
    *'"uid"'*) echo "-- 登录态：authenticate 成功 --" ;;
    *) echo "  ⛔ authenticate 失败：$(printf %s "$AUTH" | head -c 160)"; FAIL=1 ;;
  esac
  for u in /my/home /my/study /student/timetable; do
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 -b "$JAR" "http://127.0.0.1:8069$u")
    echo "  [登录态] $u $code"
    [ "$code" = "200" ] || { echo "    ⛔ 登录后应为 200；404 = 落进 nodb 路由表，查 db_name"; FAIL=1; }
  done
  rm -f "$JAR"
  AUTH_NOTE="登录态已验证"
else
  echo "  ⚠ 未提供 EDU_CHECK_LOGIN/EDU_CHECK_PASSWORD ⇒ **登录态路由未验证**（匿名 303 会掩盖登录后 404）"
fi
exit $FAIL
EOS
then
  if [ "$AUTH_VERIFIED" = "1" ]; then
    echo "冒烟全部通过（含 db_name 断言 + 登录态路由）。"
  else
    echo "匿名冒烟 + db_name 断言通过。"
    echo "⚠ 但**登录态未验证** —— 本批换机事故正是「匿名全绿、登录后全站 404」。"
    echo "  若要验证：EDU_CHECK_LOGIN=<账号> EDU_CHECK_PASSWORD=<口令> 重跑本脚本。"
  fi
else
  echo "⚠ 冒烟有异常项（见上）。"
  SMOKE_RC=9
fi

echo "-- 活体注册表门禁：库（ir_model_data）里有、跑着的 web 进程认不认识 --"
GATE_RC=0
if [ -n "${EDU_CHECK_LOGIN:-}" ]; then
  ssh "${SSH_OPTS[@]}" "$REMOTE" "cd $DIR && EDU_CHECK_LOGIN='$EDU_CHECK_LOGIN' EDU_CHECK_PASSWORD='${EDU_CHECK_PASSWORD:-}' python3 scripts/check_live_registry.py" || GATE_RC=$?
else
  echo "  （没给 EDU_CHECK_LOGIN：门禁只做模型级判定，字段级会在输出里明写未验证）"
  ssh "${SSH_OPTS[@]}" "$REMOTE" "cd $DIR && python3 scripts/check_live_registry.py" || GATE_RC=$?
fi

echo
if [ "$UPG_FAIL" != "0" ] || [ "$SMOKE_RC" != "0" ] || [ "$GATE_RC" != "0" ]; then
  echo "部署未通过（升级=$UPG_FAIL 冒烟=$SMOKE_RC 门禁=${GATE_RC}）—— **不要**宣布部署成功。"
  [ "$GATE_RC" = "0" ] || echo "  门禁非 0：DARK 行见上；若刚重启完仍 DARK，查 rsync 漏文件 / 模块是否真装。"
  exit 9
fi
echo "部署通过：升级无失败特征 → web 已重启并就绪 → 冒烟全绿 → 活体注册表门禁全绿（无 DARK）。"
echo "提醒：①首页等公开模板改动需在远端重跑 setup 移植；②本次含重启，新增 .py / 新字段已进活体注册表。"
