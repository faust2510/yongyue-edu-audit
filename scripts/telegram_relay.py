#!/usr/bin/env python3
"""Telegram 发件中继（跑在能直连 api.telegram.org 的机器上）。

容器内 Odoo 只往 edu_telegram_outbox 表写待发消息；本脚本在宿主机
认领批次 -> 经代理(或直连)调 API -> 回写状态。纯标准库。

用法:
  python3 scripts/telegram_relay.sh   # 推荐，见 relay 脚本
环境变量:
  TG_TOKEN / TG_PROXY(可选, http://127.0.0.1:12450) / DB_CONTAINER / DB_NAME
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

TOKEN = os.environ["TG_TOKEN"]
PROXY = os.environ.get("TG_PROXY", "")
CONTAINER = os.environ.get("DB_CONTAINER", "edu19-clone-db-1")
PSQL = ["docker", "exec", CONTAINER, "psql", "-U", "odoo", "-q",
        "-d", os.environ.get("DB_NAME", "edu19"), "-At", "-F", ""]

CLAIM_SQL = (
    "UPDATE edu_telegram_outbox o SET sent = true, tries = tries + 1 "
    "WHERE o.id IN ("
    "  SELECT id FROM edu_telegram_outbox WHERE sent = false "
    "  AND tries < 5 ORDER BY id LIMIT 10 FOR UPDATE SKIP LOCKED) "
    "RETURNING id || E'\x01' || chat_id || E'\x01' || method || "
    "E'\x01' || coalesce(message_id::text,'0') || E'\x01' || "
    "coalesce(keyboard,'') || E'\x01' || "
    "replace(encode(convert_to(text,'UTF8'),'base64'), E'\\n', '')"
)

UNCLAIM_SQL = "UPDATE edu_telegram_outbox SET sent=false WHERE id=%s"


def psql(sql):
    out = subprocess.run(PSQL + ["-c", sql], capture_output=True, text=True)
    if out.returncode != 0:
        sys.stderr.write(out.stderr[-300:] + "\n")
        return []
    return [l for l in out.stdout.splitlines() if l.strip()]


def api(method, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/%s" % (TOKEN, method), data=body,
        headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": PROXY, "http": PROXY})
        if PROXY else urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=15) as resp:
        return json.loads(resp.read())


def main():
    print("relay up; proxy=%s" % (PROXY or "direct"), flush=True)
    while True:
        rows = psql(CLAIM_SQL)
        for row in rows:
            parts = row.split("\x01")
            if len(parts) != 6:
                sys.stderr.write("skip bad row %r\n" % row[:80])
                continue
            rid, chat_id, method, mid, kb_b64, text_b64 = parts
            text = base64.b64decode(text_b64).decode()
            payload = {"chat_id": chat_id, "text": text}
            if method == "editMessageText":
                payload = {"chat_id": chat_id, "message_id": int(mid),
                           "text": text}
            if kb_b64:
                try:
                    payload["reply_markup"] = json.loads(kb_b64)
                except json.JSONDecodeError:
                    pass
            try:
                res = api(method, payload)
                if not res.get("ok"):
                    sys.stderr.write("API err %s: %s\n" % (rid, res))
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")[:120]
                if e.code == 400:
                    # 永久性错误（如 chat 不存在），丢弃不重试
                    sys.stderr.write("drop %s: %s\n" % (rid, body))
                else:
                    psql(UNCLAIM_SQL % rid)
                    sys.stderr.write("send fail %s: %s\n" % (rid, e))
            except Exception as e:
                # 网络类失败回滚为未发送，等下一轮重试
                psql(UNCLAIM_SQL % rid)
                sys.stderr.write("send fail %s: %s\n" % (rid, e))
        time.sleep(1)


if __name__ == "__main__":
    main()
