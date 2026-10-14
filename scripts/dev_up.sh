#!/usr/bin/env bash
# 开发环境一键拉起：隧道 + 发件中继 + webhook 注册
# 用法: TG_TOKEN=<token> TG_PROXY=<可选代理> bash scripts/dev_up.sh
set -euo pipefail
cd "$(dirname "$0")/.."
TOKEN="${TG_TOKEN:?需要 TG_TOKEN}"
PROXY="${TG_PROXY:-}"
DB_CONTAINER="${DB_CONTAINER:-edu19-clone-db-1}"
DB_NAME="${DB_NAME:-edu19}"

# 1) 发件中继
if ! pgrep -f telegram_relay >/dev/null; then
  TG_TOKEN="$TOKEN" TG_PROXY="$PROXY" DB_CONTAINER="$DB_CONTAINER" \
    DB_NAME="$DB_NAME" nohup bash scripts/telegram_relay.sh     > /tmp/relay.log 2>&1 &
  echo "relay started"
else
  echo "relay already running"
fi

# 2) 隧道（快速隧道，地址每次会变）
if ! pgrep -f "cloudflared tunnel" >/dev/null; then
  nohup cloudflared tunnel --url http://localhost:8069 --no-autoupdate     > /tmp/tunnel.log 2>&1 &
  echo "tunnel starting..."
fi

URL=""
for i in $(seq 1 20); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/tunnel.log 2>/dev/null | head -1)
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] || { echo "未获取到隧道地址"; exit 1; }
echo "tunnel: $URL"

# 3) webhook 指向新地址（secret 从库里读）
SECRET=$(docker exec "$DB_CONTAINER" psql -U odoo -d "$DB_NAME" -Atc \
  "SELECT value FROM ir_config_parameter WHERE key='edu_telegram.webhook_secret'")
TG_PROXY="$PROXY" bash scripts/register_webhook.sh "$TOKEN" "$SECRET" "$URL"
echo "DONE ✅ 机器人已恢复"
