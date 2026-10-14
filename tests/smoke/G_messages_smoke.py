#!/usr/bin/env python3
"""冒烟测试 G：P2 轻量双向私信（B9）权限矩阵与轮询（v2.1）。

目标 http://localhost:8069 (Odoo 19, docker edu19-clone, db edu19)。
账号：stu@local(学生 王小明/uid8)、faculty@local(预备科导师/uid11)、
parent@local(家长【演示】/uid10, 孩子王小明)、backoffice@local(教务/管理员)、
admin。
矩阵（熟人圈）：
- 学生↔自己的教师+管理员；学生→其他学生/家长 拦截
- 家长↔孩子任课教师+孩子+管理员；家长→其他学生 拦截
- 教师↔本班学生/家长+管理员；教师↔教师 不开放（圈内不含其他教师账号）
- 管理员=全部
造数均带「【冒烟测试可删】」标记，测试结束清库。
输出 JSON 结果到 stdout（供写入报告）。
"""
import json
import re
import sys
import requests

BASE = "http://localhost:8069"
DB = "edu19"
CSRF_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')
TAG = "【冒烟测试可删】B9"
R = []  # (item, expect, actual, result, evidence)


def auth(login, pwd):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + "/web/session/authenticate",
               json={"jsonrpc": "2.0",
                     "params": {"db": DB, "login": login, "password": pwd}},
               timeout=60)
    uid = r.json().get("result", {}).get("uid")
    if not uid:
        raise SystemExit(f"login failed {login}")
    return s


def rec(item, expect, actual, result, evidence=""):
    R.append(dict(item=item, expect=expect, actual=actual, result=result,
                  evidence=evidence))
    print(f"[{result}] {item}: {actual}")


def ok_get(s, path):
    """GET 并返回 (status, html, traceback_flag, redirect_url)。"""
    r = s.get(BASE + path, timeout=60, allow_redirects=True)
    return r.status_code, r.text, "Traceback" in r.text, r.url


# ================= 学生 stu@local（uid 8） =================
stu = auth("stu@local", "demo123")

# S1 列表页渲染
st, h, tb, url = ok_get(stu, "/my/messages")
picker_ids = sorted({int(x) for x in re.findall(r'<option value="(\d+)">', h)})
conv_rows = len(re.findall(r'class="o_portal_index_card col-12 msg-conv"', h))
s1 = st == 200 and not tb and ("发起新对话" in h or "私信" in h)
rec("S1 GET /my/messages 学生", "200 渲染列表+发起框无Traceback",
    f"{st}, rows={conv_rows}, picker={picker_ids}, tb={tb}", "PASS" if s1 else "FAIL",
    f"len={len(h)}")
# 基线未读数（共享栈可能残留他人测试数据，断言一律用增量）
BASE_STU = stu.get(BASE + "/my/messages/poll", timeout=60).json().get("unread", 0)

# 中性化私信水位：清掉 edu.alert.read.seen_map['my/messages'] 键。
# 水位语义「只升不降」（mark_read 只能提升），共享栈若被人工点过
# 「全部标为已读/提醒卡」会留下高水位，新消息未读会被水位吞掉导致
# S14c 角标断言不确定——因此基线处用 psql 直接摘除该键（与 Z1 同纪律，
# 只动 seen_map 数据，不用 DROP TABLE）。
import subprocess
try:
    subprocess.run(
        ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo", "-d", DB,
         "-c", "UPDATE edu_alert_read "
               "SET seen_map = (COALESCE(seen_map::jsonb, '{}'::jsonb) - 'my/messages')::jsonb "
               "WHERE user_id = 8;"],
        capture_output=True, text=True, timeout=60)
except Exception as exc:
    print(f"[WARN] 未能中性化私信水位（{exc}）；S14c 可能受历史水位影响")

# S2 学生熟人圈：教师(11)+管理员(2/12)，不含家长(10)、不含其他学生
#   以 picker 选项校验（管理员=backoffice(12)+admin(2)，教师=11）
expect_s = {2, 11, 12}
s2 = set(picker_ids) == expect_s
rec("S2 学生picker=教师+管理员(2,11,12)", f"picker=={sorted(expect_s)}",
    f"picker={picker_ids}", "PASS" if s2 else "FAIL")

# S3 学生→教师 对话页 200（打开即已读机制测试放后面）
st, h, tb, url = ok_get(stu, "/my/messages/11")
has_form = 'action="/my/messages/send"' in h and 'name="uid"' in h
s3 = st == 200 and not tb and has_form
rec("S3 GET /my/messages/11 学生→教师", "200 含发送表单",
    f"{st}, form={has_form}, tb={tb}", "PASS" if s3 else "FAIL")

# S4 发送：学生→教师
# t106：**紧邻基线** —— S9 断言「学生自己发出去的不算自己的未读」。
# 原实现拿脚本开头的 BASE_STU（第 65 行）在 80 行之后才比对，窗口内**并发冒烟**
# 给别人发消息就会让未读漂移（t92 实测首个失败即 `S9 poll unread=323`）。
# 故在**自己这次发送之前**重取一次基线，把窗口收到只剩本次发送 → 判据变成真正的增量。
U9 = stu.get(BASE + "/my/messages/poll", timeout=60).json().get("unread", 0)
csrf = CSRF_RE.search(h)
r = stu.post(BASE + "/my/messages/send",
             data={"csrf_token": csrf.group(1), "uid": "11",
                   "body": TAG + " 学生问候老师"},
             timeout=60, allow_redirects=True)
s4 = r.status_code == 200 and "sent=1" in r.url and "Traceback" not in r.text
rec("S4 POST send 学生→教师", "重定向 ?sent=1",
    f"{r.status_code}, url={r.url}, tb={'Traceback' in r.text}",
    "PASS" if s4 else "FAIL")

# S5 校验已入库（经教师视角的未读可见性）
st, h5, tb, url = ok_get(stu, "/my/messages/11")
bubble = ("学生问候老师" in h5)
s5 = st == 200 and not tb and bubble
rec("S5 对话页含刚发消息", "气泡含正文", f"{st}, bubble={bubble}",
    "PASS" if s5 else "FAIL")

# S6 越权：学生→家长（uid10）GET 拦截
st, h6, tb, url = ok_get(stu, "/my/messages/10")
s6 = st == 200 and "denied=1" in url and "无法与该用户通信" in h6
rec("S6 学生→家长 GET 越权拦截", "重定向 denied=1 且提示",
    f"{st}, url={url}, 提示={'无法与该用户通信' in h6}",
    "PASS" if s6 else "FAIL", f"len={len(h6)}")

# S7 越权：学生→其他学生（uid55）GET 拦截 + POST 拦截
st, h7, tb, url = ok_get(stu, "/my/messages/55")
s7a = "denied=1" in url
csrf7 = CSRF_RE.search(h5)  # 用对话页 token
r7 = stu.post(BASE + "/my/messages/send",
              data={"csrf_token": csrf7.group(1), "uid": "55", "body": TAG + " 越权"},
              timeout=60, allow_redirects=True)
s7b = "denied=1" in r7.url
s7 = s7a and s7b
rec("S7 学生→其他学生 越权拦截", "GET与POST均 denied",
    f"GET={s7a}, POST={s7b}", "PASS" if s7 else "FAIL")

# S8 越权：学生→家长 POST 拦截（uid10）
r8 = stu.post(BASE + "/my/messages/send",
              data={"csrf_token": csrf7.group(1), "uid": "10", "body": TAG + " 越权2"},
              timeout=60, allow_redirects=True)
s8 = "denied=1" in r8.url
rec("S8 学生→家长 POST 越权拦截", "denied", f"url={r8.url}", "PASS" if s8 else "FAIL")

# S9 轮询接口：学生视角（增量=0）
r9 = stu.get(BASE + "/my/messages/poll", timeout=60)
try:
    j9 = r9.json()
    # t106：与**紧邻基线 U9**（发送前）比较 → 增量 0 表示「自己发的不算自己未读」
    ok_json = j9.get("unread", 0) == U9
    s9 = r9.status_code == 200 and ok_json
    ev9 = "unread=%s 基线U9=%s 增量=%s %s" % (
        j9.get("unread"), U9,
        (j9.get("unread", 0) - U9) if isinstance(j9.get("unread"), int) else "?",
        json.dumps(j9, ensure_ascii=False)[:80])
except Exception as e:
    s9, ev9 = False, f"not json: {e}"
rec("S9 GET /my/messages/poll 学生", f"JSON unread==紧邻基线U9({U9})（增量0）",
    ev9, "PASS" if s9 else "FAIL")

# ================= 教师 faculty@local（uid 11） =================
fac = auth("faculty@local", "demo123")
st, hf, tb, url = ok_get(fac, "/my/messages")
picker_f = sorted({int(x) for x in re.findall(r'<option value="(\d+)">', hf)})
# 教师=预备科导师：本班学生（有账号的：王小明8）+家长10+管理员2/12；
# 可能还包含同班其他有账号学生（如注册冒烟遗留），取超集判读
expect_f = {2, 8, 10, 12}
f_ok = set(picker_f) >= expect_f
rec("S10 教师picker 含 学生8+家长10+管理员", f"⊇{sorted(expect_f)}",
    f"picker={picker_f}", "PASS" if f_ok else "FAIL")

# S11 教师列表见学生会话+未读角标
st, hf2, tb, url = ok_get(fac, "/my/messages")
conv_uids = sorted(set(re.findall(r'data-conv-uid="(\d+)"', hf2)))
unread_badges = len(re.findall(r'msg-conv-unread', hf2))
s11 = st == 200 and not tb and "8" in conv_uids and unread_badges >= 1
rec("S11 教师会话列表 含学生8 未读≥1", "行含8且带未读徽标",
    f"conv={conv_uids}, unread_badges={unread_badges}", "PASS" if s11 else "FAIL")

# S12 教师工作台：私信卡带未读角标（计数，data-msg-badge 轮询刷新钩子）
st, hh, tb, url = ok_get(fac, "/my/home")
wb_badge = re.search(r'a[^>]*href="/my/messages"[^>]*>.*?data-msg-badge="(\d+)"',
                     hh, re.S)
s12 = st == 200 and not tb and bool(wb_badge) and int(wb_badge.group(1)) >= 1
rec("S12 教师工作台 私信卡角标", "含 data-msg-badge 且 ≥1",
    f"badge={wb_badge.group(1) if wb_badge else None}, tb={tb}",
    "PASS" if s12 else "FAIL")

# S13 教师打开对话 → 打开即已读；再轮询**该会话**未读应为 0
# t106：原断言 `j13.unread == 0` 是**绝对基线**（要求教师**全局**未读为 0）——
# 共享库里教师还有别的会话未读（实测 uid=12 未读 11、uid=11 未读 20）⇒ 该断言永不成立。
# 「打开即已读」的判据本来就该看**被打开的那个会话**，而不是全局计数。
st, h13, tb, url = ok_get(fac, "/my/messages/8")
r13 = fac.get(BASE + "/my/messages/poll", timeout=60)
j13 = r13.json()
conv8 = next((c for c in (j13.get("convs") or []) if c.get("uid") == 8), None)
s13 = st == 200 and not tb and (conv8 is None or conv8.get("unread", 0) == 0)
rec("S13 教师读后该会话未读清零", "打开会话 8 后其 unread=0（不再要求全局 unread=0）",
    f"conv8={conv8}, 全局unread={j13.get('unread')}", "PASS" if s13 else "FAIL")

# S14 教师回发 → 学生 unread = 基线+1
# t106：同样改用**紧邻基线 U14**（教师这次发送之前取），把窗口收到只剩本次发送；
# S14/S14c 共用它，保证「+1」这条判据有明确的 t0。
U14 = stu.get(BASE + "/my/messages/poll", timeout=60).json().get("unread", 0)
csrf11 = CSRF_RE.search(h13)
r14 = fac.post(BASE + "/my/messages/send",
               data={"csrf_token": csrf11.group(1), "uid": "8",
                     "body": TAG + " 老师回复学生"},
               timeout=60, allow_redirects=True)
s14a = "sent=1" in r14.url
j14 = stu.get(BASE + "/my/messages/poll", timeout=60).json()
s14b = j14.get("unread") == U14 + 1
rec("S14 教师回发+学生轮询未读=紧邻基线+1", "sent=1 且 student_unread=U14+1",
    f"sent={s14a}, student_unread={j14.get('unread')}, 紧邻基线U14={U14}",
    "PASS" if (s14a and s14b) else "FAIL")

# S14c 通知引擎：未读私信卡 data-alert-key=my/messages + data-msg-unread=紧邻基线+1 + 铃铛 ≥1
#     t106 落点核实（静态读码，非猜测）：
#       `data-msg-unread` 在 batch2.xml:1035（模板 edu_one_cat），
#       铃铛 oe-notif-mirror 在 batch2.xml:684/746（模板 edu_dashboard_v2），
#       而 edu_dashboard_v2 由 **/my/apps** 路由渲染（batch2.py:1942 `edu_apps`）→
#       故本项落点应为 **/my/apps**，原先查 /my/home 属**页面迁移**导致的陈旧判据。
st, hs, tb, url = ok_get(stu, "/my/apps")
card_u = re.search(r'data-alert-key="my/messages"[^>]*data-msg-unread="(\d+)"',
                   hs, re.S)
bell_v = re.search(r'oe-notif-mirror[^>]*>(\d+)<', hs)
s14c = st == 200 and not tb and bool(card_u) \
    and int(card_u.group(1)) == U14 + 1 \
    and bool(bell_v) and int(bell_v.group(1)) >= 1
rec("S14c 学生应用页(/my/apps) 私信提醒卡+铃铛", f"data-msg-unread=紧邻基线+1({U14 + 1}) 且铃铛≥1",
    f"card_unread={card_u.group(1) if card_u else None}, bell={bell_v.group(1) if bell_v else None}",
    "PASS" if s14c else "FAIL")

# S14d 聊天轮询 with/after 拉到新消息（返回即已读）
j14d = stu.get(BASE + "/my/messages/poll?with=11&after=0", timeout=60).json()
got_new = any("老师回复学生" in (m.get("body") or "")
              for m in j14d.get("new", []))
unread_after = stu.get(BASE + "/my/messages/poll", timeout=60).json()["unread"]
# t106：读掉新消息后应回到**紧邻基线 U14**（同一次发送的 t0），而不是脚本开头的 BASE_STU
s14d = got_new and unread_after == U14
rec("S14d 聊天轮询 with/after 新消息+已读", f"拉到正文且读后未读==紧邻基线U14({U14})",
    f"got_new={got_new}, unread_after={unread_after}",
    "PASS" if s14d else "FAIL",
    evidence=json.dumps(j14d, ensure_ascii=False)[:160])

# S15 教师↔教师不开放：圈内无除自己外的教师（无其他教师账号→教学互发不可达）
r15 = fac.post(BASE + "/my/messages/send",
               data={"csrf_token": csrf11.group(1), "uid": "11", "body": TAG + " 自聊"},
               timeout=60, allow_redirects=True)
s15 = "denied=1" in r15.url
rec("S15 教师给自己发/同一身份 拦截", "denied", f"url={r15.url}",
    "PASS" if s15 else "FAIL")

# ================= 家长 parent@local（uid 10，孩子王小明 uid8） =================
par = auth("parent@local", "demo123")
st, hp, tb, url = ok_get(par, "/my/messages")
picker_p = sorted({int(x) for x in re.findall(r'<option value="(\d+)">', hp)})
expect_p = {2, 8, 11, 12}   # 教师11+孩子8+管理员
s16 = set(picker_p) == expect_p
rec("S16 家长picker=教师11+孩子8+管理员", f"=={sorted(expect_p)}",
    f"picker={picker_p}", "PASS" if s16 else "FAIL")

# S17 家长→教师 发送 + 家长→其他学生(55) 越权
st, hp17, tb, url = ok_get(par, "/my/messages/11")
csrfp = CSRF_RE.search(hp17)
r17 = par.post(BASE + "/my/messages/send",
               data={"csrf_token": csrfp.group(1), "uid": "11",
                     "body": TAG + " 家长问老师"},
               timeout=60, allow_redirects=True)
s17a = "sent=1" in r17.url
r17b = par.post(BASE + "/my/messages/send",
                data={"csrf_token": csrfp.group(1), "uid": "55",
                      "body": TAG + " 越权3"},
                timeout=60, allow_redirects=True)
s17b = "denied=1" in r17b.url
s17 = s17a and s17b
rec("S17 家长→教师OK 家长→其他学生拦截", "sent=1 且 denied=1",
    f"to_teacher={r17.url}, to_other={r17b.url}", "PASS" if s17 else "FAIL")

# ================= 管理员 backoffice@local（uid 12） =================
bo = auth("backoffice@local", "demo123")
st, hb, tb, url = ok_get(bo, "/my/messages")
picker_b = {int(x) for x in re.findall(r'<option value="(\d+)">', hb)}
# 管理员=全部：身份账号+管理员账号（自身 id 不出现在发起器，防自聊）
s18 = st == 200 and not tb and {8, 10, 11} <= picker_b and 12 not in picker_b
rec("S18 管理员=全部", "picker ⊇{8,10,11} 且不含自身12",
    f"picker({len(picker_b)})={sorted(picker_b)}", "PASS" if s18 else "FAIL")

# S19 管理员 POST 给任何身份均允许（如给家长10）
st, hb19, tb, url = ok_get(bo, "/my/messages/10")
csrfb = CSRF_RE.search(hb19)
r19 = bo.post(BASE + "/my/messages/send",
              data={"csrf_token": csrfb.group(1), "uid": "10",
                    "body": TAG + " 管理员通知家长"},
              timeout=60, allow_redirects=True)
s19 = "sent=1" in r19.url
rec("S19 管理员→家长 发送", "sent=1", f"url={r19.url}", "PASS" if s19 else "FAIL")


# ================= RPC 回归（评审 F1：ACL 收紧 + ir.rule 纵深防御） =================
def rpc_call(s, model, method, args, kwargs=None):
    """JSON-RPC call_kw（与后端 web 客户端同协议）。"""
    r = s.post(BASE + "/web/dataset/call_kw", json={
        "jsonrpc": "2.0", "id": 1, "method": "call",
        "params": {"model": model, "method": method, "args": args,
                   "kwargs": kwargs or {}}}, timeout=60)
    return r.json()


def rpc_err(j):
    return str(j.get("error") or "")


# S20 门户账号（学生）直连 RPC 读 edu.message → 必须 AccessError（无 ACL 行）
j20 = rpc_call(stu, "edu.message", "search_read", [[]], {"limit": 5})
e20 = rpc_err(j20)
s20 = "AccessError" in e20
rec("S20 门户RPC search_read 拒读", "AccessError",
    e20.splitlines()[0][:90] if e20 else "未报错", "PASS" if s20 else "FAIL")

# S21 内部非系统账号（教师）直连 RPC 同样 AccessError
j21 = rpc_call(fac, "edu.message", "search_read", [[]], {"limit": 5})
e21 = rpc_err(j21)
s21 = "AccessError" in e21
rec("S21 内部教师RPC search_read 拒读", "AccessError",
    e21.splitlines()[0][:90] if e21 else "未报错", "PASS" if s21 else "FAIL")

# S22 系统账号可读，且被全局 ir.rule 限域到「本人收发」（纵深防御生效）
j22 = rpc_call(bo, "edu.message", "search_read", [[]], {"limit": 100})
e22 = rpc_err(j22)
rows22 = j22.get("result") or []
own_scope = all(
    (x.get("sender_id") or [0])[0] == 12 or (x.get("recipient_id") or [0])[0] == 12
    for x in rows22)
s22 = not e22 and rows22 and own_scope
rec("S22 系统RPC 可读且限本人", "无错误，行均为本人收发",
    f"rows={len(rows22)}, own_scope={own_scope}, err={e22.splitlines()[0][:60] if e22 else ''}",
    "PASS" if s22 else "FAIL")


# ================= 清库（评审 F2：只 DELETE，禁止 DROP TABLE） =================
# 纪律：按标记删除本脚本产生的测试消息；绝不用 DROP TABLE（代码已落地时
# DROP 会使 /my/home 全员 500，见 docs/deploy-a8-runbook.md §5.1）。
import subprocess

cleanup_sql = "DELETE FROM edu_message WHERE body LIKE '%【冒烟测试可删】B9%';"
try:
    cp = subprocess.run(
        ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo",
         "-d", DB, "-c", cleanup_sql],
        capture_output=True, text=True, timeout=60)
    out = (cp.stdout or "").strip().splitlines()
    rec("Z1 清库（按标记 DELETE）", "DELETE 完成",
        out[-1] if out else (cp.stderr or "")[:80],
        "PASS" if cp.returncode == 0 else "FAIL")
except Exception as exc:
    rec("Z1 清库（按标记 DELETE）", "docker psql 删除",
        f"未能自动执行: {exc}（可手动执行：{cleanup_sql}）", "WARN")


# ================= 汇总 =================
fails = [x for x in R if x["result"] == "FAIL"]
print("\n===JSON===")
print(json.dumps(R, ensure_ascii=False, indent=1))
print("TOTAL", len(R), "FAIL", len(fails))
sys.exit(1 if fails else 0)