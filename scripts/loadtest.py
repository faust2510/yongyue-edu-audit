#!/usr/bin/env python3
"""edu.example.org 并发压测：同时登录 + 同时浏览门户（真实账号、真实流程）。
用法: python3 loadtest.py [phase]  phase ∈ anon|login|browse|all (默认 all)
目标: http://127.0.0.1:8069 （在服务器本机跑，绕过 CF/nginx，测 Odoo 真实容量）

凭据（t81 收口）：只在下面 CRED_DEFAULTS **一处**声明，可用
EDU_<角色>_LOGIN / EDU_<角色>_PASSWORD（角色 ∈ STU|FAC|PAR|BO|ADMIN）覆盖；
口令不出现在任何输出里（打印只出现登录名）。旧版写死 ('admin','admin')，而本库
admin 的口令是 demo123 —— 实测登录被拒，后果与 scripts/check_odoo_trace.py 同源：
**失败被混进「失败计数」里当成容量问题**（错误归因），而不是"凭据坏了"。
退出码：0 = 本轮全部凭据自证通过；1 = 有账号登不上（先修凭据再读容量数字）。
"""
import http.client, json, re, sys, time, threading, os
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor
from statistics import mean

HOST, PORT = "127.0.0.1", 8069

# ---- 凭据：**唯一声明点**（t81）----
# 口令只在这里出现，且**不打印**（打印只出现登录名）。admin 用 demo123：
# 旧值的 ('admin','admin') 在本库是**失效凭据**（实测 AccessDenied）。
CRED_DEFAULTS = [
    ("STU", "stu@local", "demo123"),
    ("FAC", "faculty@local", "demo123"),
    ("PAR", "parent@local", "demo123"),
    ("BO", "backoffice@local", "demo123"),
    ("ADMIN", "admin", "demo123"),      # 生产/他库：EDU_ADMIN_PASSWORD 覆盖
]
ACCOUNTS = [(os.environ.get("EDU_%s_LOGIN" % key, login),
             os.environ.get("EDU_%s_PASSWORD" % key, pwd))
            for key, login, pwd in CRED_DEFAULTS]
CSRF_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')
lock = threading.Lock()

def req(method, path, body=None, headers=None, cookie=""):
    h = {"User-Agent": "loadtest/1.0"}
    if cookie:
        h["Cookie"] = cookie
    if headers:
        h.update(headers)
    c = http.client.HTTPConnection(HOST, PORT, timeout=30)
    t0 = time.perf_counter()
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    dt = time.perf_counter() - t0
    sc = "; ".join(v[1].split(";")[0] for v in r.getheaders() if v[0].lower() == "set-cookie")
    c.close()
    return r.status, dict(r.getheaders()), data, dt, sc

def report(name, times, errors):
    times = sorted(times)
    n = len(times)
    if not n:
        print(f"[{name}] 全部失败! {errors[:5]}")
        return
    p95 = times[min(n - 1, int(n * 0.95))]
    print(f"[{name}] 请求数={n} 失败={len(errors)} 平均={mean(times)*1000:.0f}ms "
          f"中位={times[n//2]*1000:.0f}ms p95={p95*1000:.0f}ms 最慢={times[-1]*1000:.0f}ms")
    if errors:
        print(f"   错误样例: {errors[:3]}")

def merge_cookies(*jars):
    """把多步拿到的 Set-Cookie 合并成一条 Cookie 头（session_id 在 GET 时先下发）。"""
    merged = {}
    for jar in jars:
        for kv in (jar or "").split("; "):
            if "=" in kv:
                k, v = kv.split("=", 1)
                merged[k] = v
    return "; ".join(f"{k}={v}" for k, v in merged.items())


def open_login_page(cookie=""):
    """打开登录页并**跟随**友好别名跳转；返回 (状态, 最终路径, 正文, 耗时, cookie)。

    t81 修：旧代码写死 `GET /web/login` 必须 200 —— 而本库 /web/login 是
    **302 → /login** 的友好别名（t4 登录页改版）⇒ 旧实现里**每个账号**都在
    "登录页 status=302" 这一步返回失败、T1 也报 40/40 失败：整支压测从来没
    真正登进去过（与 check_odoo_trace 同族的"静默失效"，只是这里表现为 100% 失败）。
    现在跟随跳转，并**在表单实际所在的那条路径上** POST。
    """
    path, t_total, cks = "/web/login", 0.0, cookie
    for _ in range(4):
        s, h, html, dt, ck = req("GET", path, cookie=cks)
        t_total += dt
        cks = merge_cookies(cks, ck)
        loc = h.get("Location") or h.get("location") or ""
        if s in (301, 302, 303) and loc.startswith("/"):
            path = loc
            continue
        return s, path, html, t_total, cks
    return s, path, html, t_total, cks


def session_uid(cookie):
    """会话 uid（0 = 没登进去）。判据与仓内其它脚本统一（t81：不看 POST 的状态码）。"""
    try:
        _, _, body, _, _ = req(
            "POST", "/web/session/get_session_info",
            body=json.dumps({"jsonrpc": "2.0", "method": "call", "params": {}}),
            headers={"Content-Type": "application/json"}, cookie=cookie)
        return (json.loads(body.decode("utf-8", "replace")).get("result") or {}).get("uid") or 0
    except Exception:
        return 0


def anon_one(_):
    try:
        s, _p, _html, dt, _ck = open_login_page()
        # 302→/login 是**设计性**跳转（友好别名），不是失败；只有跟随之后仍非 200 才算。
        return dt, None if s == 200 else f"status={s}"
    except Exception as e:
        return None, repr(e)

def login_one(i):
    """完整登录流：GET 登录页（跟随别名跳转）拿 CSRF+cookie → POST 凭据 → 复核会话 uid。

    返回 (总耗时, cookie|None, err)。判据是**会话 uid**，不是 POST 的状态码 ——
    旧实现要求 POST 必须 303，而登录失败时 Odoo 返回 200 重渲染表单（据此判失败是对的），
    但成功路径的 302/303 因库而异；uid 是唯一不会读错的口径（t81）。
    """
    user, pwd = ACCOUNTS[i % len(ACCOUNTS)]
    try:
        s, path, html, t_get, ck = open_login_page()
        if s != 200:
            return None, None, f"{user}: 登录页 status={s}（跟随跳转后 {path}）"
        m = CSRF_RE.search(html.decode("utf-8", "replace"))
        if not m:
            return None, None, f"{user}: 未找到 csrf_token（{path}）"
        body = urlencode({"login": user, "password": pwd,
                          "csrf_token": m.group(1), "redirect": "/my"})
        # POST 到**表单实际所在的路径**（表单 action 是 /login；旧代码写死 /web/login）
        s2, h2, html2, t_post, ck2 = req("POST", path, body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"}, cookie=ck)
        cks = merge_cookies(ck, ck2)
        uid = session_uid(cks)
        if not uid:
            snippet = html2[:120].decode("utf-8", "replace").replace("\n", " ")
            return None, None, f"{user}: 凭据被拒或会话未建立（POST {path} -> {s2}, uid=0）"
        # 落点请求只是为了量"完整流程"的耗时（状态不再参与判据）
        loc = h2.get("Location", "/my")
        _, _, _, t_my, _ = req("GET", loc if loc.startswith("/") else "/" + loc, cookie=cks)
        return t_get + t_post + t_my, cks, None
        return t_get + t_post + t_my, cks, None
    except Exception as e:
        return None, None, f"{user}: {e!r}"

def browse_one(args):
    ck, paths = args
    errs, total = [], 0.0
    try:
        for _ in range(2):          # 每个虚拟用户连刷两轮
            for p in paths:
                s, _, _, dt, _ = req("GET", p, cookie=ck)
                total += dt
                if s not in (200, 303):
                    errs.append(f"{p} status={s}")
        return total, "; ".join(errs) if errs else None
    except Exception as e:
        return None, repr(e)

def run(name, fn, jobs, workers):
    print(f"\n=== {name}: {len(jobs)} 个请求, {workers} 并发 ===")
    times, errors = [], []
    t0 = time.perf_counter()
    with ThreadPoolExecutor(workers) as ex:
        for item in ex.map(fn, jobs):
            res, err = (item[0] if len(item) == 2 else item[0]), (item[1] if len(item) == 2 else item[-1])
            if err:
                errors.append(err)
            if res is not None:
                times.append(res)
    wall = time.perf_counter() - t0
    report(name, times, errors)
    ok = len(times)
    print(f"   墙钟: {wall:.1f}s  吞吐≈{ok/wall:.1f} 请求/秒")
    return [r[1] for r in zip([None]*len(jobs), [])] if False else None

if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"
    n_login = int(os.environ.get("N_LOGIN", "25"))
    n_sess = int(os.environ.get("N_SESS", "12"))
    # 预热一次，排除首次编译/缓存影响
    req("GET", "/web/login"); req("GET", "/web/login")
    sessions = []

    # ---- 凭据自证（t81）：**先证明每个账号真能登进去**，再读容量数字 ----
    # 为什么必须在最前：旧版把"某个账号凭据失效"混进 T2/T3 的「失败=N」里，
    # 读数字的人会把它当容量/性能问题（错误归因）。这里串行逐账号真登一次，
    # 登不上就**立刻非 0 退出**并点名账号（口令不打印）。
    # 例外：anon 相位不涉及凭据，不需要这道闸门。
    if phase != "anon":
        bad = []
        for i in range(len(ACCOUNTS)):
            t, ck, err = login_one(i)
            if not ck:
                bad.append((ACCOUNTS[i][0], err))
        for login_name, err in bad:
            print(f"[FAIL] 凭据自证：{login_name} 登不上 -> {err}")
        if bad:
            print("\n[FAIL] %d/%d 个账号的登录凭据不可用 —— 上面的失败**不是**容量问题。"
                  "口令可用 EDU_<角色>_PASSWORD 覆盖（STU/FAC/PAR/BO/ADMIN）；"
                  "口令不会被打印。本轮容量数字作废。" % (len(bad), len(ACCOUNTS)))
            sys.exit(1)
        print("[OK] 凭据自证：%d 个账号全部登录成功（登不上会在这里非 0 退出）"
              % len(ACCOUNTS))

    if phase in ("anon", "all"):
        run("T1 匿名同时打开登录页", anon_one, list(range(40)), 40)
    if phase in ("login", "all"):
        r = run(f"T2 {n_login}人同时登录(完整流程)", login_one, list(range(n_login)), n_login)
    if phase in ("browse", "all"):
        # 先串行建立会话供浏览测试
        for i in range(n_sess):
            t, ck, err = login_one(i)
            if ck:
                sessions.append(ck)
        print(f"\n预建会话: {len(sessions)} 个")
        if len(sessions) != n_sess:
            # 旧版只 print 个数就继续 —— 少建 10 个会话时 T3 读的是"更小的负载"，
            # 看起来仍然是绿的（假绿家族）。这里显式失败。
            print(f"[FAIL] 预建会话 {len(sessions)}/{n_sess} —— 少建的会话会让 T3 负载偏小，"
                  "读数不可比（会话建立失败的明细见上面的错误行）")
            sys.exit(1)
        jobs = [(ck, ["/my", "/my/notice_board/notice", "/my/checkin"]) for ck in sessions]
        run(f"T3 已登录学生同时浏览门户({len(sessions)}人×6页)", browse_one, jobs, len(sessions))
