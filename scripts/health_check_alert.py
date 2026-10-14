#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edu19 站点探活 + Telegram 告警（2026-09-24 立）。

起因：2026-09-24 15:42-16:25 主站断网 43 分钟无人发现 —— Cloudflare 上
edu.example.org（隧道记录）的代理状态被误置为「仅 DNS/灰云」，DNS 只回
cfargotunnel CNAME，而该名字公网解析不了 ⇒ 全网不可达。本脚本把同类故障
压到 5 分钟内被发现。

检查项（在源站 prod-host 上执行）：
  1) dns     edu.example.org 经 1.1.1.1 / 8.8.8.8 必须解析出 A 记录
             （灰云事故的指纹：只回 CNAME、没有 A）
  2) main    https://edu.example.org/               经 Cloudflare 必须 200
  3) direct  https://cn.edu.example.org/            直连入口（HAProxy SNI + nginx TLS + Odoo）必须 200
  4) origin  http://127.0.0.1:80/                 源站 nginx（Host: edu.example.org）必须 200

告警去重（状态机，存 /var/lib/edu-health/state.json）：
  OK→FAIL 立即告警；FAIL→OK 发恢复通知；持续 FAIL 每 HEALTH_REMIND_HOURS 小时重提醒。

投递：优先写 edu_telegram_outbox（常驻 telegram_relay 负责投递，无需新 token）；
      数据库不可用时回退「直连 Bot API」（token/chat 缓存于 /etc/edu-health.env，600）。

用法：
  python3 scripts/health_check_alert.py                # 探活（systemd timer 每 5 分钟调用）
  python3 scripts/health_check_alert.py --test-alert   # 只发一条测试告警
  HEALTH_FORCE_FAIL=dns python3 scripts/health_check_alert.py    # 演练：强制 dns 项失败
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta

STATE_PATH = os.environ.get("HEALTH_STATE", "/var/lib/edu-health/state.json")
ENV_PATH = os.environ.get("HEALTH_ENV", "/etc/edu-health.env")
REMIND_HOURS = float(os.environ.get("HEALTH_REMIND_HOURS", "6"))
FORCE_FAIL = os.environ.get("HEALTH_FORCE_FAIL", "")
DB_CONTAINER = os.environ.get("DB_CONTAINER", "edu19-prod-db-1")
DB_NAME = os.environ.get("DB_NAME", "edu19")
HOST = os.environ.get("HEALTH_HOST", "prod-host")


def sh(cmd, timeout=25):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "超时(%ss)" % timeout
    except FileNotFoundError as e:
        return 127, "", str(e)


def psql_at(sql, timeout=20):
    """跑一条 SQL，返回 (ok, 行列表)。表数据用 -At 输出。"""
    cmd = ["docker", "exec", DB_CONTAINER, "psql", "-U", "odoo", "-d", DB_NAME,
           "-At", "-F", "\x01", "-c", sql]
    rc, out, err = sh(cmd, timeout=timeout)
    if rc != 0:
        return False, err[-300:]
    return True, [l for l in out.splitlines() if l.strip()]


def psql_stdin(sql, timeout=20):
    """把多行 SQL 走 stdin 喂给 psql（避免引号穿越 shell）。"""
    cmd = ["docker", "exec", "-i", DB_CONTAINER, "psql", "-U", "odoo",
           "-d", DB_NAME, "-q", "-At"]
    try:
        p = subprocess.run(cmd, input=sql, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode == 0, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return False, "", "psql 超时"


# ─────────────────────────── 检查项 ───────────────────────────

def check_dns():
    if FORCE_FAIL == "dns":
        return False, "演练：强制失败", "HEALTH_FORCE_FAIL=dns"
    ips, detail = set(), []
    for resolver in ("1.1.1.1", "8.8.8.8"):
        rc, out, err = sh(["dig", "+short", "+time=5", "+tries=2", "A",
                           "edu.example.org", "@" + resolver])
        got = [l.strip() for l in out.splitlines()
               if l.strip() and l.strip()[0].isdigit()
               and l.strip().count(".") == 3]
        detail.append("%s→%s" % (resolver, ",".join(got) if got else "无 A 记录"))
        ips.update(got)
    if ips:
        return True, "解析到 %d 个 A 记录" % len(ips), " | ".join(detail)
    return False, "无 A 记录（疑似记录被置为灰云/仅 DNS）", " | ".join(detail)


def _http_code(args, timeout=25):
    rc, out, err = sh(args, timeout=timeout)
    code = (out or "").strip().splitlines()[-1] if out else ""
    return code, err


def check_main():
    args = ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
            "--max-time", "20", "https://edu.example.org/"]
    if FORCE_FAIL == "main":
        return False, "演练：强制失败", "HEALTH_FORCE_FAIL=main"
    code, err = _http_code(args)
    if code == "200":
        return True, "200", "经 Cloudflare 200"
    return False, "主站异常（HTTP %s）" % (code or "无响应"), err[-200:] or "无响应"


def check_direct():
    args = ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
            "--max-time", "15", "--resolve", "cn.edu.example.org:443:127.0.0.1",
            "https://cn.edu.example.org/"]
    if FORCE_FAIL == "direct":
        return False, "演练：强制失败", "HEALTH_FORCE_FAIL=direct"
    code, err = _http_code(args)
    if code == "200":
        return True, "200", "HAProxy SNI + nginx TLS + Odoo 200"
    return False, "直连入口异常（HTTP %s）" % (code or "无响应"), err[-200:] or "无响应"


def check_origin():
    args = ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
            "--max-time", "10", "-H", "Host: edu.example.org",
            "http://127.0.0.1/"]
    if FORCE_FAIL == "origin":
        return False, "演练：强制失败", "HEALTH_FORCE_FAIL=origin"
    code, err = _http_code(args)
    if code == "200":
        return True, "200", "源站 nginx 200"
    return False, "源站 nginx 异常（HTTP %s）" % (code or "无响应"), err[-200:] or "无响应"


CHECKS = [("dns", "主站 DNS 有 A 记录", check_dns),
          ("main", "主站经 Cloudflare 可访问", check_main),
          ("direct", "直连入口可访问", check_direct),
          ("origin", "源站 nginx 可访问", check_origin)]


# ─────────────────────────── 投递 ───────────────────────────

def get_credentials():
    """取 chat_id/token：优先库里读，读不到用 /etc/edu-health.env 缓存。"""
    chat = token = ""
    ok, rows = psql_at(
        "select value from ir_config_parameter where key='edu_feedback.admin_chat_id';")
    if ok and rows:
        chat = rows[0].strip()
    ok2, rows2 = psql_at(
        "select value from ir_config_parameter where key='edu_telegram.bot_token';")
    if ok2 and rows2:
        token = rows2[0].strip()
    cached = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    cached[k] = v
    chat = chat or cached.get("EDU_ALERT_CHAT", "")
    token = token or cached.get("EDU_ALERT_TOKEN", "")
    if chat and token:
        try:
            os.makedirs(os.path.dirname(ENV_PATH), exist_ok=True)
            with open(ENV_PATH, "w", encoding="utf-8") as f:
                f.write("# edu19 探活告警凭据缓存（DB 不可用时的回退投递路径）\n")
                f.write("EDU_ALERT_CHAT=%s\nEDU_ALERT_TOKEN=%s\n" % (chat, token))
            os.chmod(ENV_PATH, 0o600)
        except OSError:
            pass
    return chat, token


def deliver(text):
    """优先入队由 relay 投递；失败则直连 Bot API。返回 (通道, 是否成功, 说明)。"""
    chat, token = get_credentials()
    if not chat:
        return "none", False, "拿不到 chat_id（库不可用且无缓存）"
    esc = text.replace("'", "''")
    sql = ("insert into edu_telegram_outbox "
           "(chat_id, method, text, sent, tries, create_date, write_date) values "
           "('%s','sendMessage','%s',false,0, now() at time zone 'UTC', "
           "now() at time zone 'UTC') returning id;" % (chat, esc))
    ok, out, err = psql_stdin(sql)
    if ok:
        return "outbox", True, "已入队(id=%s)，由 telegram_relay 投递" % (out or "?")
    if not token:
        return "none", False, "入库失败且无 token 可回退：%s" % (err[-120:] or out[-120:])
    try:
        body = json.dumps({"chat_id": chat, "text": text}).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot%s/sendMessage" % token, data=body,
            headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=15) as resp:
            res = json.loads(resp.read())
        if res.get("ok"):
            return "direct", True, "outbox 入库失败，已直连 Bot API 投递成功"
        return "direct", False, "API 返回：%s" % str(res)[:150]
    except Exception as e:  # noqa: BLE001
        return "direct", False, "直连也失败：%s" % str(e)[:150]


# ─────────────────────────── 状态机 ───────────────────────────

def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_PATH)
    except OSError as e:
        print("状态写入失败: %s" % e, file=sys.stderr)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def build_fail_msg(results):
    lines = ["🔴 探活告警｜%s" % now_str(), ""]
    for key, label, ok, brief, _detail in results:
        lines.append("%s %s：%s" % ("✅" if ok else "❌", label, brief))
    lines += ["", "主机 %s｜edu19 健康探活（5 分钟一次）" % HOST,
              "值班口径见 docs/deploy-malaysia.md"]
    return "\n".join(lines)


def build_ok_msg(results, minutes_down):
    lines = ["🟢 已恢复｜%s" % now_str(), ""]
    for key, label, ok, brief, _detail in results:
        lines.append("%s %s：%s" % ("✅" if ok else "❌", label, brief))
    if minutes_down is not None:
        lines += ["", "本次故障持续约 %d 分钟" % int(minutes_down)]
    lines += ["", "主机 %s｜edu19 健康探活" % HOST]
    return "\n".join(lines)


def main():
    test_only = "--test-alert" in sys.argv

    if test_only:
        chat, _ = get_credentials()
        msg = ("🟡 探活测试｜%s\n\n这是一条测试消息，说明告警通道正常。\n"
               "今后主站/直连入口/DNS 出问题会在 5 分钟内推到这里。\n"
               "收件 chat_id=%s｜主机 %s" % (now_str(), chat or "?", HOST))
        channel, ok, note = deliver(msg)
        print("投递[%s]: %s —— %s" % (channel, "成功" if ok else "失败", note))
        return 0 if ok else 1

    results = []
    for key, label, fn in CHECKS:
        ok, brief, detail = fn()
        results.append((key, label, ok, brief, detail))
        print("%-7s %-24s %s  (%s)" % (key, label, "OK" if ok else "FAIL",
                                       brief))
    all_ok = all(r[2] for r in results)
    state = load_state()
    prev = state.get("status", "unknown")
    now = time.time()

    if not all_ok:
        last_alert = state.get("last_alert_at", 0)
        due = (prev != "fail") or (now - last_alert >= REMIND_HOURS * 3600)
        if due:
            msg = build_fail_msg(results)
            if prev == "fail":
                msg = msg.replace("🔴 探活告警", "🔴 仍未恢复（重提醒）")
            channel, ok, note = deliver(msg)
            print("告警投递[%s]: %s —— %s" % (channel, "成功" if ok else "失败", note))
            state["last_alert_at"] = now
        else:
            print("已知故障，未到重提醒间隔（%.1f 小时）" % REMIND_HOURS)
        if prev != "fail":
            state["fail_since"] = now
        state["status"] = "fail"
    else:
        if prev == "fail":
            down = now - state.get("fail_since", now)
            channel, ok, note = deliver(build_ok_msg(results, down / 60.0))
            print("恢复通知[%s]: %s —— %s" % (channel, "成功" if ok else "失败", note))
        else:
            print("一切正常（状态未变，不发送）")
        state["status"] = "ok"
        state.pop("fail_since", None)
        state.pop("last_alert_at", None)

    state["checked_at"] = now_str()
    state["results"] = {r[0]: ("ok" if r[2] else "fail") for r in results}
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
