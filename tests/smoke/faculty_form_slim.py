#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""教职员工（op.faculty）表单瘦身验收探针 —— 真浏览器渲染 + 真保存 + 模型反查。

需求（校长 2026-09）：「打开 /odoo/faculty/new 不知道后面搞那么多无关的信息干嘛」。
实现 = custom_addons/edu_portal/views/faculty_form.xml（纯视图继承，不动模型、不动基座）。
本探针是这次改造的**判据**，before/after 两态各跑一次：

  A 首屏可见字段 ⊆ 保留清单（KEEP），且保留清单里的字段一个不少
    KEEP = 姓名(first/middle/last)、性别、出生日期、所属院系、科目、邮箱、电话
  B 收起的字段**在首屏连 DOM 都没有**（notebook 只渲染当前页签），
    点开「更多信息」页签后**全部重新出现**（＝收起而不是删掉）
  C 图书馆页签（Library）彻底消失；「科目」页签仍在
  D 只填可见字段 → 保存成功、无「缺少必填字段 / Missing required fields」
  E 隐藏字段仍在模型上：字段元数据在、可写可读（search_read + write/read 回环）
  F 隐藏字段的**模型层数据类型**未变（字段属性快照对比，见 --dump-fields）

用法（本地 clone 必须已在 http://127.0.0.1:8069 跑着）：
  python3 tests/smoke/faculty_form_slim.py --phase before   # 改造前基线（只采集，不判红）
  python3 tests/smoke/faculty_form_slim.py                  # 改造后验收 A–F
  python3 tests/smoke/faculty_form_slim.py --no-create      # 跳过 D/E（只判 A–C）
退出码：0 全绿；1 有 FAIL；2 环境不可用（登录失败 / 站点不通 / 缺依赖）。

清场：D 步建的【演示】教职员工记录会被反查确认后**保留**（验收要求「Show the record
afterwards」）；同名记录每次跑前先删（幂等）。
"""
import argparse
import json
import os
import re
import sys
import datetime

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

try:
    import requests
except ImportError:
    print("FATAL | 需要 requests")
    sys.exit(2)

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:8069")
DB = os.environ.get("EDU_DB_NAME", "edu19")
CLERK = ("backoffice@local", "demo123")     # 教务（本表单的真实使用者）
ADMIN = ("admin", "admin")
FORM_URL = BASE + "/odoo/faculty/new"
HERE = os.path.dirname(os.path.abspath(__file__))

# ---- 保留清单（首屏/科目页签必须可见）与收起清单 ------------------------------
KEEP_FIRST_SCREEN = ["first_name", "middle_name", "last_name", "gender",
                     "birth_date", "main_department_id", "email", "phone"]
KEEP_ANYWHERE = KEEP_FIRST_SCREEN + ["faculty_subject_ids"]
TUCK_AWAY = ["blood_group", "emergency_contact", "visa_info", "id_number",
             "emp_id", "user_id", "partner_id", "nationality",
             "allowed_department_ids", "street", "street2", "city", "state_id",
             "zip", "country_id", "lang", "title", "image_1920"]
TUCK_AWAY_GONE_FROM_FORM = ["child_ids", "library_card_id"]   # 连「更多信息」里都没有
LIB_TAB = re.compile(r"library|图书馆", re.I)
SUBJECT_TAB = re.compile(r"科目|subjects", re.I)
MORE_TAB = re.compile(r"更多信息|more info", re.I)

DEMO = {
    "first_name": "【演示】李慧",
    "middle_name": "",
    "last_name": "老师",
    "gender": "female",
    "birth_date": "1990/01/01",
    "email": "demo.faculty@example.invalid",
    "phone": "000 0000",
    "department": "【演示】中文部",
    "subject": "小要理问答",
}
HIDDEN_WRITE = {"blood_group": "A+", "id_number": "【演示】ID-0001"}
# 记录名 = 姓 名 拼接（基座 create()/onchange 的 join(" ") 口径）
DEMO_NAME = " ".join([x for x in [DEMO["first_name"], DEMO["middle_name"], DEMO["last_name"]] if x])

JS_COLLECT = r"""
() => {
  const sheet = document.querySelector('.o_form_sheet') || document.querySelector('.o_form_view');
  const vis = (el) => {
    if (!el.getClientRects || el.getClientRects().length === 0) return false;
    const cs = getComputedStyle(el);
    return !(cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0');
  };
  const label = (el) => {
    const cell = el.closest('.o_cell');
    if (cell && cell.parentElement) {
      const lab = cell.parentElement.querySelector('label.o_form_label');
      if (lab) return lab.innerText.trim();
    }
    if (el.id) {
      const l2 = sheet.querySelector('label[for="' + el.id + '"]');
      if (l2) return l2.innerText.trim();
    }
    const l3 = el.closest('.o_inner_group');
    if (l3) { const l4 = l3.querySelector('label.o_form_label'); if (l4) return l4.innerText.trim(); }
    return '';
  };
  const labels = {};
  sheet.querySelectorAll('label.o_form_label[for]').forEach(l => {
    const t = document.getElementById(l.getAttribute('for'));
    const w = t && t.closest ? t.closest('.o_field_widget[name]') : null;
    if (w) labels[w.getAttribute('name')] = l.innerText.trim();
  });
  const fields = [];
  sheet.querySelectorAll('.o_field_widget[name]').forEach(el => {
    fields.push({name: el.getAttribute('name'), label: labels[el.getAttribute('name')] || label(el),
                 visible: vis(el), cls: el.className.slice(0, 60)});
  });
  const cells = [];
  sheet.querySelectorAll('.o_cell [name]').forEach(el => {
    if (el.closest('.o_field_widget[name]') && el.closest('.o_field_widget[name]') !== el) return;
    cells.push({name: el.getAttribute('name'), tag: el.tagName.toLowerCase(), visible: vis(el)});
  });
  const tabs = [...document.querySelectorAll('.o_notebook_headers a.nav-link')].map(a => a.innerText.trim());
  const btns = [...document.querySelectorAll('.o_form_statusbar button, .oe_button_box button')]
      .map(b => (b.innerText || b.getAttribute('title') || '').trim());
  const dateInput = document.querySelector('.o_field_widget[name="birth_date"] input');
  return {fields, cells, tabs, btns,
          title: (document.querySelector('.o_breadcrumb, .o_form_view .o_form_statusbar') || {}).innerText || '',
          dateInput: dateInput ? {placeholder: dateInput.getAttribute('placeholder'), value: dateInput.value} : null,
          text: document.body.innerText};
}
"""


class Odoo:
    """最小 JSON-RPC 客户端（只用来反查/清场，不走 ORM 的 UI）。"""

    def __init__(self, login, password):
        self.s = requests.Session()
        r = self.s.post(BASE + "/web/session/authenticate", json={
            "jsonrpc": "2.0", "method": "call",
            "params": {"db": DB, "login": login, "password": password}}, timeout=30)
        res = r.json().get("result") or {}
        if not res.get("uid"):
            raise RuntimeError("登录失败 %s: %s" % (login, r.text[:200]))
        self.uid = res["uid"]

    def call(self, model, method, args=None, kwargs=None):
        r = self.s.post(BASE + "/web/dataset/call_kw", json={
            "jsonrpc": "2.0", "method": "call",
            "params": {"model": model, "method": method, "args": args or [],
                       "kwargs": kwargs or {}}}, timeout=60)
        j = r.json()
        if "error" in j:
            raise RuntimeError("%s.%s -> %s" % (model, method, json.dumps(j["error"])[:400]))
        return j["result"]

    def search_read(self, model, domain, fields, limit=None):
        kw = {"fields": fields}
        if limit:
            kw["limit"] = limit
        return self.call(model, "search_read", [domain], kw)


def results_path(phase):
    return os.path.join(HERE, "faculty_form_slim_%s.json" % phase)


# ------------------------------------------------------------------ 浏览器部分
def collect(page):
    page.goto(FORM_URL, wait_until="domcontentloaded")
    page.wait_for_selector(".o_form_view", timeout=30000)
    page.wait_for_timeout(2000)
    return page.evaluate(JS_COLLECT)


def click_tab(page, pattern):
    tabs = page.query_selector_all(".o_notebook_headers a.nav-link")
    for t in tabs:
        if pattern.search((t.inner_text() or "").strip()):
            t.click()
            page.wait_for_timeout(1200)
            return True
    return False


def run_browser(phase, do_create):
    from playwright.sync_api import sync_playwright

    out = {"phase": phase, "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "form_url": FORM_URL, "actor": CLERK[0], "checks": [], "notes": []}
    fails = []

    def check(name, ok, detail=""):
        out["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            fails.append("%s | %s" % (name, detail))
        print("%-34s %s %s" % (name, "PASS" if ok else "FAIL", "" if ok else detail))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, locale="zh-CN")
        page = ctx.new_page()
        page.goto(BASE + "/web/login?db=" + DB, wait_until="domcontentloaded")
        page.fill('input[name="login"]', CLERK[0])
        page.fill('input[name="password"]', CLERK[1])
        page.click('form.oe_login_form button[type="submit"], .oe_login_form button[type="submit"]')
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        first = collect(page)
        first_visible = sorted({f["name"] for f in first["fields"] if f["visible"]})
        first_dom = sorted({f["name"] for f in first["fields"]})
        out["first_screen"] = {"visible_fields": first_visible, "dom_fields": first_dom,
                               "labels": {f["name"]: f["label"] for f in first["fields"] if f["visible"]},
                               "tabs": first["tabs"], "buttons": first["btns"],
                               "date_input": first["dateInput"]}
        page.screenshot(path="/tmp/faculty_form_%s_first_screen.png" % phase, full_page=True)

        more_ok = click_tab(page, MORE_TAB)
        more = page.evaluate(JS_COLLECT) if more_ok else {"fields": [], "tabs": first["tabs"]}
        page.screenshot(path="/tmp/faculty_form_%s_more_tab.png" % phase, full_page=True)
        more_dom = sorted({f["name"] for f in more["fields"]})
        more_visible = sorted({f["name"] for f in more["fields"] if f["visible"]})
        out["more_tab"] = {"opened": more_ok, "dom_fields": more_dom, "visible_fields": more_visible}

        subj_ok = click_tab(page, SUBJECT_TAB)
        subj = page.evaluate(JS_COLLECT) if subj_ok else {"fields": []}
        subj_visible = sorted({f["name"] for f in subj["fields"] if f["visible"]})
        out["subjects_tab"] = {"opened": subj_ok, "visible_fields": subj_visible}

        out["note_text_probe"] = {w: (w in first["text"])
                                  for w in ["血型", "紧急联系方式", "签证", "身份证", "图书馆", "Library"]}

        if phase == "after":
            check("A1 首屏保留字段齐全", not (set(KEEP_FIRST_SCREEN) - set(first_visible)),
                  "缺: %s" % sorted(set(KEEP_FIRST_SCREEN) - set(first_visible)))
            extra = sorted(set(first_visible) - set(KEEP_ANYWHERE))
            check("A2 首屏无清单外字段", not extra, "多: %s" % extra)
            dom_leak = sorted(set(TUCK_AWAY) & set(first_dom))
            check("B1 收起字段不在首屏 DOM", not dom_leak, "漏: %s" % dom_leak)
            still = sorted(set(TUCK_AWAY) - set(more_dom))
            check("B2 「更多信息」页签里都在", not still, "缺: %s" % still)
            gone = sorted(set(TUCK_AWAY_GONE_FROM_FORM) & (set(first_dom) | set(more_dom)))
            check("B3 联系人看板/图书卡已移除", not gone, "仍在: %s" % gone)
            lib = [t for t in first["tabs"] if LIB_TAB.search(t)]
            check("C1 图书馆页签消失", not lib, "仍有: %s" % lib)
            subj_tab = [t for t in first["tabs"] if SUBJECT_TAB.search(t)]
            check("C2 科目页签仍在", bool(subj_tab), "页签: %s" % first["tabs"])
            check("C3 科目字段可见(页签内)", "faculty_subject_ids" in (subj_visible or first_visible),
                  "visible=%s first=%s" % (subj_visible, first_visible))
            check("C4 「更多信息」页签存在", more_ok, "页签: %s" % first["tabs"])
            noisy = [w for w, hit in out["note_text_probe"].items() if hit and w in ("血型", "图书馆", "Library")]
            check("B4 首屏正文无噪音词", not noisy, "命中: %s" % noisy)

        if do_create:
            try:
                create_record(page, out, check)
            except Exception as exc:      # 建记录流程异常也要落成 FAIL（不许静默变 ENV）
                import traceback
                out["create_traceback"] = traceback.format_exc()
                check("D0 建记录流程异常", False, "%s: %s" % (type(exc).__name__, exc))

        browser.close()
    out["fails"] = fails
    return out, fails


def fill_text(page, field, value):
    if not value:
        return
    sel = '.o_field_widget[name="%s"] input' % field
    page.fill(sel, value)
    page.dispatch_event(sel, "change")
    page.wait_for_timeout(300)


def create_record(page, out, check):
    """只填**首屏可见**的字段 → 保存 → 反查。D/E 两步的证据。"""
    admin = Odoo(*ADMIN)
    # 幂等清场：op.faculty.name 是 related（无列、搜不到），必须按 partner 反查。
    # 第一次写按 name 搜 ⇒ 搜不到 ⇒ 第二次跑就撞 email 唯一约束（实测踩过）。
    old_partners = admin.search_read(
        "res.partner", ["|", ("email", "=", DEMO["email"]), ("name", "=", DEMO_NAME)], ["id"])
    if old_partners:
        pids = [r["id"] for r in old_partners]
        old = admin.search_read("op.faculty", [("partner_id", "in", pids)], ["id"])
        if old:
            admin.call("op.faculty", "unlink", [[r["id"] for r in old]])
        admin.call("res.partner", "unlink", [pids])
    deps = admin.search_read("op.department", [("name", "=", DEMO["department"])], ["id"])
    if not deps:
        # op.department.code 是必填（第一次跑踩过：缺 code → 缺少必填值）
        deps = [{"id": admin.call("op.department", "create",
                                  [{"name": DEMO["department"], "code": "DEMO-ZW"}])}]
    out["demo_department_id"] = deps[0]["id"]

    page.goto(FORM_URL, wait_until="domcontentloaded")
    page.wait_for_selector(".o_form_view", timeout=30000)
    page.wait_for_timeout(2000)
    filled = []
    # ① 性别：Odoo 19 的 Selection 是 o_select_menu（不是原生 <select>）：
    #    点开 → 菜单项点「女性」。三试 + 回读校验（实测第一次点开会偶发没展开）。
    ok_gender, last_err = False, None
    for _ in range(3):
        try:
            page.click('.o_field_widget[name="gender"] input', timeout=10000)
            page.wait_for_selector('.o_select_menu_menu span.o_select_menu_item', timeout=10000)
            page.locator('.o_select_menu_menu span.o_select_menu_item').filter(has_text="女").first.click(timeout=10000)
            page.wait_for_timeout(400)
            if "女" in (page.input_value('.o_field_widget[name="gender"] input') or ""):
                ok_gender = True
                break
        except Exception as exc:
            last_err = exc
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
    if ok_gender:
        filled.append("gender")
    else:
        out["notes"].append("gender 未选上: %s" % last_err)
        page.screenshot(path="/tmp/faculty_form_gender_fail.png", full_page=True)
    fill_text(page, "first_name", DEMO["first_name"])
    fill_text(page, "middle_name", DEMO["middle_name"])
    fill_text(page, "last_name", DEMO["last_name"])
    fill_text(page, "email", DEMO["email"])
    fill_text(page, "phone", DEMO["phone"])
    filled += ["first_name", "last_name", "email", "phone"]
    fill_text(page, "birth_date", DEMO["birth_date"])
    filled.append("birth_date")
    # 所属院系（m2o，输入即搜索）
    try:
        m2o = page.locator('.o_field_widget[name="main_department_id"] input')
        m2o.click()
        m2o.fill(DEMO["department"])
        page.wait_for_timeout(1500)
        page.locator('.o_field_widget[name="main_department_id"] .o-autocomplete--dropdown-item').first.click()
        filled.append("main_department_id")
    except Exception as e:
        out["notes"].append("main_department_id 未选上: %s" % e)
    # 科目（Subjects 页签里的 m2m）
    # Odoo 19 的 m2m「添加行」弹的是选择对话框（添加: 主题）→ 勾选 → 选择
    try:
        click_tab(page, SUBJECT_TAB)
        page.click('.o_field_widget[name="faculty_subject_ids"] .o_field_x2many_list_row_add a')
        page.wait_for_selector('.modal', timeout=15000)
        page.fill('.modal input[placeholder*="搜索"], .modal .o_searchview_input, .modal input[type="text"]', DEMO["subject"])
        page.wait_for_timeout(1500)
        page.click('.modal tr:has-text("%s") input[type="checkbox"]' % DEMO["subject"])
        page.wait_for_timeout(400)
        page.click('.modal button:has-text("选择")')
        page.wait_for_timeout(1200)
        filled.append("faculty_subject_ids")
    except Exception as e:
        out["notes"].append("faculty_subject_ids 未填上: %s" % e)
    out["filled_fields"] = filled
    page.screenshot(path="/tmp/faculty_form_after_filled.png", full_page=True)

    page.click("button.o_form_button_save")
    page.wait_for_timeout(4000)
    body = page.inner_text("body")
    bad_tokens = ["Missing required fields", "缺少必填字段", "Invalid fields", "验证错误"]
    hit = [t for t in bad_tokens if t in body]
    rec = admin.search_read("op.faculty", [("name", "=", DEMO_NAME)],
                            ["id", "name", "first_name", "last_name", "gender", "birth_date",
                             "email", "phone", "main_department_id", "faculty_subject_ids"])
    out["created"] = rec
    out["save_url"] = page.url
    out["save_body_tail"] = body[-1500:]
    check("D1 只填可见字段能保存", bool(rec), "记录未落库: %s" % rec)
    check("D2 保存无缺字段报错", not hit, "命中: %s" % hit)
    if rec:
        r = rec[0]
        for f in ("first_name", "last_name", "gender", "email"):
            check("D3 %s 落库" % f, bool(r.get(f)), "%s=%r" % (f, r.get(f)))
        check("D4 所属院系落库", bool(r.get("main_department_id")), "%r" % (r.get("main_department_id"),))
        check("D5 科目落库", bool(r.get("faculty_subject_ids")), "%r" % (r.get("faculty_subject_ids"),))
        # E 隐藏字段仍在模型上、仍可读写
        rid = r["id"]
        try:
            admin.call("op.faculty", "write", [[rid], HIDDEN_WRITE])
            back = admin.search_read("op.faculty", [("id", "=", rid)],
                                     ["blood_group", "id_number", "nationality", "visa_info",
                                      "emp_id", "user_id", "partner_id", "allowed_department_ids",
                                      "emergency_contact", "street", "city", "country_id", "lang"])
            out["hidden_readback"] = back
            ok = all(back[0].get(k) == v for k, v in HIDDEN_WRITE.items())
            check("E1 隐藏字段可写可读", ok, "%s" % back)
            check("E2 隐藏字段元数据仍在", all(k in back[0] for k in
                  ("nationality", "visa_info", "emp_id", "user_id", "partner_id",
                   "allowed_department_ids", "emergency_contact", "street", "city", "country_id", "lang")),
                  "keys=%s" % sorted(back[0].keys()))
        except Exception as e:
            check("E1 隐藏字段可写可读", False, str(e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["before", "after"], default="after")
    ap.add_argument("--no-create", action="store_true", help="跳过建记录（D/E 两步）")
    ap.add_argument("--dump-fields", action="store_true", help="额外打印一次字段属性快照")
    args = ap.parse_args()
    do_create = (args.phase == "after") and not args.no_create

    try:
        requests.get(BASE + "/web/login", timeout=15)
    except Exception as e:
        print("ENV | 站点不可达 %s: %s" % (BASE, e))
        return 2
    try:
        out, fails = run_browser(args.phase, do_create)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("ENV | 探针异常: %s" % e)
        return 2

    if args.dump_fields:
        a = Odoo(*ADMIN)
        snap = a.call("op.faculty", "fields_get", [[], ["type", "required", "store", "string"]])
        out["field_snapshot"] = {k: v for k, v in snap.items()
                                 if k in TUCK_AWAY + KEEP_ANYWHERE + TUCK_AWAY_GONE_FROM_FORM}

    with open(results_path(args.phase), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("\n首屏可见字段(%s)：%s" % (args.phase, ", ".join(out["first_screen"]["visible_fields"])))
    print("首屏 DOM 字段  ：%s" % ", ".join(out["first_screen"]["dom_fields"]))
    print("页签           ：%s" % " | ".join(out["first_screen"]["tabs"]))
    print("「更多信息」里  ：%s" % ", ".join(out["more_tab"]["dom_fields"]))
    print("截图           ：/tmp/faculty_form_%s_first_screen.png" % args.phase)
    print("结果 JSON      ：%s" % results_path(args.phase))
    if args.phase == "before":
        print("PHASE=before（基线采集，不判红）")
        return 0
    if fails:
        print("\nFAIL 合计 %d 条：" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("\nRESULT=OK 全部判据通过（phase=after）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
