#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下拉框内容冒烟：防「字典被 QWeb 直接遍历」字母化回归 + 分类档案接线检查。

背景（2026-09-15 用户报「这个 a u 什么的是什么」）：
模板写成 <t t-foreach="state_label" t-as="s"><option value="s[0]">s[1]</option>
而状态字典是 dict，QWeb 遍历 dict 得到的是 key 字符串 ⇒ 选项变成 "e p e a"，
value 变成 'r'/'a'/'p' 等非法值：筛选静默失效、记账方向恒被兜底成「应收」。

2026-09-16 起分类改为**可配置档案** edu.fee.category（校方自助增删），
故本脚本的分类断言从「7 个固定标签」改为「按 sequence 顺序的中文名 + 数值 id」。

用法：python3 tests/smoke/ledger_select_labels.py
环境变量：EDU_BASE（默认 http://127.0.0.1:8069）、EDU_LOGIN/EDU_PWD（默认 admin/admin）
"""
import os
import re
import sys

import requests

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
BASE = os.environ.get("EDU_BASE", "http://127.0.0.1:8069")
LOGIN = os.environ.get("EDU_LOGIN", "admin")
PWD = os.environ.get("EDU_PWD", "admin")
P = {"http": None, "https": None}
HDRS = {"Accept-Language": "zh-CN,zh;q=0.9"}

# 分类档案的初始清单（sequence 顺序；改种子数据时同步这里）
CATEGORY_ORDER = ["统筹", "房租", "交通", "活动", "接待", "补助", "补贴",
                  "课时费", "粮草", "日常物品", "奉献", "礼物", "教材",
                  "打印", "其他"]
# 这些分类带「方向倾向」；通用项两边都能选
PAYABLE_ONLY = {"房租", "接待", "补助", "补贴", "课时费", "粮草", "日常物品"}
RECEIVABLE_ONLY = {"统筹", "奉献"}

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS | %s | %s" % (name, detail))
    else:
        fail += 1
        print("FAIL | %s | %s" % (name, detail))


def login():
    s = requests.Session()
    s.headers.update(HDRS)
    r = s.get(BASE + "/web/login", headers=HDRS, proxies=P)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    s.post(BASE + "/web/login",
           data={"login": LOGIN, "password": PWD,
                 "csrf_token": m.group(1) if m else "",
                 "redirect": "/my/home"},
           allow_redirects=True, proxies=P)
    return s


def options(html, select_name):
    """取出某个 <select name=...> 里的 [(value, label)]。"""
    m = re.search(r'<select[^>]*name="%s"[^>]*>(.*?)</select>'
                  % re.escape(select_name), html, re.S)
    if not m:
        return None
    return [(v, re.sub(r"<[^>]+>", "", lab).strip())
            for v, lab in re.findall(
                r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', m.group(1), re.S)]


def labels_of(html, select_name):
    opts = options(html, select_name)
    return None if opts is None else [lab for _, lab in opts]


s = login()
r = s.get(BASE + "/ledger", allow_redirects=True, proxies=P)
check("登录并打开 /ledger", r.status_code == 200 and "财务总台账" in r.text,
      "code=%d" % r.status_code)

EXPECT_SIMPLE = {
    "direction": {"": "全部", "receivable": "应收", "payable": "应付"},
    "state": {"": "全部", "open": "待缴", "partial": "部分缴纳",
              "paid": "已缴清", "void": "作废"},
    "reimburse": {"": "全部", "request": "申请中", "approved": "已同意待付",
                  "refused": "已驳回", "paid": "已付款"},
}
for name, want in EXPECT_SIMPLE.items():
    got = options(r.text, name)
    check("/ledger 筛选 %s 选项 = %d 项且标签为中文"
          % (name, len(want)), got is not None and dict(got) == want,
          "实际=%s" % (got,))

# 分类：值必须是数值 id，标签必须是档案里的中文名且按 sequence 排序
cat_opts = options(r.text, "category") or []
cat_labels = [lab for _, lab in cat_opts]
check("/ledger 筛选 category 是「全部 + %d 条档案」"
      % len(CATEGORY_ORDER), cat_labels[:1] == ["全部"]
      and cat_labels[1:] == CATEGORY_ORDER, "实际=%s" % (cat_labels,))
check("category 的 value 全是数值 id（不是字母化的 key 切片）",
      all(v == "" or v.isdigit() for v, _ in cat_opts),
      "值=%s" % ([v for v, _ in cat_opts],))

# 通用守卫：任何下拉项都不该是单字母（字母化的特征）
ALL = [(n, lab) for n in ("direction", "category", "state", "reimburse")
       for lab in (labels_of(r.text, n) or [])]
bad = [(n, lab) for n, lab in ALL if len(lab) <= 1 and lab.isascii() and lab]
check("无单字母选项（字母化回归）", not bad, "可疑=%s" % (bad,))

codes = set()
for name in ("direction", "state", "reimburse"):
    for v, _ in (options(r.text, name) or []):
        codes.add(v)
check("选项 value 为合法状态码", not (codes & {"r", "a", "p", "o", "v", "t", "e"}),
      "出现非法值=%s" % (sorted(codes & {"r", "a", "p", "o", "v", "t", "e"}),))

# 记总账表单：分类必须来自档案（全部 15 条，含方向倾向属性供前端联动）
r2 = s.get(BASE + "/ledger/new", allow_redirects=True, proxies=P)
check("打开 /ledger/new", r2.status_code == 200 and "记总账" in r2.text,
      "code=%d" % r2.status_code)
d_new = dict(options(r2.text, "direction") or [])
check("/ledger/new 方向仅 应收/应付（无「全部」）",
      d_new == {"receivable": "应收", "payable": "应付"}, "实际=%s" % (d_new,))
c_new = labels_of(r2.text, "category") or []
check("/ledger/new 列出全部 %d 条分类" % len(CATEGORY_ORDER),
      sorted(c_new) == sorted(CATEGORY_ORDER), "实际=%s" % (c_new,))
blk = re.search(r'<select[^>]*name="category"[^>]*>(.*?)</select>', r2.text, re.S)
hints = re.findall(r'data-hint="([^"]*)"', blk.group(1) if blk else "")
check("分类选项带 data-hint（供前端按方向联动）", len(hints) == len(CATEGORY_ORDER),
      "hints=%d" % len(hints))

print("\n合计：PASS %d / FAIL %d" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
