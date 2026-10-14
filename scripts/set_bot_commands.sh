#!/usr/bin/env bash
# 发布 Telegram 机器人 @sctrs_bot 的命令菜单（Telegram 里点 "/" 看到的那份列表）。
#
# 为什么要有这个脚本：2026-10-09 发现生产 bot 的菜单里**只有一条**手工在 BotFather 里设的 /zhuce
# —— 全仓（custom_addons + scripts）grep setMyCommands 0 命中，也就是说没有任何代码在维护它；
# 用户在 Telegram 里点开 "/" 只看得到一条，既找不到 /assist，也会以为"这机器人没什么功能"。
#
# 用法：
#   ./set_bot_commands.sh <bot_token>
# 服务器上不想把 token 写进命令行时（值只在远端 shell 里流转，不打印）：
#   cd /opt/edu-app
#   TG_TOKEN=$(docker compose exec -T db psql -U odoo -d edu19 -tAc \
#     "select value from ir_config_parameter where key='edu_tg_bind.token'") \
#     ./set_bot_commands.sh
# 可用 TG_PROXY 走代理（同 register_webhook.sh）。
set -euo pipefail
TOKEN="${1:-${TG_TOKEN:-}}"
[ -n "$TOKEN" ] || { echo "用法: $0 <bot_token>（或设 TG_TOKEN）" >&2; exit 2; }
PX=()
[ -n "${TG_PROXY:-}" ] && PX=(-x "$TG_PROXY")

api() { curl -s "${PX[@]}" -H 'Content-Type: application/json' \
  "https://api.telegram.org/bot$TOKEN/$1" -d "$2"; echo; }

# 私聊菜单：学生两条 + 老师五条 + 行政三条 + 停发一条。描述里的"学生/老师/行政"必须写清，
# 因为这份菜单是**所有人共用**的（学生也看得到老师那几条）。
# 2026-10-12：补 /bind 与 /bindcode —— 身份绑定码上线时漏了这一步，用户在 Telegram 里
# 点 "/" 看不到这两条（后台菜单「绑定码」还在，但老师不知道有这功能）。教训：**新增指令必须同步这里**。
# 2026-10-13：补 /menu（按钮化界面）。排在第一位——不想记指令的人点开 "/" 第一眼就看到它。
PRIVATE_CMDS='menu|所有人：点按钮就行（把按钮菜单叫回来，不用记指令）
start|学生：领取注册邀请码（一人一码）
zhuce|学生：领取注册邀请码（同 /start）
assist|老师/行政：进入班务助手（第一次请发它）
bind|老师：用绑定码一次绑定身份，例如 /bind BIND-XXXXXX
name|老师：登记或修改真名，例如 /name 张三
whoami|老师：查看机器人心里的你是谁
dm|行政：一对一私发，例如 /dm 张三 明天记得交表
bindcode|行政：生成一张身份绑定码，例如 /bindcode 教师 张三
tpl|老师：查看现成文案模板
notify|行政：在群里广播，例如 /notify 学习群 各位同事请注意
stop|老师：停止一对一私发（想恢复再发 /start）'

# 群菜单：群里不需要学生的领码那条。
GROUP_CMDS='notify|行政：把这段话广播到指定短名的群
alias|行政：给这个群起个短名，例如 /alias 学习群
assist|老师：进入班务助手（第一次请发它登记）'

build_payload() { # $1 = scope type: default | all_private_chats | all_group_chats
  SCOPE="$1" python3 -c '
import json, os, sys
cmds = [l.split("|", 1) for l in sys.stdin.read().strip().splitlines() if l.strip()]
payload = {"scope": {"type": os.environ["SCOPE"]},
           "commands": [{"command": c, "description": d} for c, d in cmds]}
print(json.dumps(payload, ensure_ascii=False))
'
}

DEFAULT_PAYLOAD=$(printf '%s\n' "$PRIVATE_CMDS" | build_payload default)
PRIVATE_PAYLOAD=$(printf '%s\n' "$PRIVATE_CMDS" | build_payload all_private_chats)
GROUP_PAYLOAD=$(printf '%s\n' "$GROUP_CMDS" | build_payload all_group_chats)

# 注意：故意**不列 /help** —— /help 不在前门白名单里，仍然走学生领码那条路（见 design §9.3/§9.8）。
api setMyCommands "$DEFAULT_PAYLOAD"
api setMyCommands "$PRIVATE_PAYLOAD"
api setMyCommands "$GROUP_PAYLOAD"

echo "--- 回读核对 ---"
for SC in default all_private_chats all_group_chats; do
  echo "[$SC]"
  api getMyCommands "{\"scope\":{\"type\":\"$SC\"}}"
done
