# edu_telegram 部署与迁移手册

Telegram 前端全部状态都在 Odoo 数据库里，换服务器 = 迁库 + 重跑注册脚本。

## 1. 配置项（ir.config_parameter，系统参数里改）

| key | 作用 |
|---|---|
| edu_telegram.bot_token | BotFather 的 token |
| edu_telegram.webhook_secret | webhook 防伪头 + 报表签名密钥（openssl rand -hex 16）|
| edu_telegram.admin_key | 管理员绑定管理码 |
| edu_telegram.public_base_url | 对外 HTTPS 地址（深链和 PDF 链接用）|
| edu_telegram.dry_run | =1 时只回显不投递（本地调试）|

## 2. 迁移步骤

```
git pull && docker compose up -d          # 起服务
docker compose exec web odoo --db_host=db -d <库名> \
  -u edu_telegram --stop-after-init       # 升级模块（可选）
scripts/register_webhook.sh <token> <secret> https://edu.example.com
```

就这两步。绑定关系、角色、参数全在库里跟着迁。

## 3. 网络与发件架构

- 入站：Telegram → 你的 HTTPS webhook（Caddy/Nginx 终结证书）
- 出站：Odoo 只把回复写进 edu_telegram_outbox 表；
  **scripts/telegram_relay.sh 在宿主机常驻**，认领队列经代理（或直连）调
  api.telegram.org 投递。容器本身不需要能翻墙。
- 启动：TG_TOKEN=xxx [TG_PROXY=http://127.0.0.1:代理端口] \
    bash scripts/telegram_relay.sh &
- 海外服务器部署时 TG_PROXY 留空即直连。

## 4. 测试

```
docker compose exec web odoo -d <库名> -u edu_telegram --stop-after-init \
  --test-tags /edu_telegram --http-port=18069
```

注意：--test-tags 会起 HTTP；运行中的服务占着 8069 时必须换端口或先停服。

## 5. 用户入口

- 网页端：/my/telegram 生成一次性绑定码（7 天有效、一次可用）
- Telegram：/start 绑定码；备用 /start 学号(或HR工号) 出生年月YYYYMMDD；
  管理员 /start 管理码 任意生日
- 角色自动识别：学生(op.student) / 教师(op.faculty) / 家长(op.parent) / 管理员

## 6. 已知取舍

- 单条回复上限 4000 字截断；列表已分页缓解
- inline 翻页按钮的加载圈由客户端超时自清（省一次出站调用）
- 发送文件需要真出站通道，当前用「签名临时链接」代替（10 分钟有效）
