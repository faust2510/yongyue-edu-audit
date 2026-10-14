#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""注册「重复提交」事故取证 / 回归（2026-09-24 生产 edu.example.org）。

现象：学生连点两次「注册」，第一次其实注册成功并自动登录，第二次请求到达时邀请码
已被第一次消费 → 旧实现回「该邀请码已被使用」并渲染在浏览器里 ⇒ 本人以为注册失败。

用法：
    python3 tests/smoke/register_race.py before   # 改前基线
    python3 tests/smoke/register_race.py after    # 改后回归
结果落 tests/smoke/register_race_<phase>.json；账号一律带 race-<stamp> 前缀便于清场。

判据（phase=after）：
  A 连点两次：两次响应落点都不含「该邀请码已被使用」；只多 1 个账号
  B 事后重提：落到「你已注册成功，请直接登录」；账号数不变
  C 他人占用：码被 A 用掉后 B 用同一码 → 仍然「该邀请码已被使用」
  D 正常路径：新码注册 → 303 /my/home 且账号建立
  E 常规错误：无效码 / 过期码 仍然照常报错
  F 前端守卫：真浏览器里双击按钮只发出 1 个 POST
"""
import json
import re
import sys
import time
import xmlrpc.client
from pathlib import Path

import requests

import os
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

BASE = os.environ.get("SMOKE_BASE", "http://localhost:8069")
DB = os.environ.get("EDU_DB_NAME", "edu19")
ADMIN_LOGIN = os.environ.get("EDU_ADMIN_LOGIN", "admin")
ADMIN_PWD = os.environ.get("EDU_ADMIN_PWD", "admin")
HERE = Path(__file__).resolve().parent
PHASE = (sys.argv[1] if len(sys.argv) > 1 else "before").lower()
STAMP = time.strftime("%m%d%H%M%S")
PWD_ = "demo123"
EVID = {"phase": PHASE, "stamp": STAMP, "cases": {}}

common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common")
UID = common.authenticate(DB, ADMIN_LOGIN, ADMIN_PWD, {})
assert UID, "admin 认证失败"
OBJ = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object")


def orm(model, method, *args, **kw):
    return OBJ.execute_kw(DB, UID, ADMIN_PWD, model, method, list(args), kw)


def mk_code(tag, tier="student", expire_past=False):
    code = f"RACE-{tag}-{STAMP}"
    vals = {"code": code, "code_kind": "tier", "tier": tier, "note": "【冒烟】注册赛跑"}
    if expire_past:
        vals["expire_at"] = "2020-01-01 00:00:00"
    cid = orm("edu.invite.code", "create", [vals])
    return code, cid


def users_with_login(login):
    return orm("res.users", "search_count", [("login", "=", login)])


def total_users():
    return orm("res.users", "search_count", [])


# 清场（跑完想还原库时用）：删掉本脚本建过的账号与邀请码
if PHASE == "cleanup":
    uids = orm("res.users", "search", [("login", "like", "race-%@race.local")])
    orm("res.users", "unlink", uids)
    cids = orm("edu.invite.code", "search", [("code", "like", "RACE-%")])
    orm("edu.invite.code", "unlink", cids)
    print("cleanup: users=%d codes=%d" % (len(uids), len(cids)))
    sys.exit(0)


def anon_get(path, follow=True):
    """匿名（独立 cookie jar）取页面，返回 (status, final_url, html)。"""
    s = requests.Session()
    s.trust_env = False
    r = s.get(BASE + path, timeout=30, allow_redirects=follow)
    return r.status_code, r.url, r.text, s


def csrf_of(html):
    m = (re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
         or re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html))
    return m.group(1) if m else None


def _post(cookies, token, code, email, name):
    """用**给定快照 cookie**提交（不禁用 cookie jar 的自动更新——正是要复刻浏览器
    在同一时刻发出的两个请求：两者都只带提交前的匿名会话）。"""
    data = {"csrf_token": token, "code": code, "name": name, "email": email,
            "password": PWD_, "confirm": PWD_}
    r = requests.post(BASE + "/register/submit", data=data, cookies=cookies,
                      allow_redirects=False, timeout=30)
    sid = ""
    m = re.search(r"session_id=([^;]+)", r.headers.get("Set-Cookie", ""))
    if m:
        sid = m.group(1)
    return {"status": r.status_code, "location": r.headers.get("Location", ""),
            "len": len(r.content), "session_id": sid}


def winner_home(sid):
    """用**赢家**响应发下来的会话 cookie 访问 /my/home（证明第一次提交其实已登录）。"""
    if not sid:
        return {}
    r = requests.get(BASE + "/my/home", cookies={"session_id": sid},
                     allow_redirects=False, timeout=30)
    return {"status": r.status_code, "location": r.headers.get("Location", "")}


def submit_pair(code, email, name, parallel=False):
    """连点两次：两次都用**提交前**的匿名 cookie + 同一个 csrf。"""
    st, url, html, sess = anon_get("/register")
    token = csrf_of(html)
    assert st == 200 and token, f"注册页取 csrf 失败 status={st}"
    cookies = sess.cookies.get_dict()
    out = {"step0_get_register": {"status": st, "csrf": bool(token)}}
    if parallel:
        import threading
        box = {}

        def fire(k):
            box[k] = _post(cookies, token, code, email, name)
        ts = [threading.Thread(target=fire, args=(i,)) for i in (1, 2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        out["resp1"], out["resp2"] = box[1], box[2]
    else:
        out["resp1"] = _post(cookies, token, code, email, name)
        out["resp2"] = _post(cookies, token, code, email, name)
    out["cookies_snapshot"] = sorted(cookies)
    return out, cookies


def land(cookies, location):
    """以提交前 cookie 跟到落点页（= 输家那一屏真正渲染的内容）。"""
    r = requests.get(BASE + location, cookies=cookies, timeout=30)
    return {"status": r.status_code, "final": r.url, "len": len(r.text),
            "page": page_facts(r.text)}


def page_facts(html):
    return {
        "已被使用": "该邀请码已被使用" in html,
        "已注册成功": "你已注册成功" in html,
        "已过期": "该邀请码已过期" in html,
        "无效": "邀请码无效" in html,
        "有注册表单": 'action="/register/submit"' in html,
        "有登录链接": 'href="/login"' in html,
        "守卫脚本": "register-submit-guard" in html,
    }


def case(name, **data):
    EVID["cases"][name] = data
    print("\n--- %s ---" % name)
    for k, v in data.items():
        print("  %-22s %s" % (k, json.dumps(v, ensure_ascii=False)[:400]))


# ============================ A 连点两次 ============================
code_a, _ = mk_code("A")
email_a = f"race-a-{STAMP}@race.local"
n0 = total_users()
pair, snap = submit_pair(code_a, email_a, "冒烟A")
land2 = land(snap, pair["resp2"]["location"]) if pair["resp2"]["location"] else {}
n1 = total_users()
case("A_连点两次",
     code=code_a, email=email_a,
     resp1=pair["resp1"], resp2=pair["resp2"],
     loser_landing=land2,
     users_before=n0, users_after=n1, delta=n1 - n0,
     accounts_for_email=users_with_login(email_a),
     winner_session_home=winner_home(pair["resp1"]["session_id"]),
     authed_open_registered_state=(lambda sid: requests.get(
         BASE + "/register?registered=1", cookies={"session_id": sid},
         allow_redirects=False, timeout=30).status_code)(
             pair["resp1"]["session_id"]))

# ============================ B 事后重提 ============================
code_b, _ = mk_code("B")
email_b = f"race-b-{STAMP}@race.local"
first, snap_b = submit_pair(code_b, email_b, "冒烟B")
# 独立会话（新匿名 jar）再提一次：同邮箱 + 已消费的码
st, url, html, sess2 = anon_get("/register")
token2 = csrf_of(html)
nb_users_before_resubmit = total_users()
again = _post(sess2.cookies.get_dict(), token2, code_b, email_b, "冒烟B")
nb0 = users_with_login(email_b)
nb1_all = total_users()
land_again = land(sess2.cookies.get_dict(), again["location"]) if again["location"] else {}
case("B_事后重提",
     code=code_b, email=email_b,
     first_submit=first["resp1"],
     resubmit=again,
     landing=land_again,
     accounts_for_email_before=nb0,
     accounts_for_email_after=users_with_login(email_b),
     total_users_before_resubmit=nb_users_before_resubmit,
     total_users_after=nb1_all,
     delta=nb1_all - nb_users_before_resubmit)

# ============================ C 他人占用 ============================
code_c, _ = mk_code("C")
email_c1 = f"race-c1-{STAMP}@race.local"
email_c2 = f"race-c2-{STAMP}@race.local"
s1, snap_c = submit_pair(code_c, email_c1, "冒烟C1")
st, url, html, sess3 = anon_get("/register")
token3 = csrf_of(html)
other = _post(sess3.cookies.get_dict(), token3, code_c, email_c2, "冒烟C2")
land_other = land(sess3.cookies.get_dict(), other["location"]) if other["location"] else {}
case("C_他人占用",
     code=code_c, owner_email=email_c1, other_email=email_c2,
     owner_submit=s1["resp1"], other_submit=other, other_landing=land_other,
     other_accounts=users_with_login(email_c2))

# ============================ D 正常路径 ============================
code_d, _ = mk_code("D")
email_d = f"race-d-{STAMP}@race.local"
s_d, snap_d = submit_pair(code_d, email_d, "冒烟D")
home = requests.get(BASE + "/my/home", cookies=sess.cookies.get_dict(), timeout=30) \
    if False else None
case("D_正常路径",
     code=code_d, email=email_d,
     resp1=s_d["resp1"], resp2=s_d["resp2"],
     accounts_for_email=users_with_login(email_d))

# ============================ E 常规错误 ============================
code_e, _ = mk_code("E", expire_past=True)
st, url, html, sess4 = anon_get("/register")
token4 = csrf_of(html)
bad = _post(sess4.cookies.get_dict(), token4, "RACE-NOPE-" + STAMP,
            f"race-e1-{STAMP}@race.local", "冒烟E1")
land_bad = land(sess4.cookies.get_dict(), bad["location"]) if bad["location"] else {}
exp = _post(sess4.cookies.get_dict(), token4, code_e,
            f"race-e2-{STAMP}@race.local", "冒烟E2")
land_exp = land(sess4.cookies.get_dict(), exp["location"]) if exp["location"] else {}
case("E_常规错误", invalid_submit=bad, invalid_landing=land_bad,
     expired_submit=exp, expired_landing=land_exp)

# ============================ F 真浏览器双击 ============================
code_f, _ = mk_code("F")
email_f = f"race-f-{STAMP}@race.local"
# 对照组（改前 DOM）：同一张真页面、同一个会话与 csrf，只把守卫的 submit 监听
# 「吞掉」—— 用 add_init_script 在页面脚本之前改写 addEventListener，等价于那次事故
# 发生时页面上**没有**守卫。其余一切相同，因此两组之差就是守卫本身的作用。
NEUTRALIZE = """(function () {
    var orig = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function (type, fn, opts) {
        if (type === 'submit' && this && this.tagName === 'FORM') { return; }
        return orig.call(this, type, fn, opts);
    };
})();"""
SEL = 'form[action="/register/submit"] button[type="submit"]'


def browser_double_click(browser, code, email, neutralize):
    """真浏览器连点两次：数 POST 个数 + 最终落在哪一屏（不拦不改）。"""
    posts = []
    page = browser.new_context(locale="zh-CN").new_page()
    if neutralize:
        page.add_init_script(NEUTRALIZE)
    page.on("request", lambda r: posts.append(r.url)
            if r.method == "POST" and "/register/submit" in r.url else None)
    page.goto(BASE + "/register", wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("load", timeout=45000)      # 必须等 load，否则表单提交不动
    except Exception:
        pass
    page.fill("#reg-code", code)
    page.fill("#reg-name", "冒烟F")
    page.fill("#reg-email", email)
    page.fill("#reg-password", PWD_)
    page.fill("#reg-confirm", PWD_)
    # 真人连点：两次**可信**鼠标点击，间隔 150ms（生产事故里两次相隔 870ms）
    box = page.locator(SEL).bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(150)
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(4000)
    final_url = page.url
    body = page.evaluate("() => document.body ? document.body.innerText : ''")
    page.close()
    return {"post_count": len(posts), "final_url": final_url,
            "on_error_page": "该邀请码已被使用" in body,
            "success_page": "你已注册成功" in body,
            "on_home": "/my/home" in final_url,
            "accounts": users_with_login(email)}


try:
    from playwright.sync_api import sync_playwright

    code_f0, _ = mk_code("F0")
    email_f0 = f"race-f0-{STAMP}@race.local"
    code_f1, _ = mk_code("F1")
    email_f1 = f"race-f1-{STAMP}@race.local"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        control = browser_double_click(browser, code_f0, email_f0, neutralize=True)
        guarded = browser_double_click(browser, code_f1, email_f1, neutralize=False)
        browser.close()
    case("F_浏览器双击",
         guard_element=requests.get(BASE + "/register", timeout=30).text.count(
             'id="register-submit-guard"'),
         control_no_guard=control, guarded_with_guard=guarded)
    EVID["cases"]["F_浏览器双击"]["verdict"] = (
        "control: %d POST（改前=重提交）／guarded: %d POST（改后=只发一个）"
        % (control["post_count"], guarded["post_count"]))
except Exception as exc:  # noqa: BLE001
    case("F_浏览器双击", error=f"{type(exc).__name__}: {exc}")

out = HERE / f"register_race_{PHASE}.json"
out.write_text(json.dumps(EVID, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n== 结果 -> %s ==" % out)
