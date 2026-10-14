# -*- coding: utf-8 -*-
"""manifest 装载顺序门禁：同一模块内，inherit_id / ref 指向的 xmlid 必须定义在**更早**的 data 文件里。

为什么需要它（2026-10-01 重建生产时真实事故）：
  edu_portal/views/roles.xml 用 inherit_id 继承了 edu_portal/views/enroll.xml 里的
  edu_registrar_subject_approvals，而 enroll.xml 在 manifest 里排在 roles.xml **之后**。
  老库因历次增量升级早就存了该 xmlid，装载期 id_get 直接命中，所以从来没炸；
  全新库 / 首次升级时 id_get 抛 ValueError -> ParseError -> **整个注册表加载失败**
  （实测 -u all 在 Loading module edu_portal (133/135) 处 CRITICAL + exit 255）。
  同类事故本仓此前已发生过一次（docs/plans/ux-v3-verification.md 记的
  「13:13 的 edu_registrar_subject_approvals_bulk 事故」），当时只补了 view xpath 检查，
  没覆盖装载顺序 —— 于是又炸了一次。

用法：
  python3 scripts/check_manifest_order.py             # 全仓扫描；有问题 exit 1
  python3 scripts/check_manifest_order.py --selftest  # 反向注入自证：能红才 exit 0，不能红 exit 3
"""
import ast
import io
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

ADDONS = "custom_addons"
TAG_IDS = ("record", "template", "menuitem", "act_window", "report")
REF_ATTRS = ("inherit_id", "ref", "action", "menu", "parent")


def load_manifest(path):
    src = io.open(path, encoding="utf-8").read()
    src = "\n".join(l for l in src.split("\n") if not l.lstrip().startswith("#"))
    return ast.literal_eval(src[src.index("{"):])


def collect(mod_dir, mod, order):
    ids, refs = set(), []
    for rel in order:
        p = os.path.join(mod_dir, rel)
        if not os.path.exists(p):
            continue
        root = ET.fromstring(io.open(p, encoding="utf-8").read())
        for el in root.iter():
            rid = el.get("id")
            if rid and el.tag in TAG_IDS:
                ids.add((mod + "." + rid, rel))
            for attr in REF_ATTRS:
                v = el.get(attr)
                if v and v.startswith(mod + "."):
                    refs.append((rel, v, attr))
    defined = {}
    for xid, rel in sorted(ids):
        defined.setdefault(xid, rel)
    by_file = {}
    for rel, xid, attr in refs:
        by_file.setdefault(rel, []).append((xid, attr))
    return by_file, defined


def check_order(order, by_file, defined):
    idx = {f: i for i, f in enumerate(order)}
    bad = []
    for f in order:
        for xid, attr in by_file.get(f, []):
            d = defined.get(xid)
            if d is None:
                bad.append(("UNDEFINED", f, xid, attr, ""))
            elif idx.get(d, -1) > idx.get(f, -1):
                bad.append(("ORDER", f, xid, attr, d))
    return bad


def scan_all():
    problems = []
    scanned = 0
    if not os.path.isdir(ADDONS):
        return 0, problems
    for mod in sorted(os.listdir(ADDONS)):
        mod_dir = os.path.join(ADDONS, mod)
        man = os.path.join(mod_dir, "__manifest__.py")
        if not os.path.isfile(man):
            continue
        try:
            m = load_manifest(man)
        except Exception as e:
            problems.append(("MANIFEST_UNREADABLE", mod, str(e), "", ""))
            continue
        order = [d for d in m.get("data", []) if d.endswith(".xml")]
        if not order:
            continue
        scanned += 1
        by_file, defined = collect(mod_dir, mod, order)
        for kind, f, xid, attr, d in check_order(order, by_file, defined):
            problems.append((kind, mod + "/" + f, xid, attr, d))
    return scanned, problems


def selftest():
    tmp = tempfile.mkdtemp()
    md = os.path.join(tmp, "synth_mod")
    os.makedirs(md)
    io.open(os.path.join(md, "b.xml"), "w", encoding="utf-8").write(
        "<odoo><template id=\"base_tpl\" name=\"b\"/></odoo>")
    io.open(os.path.join(md, "a.xml"), "w", encoding="utf-8").write(
        "<odoo><template id=\"child_tpl\" inherit_id=\"synth_mod.base_tpl\" name=\"a\"/></odoo>")
    injected_order = ["a.xml", "b.xml"]
    by_file, defined = collect(md, "synth_mod", injected_order)
    got = len(check_order(injected_order, by_file, defined))
    control_order = ["b.xml", "a.xml"]
    got_control = len(check_order(control_order, by_file, defined))
    ok = (got == 1 and got_control == 0)
    print("SELFTEST injected_inversion_detected=" + str(got) + " control_clean=" + str(got_control))
    if ok:
        print("SELFTEST OK: 尺子能红（注入 1 条被抓），控制组为 0（不是恒红）")
        return 0
    print("SELFTEST FAIL: 尺子坏了，拒绝判绿")
    return 3


def main():
    if "--selftest" in sys.argv:
        return selftest()
    scanned, problems = scan_all()
    print("MANIFEST_ORDER scanned_modules=" + str(scanned) + " problems=" + str(len(problems)))
    for kind, where, xid, attr, d in problems:
        tail = ("  (defined later in " + d + ")") if d else ""
        print("  " + kind + "  " + where + "  -> " + xid + "  via " + attr + tail)
    if problems:
        print("MANIFEST_ORDER FAIL")
        return 1
    print("MANIFEST_ORDER PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())