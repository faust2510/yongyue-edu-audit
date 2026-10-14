#!/usr/bin/env python3
"""冒烟测试代理C - HTTP层：A家长端(/my/child*) + B后台教务(/alumni/job*)
输出 JSON 结果到 stdout（供写入报告）。请假提交为演示库造数。
"""
import re, json, sys, datetime, requests

BASE = "http://localhost:8069"
DB = "edu19"
CSRF_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')
R = []  # (item, method, expect, actual, result, evidence)

def auth(login, pwd):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + "/web/session/authenticate",
               json={"jsonrpc": "2.0", "params": {"db": DB, "login": login, "password": pwd}},
               timeout=60)
    uid = r.json().get("result", {}).get("uid")
    if not uid:
        raise SystemExit(f"login failed {login}")
    return s

def rec(item, method, expect, actual, result, evidence):
    R.append(dict(item=item, method=method, expect=expect, actual=actual,
                  result=result, evidence=evidence))
    print(f"[{result}] {item}: {actual}")

# ---------- A 家长端 ----------
s = auth("parent@local", "demo123")

# A1 列表
r = s.get(BASE + "/my/child", timeout=60)
h = r.text
ok200 = r.status_code == 200
no_tb = "Traceback" in h
has_card = ("o_portal" in h or 'class="card' in h) and ("查看仪表盘" in h or "孩子" in h)
a1 = ok200 and not no_tb and has_card
rec("A1 GET /my/child", "HTTP requests", "200 渲染孩子卡片无Traceback",
    f"{r.status_code}, 卡片标记={has_card}, Traceback={no_tb}",
    "PASS" if a1 else "FAIL", f"len={len(h)}")

ids = sorted(set(re.findall(r'/my/child/(\d+)', h)), key=int)

# A2 详情
if ids:
    cid = ids[0]
    r2 = s.get(BASE + f"/my/child/{cid}", timeout=60)
    h2 = r2.text
    marks = [kw for kw in ["课表", "timetable", "考勤", "attendance", "作业", "homework", "assignment"]
             if kw.lower() in h2.lower()]
    no_tb2 = "Traceback" not in h2
    a2 = r2.status_code == 200 and no_tb2 and bool(marks)
    rec(f"A2 GET /my/child/{cid}", "HTTP requests", "200 孩子仪表盘(课表/考勤/作业任一)",
        f"{r2.status_code}, 命中标记={marks}", "PASS" if a2 else "FAIL", f"len={len(h2)}")

    # A3 请假造数
    r3 = s.get(BASE + f"/my/child/{cid}/leave", timeout=60)
    h3 = r3.text
    csrf = CSRF_RE.search(h3)
    fields = set(re.findall(r'name="(leave_type|date_from|date_to|reason)"', h3))
    action_m = re.search(r'<form[^>]*action="([^"]*leave/save[^"]*)"', h3)
    action = action_m.group(1) if action_m else f"/my/child/{cid}/leave/save"
    today = datetime.date.today()
    d_from = today + datetime.timedelta(days=7)
    d_to = d_from + datetime.timedelta(days=1)
    a3_form = r3.status_code == 200 and csrf and {"date_from", "reason"} <= fields
    rec(f"A3a GET /my/child/{cid}/leave 表单", "HTTP requests",
        "200 含csrf与必填(date_from,reason)", f"{r3.status_code}, csrf={bool(csrf)}, 字段={sorted(fields)}",
        "PASS" if a3_form else "FAIL", f"action={action}")

    payload = {
        "csrf_token": csrf.group(1),
        "leave_type": "casual",
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "reason": "【冒烟测试可删】代理C端到端验证 smoke test C - deletable demo data",
    }
    r4 = s.post(BASE + action, data=payload, timeout=60, allow_redirects=True)
    h4 = r4.text
    submitted = ("box=submitted" in r4.url) or ("已提交" in h4) or ("submitted" in h4)
    no_tb4 = "Traceback" not in h4
    a3 = (r4.status_code == 200) and submitted and no_tb4
    rec(f"A3b POST {action} 造数", "HTTP requests(form post)",
        "成功标志 box=submitted 或「已提交」",
        f"{r4.status_code}, url={r4.url}, 已提交标志={submitted}, Traceback={not no_tb4}",
        "PASS" if a3 else "FAIL",
        f"日期{d_from}~{d_to} 理由注明冒烟可删 → 已造数")
else:
    rec("A2/A3", "-", "存在孩子详情链接", "未解析到 /my/child/<id>", "FAIL", "-")

# ---------- B 后台教务 ----------
s2 = auth("backoffice@local", "demo123")
r5 = s2.get(BASE + "/alumni/job/list", timeout=60)
h5 = r5.text
marks5 = [kw for kw in ["校友", "职位", "招聘", "job", "alumni"] if kw.lower() in h5.lower()]
tb5 = "Traceback" in h5
has_table = ("<table" in h5) or ('class="card' in h5) or ("list-group" in h5)
b4 = r5.status_code == 200 and not tb5 and bool(marks5) and has_table
rec("B4 GET /alumni/job/list", "HTTP requests", "200 管理列表(表格/卡片,校友或职位标记)",
    f"{r5.status_code}, 标记={marks5}, 表格/卡片={has_table}, Traceback={tb5}",
    "PASS" if b4 else "FAIL", f"len={len(h5)}")

# B5 新建入口
new_link = None
m = re.search(r'href="(/alumni/job/new[^"]*|/alumni/job/list\?[^"]*create[^"]*|/alumni/job/[^\"]*create[^"]*)"',
              h5)
btn_new = re.search(r'>\s*(新建|新增|New)\s*<', h5)
if m:
    new_link = m.group(1)
elif btn_new:
    # 找按钮附近的链接
    seg = h5[max(0, btn_new.start() - 400):btn_new.start()]
    lm = re.findall(r'href="([^"]+)"', seg)
    new_link = lm[-1] if lm else None

if new_link:
    url6 = BASE + new_link if new_link.startswith("/") else new_link
    r6 = s2.get(url6, timeout=60, allow_redirects=True)
    tb6 = "Traceback" in r6.text
    b5 = r6.status_code == 200 and not tb6
    rec("B5 新建入口页", "HTTP requests", "新建入口存在且渲染正常",
        f"{r6.status_code} {url6}, Traceback={tb6}", "PASS" if b5 else "FAIL", f"len={len(r6.text)}")
else:
    rec("B5 新建入口页", "HTTP requests", "新建入口存在且渲染正常",
        "列表页未见「新建」入口链接", "WARN", "grep 无 /alumni/job/new 或 create 链接")

print("\n===JSON===")
print(json.dumps(R, ensure_ascii=False, indent=1))
