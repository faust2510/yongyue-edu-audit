#!/usr/bin/env bash
# Telegram webhook 注册脚本（迁移服务器后跑一次即可）
# 用法: ./register_webhook.sh <bot_token> <webhook_secret> <https_base_url>
#   例: ./register_webhook.sh 12345:ABC xxx https://edu.example.com
set -euo pipefail
TOKEN="$1"; SECRET="$2"; BASE="${3%/}"
PX=()
[ -n "${TG_PROXY:-}" ] && PX=(-x "$TG_PROXY")   # 本机调试可借代理

curl -s "${PX[@]}" "https://api.telegram.org/bot$TOKEN/setWebhook" \
  --data-urlencode "url=$BASE/telegram/webhook" \
  --data-urlencode "secret_token=$SECRET" \
  --data-urlencode 'allowed_updates=["message","callback_query"]' \
  -d drop_pending_updates=true
echo
curl -s "${PX[@]}" "https://api.telegram.org/bot$TOKEN/getWebhookInfo"
echo
