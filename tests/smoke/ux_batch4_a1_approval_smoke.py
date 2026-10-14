#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A1 审批待办聚合 E2E 冒烟（ux-rework 批次 4 · P2）。

目标 http://127.0.0.1:8069 (Odoo 19, docker edu19-clone, db edu19)。
账号：stu@local(学生 uid8)、faculty@local(教师 uid11)、backoffice@local(教务 uid12)、
admin、parent@local。

链路：
- 学生提交请假/申诉 → 教师首页「待办提醒」卡计数 +1
- 教师请假详情页：常驻同意/驳回主行动（pending 显示）+ 步骤条（审批中）
- 同意/驳回后：详情页主行动隐藏、步骤条变已通过/已驳回
- 申请人收到 edu.message 通知（B5 引擎）+ 学生首页提醒卡计数（seen_map 水位）
- 申诉门户列表/详情 + /grievances/set_state 同意（解决）/驳回
- 四角色（含教务/家长）/my/home 均 200

造数均带「【A1冒烟】」标记，测试结束按标记 DELETE（禁 DROP TABLE）。
"""
import json
import re
import subprocess
import sys

import requests

BASE = "http://127.0.0.1:8069"
DB = "edu19"
DB_CONTAINER = "edu19-clone-db-1"
P = {"http": None, "https": None}
HDRS = {"Accept-Language": "zh-CN,zh;q=0.9"}
CSRF_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')
TAG = "【A1冒烟】"
STU_UID, FAC_UID = 8, 11

R = []


def rec(item, expect, actual, ok, evidence=""):
    R.append(dict(item=item, expect=expect, actual=str(actual)[:300],
                  result="PASS" if ok else "FAIL", evidence=str(evidence)[:300]))
    print("[%s] %s | %s" % ("PASS" if ok else "FAIL", item, actual))


def auth(login, pwd):
    s = requests.Session()
    s.trust_env = False
    s.headers.update(HDRS)
    r = s.post(BASE + "/web/session/authenticate",
               json={"jsonrpc": "2.0",
                     "params": {"db": DB, "login": login, "password": pwd}},
               timeout=60, proxies=P)
    uid = r.json().get("result", {}).get("uid")
    if not uid:
        raise SystemExit("login failed: %s" % login)
    return s


def csrf_of(s, path):
    r = s.get(BASE + path, timeout=60, proxies=P)
    m = CSRF_RE.search(r.text)
    return m.group(1) if m else ""


def psql(sql):
    cp = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", "odoo",
         "-d", DB, "-tAc", sql],
        capture_output=True, text=True, timeout=60)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip()[:200])
    return cp.stdout.strip()


def alert_count(html, title):
    """教师首页「待办提醒」卡计数（badge 紧随标题）。"""
    m = re.search(r"%s.*?badge[^>]*>\s*(\d+)" % re.escape(title), html, re.S)
    return int(m.group(1)) if m else None


def main():
    stu = auth("stu@local", "demo123")
    fac = auth("faculty@local", "demo123")

    # ---------- 0. 基线 ----------
    home0 = fac.get(BASE + "/my/home", timeout=60, proxies=P)
    rec("0 教师首页 200 且含待办提醒区", "200/有结构",
        home0.status_code,
        home0.status_code == 200 and "待办提醒" in home0.text,
        "待办提醒 in html: %s" % ("待办提醒" in home0.text))
    n0 = alert_count(home0.text, "待批请假")
    g0 = alert_count(home0.text, "待处理申诉")
    rec("0 教师首页待批请假计数可解析", "整数", n0, n0 is not None)
    rec("0 教师首页待处理申诉计数可解析", "整数", g0, g0 is not None)

    # ---------- 1. 学生提交请假 → 提醒卡计数 +1 ----------
    token = csrf_of(stu, "/my/time_off")
    r = stu.post(BASE + "/my/time_off/save", data={
        "csrf_token": token, "leave_type": "sick",
        "date_from": "2026-10-09", "date_to": "2026-10-10",
        "reason": TAG + "同意路径用例",
    }, timeout=60, proxies=P, allow_redirects=True)
    rec("1 学生提交请假", "box=submitted", r.url[-40:],
        "box=submitted" in r.url)
    leave_id = int(psql("SELECT max(id) FROM edu_leave WHERE reason LIKE %s"
                        % ("'%%%s%%'" % TAG,)))
    rec("1 新请假落库", "id>0", leave_id, leave_id > 0)

    home1 = fac.get(BASE + "/my/home", timeout=60, proxies=P)
    n1 = alert_count(home1.text, "待批请假")
    rec("1 教师首页待批请假 +1", "%d -> %d" % (n0, n1),
        n1, n1 == (n0 or 0) + 1)

    # ---------- 2. 请假详情页：主行动 + 步骤条（审批中） ----------
    d = fac.get(BASE + "/leave/approvals/%d" % leave_id, timeout=60, proxies=P)
    has_btn = ("value=\"approved\"" in d.text and "value=\"refused\"" in d.text
               and ">同意" in d.text and ">驳回" in d.text)
    rec("2 详情页 200 + 同意/驳回常驻主行动", "pending 显示",
        d.status_code, d.status_code == 200 and has_btn)
    rec("2 步骤条审批中", "ux-step--current 审批中",
        "ux-step--current" in d.text,
        "ux-step--current" in d.text and "审批中" in d.text)

    # ---------- 3. 同意 → 步骤条已通过 + 主行动隐藏 + 通知 ----------
    token = csrf_of(fac, "/leave/approvals/%d" % leave_id)
    r = fac.post(BASE + "/leave/set_state", data={
        "csrf_token": token, "leave_id": str(leave_id),
        "state": "approved", "next": "/leave/approvals/%d" % leave_id,
    }, timeout=60, proxies=P, allow_redirects=True)
    ok = r.url.endswith("/leave/approvals/%d" % leave_id)
    rec("3 同意后回跳详情", "next 生效", r.url[-45:], ok)
    d2 = fac.get(BASE + "/leave/approvals/%d" % leave_id, timeout=60, proxies=P)
    rec("3 步骤条已通过 + 主行动隐藏", "已通过/无按钮",
        "ux-step--done" in d2.text,
        "已通过" in d2.text and 'value="approved"' not in d2.text)
    # 通知正文按申请编号匹配（同意正文不含 reason，不能用 reason 标记匹配）
    lv_name = psql("SELECT name FROM edu_leave WHERE id=%d" % leave_id)
    msg_n = int(psql(
        "SELECT count(*) FROM edu_message WHERE recipient_id=%d "
        "AND sender_id=%d AND body LIKE '%%审批通知%%' AND body LIKE %s"
        % (STU_UID, FAC_UID, "'%%%s%%'" % lv_name)))
    rec("3 申请人收到 B5 通知(edu.message)", ">=1", msg_n, msg_n >= 1)
    # t100 ③：落点已随 v3 迁移 —— 首页提醒卡文案现在出现在 **/my/apps**（t91 实测：
    # 改 approved 后 /my/apps 出现「您的请假状态已更新」）。故断言改落点。
    shome = stu.get(BASE + "/my/apps", timeout=60, proxies=P)
    rec("3 学生应用页提醒卡(/my/apps 请假状态已更新)", "卡片渲染",
        "您的请假状态已更新" in shome.text,
        "您的请假状态已更新" in shome.text)

    # ---------- 4. 驳回路径 ----------
    stu.post(BASE + "/my/time_off/save", data={
        "csrf_token": csrf_of(stu, "/my/time_off"), "leave_type": "other",
        "date_from": "2026-10-11", "date_to": "2026-10-11",
        "reason": TAG + "驳回路径用例",
    }, timeout=60, proxies=P, allow_redirects=True)
    leave2 = int(psql("SELECT max(id) FROM edu_leave WHERE reason LIKE %s"
                      % ("'%%%s%%'" % TAG,)))
    token = csrf_of(fac, "/leave/approvals/%d" % leave2)
    r = fac.post(BASE + "/leave/set_state", data={
        "csrf_token": token, "leave_id": str(leave2), "state": "refused",
        "reject_reason": TAG + "日期与考试冲突",
        "next": "/leave/approvals/%d" % leave2,
    }, timeout=60, proxies=P, allow_redirects=True)
    d3 = fac.get(BASE + "/leave/approvals/%d" % leave2, timeout=60, proxies=P)
    rec("4 驳回后步骤条已驳回 + 原因可见", "已驳回/原因",
        "已驳回" in d3.text,
        "已驳回" in d3.text and "日期与考试冲突" in d3.text
        and 'value="approved"' not in d3.text)
    lv2_name = psql("SELECT name FROM edu_leave WHERE id=%d" % leave2)
    msg2 = int(psql(
        "SELECT count(*) FROM edu_message WHERE recipient_id=%d "
        "AND body LIKE '%%已驳回%%' AND body LIKE %s"
        % (STU_UID, "'%%%s%%'" % lv2_name)))
    rec("4 驳回通知送达申请人", ">=1", msg2, msg2 >= 1)

    # ---------- 5. 申诉：列表 + 详情 + 同意(解决) ----------
    stu.post(BASE + "/my/grievances/save", data={
        "csrf_token": csrf_of(stu, "/my/grievances"),
        "subject": TAG + "解决路径用例", "category": "其他",
        "description": TAG + "自动提交",
    }, timeout=60, proxies=P, allow_redirects=True)
    gv_id = int(psql("SELECT max(id) FROM edu_grievance WHERE subject LIKE %s"
                     % ("'%%%s%%'" % TAG,)))
    g1 = alert_count(fac.get(BASE + "/my/home", timeout=60, proxies=P).text,
                     "待处理申诉")
    rec("5 教师首页待处理申诉 +1", "%d -> %d" % (g0, g1),
        g1, g1 == (g0 or 0) + 1)
    gl = fac.get(BASE + "/grievances/approvals", timeout=60, proxies=P)
    rec("5 申诉列表 200 含新申诉", "200/主题可见", gl.status_code,
        gl.status_code == 200 and TAG in gl.text)
    gd = fac.get(BASE + "/grievances/approvals/%d" % gv_id, timeout=60,
                 proxies=P)
    rec("5 申诉详情主行动 + 处理中步骤", "pending 显示", gd.status_code,
        gd.status_code == 200 and ">同意（解决）" in gd.text
        and "ux-step--current" in gd.text)
    token = csrf_of(fac, "/grievances/approvals/%d" % gv_id)
    fac.post(BASE + "/grievances/set_state", data={
        "csrf_token": token, "grievance_id": str(gv_id),
        "state": "resolve", "next": "/grievances/approvals/%d" % gv_id,
    }, timeout=60, proxies=P, allow_redirects=True)
    gd2 = fac.get(BASE + "/grievances/approvals/%d" % gv_id, timeout=60,
                  proxies=P)
    rec("5 解决后步骤条已解决 + 主行动隐藏", "已解决/无按钮",
        "已解决" in gd2.text,
        "已解决" in gd2.text and 'value="resolve"' not in gd2.text)
    msg3 = int(psql(
        "SELECT count(*) FROM edu_message WHERE recipient_id=%d "
        "AND body LIKE '%%处理通知%%' AND body LIKE '%%已解决%%'"
        " AND body LIKE %s" % (STU_UID, "'%%%s%%'" % TAG)))
    rec("5 申请人收到解决通知", ">=1", msg3, msg3 >= 1)

    # ---------- 6. 申诉驳回路径 ----------
    stu.post(BASE + "/my/grievances/save", data={
        "csrf_token": csrf_of(stu, "/my/grievances"),
        "subject": TAG + "驳回路径用例", "category": "其他",
        "description": TAG + "自动提交",
    }, timeout=60, proxies=P, allow_redirects=True)
    gv2 = int(psql("SELECT max(id) FROM edu_grievance WHERE subject LIKE %s"
                   % ("'%%%s%%'" % TAG,)))
    token = csrf_of(fac, "/grievances/approvals/%d" % gv2)
    fac.post(BASE + "/grievances/set_state", data={
        "csrf_token": token, "grievance_id": str(gv2), "state": "reject",
        "reject_reason": TAG + "证据不足",
        "next": "/grievances/approvals/%d" % gv2,
    }, timeout=60, proxies=P, allow_redirects=True)
    gd3 = fac.get(BASE + "/grievances/approvals/%d" % gv2, timeout=60,
                  proxies=P)
    rec("6 驳回后步骤条已驳回 + 原因可见", "已驳回/原因",
        "已驳回" in gd3.text,
        "已驳回" in gd3.text and "证据不足" in gd3.text)
    msg4 = int(psql(
        "SELECT count(*) FROM edu_message WHERE recipient_id=%d "
        "AND body LIKE '%%处理通知%%' AND body LIKE '%%已驳回%%'"
        " AND body LIKE %s" % (STU_UID, "'%%%s%%'" % TAG)))
    rec("6 驳回通知送达申请人", ">=1", msg4, msg4 >= 1)

    # ---------- 7. 四角色 /my/home 均 200 ----------
    for login, pwd in [("admin", "admin"), ("backoffice@local", "demo123"),
                       ("faculty@local", "demo123"), ("stu@local", "demo123"),
                       ("parent@local", "demo123")]:
        s = auth(login, pwd)
        r = s.get(BASE + "/my/home", timeout=60, proxies=P)
        tb = "Traceback" in r.text
        rec("7 %s /my/home 200" % login, "200 无 Traceback",
            r.status_code, r.status_code == 200 and not tb)

    # ---------- 8. 清库（按标记 DELETE，禁 DROP TABLE） ----------
    # 同意通知正文不含 TAG（仅申请编号），一并按编号清理
    cleanup = [
        "DELETE FROM edu_message WHERE body LIKE '%%%s%%';" % TAG,
        "DELETE FROM edu_leave WHERE reason LIKE '%%%s%%';" % TAG,
        "DELETE FROM edu_grievance WHERE subject LIKE '%%%s%%';" % TAG,
    ]
    for nm in (lv_name, lv2_name):
        if nm:
            cleanup.append(
                "DELETE FROM edu_message WHERE body LIKE '%%%s%%';" % nm)
    try:
        for sql in cleanup:
            subprocess.run(["docker", "exec", DB_CONTAINER, "psql", "-U",
                            "odoo", "-d", DB, "-c", sql],
                           capture_output=True, text=True, timeout=60)
        left = psql("SELECT count(*) FROM edu_leave WHERE reason LIKE %s"
                    % ("'%%%s%%'" % TAG,))
        left_msg = 0
        for nm in (lv_name, lv2_name):
            if nm:
                left_msg += int(psql(
                    "SELECT count(*) FROM edu_message WHERE body LIKE %s"
                    % ("'%%%s%%'" % nm,)))
        rec("8 清库（按标记 DELETE）", "0 残留",
            "leave=%s msg=%d" % (left, left_msg),
            left == "0" and left_msg == 0)
    except Exception as exc:
        rec("8 清库（按标记 DELETE）", "docker psql 删除",
            "未能自动执行: %s" % exc, False)

    fails = [x for x in R if x["result"] == "FAIL"]
    print("\n===JSON===")
    print(json.dumps(R, ensure_ascii=False, indent=1))
    print("TOTAL", len(R), "FAIL", len(fails))
    # t100 ③：退出码语义修正。原先有 FAIL 时返回 **2** —— 而本项目约定 **2 = ENV（环境型）**，
    # 于是真实的脚本 FAIL 会被「环境型失败标 ENV 作废」那条读数纪律**当场漂白**，
    # 既不会被追查、也不会进统计。有 FAIL ⇒ 返回 **1**（真失败），与各门禁口径一致。
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
