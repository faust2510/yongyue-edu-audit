#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""空态巡检：按角色逐页抓「页面为空的时候到底显示什么」。

为什么要有它：check_ui_usability.py 的 D 轴只判「空 + 无出口」这种极端死胡同，
判据自述「不看文案」；空态质量（有没有说清现状、有没有下一步）在门禁里是盲区。
本脚本把 D 轴那条结构性判据放大到文案层：同一套名单（tests/ui/surface.json scope=portal）、
同一套实例解析（dead-45.json）、同一套身份口令，逐页抓 DOM + 可见文本，落盘成可复核的 JSON。

口径：
  · 视口 375x812（与 D 轴门禁同口径，空/非空的结构判据才可比）；
  · 登录走 /web/session/authenticate（db=edu19），cookie 注进浏览器上下文；
  · 只 GET、不点不写；副作用路由沿用门禁的 side_effect_reason() 直接跳过；
  · 每个路径对「该页登记的全部角色」各探一次（门禁只取 1-2 个身份，会漏「学生看得见、家长看不见」）。

用法：
    /opt/homebrew/bin/python3 docs/audit/empty-states/sweep.py --tag before
"""
import argparse
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import check_ui_usability as gate  # noqa: E402

VIEWPORT = {"width": 375, "height": 812}

MEASURE_JS = """() => {
  const norm = s => (s || "").replace(/\\s+/g, " ").trim();
  const q = s => document.querySelectorAll(s).length;
  const main = document.querySelector("main") || document.querySelector("#wrap") || document.body;
  const headings = [];
  document.querySelectorAll("h1,h2,h3,h4,h5").forEach(h => {
    const t = norm(h.innerText); if (t) headings.push(t.slice(0, 90)); });
  const HINT = /暂未|暂无|没有|还没有|尚未|未开放|未获得|未配置|无记录|无数据|未分配|未分班|空白|空空|未选课|未发布|未提交|待办|等待/;
  const hints = [];
  const seen = {};
  document.querySelectorAll("p,div,span,td,li,h2,h3,h4,em,strong,small").forEach(el => {
    if (el.children.length > 2) return;
    const t = norm(el.innerText);
    if (!t || t.length > 160) return;
    if (!HINT.test(t)) return;
    const k = t.slice(0, 60);
    if (seen[k]) return;
    seen[k] = 1;
    hints.push({text: t.slice(0, 160), tag: el.tagName.toLowerCase(),
                cls: (el.className || "").toString().slice(0, 90),
                html: el.outerHTML.slice(0, 500)});
  });
  const emptyBlocks = [];
  document.querySelectorAll(".oe-norec, .oe-empty, .o_view_nocontent, .o_nocontent_help, [class*=nocontent]").forEach(el => {
    emptyBlocks.push({cls: (el.className || "").toString().slice(0, 90),
                      text: norm(el.innerText).slice(0, 220),
                      links: el.querySelectorAll("a[href]").length,
                      html: el.outerHTML.slice(0, 800)});
  });
  const links = [];
  document.querySelectorAll("a[href]").forEach(a => links.push(
    {href: a.getAttribute("href"), text: norm(a.innerText).slice(0, 40)}));
  const tables = [];
  document.querySelectorAll("table").forEach(t => tables.push(
    {rows: t.querySelectorAll("tbody tr").length,
     head: norm((t.querySelector("thead") || t).innerText).slice(0, 200)}));
  const buttons = [];
  document.querySelectorAll("button,.btn,a.btn,input[type=submit]").forEach(b => {
    const t = norm(b.innerText || b.value || ""); if (t) buttons.push(t.slice(0, 40)); });
  return {title: document.title, rows: q("table tbody tr"), cards: q(".card"),
          asgCards: q(".oe-asg-card"), libCards: q("[class*=oe-lib-card]"),
          records: q("table tbody tr") + q(".card") + q(".oe-asg-card"),
          tables: tables, headings: headings, hints: hints.slice(0, 12),
          emptyBlocks: emptyBlocks.slice(0, 8),
          mainText: norm(main.innerText).slice(0, 3000),
          links: links.slice(0, 80), buttons: buttons.slice(0, 25),
          forms: q("form"), inputs: q("input,textarea,select"),
          bodyLen: (document.body.innerHTML || "").length};
}"""


def login_custom(login, pwd):
    """单账号会话（夹具账号用；口令经 /web/session/authenticate 校验，同门禁口径）。"""
    s = gate.requests.Session()
    s.trust_env = False
    try:
        r = s.post(gate.BASE + "/web/session/authenticate",
                   json={"jsonrpc": "2.0",
                         "params": {"db": gate.DB, "login": login, "password": pwd}},
                   timeout=25)
        s._dsh_uid = (r.json().get("result") or {}).get("uid")
    except Exception as e:
        s._dsh_uid = "ERR:%s" % e
    return s


def build_plan_single_role(rows, instances, label, log=print):
    """单账号计划：该账号扫**全部** portal 路径（不看登记表的角色列）。"""
    probe, skipped = [], []
    for row in rows:
        tpl = row["path"]
        why = gate.side_effect_reason(tpl)
        dync = bool(gate.DYN_SEG_RE.search(tpl))
        inst = instances.get(tpl)
        if dync and not inst:
            skipped.append({"path": tpl, "role": label, "skipped": "no-instance"})
            continue
        if why:
            skipped.append({"path": tpl, "role": label, "skipped": why})
            continue
        probe.append({"role": label, "path": inst if dync else tpl,
                      "path_template": tpl, "src": "sweep:single-role"})
    log("单账号计划：探页 %d 条 / 排除 %d 条" % (len(probe), len(skipped)))
    return probe, skipped


def _block_external(route):
    """屏蔽站外请求（fonts.googleapis.com 的 @import 会把 DOMContentLoaded 拖到 30s 超时，
    见 check_ui_usability.py 的 BROWSER_RESTART_EVERY 注释）。本巡检只判文案与出口，
    不判像素布局 ⇒ 屏蔽外网不改变结论，但把每条探页从 ~8s 压到 ~1s。"""
    url = route.request.url
    if url.startswith(gate.BASE) or url.startswith("data:") or url.startswith("blob:"):
        route.continue_()
    else:
        route.abort()


def build_plan_all_roles(rows, instances, log=print):
    probe, skipped = [], []
    for row in rows:
        tpl = row["path"]
        why = gate.side_effect_reason(tpl)
        dync = bool(gate.DYN_SEG_RE.search(tpl))
        inst = instances.get(tpl)
        if dync and not inst:
            skipped.append({"path": tpl, "role": "-", "skipped": "no-instance"})
            continue
        real = inst if dync else tpl
        roles = [r for r in (row.get("roles") or [])
                 if r in gate.ROLE_LOGINS or r in ("anon", "guest")]
        if not roles:
            roles = ["guest"]
        for role in roles:
            if why:
                skipped.append({"path": tpl, "role": role, "skipped": why})
                continue
            probe.append({"role": "guest" if role == "anon" else role,
                          "path_template": tpl, "path": real, "src": "sweep:all-roles"})
    log("计划：探页 %d 条 / 排除 %d 条" % (len(probe), len(skipped)))
    return probe, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="run")
    ap.add_argument("--only", default="", help="只探含该子串的路径（调试用）")
    ap.add_argument("--as", dest="as_login", default="",
                    help="单账号模式 login:password[:label]（只探这一个身份）")
    args = ap.parse_args()
    rows, err = gate.load_surface()
    if err:
        print("INCOMPLETE: %s" % err)
        return 3
    if args.as_login:
        parts = args.as_login.split(":")
        label = parts[2] if len(parts) > 2 else "custom"
        probe, skipped = build_plan_single_role(rows, gate.load_instances(), label)
        seed_sessions = {label: login_custom(parts[0], parts[1])}
    else:
        probe, skipped = build_plan_all_roles(rows, gate.load_instances())
        seed_sessions = {}
    if args.only:
        probe = [p for p in probe if args.only in p["path"]]
    sessions = dict(seed_sessions)
    results = []
    web = None
    try:
        names = __import__("subprocess").run(["docker", "ps", "--format", "{{.Names}}"],
                                            capture_output=True, text=True, timeout=15).stdout.split()
        web = next((n for n in names if n.endswith("web-1")), None)
    except Exception:
        web = None

    def started_at():
        if not web:
            return None
        try:
            return __import__("subprocess").run(["docker", "inspect", "-f", "{{.State.StartedAt}}", web],
                                               capture_output=True, text=True, timeout=15).stdout.strip()
        except Exception:
            return None

    ctr_before = started_at()
    started = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    with gate.sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True,
                                     args=["--no-proxy-server"])
        for i, item in enumerate(probe, 1):
            role, path = item["role"], item["path"]
            if role not in sessions:
                sessions[role] = gate.login_session(role)
            cookie = sessions[role].cookies.get("session_id")
            ctx = browser.new_context(viewport=VIEWPORT)
            ctx.route("**/*", _block_external)
            if cookie:
                ctx.add_cookies([{"name": "session_id", "value": cookie,
                                  "domain": "localhost", "path": "/"}])
            page = ctx.new_page()
            t0 = time.time()
            rec = {"role": role, "path": path, "path_template": item["path_template"],
                   "collected_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
            try:
                resp = page.goto(gate.BASE + path, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(250)
                st = page.evaluate(MEASURE_JS)
                rec.update(st)
                rec["http"] = resp.status if resp else None
                rec["ctype"] = (resp.headers or {}).get("content-type", "") if resp else ""
                rec["final_path"] = page.url.split("8069")[-1] or "/"
                rec["verdict"] = "ok"
            except Exception as e:
                rec["verdict"] = "error"
                rec["error"] = str(e)[:200]
            rec["ms"] = int((time.time() - t0) * 1000)
            results.append(rec)
            ctx.close()
            empty = (rec.get("rows") == 0 and rec.get("cards") == 0 and rec.get("records") == 0
                     and rec.get("verdict") == "ok")
            print("  [%3d/%3d] %-10s %-46s %s rows=%s cards=%s hints=%s %s"
                  % (i, len(probe), role, path, rec.get("http"), rec.get("rows"),
                     rec.get("cards"), len(rec.get("hints") or []),
                     "EMPTY" if empty else ""))
            sys.stdout.flush()
        browser.close()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    ctr_after = started_at()
    out = {"meta": {"tag": args.tag, "started": started,
                    "container": {"name": web, "before": ctr_before, "after": ctr_after,
                                  "sample_valid": (ctr_before is None or ctr_after is None
                                                   or ctr_before == ctr_after)},
                    "finished": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "viewport": VIEWPORT, "probes": len(probe), "skipped": len(skipped),
                    "source": "tests/ui/surface.json (scope=portal) x all roles"},
           "readings": results, "skipped": skipped}
    p = os.path.join(HERE, "sweep-%s-%s.json" % (args.tag, stamp))
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("落盘：%s" % p)
    empties = [r for r in results if r.get("rows") == 0 and r.get("cards") == 0
               and r.get("verdict") == "ok"]
    print("空态页（无列表行且无卡片）：%d / %d" % (len(empties), len(results)))
    for r in empties:
        print("  · %-10s %-44s hints=%d  %s" % (r["role"], r["path"], len(r.get("hints") or []),
                                                " | ".join(h["text"][:60] for h in (r.get("hints") or [])[:3])))
    return 0


if __name__ == "__main__":
    sys.exit(main())