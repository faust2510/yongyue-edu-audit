#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冒烟断言的「红历史」审计（t69；t76 修正口径）。

动机：**恒假的断言一眼可见；恒真的断言是隐形的。**
一条从来没红过的断言，可能一直在证明一个不需要证明的东西（甚至什么都不证明）。
本工具把「从未红过」变成**可发现的**，然后把问题交回作者：
    「你能描述一个让它变红的场景吗？描述不出 → 它可能是空断言。」

t76 修正（重要）：**「红过」必须限定为「因真实原因红过」**
--------------------------------------------------------
原先任何 FAIL 都算红历史 —— 包括**环境型失败**（ConnectionError / 容器重启）。
后果：那条断言**永久移出 REVIEW 名单，却从未因真实原因红过** ——
即「曾经红过」与「曾经被环境误红过」同形。
规则：
  · 判据 = **rc + 输出里的 ENV/未验证标记**（[ENV] / INCOMPLETE / 未验证面 / SKIP-ENV / rc=2）；
  · **只要该轮出现 ENV 标记，就不给任何断言记红** —— 宁可没有红历史，也不要假红历史；
  · 环境型 FAIL 进 `env_fails`（本工具按断言记 `env_runs`）桶：**既不污染红历史、也不掩盖环境问题**；
  · 环境型轮**不吃 `runs`** —— 否则「被环境吃掉的运行」会伪装成「验证过 N 次」，把断言拱进 REVIEW。

「样本被环境吃掉」单列一栏，**通常比 REVIEW 更该先看**：REVIEW 至少说明它在有效运行里一直绿；
这类意味着「我们连它行不行都不知道」。

设计要点
--------
1. **只读被测脚本**：不改变任何被测脚本的判定，只解析它们的输出。
2. **不靠造失败验证**：不制造脏数据；--record 可直接喂历史日志，完全不碰库。
3. **未运行 ≠ 通过**：只有真的解析出断言才计入（否则制造恒真）。
4. 历史文件在**库外**：`tests/smoke/.assertion_history.json`（gitignore 由仓根负责，不在本文件 inScope）。

用法
----
  python3 tests/smoke/assertion_audit.py --selftest        # 构造反例自检（不碰库）
  python3 tests/smoke/assertion_audit.py                   # 跑所有可识别的冒烟脚本并记录
  python3 tests/smoke/assertion_audit.py --only authz_endtoend_smoke.py
  python3 tests/smoke/assertion_audit.py --record /tmp/run.log --name authz_endtoend_smoke.py
  python3 tests/smoke/assertion_audit.py --report          # 只出报告，不跑
退出码：0 报告已出（REVIEW 非空**不算失败**，它是待作者解释的清单）；--selftest 失败为 1。
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
HISTORY = os.path.join(HERE, ".assertion_history.json")

LINE_RE = re.compile(r"^\s*(?:\[)?(PASS|FAIL)(?:\])?\s+(.+?)\s*$")

# 环境型运行标记（t73 三件 + 本仓既有措辞）：rc=2 / [ENV] / INCOMPLETE / 未验证面 / SKIP-ENV。
ENV_RE = re.compile(r"\[ENV\]|INCOMPLETE|未验证面|SKIP-ENV|环境不可用|环境未就绪")
ENV_RCS = (2, 3)   # 2=环境未就绪；3=INCOMPLETE（未验证面）—— 两者都不该被当成断言的红


def is_env_run(text, rc=0):
    """这一轮是否属于「环境型」（t76）。

    保守方向：**宁可没有红历史，也不要假红历史** —— 只要出现 ENV 标记，
    本轮**不给任何断言记红**。
    """
    if rc in ENV_RCS:
        return True
    return bool(ENV_RE.search(text or ""))


def split_name(rest):
    """自适配切分（t76 修「标识漂移」）：返回 (名称, 是否不可靠)。

    起因：原先只按「2 个以上空格」切；单空格格式的脚本（如 F_roles_smoke.py）
    会把**详情并进断言名** → 标识随详情漂移，同一断言被记成两条。
    判据顺序：① 2 个以上空格（本仓 check() 定宽列）② " :: " 分隔符
    ③ 都没有：像纯名称行则整体作名；**带详情迹象（含 "=" 或过长）则判不可靠**
    —— 不可靠的行**列为「不覆盖」**，不猜着记（猜就是制造漂移）。
    """
    st = rest.strip()
    parts = re.split(r"\s{2,}", st, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip()[:120], False
    if " :: " in st:
        return st.split(" :: ", 1)[0].strip()[:120], False
    if ("=" in st) or (len(st) > 60):
        return None, True
    return st[:120], False


def parse(text):
    """抽取 ({断言名: "PASS"|"FAIL"}, [不可靠行])。同一名出现多次取最差。"""
    found, unreliable = {}, []
    for line in text.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        verdict, rest = m.group(1), m.group(2)
        name, bad = split_name(rest)
        if bad:
            unreliable.append(rest.strip()[:120])
            continue
        if not name or name.lower() in ("fail", "pass"):
            continue
        if name in found and found[name] == "FAIL":
            continue
        found[name] = verdict
    return found, unreliable


def load_history():
    if os.path.exists(HISTORY):
        try:
            with io.open(HISTORY, encoding="utf-8") as fh:
                return json.load(fh)
        except (ValueError, OSError):
            print("WARN 历史文件不可读，按空历史继续：%s" % HISTORY)
    return {"assertions": {}, "known_valid": {}}


def save_history(hist):
    hist["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with io.open(HISTORY, "w", encoding="utf-8") as fh:
        json.dump(hist, fh, ensure_ascii=False, indent=1, sort_keys=True)


def record(hist, script, verdicts, env=False):
    """记一次运行。★ 只有真的解析出断言才写入 —— 未运行不得计入（否则制造恒真）。

    env=True（环境型）：**不吃 runs、不记红**，只累加 env_runs。
    """
    if not verdicts:
        return 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for name, v in verdicts.items():
        key = "%s|%s" % (script, name)
        row = hist["assertions"].setdefault(key, {
            "runs": 0, "fails": 0, "env_runs": 0, "last": "",
            "first_seen": now, "last_seen": now})
        row.setdefault("env_runs", 0)
        if env:
            row["env_runs"] += 1
        else:
            row["runs"] += 1
            if v == "FAIL":
                row["fails"] += 1
        row["last"] = v
        row["last_seen"] = now
    return len(verdicts)


def _md5(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()
    except OSError:
        return "????????"


def sibling_deps(script_path):
    """依赖集（t101）= **同目录 import 的模块** ∪ **源码里出现其文件名字面量的同目录模块**。

    两类都对单文件 md5 不可见，却会改变行为：
      · 运行时 read 并注入（authz_endtoend_smoke.py 读 _fixtures.py 源码注入 odoo shell）；
      · 静态 import（smoke_anon / smoke_student ← smoke_common）。
    匹配用**精确文件名**（含 .py），不用裸子串 —— 避免 cleanup_fixtures 命中 _fixtures 那类假阳性。
    """
    try:
        src = io.open(script_path, encoding="utf-8").read()
    except OSError:
        return []
    me = os.path.basename(script_path)
    out = []
    for fn in sorted(os.listdir(os.path.dirname(script_path))):
        if not fn.endswith(".py") or fn == me or fn.startswith("assertion_audit"):
            continue
        mod = fn[:-3]
        imp = re.search(r"(?m)^\s*(?:from\s+%s\s+import|import\s+%s\b)" % (re.escape(mod), re.escape(mod)), src)
        lit = ((chr(39) + fn + chr(39)) in src) or ((chr(34) + fn + chr(34)) in src)
        if imp or lit:
            out.append(fn)
    return out


def dep_fingerprint(script_path, deps=None, root=None):
    """(依赖集指纹8位, 依赖文件列表)；指纹 = md5(脚本 md5 + 各依赖 名:md5)。

    只改依赖文件（脚本一字未动）→ 指纹必变。这正是指纹覆盖到没覆盖的"会红"证据。
    """
    deps = sibling_deps(script_path) if deps is None else deps
    root = root or os.path.dirname(script_path)
    h = hashlib.md5(_md5(script_path).encode())
    for d in deps:
        h.update((d + ":" + _md5(os.path.join(root, d))).encode())
    return h.hexdigest()[:8], deps

def discover():
    out = []
    for fn in sorted(os.listdir(HERE)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        if fn == "assertion_audit.py":
            continue
        out.append(fn)
    return out


def git_states(names):
    """一次批量取 git 状态（t83）：给每个脚本标 clean / dirty / untracked。

    动机：本工具会把**队友写到一半的脚本**一起扫进来 —— 它的 FAIL 读数与
    "已提交脚本的真实失败"性质完全不同，不能并列示人。**读数必须带出处。**
    """
    states = {n: "clean" for n in names}
    if not names:
        return states
    rel = [os.path.join("tests", "smoke", n) for n in names]
    try:
        p = subprocess.run(["git", "status", "--porcelain", "--"] + rel,
                           capture_output=True, text=True, cwd=REPO, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {n: "unknown" for n in names}
    for line in (p.stdout or "").splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].strip().strip('"')
        base = os.path.basename(path)
        if base not in states:
            continue
        states[base] = "untracked" if code.strip() == "??" else "dirty"
    return states


def run_script(fn, timeout=900):
    path = os.path.join(HERE, fn)
    try:
        p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                           timeout=timeout, cwd=REPO)
        return (p.stdout or "") + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT %s" % fn, 124


def report(hist, min_runs, top):
    asserts = hist.get("assertions", {})
    known = hist.get("known_valid", {})
    review, untriggered, thin, env_eaten = [], [], [], []
    for key, row in sorted(asserts.items()):
        runs, fails = row.get("runs", 0), row.get("fails", 0)
        env_runs = row.get("env_runs", 0)
        if fails > 0:
            continue
        if runs < min_runs and env_runs >= min_runs:
            env_eaten.append((key, env_runs, runs))
            continue
        if runs < min_runs:
            thin.append((key, runs))
            continue
        if key in known:
            untriggered.append((key, runs, known[key].get("scenario", "")))
        else:
            review.append((key, runs))
    print("== 断言红历史审计 ==")
    print("历史文件：%s（库外）" % HISTORY)
    print("断言总数 %d ｜ 从未红过且运行≥%d 次：%d ｜ 已知有效待触发：%d ｜ 次数不足：%d ｜ 样本被环境吃掉：%d"
          % (len(asserts), min_runs, len(review), len(untriggered), len(thin), len(env_eaten)))
    print()
    print("-- REVIEW：从未红过，请作者回答「你能描述一个让它变红的场景吗？」--")
    for key, runs in review[:top]:
        print("  REVIEW  %s   （有效运行 %d 次，0 次红）" % (key, runs))
    if not review:
        print("  （无：所有已达次数的断言都有过红历史，或历史样本还不足）")
    print()
    print("-- ⚠️ 样本被环境吃掉（**优先看这一栏**）--")
    for key, er, vr in env_eaten[:top]:
        print("  ENV-EATEN  %s   （环境型 %d 次 / 有效运行仅 %d 次 → 近期未被有效验证）"
              % (key, er, vr))
    if not env_eaten:
        print("  （无）")
    print()
    print("-- 已知有效但本轮未触发（作者已登记场景，不再报 REVIEW）--")
    for key, runs, scen in untriggered[:top]:
        print("  OK      %s   （%d 次未红；场景：%s）" % (key, runs, scen[:60]))
    if not untriggered:
        print("  （无登记）")
    print()
    print("-- 次数不足 min-runs（样本太少，暂不下结论）--")
    print("  %d 条" % len(thin))
    print()
    print("提示：登记场景请写进 %s 的 known_valid，键为 \"<script>|<断言名>\"。"
          % os.path.basename(HISTORY))


def _selftest():
    """构造反例（t76 验收项）：① ENV 日志 → 任何断言都不记红；② 真实 FAIL → 正常记红。

    只跑内存逻辑：**不碰库、不写历史文件**。
    """
    ok = True

    def chk(name, cond):
        nonlocal ok
        print("  %-4s %s" % ("PASS" if cond else "FAIL", name))
        ok = ok and cond

    env_log = ("  PASS 前置：越权方是合法教师\n"
               "  FAIL 成绩·单条 save 越权后 DB 未变\n"
               "  [ENV] 环境不可用，登记为未验证面\n")
    h1 = {"assertions": {}, "known_valid": {}}
    v1, _b1 = parse(env_log)
    env1 = is_env_run(env_log, 0)
    record(h1, "demo.py", v1, env=env1)
    reds1 = sum(r["fails"] for r in h1["assertions"].values())
    chk("① ENV 日志：判定为环境型", env1)
    chk("① ENV 日志：无任何断言被记为红", reds1 == 0)
    chk("① ENV 日志：不吃 runs（env_runs=1 / runs=0）",
        all(r["runs"] == 0 and r["env_runs"] == 1 for r in h1["assertions"].values()))

    real_log = "  PASS 前置：越权方是合法教师\n  FAIL 成绩·单条 save 越权后 DB 未变\n"
    h2 = {"assertions": {}, "known_valid": {}}
    v2, _b2 = parse(real_log)
    env2 = is_env_run(real_log, 1)
    record(h2, "demo.py", v2, env=env2)
    reds2 = sum(r["fails"] for r in h2["assertions"].values())
    chk("② 真实 FAIL：判定为非环境型", not env2)
    chk("② 真实 FAIL：正常记红 1 条", reds2 == 1)

    chk("③ rc=2 单独即判环境型（正文无 ENV 字样）", is_env_run("  FAIL 某断言\n", 2))

    # ⑤ rc=3 且正文无 ENV/INCOMPLETE 字样（调用方可能把正文过滤成只剩 PASS/FAIL 行）
    chk("⑤ rc=3 单独即判环境型（正文无 ENV/INCOMPLETE 字样）",
        is_env_run("  FAIL 某断言\n", 3))
    partial = ("  PASS 前置：越权方是合法教师\n"
               "  FAIL 成绩·单条 save 越权后 DB 未变\n")
    h5 = {"assertions": {}, "known_valid": {}}
    v5, _b5 = parse(partial)
    record(h5, "demo.py", v5, env=is_env_run(partial, 3))
    chk("⑤ 部分过滤 + rc=3：不给任何断言记红",
        sum(r["fails"] for r in h5["assertions"].values()) == 0)

    n4, bad4 = split_name("t12 管理员后台菜单探活（odoo shell） :: 7/7 行返回, 全部有效=False")
    chk("④ 「 :: 」切分不含详情", (not bad4) and n4 == "t12 管理员后台菜单探活（odoo shell）")
    _n5, bad5 = split_name("状态异常 detail=xxx")
    chk("④ 无分隔符且带详情迹象 → 判不可靠（不猜）", bad5)
    n6, bad6 = split_name("清理完成")
    chk("④ 纯名称行 → 可靠", (not bad6) and n6 == "清理完成")

    # t101：依赖集指纹必须覆盖共享文件 —— 只改依赖、脚本一字未动 → 指纹必变
    _ta = tempfile.mkdtemp(prefix="t101a_")
    _tb = tempfile.mkdtemp(prefix="t101b_")
    try:
        for _d in (_ta, _tb):
            io.open(os.path.join(_d, "s.py"), "w", encoding="utf-8").write("x=1")
        io.open(os.path.join(_ta, "dep.py"), "w", encoding="utf-8").write("y=1")
        io.open(os.path.join(_tb, "dep.py"), "w", encoding="utf-8").write("y=2")
        _f1, _ = dep_fingerprint(os.path.join(_ta, "s.py"), ["dep.py"], root=_ta)
        _f2, _ = dep_fingerprint(os.path.join(_tb, "s.py"), ["dep.py"], root=_tb)
        chk("t101 反例：脚本相同、只改依赖文件 → 依赖集指纹不同",
            _f1 != _f2)
        _f3, _ = dep_fingerprint(os.path.join(_ta, "s.py"), [], root=_ta)
        chk("t101 反例：依赖集为空时指纹退化为脚本指纹（并不同）", _f3 != _f1)
    finally:
        shutil.rmtree(_ta, ignore_errors=True)
        shutil.rmtree(_tb, ignore_errors=True)
    print("== 反例自检 %s ==" % ("通过" if ok else "未通过"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="append", default=[],
                    help="喂已有的运行日志：--record /path/log.txt（可重复）")
    ap.add_argument("--name", default="", help="配合 --record：日志属于哪个脚本")
    ap.add_argument("--only", default="", help="只跑/只报某个脚本（子串匹配）")
    ap.add_argument("--report", action="store_true", help="只出报告，不跑脚本")
    ap.add_argument("--min-runs", type=int, default=3)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--budget", type=int, default=900,
                    help="默认模式跑脚本的总时长预算（秒）；超预算即停止并报告哪些没跑")
    ap.add_argument("--selftest", action="store_true",
                    help="构造反例自检：ENV 日志不记红 / 真实 FAIL 记红")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    hist = load_history()
    cov_ran, cov_none = [], []
    # t83：一次批量取状态，之后只查表（不逐文件调 git）
    _states = git_states(discover())

    def _tag(nm):
        return ", %s" % _states.get(nm, "external")

    for path in args.record:
        try:
            with io.open(path, encoding="utf-8", errors="replace") as fh:
                blob = fh.read()
        except OSError as exc:
            print("SKIP --record 读不到 %s（%s）" % (path, exc))
            continue
        name = args.name or os.path.basename(path)
        v, bad = parse(blob)
        env = is_env_run(blob, 0)
        n = record(hist, name, v, env=env)
        if bad:
            cov_none.append("%s(不可靠切分 %d 行 → 不覆盖%s)" % (name, len(bad), _tag(name)))
        if n:
            cov_ran.append("%s(%d 断言%s%s)" % (name, n, ", ENV轮" if env else "", _tag(name)))

    if not args.report:
        t0 = time.time()
        skipped = []
        for fn in discover():
            if args.only and args.only not in fn:
                continue
            if args.only == "" and (time.time() - t0) > args.budget:
                skipped.append(fn)
                continue
            print("-- 运行 %s …" % fn, flush=True)
            _t0 = datetime.now().astimezone().isoformat(timespec="seconds")
            _sp = os.path.join(HERE, fn)
            _self_md5 = _md5(_sp)[:8]
            _depfp, _deps = dep_fingerprint(_sp)
            out, rc = run_script(fn)
            verdicts, badl = parse(out)
            env = is_env_run(out, rc)
            n = record(hist, fn, verdicts, env=env)
            if badl:
                cov_none.append("%s(不可靠切分 %d 行 → 不覆盖%s)" % (fn, len(badl), _tag(fn)))
            if n:
                fails = sum(1 for x in verdicts.values() if x == "FAIL")
                cov_ran.append("%s(%d 断言, %d FAIL, rc=%d%s%s) @%s md5=%s dep=%s%s"
                               % (fn, n, fails, rc, ", ENV轮" if env else "", _tag(fn),
                                  _t0, _self_md5, _depfp,
                                  (" 依据=[" + ",".join(_deps) + "]") if _deps else ""))
            else:
                cov_none.append("%s(无可识别断言, rc=%d%s)" % (fn, rc, _tag(fn)))
            save_history(hist)
        if skipped:
            print()
            print("== 超预算未运行（%d 个脚本）==" % len(skipped))
            print("  %s" % "、".join(skipped[:12]))
            print("  说明：这些脚本**本次未验证**，不等于通过；可在干净窗口用 --only <脚本名> 单独补跑。")

    save_history(hist)
    print()
    # t83：**在途产物与已提交脚本分开展示**，避免半成品被读成"发现缺陷"
    def _inflight(lst):
        return [x for x in lst if (", dirty" in x or ", untracked" in x)]

    print("== 覆盖面 ==")
    print("【已提交/干净】")
    _s = [x for x in cov_ran if x not in _inflight(cov_ran)] + \
         [x for x in cov_none if x not in _inflight(cov_none)]
    print("  %s" % ("；".join(_s) if _s else "（无）"))
    print("【⚠️ 在途产物（dirty/untracked）—— 其 FAIL 可能是半成品，不是缺陷发现】")
    _f = _inflight(cov_ran) + _inflight(cov_none)
    print("  %s" % ("；".join(_f) if _f else "（无）"))
    print("状态取自一次批量 git status --porcelain；external = 非本目录文件（如 --record 的日志）。")
    print("说明：只覆盖输出里形如 \"<PASS|FAIL> 名称  详情\" 或 \"名称 :: 详情\" 的行；"
          "其它打印形态**未覆盖**，需其作者补齐标记。")
    print()
    report(hist, args.min_runs, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
