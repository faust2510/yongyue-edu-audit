#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「新建院系部门」表单：**逐字列出用户会看到的每一个标签**（真浏览器口径）。

为什么必须单独做这一次（而不是复用 department_path.py）：
  department_path.py 的 form_labels 只取前 12 个、且 L4 是「建一条能存」的动线断言；
  本脚本回答的是另一个问题：**这张表单从上到下每个标签读起来对不对**（含 tab/分组标题/
  必填星号/字段名→标签映射/列表页列头）。改前改后各跑一次即可逐条对照。

动线：backoffice@local 登录 → 菜单 265（院系部门）列表 → 新建 → 抓全部标签；
      并顺带抓列表页列头（用户点进 265 先看到的那一屏）。
用法：
  python3 tests/smoke/department_form_sweep.py --out tests/smoke/dept_form_labels_before.json
退出码：0 抓取成功；1 有 FAIL（表单打不开）；2 环境不可用。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

try:
    import requests
except ImportError:
    print("FATAL | 需要 requests")
    sys.exit(2)

BASE = os.environ.get("DFS_BASE", "http://localhost:8069")
DB_NAME = os.environ.get("DFS_DB", "edu19")
USER = (os.environ.get("DFS_USER", "backoffice@local"), os.environ.get("DFS_PWD", "demo123"))
MENU_DEPT = 265
ACTION_DEPT = 380
ROOT = Path(__file__).resolve().parent.parent.parent
SHOTS = ROOT / "shots" / "smoke"
SHOTS.mkdir(parents=True, exist_ok=True)

JS_SWEEP = """
() => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  const labels = Array.from(document.querySelectorAll('.o_form_view .o_form_label'));
  const widgets = Array.from(document.querySelectorAll('.o_form_view .o_field_widget[name]'));
  // Odoo 19 的两列布局里 label 与它的 input 不一定在同一 .o_wrap_field 内，
  // 故用「文档顺序里紧随该 label 之后的第一个字段部件」做映射（本表 3 个字段均一对一）。
  const rows = labels.map(l => {
    const next = widgets.find(w => l.compareDocumentPosition(w) & Node.DOCUMENT_POSITION_FOLLOWING);
    const cell = l.closest('.o_cell') || l.parentElement;
    return {
      label: norm(l.textContent),
      field: next ? next.getAttribute('name') : null,
      required: !!(cell && l.textContent.indexOf('*') >= 0)
                || (l.parentElement ? l.parentElement.className.indexOf('required') >= 0 : false),
    };
  });
  // 没有任何 label 的字段（例如只靠 placeholder 的）——必须显式列出来，不能静默漏掉
  const labeled = new Set(rows.map(r => r.field));
  const unlabeled = widgets.filter(w => !labeled.has(w.getAttribute('name')))
                           .map(w => w.getAttribute('name'));
  return {
    field_labels: rows,
    unlabeled_fields: unlabeled,
    all_labels: labels.map(e => norm(e.textContent)),
    group_titles: Array.from(document.querySelectorAll(
      '.o_form_view .o_group_name, .o_form_view .o_horizontal_separator, '
      + '.o_form_view .o_notebook .nav-link'
    )).map(e => norm(e.textContent)).filter(Boolean),
    buttons: Array.from(document.querySelectorAll(
      '.o_control_panel button, .o_form_view header button, .o_form_view .o_cp_buttons button'
    )).map(e => norm(e.textContent)).filter(Boolean),
  };
}
"""


def sess_login():
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + "/web/session/authenticate",
               json={"jsonrpc": "2.0", "method": "call",
                     "params": {"db": DB_NAME, "login": USER[0], "password": USER[1]}},
               timeout=30)
    data = r.json()
    if data.get("error") or not data.get("result", {}).get("uid"):
        print("FATAL | 登录失败：%s" % json.dumps(data, ensure_ascii=False)[:400])
        sys.exit(2)
    return s, data["result"]["uid"]


def sql(sql_text):
    out = subprocess.run(
        ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo", "-d", DB_NAME,
         "-t", "-A", "-c", sql_text],
        capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    args = ap.parse_args()
    sess, uid = sess_login()
    print("PASS | ENV·登录 | %s uid=%s lang=zh_CN" % (USER[0], uid))
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("FATAL | 未安装 playwright")
        sys.exit(2)

    info = {"base": BASE, "db": DB_NAME, "role": USER[0], "uid": uid}
    sid = sess.cookies.get("session_id")
    host = BASE.split("//")[-1].split(":")[0]
    fail = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(locale="zh-CN", viewport={"width": 1500, "height": 1000})
        ctx.add_cookies([{"name": "session_id", "value": sid, "domain": host, "path": "/"}])
        page = ctx.new_page()
        page.goto("%s/odoo/action-%s?menu_id=%s" % (BASE, ACTION_DEPT, MENU_DEPT),
                  wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_selector(".o_control_panel", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        info["breadcrumb"] = page.locator(".o_breadcrumb").first.inner_text().strip() \
            if page.locator(".o_breadcrumb").count() else ""
        # 列表列头：用户点进 265 先看到的那一屏
        info["list_headers"] = page.locator(".o_list_view thead th").all_inner_texts()
        page.screenshot(path=str(SHOTS / "dept_form_sweep_1_list.png"))
        print("读数 | 列表页 | 面包屑=%r 列头=%s"
              % (info["breadcrumb"], json.dumps(info["list_headers"], ensure_ascii=False)))
        # 新建 → 抓全部标签
        opened = False
        for sel in (".o_list_button_add", ".o-kanban-button-new", "button[name='create']"):
            if page.locator(sel).count():
                page.locator(sel).first.click()
                opened = True
                break
        try:
            page.wait_for_selector(".o_form_view", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        info["form_open"] = bool(page.locator(".o_form_view").count())
        info["form_title"] = page.title()
        if info["form_open"]:
            info.update(page.evaluate(JS_SWEEP))
            page.screenshot(path=str(SHOTS / "dept_form_sweep_2_new_form.png"), full_page=True)
        else:
            fail += 1
            print("FAIL | 新建表单未打开（clicked_add=%s）" % opened)
        browser.close()

    print("== 新建表单：标签 → 字段 逐条（DOM 顺序，用户从上到下看到的） ==")
    for row in info.get("field_labels", []):
        print("   %-14s → %-14s %s" % (row["label"], row["field"],
                                       "【必填】" if row["required"] else ""))
    if info.get("unlabeled_fields"):
        print("   ⚠ 没有任何 label 的字段（会静默漏掉，必须显式看）: %s"
              % json.dumps(info["unlabeled_fields"], ensure_ascii=False))
    print("== 表单全部 .o_form_label ==")
    print("   %s" % json.dumps(info.get("all_labels"), ensure_ascii=False))
    print("== 分组/页签标题 ==")
    print("   %s" % json.dumps(info.get("group_titles"), ensure_ascii=False))
    print("== 表单按钮 ==")
    print("   %s" % json.dumps(info.get("buttons"), ensure_ascii=False))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(info, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        print("written %s" % args.out)
    print("== FAIL=%d ==" % fail)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
