#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冒烟测试 D：未登录游客只读检查 http://localhost:8069 (Odoo 19 学校系统复刻, docker edu19-clone, db edu19)。
不带任何 cookie；失败自动重试一次再判 FAIL。结果写入 tests/smoke/D_public.md。
"""
import datetime
import time

import requests

BASE = "http://localhost:8069"
TIMEOUT = 25
BAD = ("Traceback", "Internal Server Error")
OUT = "tests/smoke/D_public.md"

UA = {"User-Agent": "smoke-test-agentD/1.0 (read-only guest)"}

PUBLIC_ROUTES = [
    ("/courses", ["课程"]),
    ("/online-exams", ["在线考试", "考试"]),
    ("/digital-library", ["数字图书馆", "图书馆"]),
    ("/my-courses", ["我的课程"]),
    ("/alumni", ["校友"]),
    ("/campus/jobs", ["职位", "校园招聘", "工作"]),
    ("/alumni/job/card", None),  # 特判：岗位卡或空态
    ("/courses-offered", ["课程"]),
    ("/program-offered", ["项目", "专业", "课程"]),
    ("/booking", ["预订", "预约"]),
]

JOB_CARD_MARKERS = ["职位", "岗位", "招聘", "job", "Job",
                    "暂无", "没有", "尚无", "空", "No ", "no data"]
EMPTY_HINTS = ("暂无", "没有", "尚无", "空")


# 直连本机服务：绕过 macOS 系统代理(127.0.0.1:12450)，否则 localhost 请求被代理劫持返回 502
SESSION = requests.Session()
SESSION.trust_env = False


def fetch(path, allow_redirects=True):
    return SESSION.get(BASE + path, allow_redirects=allow_redirects,
                       timeout=TIMEOUT, headers=UA)


def body_of(r):
    if not r.encoding:
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def history_chain(r):
    parts = []
    for h in r.history:
        parts.append("%d->%s" % (h.status_code, h.headers.get("Location", "")))
    return " ; ".join(parts)


def check(fn, retries=2):
    """执行 fn()，FAIL 时最多重试一次。返回 (result_dict, attempts)。"""
    last = None
    for i in range(retries):
        last = fn()
        if last["res"] != "FAIL":
            last["attempts"] = i + 1
            return last
        time.sleep(1)
    last["attempts"] = retries
    return last


def check_public(path, markers):
    def fn():
        d = {"route": path, "http": "-", "note": "", "res": "FAIL", "remark": ""}
        try:
            r = fetch(path, True)
            text = body_of(r)
            d["http"] = str(r.status_code)
            d["remark"] = history_chain(r) or "直连200"
            bad = [b for b in BAD if b in text]
            to_login = r.url.rstrip("/").endswith("/web/login")
            if to_login:
                d["res"] = "FAIL"
                d["note"] = "被重定向到登录页(应公开)"
                return d
            if markers is None:  # /alumni/job/card：岗位卡或空态
                hits = [m for m in JOB_CARD_MARKERS if m in text]
                empty_hit = [m for m in EMPTY_HINTS if m in text]
                if r.status_code == 200 and not bad and (hits or len(text) > 1000):
                    d["res"] = "PASS"
                    kind = "空态" if empty_hit else "岗位卡/列表内容"
                    d["note"] = "正常渲染(%s)" % kind + (
                        "; 标记:" + ",".join(hits[:3]) if hits else "")
                elif r.status_code == 200 and not bad:
                    d["res"] = "WARN"
                    d["note"] = "200干净但未见岗位卡/空态标记(len=%d)" % len(text)
                else:
                    d["res"] = "FAIL"
                    d["note"] = "status=%d%s" % (r.status_code,
                                "; 含错误字样:%s" % bad if bad else "")
                return d
            hits = [m for m in markers if m in text]
            if r.status_code == 200 and not bad and hits:
                d["res"] = "PASS"
                d["note"] = "命中标记: " + ", ".join(hits[:3])
            elif r.status_code == 200 and not bad:
                d["res"] = "WARN"
                d["note"] = "200无错误但未命中预期标记(%s)" % "/".join(markers)
            else:
                d["res"] = "FAIL"
                d["note"] = "status=%d%s" % (r.status_code,
                            "; 含错误字样:%s" % bad if bad else "")
            return d
        except Exception as e:  # noqa: BLE001
            d["note"] = "请求异常: %s: %s" % (type(e).__name__, e)
            return d
    return check(fn)


def check_home():
    def fn():
        d = {"route": "/", "http": "-", "note": "", "res": "FAIL", "remark": ""}
        try:
            r = fetch("/", True)
            text = body_of(r)
            d["http"] = str(r.status_code)
            d["remark"] = history_chain(r) or "直连200"
            bad = [b for b in BAD if b in text]
            nav_hits = [m for m in ["首页"] if m in text]
            hero_hits = [m for m in ["hero", "carousel", "banner", "主视觉", "<nav"]
                         if m.lower() in text.lower()]
            if r.status_code == 200 and not bad and (nav_hits or hero_hits):
                d["res"] = "PASS"
                d["note"] = ("导航命中:" + ",".join(nav_hits) if nav_hits else
                             "hero/主视觉标记:" + ",".join(hero_hits[:3]))
            elif r.status_code == 200 and not bad:
                d["res"] = "WARN"
                d["note"] = "200干净但未见首页导航/hero标记"
            else:
                d["res"] = "FAIL"
                d["note"] = "status=%d%s" % (r.status_code,
                            "; 含错误字样:%s" % bad if bad else "")
            return d
        except Exception as e:  # noqa: BLE001
            d["note"] = "请求异常: %s: %s" % (type(e).__name__, e)
            return d
    return check(fn)


def check_login_demo_btn():
    def fn():
        path = "/web/login"
        d = {"route": path, "http": "-", "note": "", "res": "FAIL", "remark": ""}
        try:
            r = fetch(path, True)
            text = body_of(r)
            d["http"] = str(r.status_code)
            d["remark"] = history_chain(r) or "直连200"
            cnt = text.count("demo-login-btn")
            bad = [b for b in BAD if b in text]
            if r.status_code == 200 and not bad and cnt >= 1:
                d["res"] = "PASS"
                d["note"] = 'class="demo-login-btn" 出现 %d 次' % cnt
            elif r.status_code == 200 and not bad:
                d["res"] = "FAIL"
                d["note"] = "登录页200但未见 demo-login-btn"
            else:
                d["res"] = "FAIL"
                d["note"] = "status=%d%s" % (r.status_code,
                            "; 含错误字样:%s" % bad if bad else "")
            return d
        except Exception as e:  # noqa: BLE001
            d["note"] = "请求异常: %s: %s" % (type(e).__name__, e)
            return d
    return check(fn)


def check_guard_strict(path):
    """鉴权守卫：不跟随跳转，期望 303/302 且 Location 指向 /web/login。"""
    def fn():
        d = {"route": path, "http": "-", "note": "", "res": "FAIL", "remark": "不跟随跳转"}
        try:
            r = fetch(path, False)
            d["http"] = str(r.status_code)
            loc = r.headers.get("Location", "")
            to_login = ("/web/login" in loc)
            if r.status_code in (302, 303) and to_login:
                d["res"] = "PASS"
                d["note"] = "%d -> %s" % (r.status_code, loc)
            elif r.status_code in (301, 307, 308) and to_login:
                d["res"] = "WARN"
                d["note"] = "%d(非302/303) -> %s" % (r.status_code, loc)
            elif r.status_code == 200:
                d["res"] = "FAIL"
                d["note"] = "未登录直接200，疑似越权暴露"
            elif r.status_code in (301, 302, 303, 307, 308):
                d["res"] = "WARN"
                d["note"] = "%d -> %s (非登录页)" % (r.status_code, loc)
            else:
                d["res"] = "FAIL"
                d["note"] = "status=%d location=%s" % (r.status_code, loc)
            return d
        except Exception as e:  # noqa: BLE001
            d["note"] = "请求异常: %s: %s" % (type(e).__name__, e)
            return d
    return check(fn)


def check_quiz():
    """/quiz：200 公开列表 或 重定向登录 都算 PASS，记录实际行为。"""
    def fn():
        path = "/quiz"
        d = {"route": path, "http": "-", "note": "", "res": "FAIL",
             "remark": "先不跟随跳转探测"}
        try:
            r = fetch(path, False)
            d["http"] = str(r.status_code)
            loc = r.headers.get("Location", "")
            if r.status_code in (301, 302, 303, 307, 308):
                if "/web/login" in loc:
                    d["res"] = "PASS"
                    d["note"] = "%d 重定向登录 -> %s" % (r.status_code, loc)
                else:
                    d["res"] = "WARN"
                    d["note"] = "%d 重定向至非登录页 -> %s" % (r.status_code, loc)
                return d
            if r.status_code == 200:
                text = body_of(r)
                bad = [b for b in BAD if b in text]
                if bad:
                    d["res"] = "FAIL"
                    d["note"] = "200但含错误字样:%s" % bad
                else:
                    hits = [m for m in ["测验", "quiz", "Quiz", "题目", "考试"] if m in text]
                    d["res"] = "PASS"
                    d["note"] = "公开200列表" + ("; 标记:" + ",".join(hits[:3]) if hits else "(未见明显列表标记)")
                return d
            d["res"] = "FAIL"
            d["note"] = "status=%d location=%s" % (r.status_code, loc)
            return d
        except Exception as e:  # noqa: BLE001
            d["note"] = "请求异常: %s: %s" % (type(e).__name__, e)
            return d
    return check(fn)


def main():
    rows = []

    def add(idx, d):
        rows.append((idx, d))
        print("[%02d] %-22s http=%-4s %-4s %s%s" % (
            idx, d["route"], d["http"], d["res"], d["note"],
            (" | " + d["remark"]) if d["remark"] and d["remark"] != "直连200" else ""))

    idx = 1
    for path, markers in PUBLIC_ROUTES:
        add(idx, check_public(path, markers)); idx += 1
    add(11, check_home())
    add(12, check_login_demo_btn())
    add(13, check_guard_strict("/my/home"))
    add(14, check_guard_strict("/openeducat/apps_menu"))
    add(15, check_quiz())

    n_pass = sum(1 for _, d in rows if d["res"] == "PASS")
    n_warn = sum(1 for _, d in rows if d["res"] == "WARN")
    n_fail = sum(1 for _, d in rows if d["res"] == "FAIL")

    lines = [
        "# 冒烟测试 D —— 未登录游客只读公开路由测试",
        "",
        "- 时间：%s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 目标：%s（Odoo 19 学校系统复刻，docker 容器 edu19-clone，数据库 edu19）" % BASE,
        "- 方法：python3 + requests，**不带任何 cookie**；GET 判定 = 最终 200 + 无 "
        "Traceback/Internal Server Error + 命中至少一个预期标记；守卫项 "
        "`allow_redirects=False` 检查跳转；失败自动重试一次再判 FAIL。",
        "",
        "| # | 路由 | HTTP(最终) | 标记/行为 | 结果 | 备注 |",
        "|---|------|-----------|-----------|------|------|",
    ]
    for i, d in rows:
        remark = d["remark"]
        if remark == "直连200":
            remark = ""
        note = d["note"].replace("|", "\\|")
        rmk = remark.replace("|", "\\|")
        lines.append("| %d | `%s` | %s | %s | %s | %s |" % (
            i, d["route"], d["http"], note, d["res"], rmk))
    lines += [
        "",
        "## 统计",
        "",
        "- 总计 **%d** 项：PASS **%d**、WARN **%d**、FAIL **%d**。" % (len(rows), n_pass, n_warn, n_fail),
    ]
    warns = ["`%s`：%s" % (d["route"], d["note"]) for _, d in rows if d["res"] == "WARN"]
    fails = ["`%s`：%s" % (d["route"], d["note"]) for _, d in rows if d["res"] == "FAIL"]
    if warns:
        lines.append("- WARN 明细：" + "；".join(warns))
    if fails:
        lines.append("- FAIL 明细：" + "；".join(fails))
    lines.append("")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\nwrote %s  (PASS=%d WARN=%d FAIL=%d)" % (OUT, n_pass, n_warn, n_fail))


if __name__ == "__main__":
    main()
