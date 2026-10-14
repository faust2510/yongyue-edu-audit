#!/bin/bash
# 对**生产**跑 UI 可用性门禁（四轴：横向溢出 / 主操作越界 / 措辞 / 空态出口）
#
# 为什么需要它（2026-10-02）：check_ui_usability.py 的 BASE 原先硬编码 localhost:8069，
#   ⇒ 这条门禁**从来没有在生产上跑过**，而生产才是学生/教务真正看到的界面。
#   同类「只测本地」盲区已经致过一次事故：换机后生产缺 db_name ——
#   匿名页全绿、登录后 /my/home 等全部 404，只有真登录才看得见。
#
# 用法：
#   EDU_PROD_USERS=/path/to/users.json bash scripts/gate_ui_prod.sh [额外参数...]
#   # users.json 形如 {"student": ["登录名","口令"], "backoffice": [...]}
#   # ⚠ 该文件**不要放进仓库**（含口令）；脚本会拒绝读取仓库内的路径。
#
# 退出码：0=门禁通过 ｜ 2=环境/凭据未就绪（**不是通过**）｜ 其它=门禁自身退出码
#
# ⚠ 已知限制（2026-10-02 实测，别再踩）：**不能用 SSH 隧道把 --base-url 指到源站**。
#   试过 `ssh -L 18069:127.0.0.1:8069 prod-host` 再 --base-url http://127.0.0.1:18069：
#   隧道本身很快（curl 直取 / 0.32s），但**浏览器会卡住**（实测 25 分钟无输出）。取证 ——
#   生产页面里硬编码了指向正式域名的**绝对 URL**：
#       https://edu.example.org/logo.png?company=1
#       https://edu.example.org/web/image/website/1/logo/300x300
#   ⇒ Playwright 载入 http://127.0.0.1:18069 之后会去 https://edu.example.org 取这些资源，
#     **绕开隧道回到 Cloudflare**；在网络受限的机器上表现就是每页干等超时。
#   为什么不能用 --host-resolver-rules 把域名映射到隧道：那会走 https，而隧道那头是明文 8069。
#   ⇒ 生产门禁要在**能顺畅访问正式域名**的地方跑（例如装了 playwright 的生产机本身、或网络通畅的
#     跳板机/CI）。本脚本的价值＝给出这个入口与「绝不用错身份」的护栏，不是替你把网络也修好。
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

PY="${EDU_UI_PYTHON:-/opt/homebrew/bin/python3}"
BASE="${EDU_PROD_BASE:-https://edu.example.org}"
DB="${EDU_PROD_DB:-edu19}"
ROLES="${EDU_PROD_ROLES:-student,backoffice}"
USERS="${EDU_PROD_USERS:-}"

fail_env() { echo "SKIP-ENV：$*" >&2; echo "（这不是「通过」—— 没有凭据就没有覆盖）" >&2; exit 2; }

# 凭据必须显式给出：**绝不退回演示账号**。生产没有 stu@local；
# 悄悄换账号会让门禁以错误身份探页并给出看似有效的读数 —— 那比不跑更坏。
[ -n "$USERS" ] || fail_env "未设置 EDU_PROD_USERS —— 拒绝在生产上用演示账号冒充"
[ -f "$USERS" ] || fail_env "凭据文件不存在：$USERS"
ABSPATH="$(cd "$(dirname "$USERS")" && pwd)/$(basename "$USERS")"
case "$ABSPATH" in
  "$(pwd)"/*) fail_env "凭据文件在仓库内（${USERS}）—— 含口令的文件不许入库，请移到仓库外" ;;
esac
[ -x "$PY" ] || fail_env "找不到带 playwright 的解释器：${PY}（可用 EDU_UI_PYTHON 覆盖）"

echo "== 生产 UI 门禁 =="
echo "  源站：$BASE ｜ 库：$DB ｜ 身份：$ROLES"
echo "  凭据：${USERS}（内容不打印）"
echo "  ⚠ 本门禁只做只读 GET 探页；它不会点任何副作用按钮。"

BEFORE=$(ls -1t tests/ui/readings/usability-*.json 2>/dev/null | head -1)
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy "$PY" scripts/check_ui_usability.py --base-url "$BASE" --db "$DB" --users-file "$USERS" --roles "$ROLES" "$@"
RC=$?

# 生产读数单独存档，避免混进本地克隆的 ratchet 基线链
AFTER=$(ls -1t tests/ui/readings/usability-*.json 2>/dev/null | head -1)
if [ -n "$AFTER" ] && [ "$AFTER" != "$BEFORE" ]; then
  TAGGED="${AFTER%.json}-prod.json"
  mv "$AFTER" "$TAGGED" && echo "生产读数已单独存档：$TAGGED"
fi
echo "PROD_GATE_EXIT=$RC"
exit $RC