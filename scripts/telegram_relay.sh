#!/usr/bin/env bash
# 宿主机 Telegram 发件中继启动器
set -euo pipefail
cd "$(dirname "$0")/.."
export TG_TOKEN="${TG_TOKEN:?需要 TG_TOKEN}"
export TG_PROXY="${TG_PROXY:-}"
export DB_CONTAINER="${DB_CONTAINER:-edu19-clone-db-1}"
export DB_NAME="${DB_NAME:-edu19}"
exec python3 scripts/telegram_relay.py
