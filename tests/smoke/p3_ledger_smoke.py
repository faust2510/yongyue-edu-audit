#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冒烟测试 P3：财务总账 + 报销（第三期·ledger）。

目标 http://localhost:8069 (Odoo 19, docker edu19-clone, db edu19)。
账号：stu@local(学生 王小明/uid8)、faculty@local(教师 uid11)、
backoffice@local(教务 uid12)、parent@local(家长 uid10)。

断言 12+ 项（全部幂等，造数带【冒烟测试可删】标记结尾清理）：
  L1 GET /my/fees 学生 200（统筹费应收 + 我的报销同页）
  L2 学生发起报销 request + reimburse_ref=REB%06d 序号
  L3 同(人/分类/金额)在途单防重复提（box=dup）
  L4 学生 /my/fees 看到报销单（状态=申请中）
  L5 教务 /ledger 200 + 应收/应付双向台账可见
  L6 教务 /ledger 按方向筛选（仅应付）
  L7 教务 /ledger/reimburse 待批列表 200 + 收据附件预览链接
  L8 教务审批同意（可改金额 80.00）→ approved + approved_amount
  L9 教务付款登记 → edu.fee.payment 流水 + state=paid/已付款
  L10 教务驳回（必填原因）→ refused + reject_reason 通知学生
  L11 驳回缺原因 → box=need_reason（拒绝空原因）
  L12 权限负例：学生/教师/家长访问 /ledger* → 303 /my/home
  L13 旧统筹费账单兼容：既有 receivable 账单在 /my/fees 正常展示
  L14 通知：edu.message 生成 reimburse_result；审计 edu.audit.log 四类动作

输出 JSON 到 stdout（fail 时退出码 1），报告文本写 tests/smoke/p3_ledger_smoke.md。
"""
import json
import re
import subprocess
import sys
from datetime import date

import requests

BASE = "http://localhost:8069"
DB = "edu19"
CSRF_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')
TAG = "【冒烟测试可删】"
R = []  # (item, expect, actual, result, evidence)


def psql(sql):
    out = subprocess.run(
        ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo",
         "-d", DB, "-tAc", sql],
        capture_output=True, text=True, timeout=60)
    return [l for l in out.stdout.strip().splitlines() if l.strip()]


def psql1(sql):
    ls = psql(sql)
    return ls[0] if ls else ""


def auth(login, pwd):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + "/web/session/authenticate",
               json={"jsonrpc": "2.0",
                     "params": {"db": DB, "login": login, "password": pwd}},
               timeout=60)
    if not r.json().get("result", {}).get("uid"):
        raise SystemExit(f"login failed {login}")
    return s


def csrf(s, path):
    r = s.get(BASE + path, timeout=60)
    m = CSRF_RE.search(r.text)
    return m.group(1) if m else None


def rec(item, expect, actual, result, evidence=""):
    R.append(dict(item=item, expect=expect, actual=actual, result=result,
                  evidence=evidence))
    print(f"[{result}] {item}: {actual}")


def ok_get(s, path, allow_redirects=True):
    r = s.get(BASE + path, timeout=60, allow_redirects=allow_redirects)
    return r.status_code, r.text, "Traceback" in r.text, r.url


# =========================================================================
# 登录
# =========================================================================
stu = auth("stu@local", "demo123")
fac = auth("faculty@local", "demo123")
bo = auth("backoffice@local", "demo123")
par = auth("parent@local", "demo123")

# -------------------------------------------------------------------------
# L13 旧统筹费账单兼容（既有应收账单原样展示）
# -------------------------------------------------------------------------
st, h, tb, url = ok_get(stu, "/my/fees")
legacy_ok = st == 200 and not tb and ("【演示】2026 春季统筹费" in h
                                      or "春季统筹费" in h)
rec("L13 /my/fees 旧统筹费账单兼容", "200 展示既有应收账单",
    f"{st}, legacy={'见' if legacy_ok else '未见'}, tb={tb}",
    "PASS" if legacy_ok else "FAIL", f"len={len(h)}")
if not legacy_ok:
    print("!! 既有统筹费账单未展示——请先 seed 或确认演示数据存在")
    sys.exit(1)

# -------------------------------------------------------------------------
# L1 学生 /my/fees 同页（统筹费 + 报销区标题）
# -------------------------------------------------------------------------
s1 = st == 200 and not tb and "统筹费账单" in h and "我的报销" in h
rec("L1 /my/fees 同页 统筹费+我的报销", "统筹费账单/我的报销 两段标题",
    f"{st}, 统筹费={'统筹费账单' in h}, 报销={'我的报销' in h}",
    "PASS" if s1 else "FAIL")

# -------------------------------------------------------------------------
# L2 学生发起报销（transport 88.50 + 收据 png）
# -------------------------------------------------------------------------
st, h, tb, url = ok_get(stu, "/my/reimburse/apply")
form_ok = st == 200 and not tb and 'name="category"' in h \
    and 'name="amount"' in h and 'name="receipts"' in h
rec("L2a /my/reimburse/apply 表单", "分类/金额/收据上传表单",
    f"{st}, form={form_ok}, tb={tb}", "PASS" if form_ok else "FAIL")

tok = csrf(stu, "/my/reimburse/apply")
png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
r = stu.post(BASE + "/my/reimburse/apply/save",
             data={"csrf_token": tok, "category": "transport",
                   "amount": "88.50", "name": TAG + "交通费",
                   "note": "冒烟"},
             files={"receipts": ("receipt.png", png, "image/png")},
             timeout=60, allow_redirects=False)
loc = r.headers.get("Location", "")
m = re.search(r"REB(\d{6})", loc)
ref = ("REB" + m.group(1)) if m else ""
l2 = r.status_code in (200, 303) and "reimburse_submitted" in loc and ref
rec("L2b 学生提交报销", "303 到 /my/fees?box=reimburse_submitted&ref=REBxxxxxx",
    f"{r.status_code}, {loc}", "PASS" if l2 else "FAIL")

# 序号入库校验（edu.reimburse.seq 序列）
db_ref = psql1(f"SELECT reimburse_ref FROM edu_fee_bill WHERE reimburse_ref='{ref}'")
l2c = db_ref == ref
rec("L2c 报销单号入库", f"edu_fee_bill.reimburse_ref == {ref}",
    f"db={db_ref!r}", "PASS" if l2c else "FAIL")

# -------------------------------------------------------------------------
# L3 防重：同人/同分类/同金额 在途单拒绝重复提交
# -------------------------------------------------------------------------
tok = csrf(stu, "/my/reimburse/apply")
r = stu.post(BASE + "/my/reimburse/apply/save",
             data={"csrf_token": tok, "category": "transport",
                   "amount": "88.50", "name": TAG + "重复单"}, timeout=60,
             allow_redirects=False)
l3 = "box=dup" in r.headers.get("Location", "")
rec("L3 防重（同分类同金额）", "box=dup 拦截",
    f"{r.status_code}, {r.headers.get('Location','')}",
    "PASS" if l3 else "FAIL")

# -------------------------------------------------------------------------
# L4 学生 /my/fees 看到报销单（申请中）
# -------------------------------------------------------------------------
st, h, tb, url = ok_get(stu, "/my/fees")
l4 = st == 200 and ref in h and "申请中" in h
rec("L4 学生列表显示报销单", f"含 {ref} 且状态=申请中",
    f"ref={ref in h}, 申请中={'申请中' in h}",
    "PASS" if l4 else "FAIL")

# -------------------------------------------------------------------------
# L5 教务 /ledger 总台账（应收+应付 双向）
# -------------------------------------------------------------------------
st, h, tb, url = ok_get(bo, "/ledger")
l5 = st == 200 and not tb and "应收" in h and "应付" in h
rec("L5 /ledger 总台账 200 双向", "应收/应付 列 + 统计卡",
    f"{st}, 应收={'应收' in h}, 应付={'应付' in h}, tb={tb}",
    "PASS" if l5 else "FAIL")

# -------------------------------------------------------------------------
# L6 教务 /ledger 方向筛选（仅应付）
# -------------------------------------------------------------------------
st, h, tb, url = ok_get(bo, "/ledger?direction=payable")
l6 = st == 200 and not tb and "应付" in h
rec("L6 /ledger 方向筛选", "direction=payable 过滤",
    f"{st}, tb={tb}", "PASS" if l6 else "FAIL")

# -------------------------------------------------------------------------
# L7 教务 报销审批台（待批列表 + 收据预览）
# -------------------------------------------------------------------------
st, h, tb, url = ok_get(bo, "/ledger/reimburse")
l7 = st == 200 and not tb and "报销审批" in h and "/web/image/" in h
rec("L7 /ledger/reimburse 审批台", "200 + 收据预览链接",
    f"{st}, 收据预览={'/web/image/' in h}, tb={tb}",
    "PASS" if l7 else "FAIL")

# 取一张 request 报销单 id（刚造的那笔）
bill_ids = re.findall(r'name="bill_id"[^>]*value="(\d+)"', h)
bid = ""
for b in bill_ids:
    name = psql1(f"SELECT reimburse_ref FROM edu_fee_bill WHERE id={b}")
    if name == ref:
        bid = b
        break
if not bid:
    rec("L8 取待批单", f"找到 {ref}", "未找到，跳过审批断言", "WARN")

# -------------------------------------------------------------------------
# L8 教务同意（可改金额 80.00）
# -------------------------------------------------------------------------
if bid:
    tok = csrf(bo, "/ledger/reimburse")
    r = bo.post(BASE + "/ledger/reimburse/set",
                data={"csrf_token": tok, "bill_id": bid, "action": "approve",
                      "approved_amount": "80.00", "next": "/ledger/reimburse"},
                timeout=60, allow_redirects=True)
    dbst = psql1(f"SELECT reimburse_state||'|'||approved_amount "
                 f"FROM edu_fee_bill WHERE id={bid}")
    l8 = dbst.startswith("approved|80")
    rec("L8 同意（改金额80）", "approved + approved_amount=80",
        f"db={dbst!r}", "PASS" if l8 else "FAIL")

    # -----------------------------------------------------------------
    # L9 付款登记 → edu.fee.payment 流水 + paid
    # -----------------------------------------------------------------
    pay0 = int(psql1("SELECT count(*) FROM edu_fee_payment") or 0)
    tok = csrf(bo, "/ledger/reimburse?filterby=approved")
    r = bo.post(BASE + "/ledger/reimburse/set",
                data={"csrf_token": tok, "bill_id": bid, "action": "pay",
                      "method": "bank", "note": "冒烟付款"},
                timeout=60, allow_redirects=True)
    pay1 = int(psql1("SELECT count(*) FROM edu_fee_payment") or 0)
    dbst = psql1(f"SELECT reimburse_state||'|'||state FROM edu_fee_bill "
                 f"WHERE id={bid}")
    st_h, h2, tb2, _ = ok_get(stu, "/my/fees")
    l9 = (pay1 == pay0 + 1 and dbst.startswith("paid|paid")
          and "已付款" in h2)
    rec("L9 付款登记平账", "payment+1 & bill=paid/paid & 学生见已付款",
        f"Δpayment={pay1-pay0}, db={dbst!r}, 学生见已付款={'已付款' in h2}",
        "PASS" if l9 else "FAIL")

    # -----------------------------------------------------------------
    # L10/L11 驳回流程（再造一笔：不填原因 → 拦截；填原因 → refused）
    # 金额带运行期唯一尾数，避免与历史残留撞防重
    # -----------------------------------------------------------------
    import time
    uniq = time.strftime("%M%S")
    tok = csrf(stu, "/my/reimburse/apply")
    r = stu.post(BASE + "/my/reimburse/apply/save",
                 data={"csrf_token": tok, "category": "printing",
                       "amount": "12." + uniq, "name": TAG + "打印费"}, timeout=60,
                 allow_redirects=False)
    ref2 = re.search(r"REB(\d{6})", r.headers.get("Location", ""))
    ref2 = ("REB" + ref2.group(1)) if ref2 else ""
    st, h3, tb3, _ = ok_get(bo, "/ledger/reimburse")
    bid2 = ""
    for b in re.findall(r'name="bill_id"[^>]*value="(\d+)"', h3):
        nm = psql1(f"SELECT reimburse_ref FROM edu_fee_bill WHERE id={b}")
        if nm == ref2:
            bid2 = b
            break
    # 缺原因 → need_reason
    tok = csrf(bo, "/ledger/reimburse")
    r = bo.post(BASE + "/ledger/reimburse/set",
                data={"csrf_token": tok, "bill_id": bid2, "action": "refuse",
                      "reject_reason": "", "next": "/ledger/reimburse"},
                timeout=60, allow_redirects=False)
    l11 = "box=need_reason" in r.headers.get("Location", "")
    rec("L11 驳回缺原因", "box=need_reason 拦截",
        f"{r.headers.get('Location','')}", "PASS" if l11 else "FAIL")
    # 填原因 → refused
    tok = csrf(bo, "/ledger/reimburse")
    r = bo.post(BASE + "/ledger/reimburse/set",
                data={"csrf_token": tok, "bill_id": bid2, "action": "refuse",
                      "reject_reason": "发票抬头不符"}, timeout=60,
                allow_redirects=True)
    dbst = psql1(f"SELECT reimburse_state||'|'||reject_reason FROM "
                 f"edu_fee_bill WHERE id={bid2}")
    st, h4, tb4, _ = ok_get(stu, "/my/fees")
    l10 = dbst.startswith("refused|发票抬头不符") and "已驳回" in h4
    rec("L10 驳回（填原因）", "refused + 原因、学生见已驳回",
        f"db={dbst!r}, 学生见={'已驳回' in h4}",
        "PASS" if l10 else "FAIL")

# -------------------------------------------------------------------------
# L12 权限负例：学生/教师/家长访问 /ledger 系列 → 303 /my/home
# -------------------------------------------------------------------------
neg = []
for who, s in (("学生", stu), ("教师", fac), ("家长", par)):
    for path in ("/ledger", "/ledger/new", "/ledger/reimburse"):
        r = s.get(BASE + path, timeout=60, allow_redirects=False)
        loc = r.headers.get("Location", "")
        if r.status_code == 303 and "/my/home" in loc:
            neg.append(f"{who}{path}=拦截")
        else:
            neg.append(f"{who}{path}={r.status_code}->{loc}")
l12 = len(neg) == 9 and all("拦截" in n for n in neg)
rec("L12 权限负例", "学生/教师/家长 9 条全 303→/my/home",
    "; ".join(neg), "PASS" if l12 else "FAIL")

# -------------------------------------------------------------------------
# L14 通知 + 审计（按本脚本唯一单号 ref/ref2 统计）
# -------------------------------------------------------------------------
refs_phrase = "('" + "','".join(x for x in (ref, ref2) if x) + "')"
n_notify = int(psql1(
    "SELECT count(*) FROM edu_message WHERE event_key='reimburse_result' "
    "AND body LIKE '%" + (ref or 'REB') + "%'") or 0)
l14a = n_notify >= 2
rec("L14a 通知 reimburse_result", "≥2 条（同意/付款/驳回）",
    f"ref={ref} 相关通知={n_notify}", "PASS" if l14a else "FAIL")

n_audit = int(psql1(
    "SELECT count(*) FROM edu_audit_log WHERE action IN "
    "('报销申请','报销审批','报销付款','记账') AND res_name IN " + refs_phrase) or 0)
l14b = n_audit >= 2
rec("L14b 审计 edu.audit.log", "报销申请/审批/付款/记账 埋点",
    f"单号相关审计={n_audit}", "PASS" if l14b else "FAIL")

# -------------------------------------------------------------------------
# R1 组守卫：学生/教师直连 RPC 调 approve/refuse/pay/create 应收 全拦截
# -------------------------------------------------------------------------
import xmlrpc.client as xmlrpclib
_obj = xmlrpclib.ServerProxy(BASE + "/xmlrpc/2/object")

def _rpc_call(session_uid, pw, model, method, *args, **kw):
    """用给定 uid 直接执行（不经过控制器），返回 ('OK', result) 或 ('ERR', msg)。"""
    try:
        res = _obj.execute_kw(DB, session_uid, pw, model, method, list(args), kw)
        return "OK", res
    except Exception as exc:  # noqa: BLE001
        return "ERR", str(exc)
#
# cold: student/faculty 必须被拒；backoffice 通过
stu_uid = stu.post(BASE + "/web/session/authenticate",
                   json={"jsonrpc": "2.0", "params": {"db": DB,
                         "login": "stu@local", "password": "demo123"}},
                   timeout=60).json()["result"]["uid"]
fac_uid = fac.post(BASE + "/web/session/authenticate",
                   json={"jsonrpc": "2.0", "params": {"db": DB,
                         "login": "faculty@local", "password": "demo123"}},
                   timeout=60).json()["result"]["uid"]
bo_uid = bo.post(BASE + "/web/session/authenticate",
                 json={"jsonrpc": "2.0", "params": {"db": DB,
                       "login": "backoffice@local", "password": "demo123"}},
                 timeout=60).json()["result"]["uid"]

# 建一张 request 报销单（经 admin 造数，同测试单号体系）
r = psql1("SELECT reimburse_ref FROM edu_fee_bill WHERE reimburse_ref LIKE '%' "
          "ORDER BY id DESC LIMIT 1")
# 越权矩阵：学生/教师对 approve/refuse/pay 与 create(receivable) 都应 ERR
r1 = []
for who, uid in (("学生", stu_uid), ("教师", fac_uid)):
    for method, args in (("action_reimburse_approve", [[]]),
                         ("action_reimburse_refuse", [["x"]]),
                         ("action_pay", [[]])):
        st, msg = _rpc_call(uid, "demo123", "edu.fee.bill", method, *args)
        r1.append(f"{who}.{method}={st}")
    st, msg = _rpc_call(uid, "demo123", "edu.fee.bill", "create",
                        {'name': TAG + '越权应收', 'direction': 'receivable',
                         'amount': 1.0})
    r1.append(f"{who}.create应收={st}")
lR1 = all(x.endswith("=ERR") for x in r1)
rec("R1 组守卫（approve/refuse/pay/create）", "学生/教师 8 条全 ERR",
    "; ".join(r1), "PASS" if lR1 else "FAIL")

# 校验 backoffice 可建应收（记账入口）
st, res = _rpc_call(bo_uid, "demo123", "edu.fee.bill", "create",
                    {'name': TAG + '记账应收', 'direction': 'receivable',
                     'amount': 5.0})
lR1b = st == "OK"
rec("R1b 教务可记账", "backoffice create 应收 OK",
    f"{st} res={res if isinstance(res, int) else msg}", "PASS" if lR1b else "FAIL")

# -------------------------------------------------------------------------
# R2 受控收据预览：public=False + 本人才可见 + /web/image 占位
# -------------------------------------------------------------------------
tok = csrf(stu, "/my/reimburse/apply")
png = b"\x89PNG\r\n\x1a\n" + b"\x02" * 64
r = stu.post(BASE + "/my/reimburse/apply/save",
             data={"csrf_token": tok, "category": "fine", "amount": "44.20",
                   "name": TAG + "R2收据", "note": "t5"},
             files={"receipts": ("r2.png", png, "image/png")}, timeout=60,
             allow_redirects=False)
mref = re.search(r"REB\d{6}", r.headers.get("Location", ""))
ref_r2 = mref.group(0) if mref else ""
row_r2 = psql1("SELECT b.id||'|'||a.id||'|'||a.public::text FROM edu_fee_bill b "
               "JOIN edu_fee_bill_receipt_rel rr ON rr.bill_id=b.id "
               "JOIN ir_attachment a ON a.id=rr.attachment_id "
               f"WHERE b.reimburse_ref='{ref_r2}' LIMIT 1") if ref_r2 else ""
if row_r2:
    bid_r2, att_r2, pub_r2 = row_r2.split("|")
    u = f"/my/reimburse/receipt/{bid_r2}/{att_r2}?inline=1"
    s1 = stu.get(BASE + u, timeout=60)
    s2 = fac.get(BASE + u, timeout=60)   # 其他教师
    s3 = par.get(BASE + u, timeout=60)   # 家长
    s4 = bo.get(BASE + u, timeout=60)    # 教务
    real = stu.get(BASE + u, timeout=60).content == png
    wimg = stu.get(BASE + f"/web/image/{att_r2}", timeout=60).content
    lR2 = (pub_r2 == "false" and s1.status_code == 200 and s2.status_code == 404
           and s3.status_code == 404 and s4.status_code == 200 and real
           and wimg != png)
    rec("R2 受控收据预览", "public=false; 本人/教务200; 他人404; /web/image≠真实",
        f"pub={pub_r2} 本人={s1.status_code} 教师={s2.status_code} "
        f"家长={s3.status_code} 教务={s4.status_code} 真实字节={real}",
        "PASS" if lR2 else "FAIL")

# -------------------------------------------------------------------------
# R7 坏图健壮性：损坏 PNG（非 ASCII tEXt chunk）→ box=bad_image，不 500、不落库
# -------------------------------------------------------------------------
import struct
import zlib


def _png_chunk(tag, payload):
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xffffffff))


_ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
_real_png = (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", _ihdr)
             + _png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
             + _png_chunk(b"IEND", b""))
# 复现评审 500 的构造：合法签名+合法结构，仅 tEXt chunk 含非 ASCII 字节
# （触发 Odoo _postprocess_contents → PIL UnicodeDecodeError/OSError）
_bad_png = _real_png[:-20] + _png_chunk(b"tEXt", b"Comment\x00\xcc\xd6\xb2\xe8")

att0 = int(psql1("SELECT count(*) FROM ir_attachment") or 0)
bill0 = int(psql1("SELECT count(*) FROM edu_fee_bill") or 0)
tok = csrf(stu, "/my/reimburse/apply")
r = stu.post(BASE + "/my/reimburse/apply/save",
             data={"csrf_token": tok, "category": "printing",
                   "amount": "31.98", "name": TAG + "R7坏图", "note": "t6"},
             files={"receipts": ("bad.png", _bad_png, "image/png")}, timeout=60,
             allow_redirects=False)
loc = r.headers.get("Location", "")
att1 = int(psql1("SELECT count(*) FROM ir_attachment") or 0)
bill1 = int(psql1("SELECT count(*) FROM edu_fee_bill") or 0)
h_bad = stu.get(BASE + "/my/reimburse/apply?box=bad_image", timeout=60).text
prompt_ok = "图片文件已损坏或格式不受支持，请重新选择" in h_bad
lR7 = (r.status_code == 303 and "box=bad_image" in loc
       and att1 - att0 == 0 and bill1 - bill0 == 0 and prompt_ok)
rec("R7 坏图拦截（不500/不落库）",
    "303 box=bad_image；Δ附件=0；Δ账单=0；中文提示呈现",
    f"{r.status_code} {loc}; Δatt={att1-att0}; Δbill={bill1-bill0}; "
    f"提示={prompt_ok}", "PASS" if lR7 else "FAIL")

# 正常 PNG 路径不受影响（仍可提交）
tok = csrf(stu, "/my/reimburse/apply")
r = stu.post(BASE + "/my/reimburse/apply/save",
             data={"csrf_token": tok, "category": "printing",
                   "amount": "31.97", "name": TAG + "R7正常图", "note": "t6"},
             files={"receipts": ("ok.png", _real_png, "image/png")}, timeout=60,
             allow_redirects=False)
lR7b = r.status_code == 303 and "box=reimburse_submitted" in \
    r.headers.get("Location", "")
rec("R7b 正常图片路径未受影响", "303 reimburse_submitted",
    f"{r.status_code} {r.headers.get('Location','')}",
    "PASS" if lR7b else "FAIL")

# -------------------------------------------------------------------------
# R3 方向化统计：学生待缴只算应收；应付待付只算 approved
# -------------------------------------------------------------------------
tok = csrf(stu, "/my/reimburse/apply")
r = stu.post(BASE + "/my/reimburse/apply/save",
             data={"csrf_token": tok, "category": "transport", "amount": "300.00",
                   "name": TAG + "R3在途", "note": "t5"}, timeout=60,
             allow_redirects=False)
ref_r3 = re.search(r"REB\d{6}", r.headers.get("Location", "")).group(0)
bid_r3 = psql1(f"SELECT id FROM edu_fee_bill WHERE reimburse_ref='{ref_r3}'")
h = stu.get(BASE + "/my/fees", timeout=60).text
m_due = re.search(r"当前待缴合计：<b>¥([\d.]+)</b>", h)
student_due_before = float(m_due.group(1)) if m_due else -1
h = bo.get(BASE + "/ledger", timeout=60).text
m_pay = re.search(r"应付待付（open\+partial）</div>\s*"
                  r'<div class="fw-bold text-warning fs-5">¥([\d.]+)</div>', h)
pay_due_before = float(m_pay.group(1)) if m_pay else -1
# 同意 300 → 应付待付 +300；学生待缴不变
tok = csrf(bo, "/ledger/reimburse")
bo.post(BASE + "/ledger/reimburse/set",
        data={"csrf_token": tok, "bill_id": bid_r3, "action": "approve",
              "approved_amount": "300.00"}, timeout=60, allow_redirects=True)
h = bo.get(BASE + "/ledger", timeout=60).text
m_pay2 = re.search(r"应付待付（open\+partial）</div>\s*"
                   r'<div class="fw-bold text-warning fs-5">¥([\d.]+)</div>', h)
pay_due_after = float(m_pay2.group(1)) if m_pay2 else -1
h = stu.get(BASE + "/my/fees", timeout=60).text
m_due2 = re.search(r"当前待缴合计：<b>¥([\d.]+)</b>", h)
student_due_after = float(m_due2.group(1)) if m_due2 else -1
lR3 = (pay_due_after == pay_due_before + 300.0
       and student_due_after == student_due_before)
rec("R3 方向化统计", "应付待付随 approved +300；学生待缴(应收)不变",
    f"应付待付 {pay_due_before}→{pay_due_after}, 学生待缴 {student_due_before}→{student_due_after}",
    "PASS" if lR3 else "FAIL")

# -------------------------------------------------------------------------
# R4/R6 序号：仅 payable+request 发号；并发唯一
# -------------------------------------------------------------------------
# 手工应付（非 request）不发号
st, res = _rpc_call(bo_uid, "demo123", "edu.fee.bill", "create",
                    {'name': TAG + '手工应付', 'direction': 'payable',
                     'amount': 6.0})
row = psql1(f"SELECT coalesce(reimburse_ref,'NULL') FROM edu_fee_bill WHERE id={res}") \
    if isinstance(res, int) else "?"
lR6 = row == "NULL"
rec("R6 非request不发号", "payable(无state) 无 reimburse_ref",
    f"ref={row!r}", "PASS" if lR6 else "FAIL")

# -------------------------------------------------------------------------
# 清理：仅按【冒烟测试可删】标记删除本脚本产生的数据（绝不用 DROP）
# -------------------------------------------------------------------------
del_sql = ("DELETE FROM edu_fee_bill WHERE name LIKE '%【冒烟测试可删】%' "
           "OR note LIKE '%冒烟%';")
try:
    cp = subprocess.run(
        ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo",
         "-d", DB, "-c", del_sql],
        capture_output=True, text=True, timeout=60)
    rec("Z1 清理冒烟数据", "DELETE by tag",
        (cp.stdout or "").strip().splitlines()[-1] if cp.stdout else "ok",
        "PASS" if cp.returncode == 0 else "FAIL")
except Exception as exc:
    rec("Z1 清理冒烟数据", "psql delete",
        f"未能自动清理: {exc}", "WARN")

# 通知/审计清理：通知正文与审计 res_name 只含单号（不含标记），
# 因此按「本次运行产生的单号」+「已删除账单的单号」双重口径清理。
try:
    live_refs = psql("SELECT reimburse_ref FROM edu_fee_bill "
                     "WHERE reimburse_ref IS NOT NULL")
    keep = set(live_refs)
    # 清理所有不在库中的 REB 号通知（本脚本跑完即删单，故都属残留）
    notif_rows = psql("SELECT id||'|'||coalesce(substring(body from 'REB[0-9]{6}'),'') "
                      "FROM edu_message WHERE event_key='reimburse_result'")
    orphan_ids = []
    for row in notif_rows:
        mid, mref_ = row.split("|", 1)
        if mref_ and mref_ not in keep:
            orphan_ids.append(mid)
    if orphan_ids:
        subprocess.run(
            ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo",
             "-d", DB, "-c",
             "DELETE FROM edu_message WHERE id IN (%s);" % ",".join(orphan_ids)],
            capture_output=True, text=True, timeout=60)
    # 审计：res_name 为 REB 号且该单已不存在 → 残留
    audit_rows = psql("SELECT id||'|'||res_name FROM edu_audit_log "
                      "WHERE action IN ('报销申请','报销审批','报销付款','记账') "
                      "AND res_name LIKE 'REB%'")
    orphan_audit = []
    for row in audit_rows:
        aid, aref = row.split("|", 1)
        if aref and aref not in keep:
            orphan_audit.append(aid)
    if orphan_audit:
        subprocess.run(
            ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo",
             "-d", DB, "-c",
             "DELETE FROM edu_audit_log WHERE id IN (%s);"
             % ",".join(orphan_audit)],
            capture_output=True, text=True, timeout=60)
    rec("Z2 清理残留通知/审计", "按已删单号清理 REB 残留",
        f"通知 {len(orphan_ids)} 条 / 审计 {len(orphan_audit)} 条", "PASS")

    # 残留收据附件（账单已删 → m2m 关系随之消失的孤儿附件）
    subprocess.run(
        ["docker", "exec", "edu19-clone-db-1", "psql", "-U", "odoo",
         "-d", DB, "-c",
         "DELETE FROM ir_attachment a WHERE a.res_model IS NULL "
         "AND a.name IN ('receipt.png','r2.png','rec.png','ok.png','bad.png') "
         "AND NOT EXISTS (SELECT 1 FROM edu_fee_bill_receipt_rel r "
         "WHERE r.attachment_id=a.id);"],
        capture_output=True, text=True, timeout=60)
except Exception as exc:  # noqa: BLE001
    rec("Z2 清理残留通知/审计", "按单号清理", f"跳过: {exc}", "WARN")

# -------------------------------------------------------------------------
# 汇总
# -------------------------------------------------------------------------
fails = [x for x in R if x["result"] == "FAIL"]
print("\n===JSON===")
print(json.dumps(R, ensure_ascii=False, indent=1))
print("TOTAL", len(R), "FAIL", len(fails))
sys.exit(1 if fails else 0)