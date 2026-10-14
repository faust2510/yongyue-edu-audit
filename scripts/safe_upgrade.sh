#!/usr/bin/env bash
# ============================================================================
# 同容器模块升级：串行锁 + DB 参数 + 挂载新鲜度自检 + 失败特征硬失败
#
# 为什么需要这个脚本（2026-09-12 三起事故）：
#   1) docker compose exec 绕过 ENTRYPOINT，官方镜像的 entrypoint.sh 才负责追加
#      --db_host/--db_port/--db_user/--db_password；本仓 config/odoo.conf 无 db_host
#      → 不传参会去连容器内 unix socket 并失败。
#   2) 主 odoo 服务占用 8069，--stop-after-init 仍会先 bind → 必须 --no-http。
#   3) -u 只对已安装模块生效；新模块首装要 -i。**本脚本默认 -u**（2026-09-12 起）。
#      ⚠ 实测更正：-i 对**已装**模块**不重载 data/view 文件**（新字段会建、新视图不会进库），
#      会制造「升级成功但页面没变」的假象 —— 验证视图/模板必须用 -u。
#   4) **挂载失步（静默灾难）**：Docker Desktop 偶尔让容器读到旧内容，表现为
#      "manifest not found / not installable, skipped / inconsistent states"，
#      **而退出码仍是 0**，极易误判成功。本脚本在升级前对拍宿主/容器 md5，
#      发现失步就强制重建容器；升级后再扫输出里的失败特征并硬失败。
#
# 用法：
#   bash scripts/safe_upgrade.sh edu_portal,edu_brand     # 默认 -u（升级已装模块，会重载 data/view）
#   bash scripts/safe_upgrade.sh -i edu_zh                # 仅限**首次安装新模块**
#   SKIP_MOUNT_CHECK=1 bash scripts/safe_upgrade.sh ...   # 跳过挂载自检（不推荐）
#
# 退出码：0 成功；3 等待锁超时；4 挂载失步未修复；5 输出里有失败特征；6 = 升级前静态检查拒绝
#   （gate A manifest 跟踪 / gate B 继承视图 / gate C shell 变量 / gate D init() 跨表 / gate E 薄别名被继承
#    —— 任一真 FAIL 即 6；另有「资产新鲜度」**只提示不拒绝**，见下）；
#   其它 = odoo 退出码
# ============================================================================
set -euo pipefail

# ⚠ 默认改为 -u（2026-09-12 实测更正）：**-i 对已装模块不会重载 data/view 文件**！
#   实测：-i edu_portal → 新模型字段建好了，但新建的 views/*.xml 根本没进库（/my/study 仍 404）
#   → 会得到「升级成功但什么都没变」的假象。**验证视图/模板必须用 -u**。
#   只有**首次安装新模块**（如 edu_zh 第一次装）才用 -i。
ACTION="-u"
if [ "${1:-}" = "-u" ] || [ "${1:-}" = "-i" ]; then
  ACTION="$1"
  shift
fi
MODULES="${1:-edu_portal}"
# 额外 odoo 参数透传（2026-09-12 加，i18n-eng 指出）：edu_zh 这类"用 i18n_extra PO
# 覆盖他模块既有译文"的模块，必须带 --i18n-overwrite 才有 overwrite 语义；
# 脚本原先写死了命令行，导致这类升级跑不出效果。
# 用法：UPGRADE_EXTRA_ARGS="--i18n-overwrite" bash scripts/safe_upgrade.sh -u edu_zh
EXTRA_ARGS="${UPGRADE_EXTRA_ARGS:-}"
# 升级锁路径解析（t5 统一口径，**三方同源**）：本脚本 / tests/smoke/authz_endtoend_smoke.py
#   的 preflight / scripts/check_view_xpath.py 的 _lock_path() 必须解析出**同一个路径**：
#   EDU_UPGRADE_LOCK 覆盖 ＞ TMPDIR（未设或为空 ⇒ /tmp）＞ 固定文件名 edu19_upgrade.lock
# ⚠ 历史坑（t5 修）：读取方曾**硬编码** /tmp/edu19_upgrade.lock，而 macOS 的
#   TMPDIR=/var/folders/…/T ⇒ 写的与查的不是同一个文件，该 preflight 在本机**永远看不见锁**
#   （门没接上：升级进行中跑冒烟不会被拦住，会拿到跨升级的"半程读数"）。
# 本处**只统一路径解析**，锁语义一字未动：取锁时机仍是静态检查之后、原子占锁仍是 mkdir、
#   等待上限仍是 WAIT_MAX、超时/挂载/失败特征的退出码（3/4/5/6）不变。
# 规范化基准目录（t5 实测补充）：macOS 的 TMPDIR **自带尾斜杠**（/var/folders/…/T/），
#   直接拼会得到 "…/T//edu19_upgrade.lock"。文件系统上 // 与 / 等价（门其实是通的），
#   但**字符串**与 python 侧（os.path.join 的规范形态）不一致 —— 会让"三方对拍"看着失败。
#   故先去尾斜杠再拼；根 "/" 归一为空串（拼出 "/name" 而非 "//name"，与 os.path.join 一致），
#   空/未设回退 /tmp。
TMP_BASE="${TMPDIR:-/tmp}"
while [ "${TMP_BASE}" != "/" ] && [ "${TMP_BASE%/}" != "${TMP_BASE}" ]; do
  TMP_BASE="${TMP_BASE%/}"
done
if [ "${TMP_BASE}" = "/" ]; then TMP_BASE=""; fi
LOCK="${EDU_UPGRADE_LOCK:-$TMP_BASE/edu19_upgrade.lock}"
# 日志按时间戳落盘并保留最近 10 份（2026-09-12 修）：固定文件名会被下一次升级覆盖，
# 失败现场随之丢失——credit_points 事故的两份失败日志就是这样没的，只能靠成员的一次性记录。
# /tmp/edu19_upgrade.log 保留为指向最新一份的软链（既有引用与"看第一行时间戳"的判据仍可用）。
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="/tmp/edu19_upgrade.${STAMP}.log"
finalize_log() {
  ln -sf "$LOG" /tmp/edu19_upgrade.log 2>/dev/null || cp -f "$LOG" /tmp/edu19_upgrade.log 2>/dev/null || true
  local old
  old="$(ls -1t /tmp/edu19_upgrade.*.log 2>/dev/null | tail -n +11 || true)"
  if [ -n "$old" ]; then echo "$old" | xargs rm -f 2>/dev/null || true; fi
}
WAIT_MAX="${UPGRADE_WAIT_MAX:-2700}"
SLEEP_STEP=15

# 升级前静态检查（2026-09-12 加；同日修正一起顺序类假红）：
# 必须在**取锁之前**跑 —— 检查器会解析同一个锁路径，若放在取锁之后，
# 它看到的是本脚本刚建的锁，判 SKIP-ENV → 拒绝 → 形成「自锁 → 自检 → 自我拒绝」。
# 另外把「因环境被跳过」与「检查失败」分开：前者不拒绝（继续走锁等待），后者才 exit 6。
# 按检查器的**退出码契约**分级处置（2026-09-12 修第二起同型事故）：
#   0=OK 通过 ｜ 1=FAIL 真失败（唯一拒绝升级的情形）｜ 2=ENV 环境未就绪 ｜ 3=INCOMPLETE 有未覆盖/边界漂移
# 教训：接入新检查时**不能"非零即拒"** —— 那会把「边界型未覆盖」「环境未就绪」也当成失败，
# 而门禁恰恰是有意区分这三者的；一刀切会让全队升级被健康检查自己挡死（本日第二次）。
# （原 run_static_check() 函数已在 t97 删除：其分级逻辑迁入下方 gate B 的 case，
#   并改为在**已捕获退出码**的变量上分派 —— 函数内直接调用检查器时，
#   `set -e` 会让 rc=2/3 也表现为"静默中止"。）
# —— 升级前静态检查（2026-09-12 加；2026-09-13 t97 修正互相独立性）——
# t97 blocker 复盘：原先 manifest 块在 run_static_check 之后，且用
#   python3 scripts/check_manifest_tracking.py > log 2>&1
#   mt_rc=$?
# 在 `set -euo pipefail` 下，检查器返回 1 会让**脚本当场以 1 退出**——
# `mt_rc=$?` 是死代码，`exit 6` 分支永不可达。观测与之完全吻合：
# UPGRADE_EXIT=1（应为 6）、manifest 块的消息一条都没打印、LOCK_ABSENT（从未走到取锁）。
# 修法：① 每次调用都用 `|| rc=$?` 显式承接退出码（否则 set -e 立即终止）；
#        ② 两块**互相独立**：先跑（零环境依赖、最便宜的）manifest，再跑 view_xpath；
#           任一 gate 的中止都不得让另一个 gate 永远不可达。
manifest_rc=0
if [ -f scripts/check_manifest_tracking.py ]; then
  python3 scripts/check_manifest_tracking.py > /tmp/edu19_manifest_tracking.log 2>&1 || manifest_rc=$?
fi
viewx_rc=0
if [ -f scripts/check_view_xpath.py ]; then
  python3 scripts/check_view_xpath.py > /tmp/edu19_viewxpath.log 2>&1 || viewx_rc=$?
fi
# gate E（2026-10-03 加）：薄别名被 inherit_id 继承 —— 与上两块**互相独立**，同样用 `|| rc=$?` 承接退出码。
# （⚠ 本块**不是**原来的 gate C —— 那是 t109 的 shell 变量检查，在更下面；命名别撞车。）
# 立它的原因是一次真实事故：把 edu_page 改成薄别名后升级**当场失败并整批回滚**
# （ParseError: 上级视图内找不到元素），因为该模板被 2 个视图用 xpath 扩展，而别名没有扩展点。
# 这个检查必须在**升级之前**跑：炸点在装载期，跑完再发现就已经白跑一轮。
alias_rc=0
if [ -f scripts/check_alias_not_extended.py ]; then
  python3 scripts/check_alias_not_extended.py > /tmp/edu19_alias_not_extended.log 2>&1 || alias_rc=$?
fi

# gate A：manifest 引用集 ⊆ git 跟踪集（t93）。0=通过；1=真失败 → 拒绝；其它=未完成（不拒绝，但显式提示）
if [ -f scripts/check_manifest_tracking.py ]; then
  if [ "$manifest_rc" -eq 0 ]; then
    echo "[safe_upgrade] manifest 跟踪检查通过（scripts/check_manifest_tracking.py）"
  elif [ "$manifest_rc" -eq 1 ]; then
    echo "[safe_upgrade] manifest 跟踪检查未通过（exit 1），详见 /tmp/edu19_manifest_tracking.log" >&2
    tail -20 /tmp/edu19_manifest_tracking.log >&2
    echo "[safe_upgrade] 拒绝升级：manifest 引用了不存在或未入库的文件" >&2
    exit 6
  else
    echo "[safe_upgrade] manifest 跟踪检查未完成（exit ${manifest_rc}）—— 这不是「检查通过」" >&2
  fi
fi

# gate E 分派（2026-10-03）：契约与 gate A 同形 —— 0=通过｜1=真失败 ⇒ 拒绝升级｜其它=未完成（不拒绝，但显式提示）。
if [ -f scripts/check_alias_not_extended.py ]; then
  if [ "$alias_rc" -eq 0 ]; then
    echo "[safe_upgrade] 薄别名检查通过（scripts/check_alias_not_extended.py）"
  elif [ "$alias_rc" -eq 1 ]; then
    echo "[safe_upgrade] 薄别名检查**未通过**：有模板既是薄别名、又被 inherit_id 继承" >&2
    tail -20 /tmp/edu19_alias_not_extended.log >&2
    echo "[safe_upgrade] 拒绝升级：薄别名没有扩展点，它的子视图在装载期必然「找不到元素」并整批回滚" >&2
    exit 6
  else
    echo "[safe_upgrade] 薄别名检查未完成（exit ${alias_rc}）—— 这不是「检查通过」" >&2
  fi
fi

# gate B：视图/路由静态检查（t25 起）。按**退出码契约**分级：0=OK｜1=FAIL(唯一拒绝)｜2=ENV｜3=INCOMPLETE
# t97：改走 viewx_rc 显式分派，不再在函数里直接跑检查器 —— 避免 set -e 把 2/3 也变成"静默中止"。
case "$viewx_rc" in
  0) if [ -f scripts/check_view_xpath.py ]; then
       echo "[safe_upgrade] 静态检查通过（scripts/check_view_xpath.py $(grep -oE "RESULT=[A-Z]+" /tmp/edu19_viewxpath.log | tail -1 || true))"
     fi ;;
  1) echo "[safe_upgrade] 静态检查**失败**，拒绝升级（避免装载期炸库）：" >&2
     tail -20 /tmp/edu19_viewxpath.log >&2
     exit 6 ;;
  2) echo "[safe_upgrade] 静态检查因**环境未就绪**跳过（多为他人持锁）—— 不视为失败，继续按锁等待" >&2
     grep -E "SKIP-ENV|未就绪|锁" /tmp/edu19_viewxpath.log | tail -3 >&2 || true ;;
  3) echo "[safe_upgrade] 静态检查报 INCOMPLETE：**失败项为 0，但存在未覆盖/边界漂移** —— 不拒绝升级，仅提示：" >&2
     grep -E "未覆盖|跳过|RESULT" /tmp/edu19_viewxpath.log | tail -5 >&2 || true ;;
  *) echo "[safe_upgrade] 静态检查退出码 $viewx_rc —— 非 FAIL，按不拒绝处理，请人工留意：" >&2
     tail -10 /tmp/edu19_viewxpath.log >&2 ;;
esac

# gate C（t109）：shell 变量紧邻非 ASCII 静态检查 —— 取锁之前，与其它 gate 同阶段。
shell_rc=0
if [ -f scripts/check_shell_exitcode.py ]; then
  python3 scripts/check_shell_exitcode.py > /tmp/edu19_shell_exitcode.log 2>&1 || shell_rc=$?
fi
if [ -f scripts/check_shell_exitcode.py ]; then
  case "$shell_rc" in
    0) echo "[safe_upgrade] shell 变量静态检查通过（scripts/check_shell_exitcode.py）" ;;
    1) echo "[safe_upgrade] shell 变量静态检查**失败**，拒绝升级：" >&2
       tail -20 /tmp/edu19_shell_exitcode.log >&2
       exit 6 ;;
    *) echo "[safe_upgrade] shell 变量静态检查未完成（exit ${shell_rc}）—— 不是「检查通过」" >&2 ;;
  esac
fi

# ── 资产新鲜度提示（2026-10-03 加）—— **只提示，绝不拒绝** ──────────────────────
# 为什么只提示：静态资产陈旧**不是代码错**，而是「验证前提不成立」。
# 实测（2026-10-03）：改 static/src/css/*.css 后升级，服务端下发的仍是旧资产包
#   （717b303 含目标类名 40 次但不含新规则）；**重启 web 后**哈希变 0867e66 才生效。
# 不提示的后果不是页面坏，而是**人拿旧资产验收新代码**（本仓口径：样本有效性）。
if [ -f scripts/check_asset_freshness.py ]; then
  asset_rc=0
  python3 scripts/check_asset_freshness.py > /tmp/edu19_asset_freshness.log 2>&1 || asset_rc=$?
  if [ "$asset_rc" -eq 1 ]; then
    echo "[safe_upgrade] ⚠ 有静态资产比 web 进程新 —— 本次升级**不会**重建资产包。" >&2
    echo "[safe_upgrade]   要按渲染结果验收 CSS/JS，请先重启 web 再加验；否则可能验的是旧资产。" >&2
    tail -3 /tmp/edu19_asset_freshness.log >&2 || true
  fi
fi

# gate D（2026-09-29）：init() 跨表回填静态检查（tests/smoke/init_cross_table_check.py）
# 为什么接在这里：升级链的第一件事就是 registry 的 init_models() **逐模型**跑 init()，
#   「某模型的 init() 里写别的表」会在升级时炸整站（2026-09-28 生产事故：整个升级
#   退出码 255、Failed to load registry）。原先这条判据只存在于 tests/smoke/，
#   没有任何**执行**路径调用它 —— 规矩只靠自觉。接到重启前自证链 = 让它在每次升级
#   真跑一遍。它离线（不连库、不联网）、快（全仓 74 个模型文件 <1s）、零环境依赖。
# 退出码契约与 gate A/B/C 完全相同：0=OK ｜ 1=FAIL（**唯一拒绝**）｜ 2=ENV（扫不到
#   仓库结构 —— 不拒绝，只提示）。⚠ 不要改成「非零即拒」：那会把 ENV 也当成失败。
initx_rc=0
if [ -f tests/smoke/init_cross_table_check.py ]; then
  python3 tests/smoke/init_cross_table_check.py > /tmp/edu19_init_cross_table.log 2>&1 || initx_rc=$?
fi
if [ -f tests/smoke/init_cross_table_check.py ]; then
  case "$initx_rc" in
    0) echo "[safe_upgrade] init() 跨表回填静态检查通过（tests/smoke/init_cross_table_check.py）" ;;
    1) echo "[safe_upgrade] init() 跨表回填静态检查**失败**，拒绝升级（避免装载期炸整站）：" >&2
       tail -20 /tmp/edu19_init_cross_table.log >&2
       echo "[safe_upgrade] 拒绝升级：有模型的 init() 写了**别的表**（修法见 /tmp/edu19_init_cross_table.log，判据同时给出行号与 SQL）" >&2
       exit 6 ;;
    *) echo "[safe_upgrade] init() 跨表回填静态检查未完成（exit ${initx_rc}）—— 这不是「检查通过」" >&2 ;;
  esac
fi

waited=0
while ! mkdir "$LOCK" 2>/dev/null; do
  if [ "$waited" -ge "$WAIT_MAX" ]; then
    echo "[safe_upgrade] 等待锁超时（${WAIT_MAX}s）：$LOCK 仍被占用" >&2
    echo "[safe_upgrade] 确认没有其他升级在跑后，可执行： rmdir $LOCK" >&2
    exit 3
  fi
  echo "[safe_upgrade] 有其他成员正在升级，等待中…（已等 ${waited}s）"
  sleep "$SLEEP_STEP"
  waited=$((waited + SLEEP_STEP))
done
cleanup() { rmdir "$LOCK" 2>/dev/null || true; }
trap 'finalize_log; cleanup' EXIT INT TERM

host_hash() { if command -v md5 >/dev/null 2>&1; then md5 -q "$1"; else md5sum "$1" | cut -d" " -f1; fi; }
container_hash() { docker compose exec -T web md5sum "$1" 2>/dev/null | cut -d" " -f1; }

check_mounts() {
  local stale=0 checked=0 f h c rel
  while IFS= read -r f; do
    rel="${f#custom_addons/}"
    h="$(host_hash "$f")"
    c="$(container_hash "/mnt/custom-addons/$rel")"
    checked=$((checked + 1))
    if [ "$h" != "$c" ]; then
      stale=$((stale + 1))
      [ "$stale" -le 3 ] && echo "[safe_upgrade] 挂载失步：${f}（宿主 ${h:0:8} vs 容器 ${c:0:8}）" >&2
    fi
  done < <(find custom_addons -type f -mmin -30 ! -path "*__pycache__*" ! -name "*.pyc" 2>/dev/null | head -40)
  echo "$checked $stale"
}

if [ "${SKIP_MOUNT_CHECK:-0}" != "1" ]; then
  read -r CHECKED STALE <<< "$(check_mounts | tail -1)"
  echo "[safe_upgrade] 挂载自检：抽查 ${CHECKED} 个近期改动文件，失步 ${STALE} 个"
  if [ "${STALE:-0}" -gt 0 ]; then
    echo "[safe_upgrade] 检测到挂载失步，强制重建 web 容器…"
    docker compose up -d --force-recreate web >/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      docker compose exec -T web true 2>/dev/null && break
      sleep 3
    done
    read -r CHECKED2 STALE2 <<< "$(check_mounts | tail -1)"
    echo "[safe_upgrade] 重建后复检：抽查 ${CHECKED2} 个，失步 ${STALE2} 个"
    if [ "${STALE2:-0}" -gt 0 ]; then
      echo "[safe_upgrade] 仍失步，放弃升级（避免静默载入旧代码）。" >&2
      echo "[safe_upgrade] 建议：重启 Docker Desktop 后重试，或 docker compose down && docker compose up -d" >&2
      exit 4
    fi
  fi
fi

echo "[safe_upgrade] 已取锁：$ACTION $MODULES"
{
  echo "# safe_upgrade: ACTION=$ACTION MODULES=$MODULES EXTRA_ARGS=${EXTRA_ARGS:-（无）}"
  echo "# 开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "# 失败诊断请附本文件；历史日志保留最近 10 份于 /tmp/edu19_upgrade.*.log"
} > "$LOG"
set +e
docker compose exec -T web odoo \
  --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo \
  --no-http -c /etc/odoo/odoo.conf -d edu19 \
  "$ACTION" "$MODULES" $EXTRA_ARGS --stop-after-init 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
set -e

if [ "$RC" -ne 0 ]; then
  echo "[safe_upgrade] odoo 退出码 ${RC}（日志：${LOG}）" >&2
  exit "$RC"
fi
if grep -qE "Traceback \(most recent call last\)|CRITICAL|manifest not found|not installable, skipped|inconsistent states" "$LOG"; then
  echo "[safe_upgrade] 退出码为 0，但输出中发现失败特征（很可能没真正升级）：" >&2
  grep -nE "Traceback \(most recent call last\)|CRITICAL|manifest not found|not installable, skipped|inconsistent states" "$LOG" | head -10 >&2
  echo "[safe_upgrade] 完整日志：$LOG" >&2
  exit 5
fi
# 升级后重启：清 CodeTranslations 等**进程内缓存**（PO 改动尤其需要），
# 并保证「升级了什么，跑的就是什么」。就绪探活必须带库名——多库环境下
# 不带 ?db= 的请求会一律 404，看起来像站点崩了（2026-09-12 实测踩坑）。
echo "[safe_upgrade] 重启 web 以清进程内缓存…"
docker compose restart web >/dev/null
READY=0
for _ in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 'http://localhost:8069/web/login?db=edu19' || true)
  case "$code" in
    200|302|303) READY=1; break ;;
    *) sleep 3 ;;
  esac
done
if [ "$READY" = "1" ]; then
  echo "[safe_upgrade] 就绪：/web/login?db=edu19 → $code"
else
  echo "[safe_upgrade] 警告：重启后 40 次探活仍未就绪（最后一次 ${code}），请查看 ${LOG} 与 docker compose logs web" >&2
fi
echo "[safe_upgrade] 结束：${MODULES}（无失败特征；完整日志 ${LOG}）"
