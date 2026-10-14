#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shell 退出码承接死代码检查（t99）：set -e 下「裸命令紧跟 X=$?」。

判据（来自 t97 的真实 blocker）：脚本含 set -e（含 set -euo pipefail）时，
若某行是裸命令（不以 if/elif/while/until/!/time 开头、也不含 && 或 ||），
而下一行是 X=$?（可带 local），则命令返回非零时 shell 当场以该码退出 ——
X=$? 成死代码、后续分支永不可达。t97 实例：
  python3 check_manifest_tracking.py > log 2>&1
  mt_rc=$?          # ← 死代码；检查器 rc=1 时脚本 exit 1（应为 6）
对照：旧 run_static_check() 之所以 rc=2/3 不中止，是因为它被 if ! 条件调用 ——
**命令是否处于条件上下文，决定 set -e 是否放行**。
修法：cmd || X=$?（或把命令放进 if 条件）。

覆盖边界（显式声明不覆盖）
--------------------------
1. 条件上下文内的承接（if/elif/while/until/! 开头，或含 && / ||）→ 不报（合法）；
2. set +e 之后的区段 → 保守放行不判（宁漏不误报）；
3. trap / eval / 动态拼接命令 → 不判（静态不可知）；
4. 行尾续行（反斜杠）与函数定义行 → 不判；
5. 默认只扫 scripts/*.sh；其它位置的 shell 入口需显式传参加入。

退出码契约：0=OK｜1=FAIL（有命中）｜2=ENV（扫描面不存在）｜3=INCOMPLETE（有跳过/漂移）
用法：
  python3 scripts/check_shell_exitcode.py            # 扫 scripts/*.sh
  python3 scripts/check_shell_exitcode.py PATH ...    # 指定文件/目录
  python3 scripts/check_shell_exitcode.py --selftest  # 双向自证（构造反例）
"""
import datetime
import glob
import hashlib
import os
import re
import sys
import tempfile

REVISION = 'r1'
# 基线常量（t99 标定）：脚本目录当前 **0 命中** —— 由 t97 修复后达到的干净基线。
# 机制同 t53/t96：命中数与之不符即打印 BOUNDARY-DRIFT 并计入 INCOMPLETE（有命中时 rc=1 优先）。
# 若将来确实要保留一处命中（例：确属误报），必须同步本常量并在 diff 写明理由。
EXPECTED_HITS = 0
RUN_STAMP = datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()

VAR_REF = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)')
RC_ASSIGN = re.compile(r'^\s*(?:local\s+)?([A-Za-z_][A-Za-z0-9_]*)=\$\?\s*$')
COND_START = re.compile(r'^\s*(if|elif|while|until|!|time)\b')
SKIP_START = re.compile(r'^\s*(#|$|fi|done|esac|then|else|do|\}|\)|;;|set\s|trap\s|shift\b|return\b|export\s|declare\s|function\b)')
FUNC_DEF = re.compile(r'^\s*[A-Za-z_][A-Za-z0-9_]*\s*\(\)\s*\{')

def _fingerprint():
    try:
        with open(os.path.abspath(__file__), 'rb') as fh:
            return hashlib.md5(fh.read()).hexdigest()[:8]
    except Exception:
        return '????????'

def scan_file(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().split("\n")
    has_errexit = any(re.match(r'^\s*set\s+-[a-z]*e', ln) for ln in lines)
    hits = []
    # 规则二（t109）—— **书写约定**，不是正确性规则（2026-10-02 复核更正，判据强度未变）。
    #
    # ⚠ 本条原先写的理由是「bash 会把全角字节吞进变量名」—— 该理由**已被实测否证**：
    #   bash 的变量名只认 ASCII [A-Za-z0-9_]，后面跟全角字符不会吞。实测（STAGE_DIR=/tmp/stage）：
    #       echo "x $STAGE_DIR（含…）"   →   x /tmp/stage（含…）     ← 正常
    #       echo "z $BASE_x"             →   z                     ← **空的**！$BASE_x 被当成变量名
    #   ⇒ 真正的坑是「$VAR 紧跟 **ASCII 词字符**」（如 $BASE_x），不是紧跟全角。
    #   原文提到的「echo "$M（" 在 set -u 下报 unbound」确实会发生，但原因是 **M 本身没赋值**，
    #   与后面跟不跟全角无关（后面换成任意字符同样报）。
    #
    # 那为什么保留本条？—— ① 花括号写法在**任何后续编辑**下都无歧义（上面 $BASE_x 就是反例，
    #   有人想写 "${BASE}_x" 却写成 "$BASE_x" 是最常见的真实事故）；② 全仓已满足（命中 0），
    #   作为统一风格零成本。
    # ⇒ 判据强度**不放宽**（仍是 FAIL），只更正错误的理由；下一个人不必再花一轮证伪它。
    #   历史：2026-10-02 三名队友因这条卡住 safe_upgrade，其中一人做了控制实验证伪了原理由。
    # 与 set -e 无关，故**所有** shell 脚本都扫；${VAR} 已加花括号不会被匹配。
    for i, ln in enumerate(lines):
        for m2 in VAR_REF.finditer(ln):
            nxt2 = ln[m2.end():m2.end() + 1]
            if nxt2 and ord(nxt2) > 127:
                hits.append((i + 1, ln.strip(),
                             '改为${%s}（统一花括号写法；理由见 scan_file 顶部注释，非「全角被吞」）' % m2.group(1)))
    if not has_errexit:
        return hits, False
    for i, ln in enumerate(lines[:-1]):
        nxt = lines[i + 1]
        m = RC_ASSIGN.match(nxt)
        if not m:
            continue
        if SKIP_START.match(ln) or FUNC_DEF.match(ln):
            continue
        if COND_START.match(ln) or '&&' in ln or '||' in ln:
            continue
        if ln.rstrip().endswith(chr(92)):
            continue
        var = m.group(1)
        hits.append((i + 1, ln.strip(), '改为 `%s || %s=$?`（或把命令放进 if 条件）' % (ln.strip(), var)))
    return hits, True

def run(paths, verbose=True):
    files, skipped = [], []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, '*.sh')))
        elif os.path.isfile(p):
            files.append(p)
        else:
            skipped.append(p)
    if not files:
        if verbose:
            print('SKIP-ENV：扫描面无 .sh 文件（%s）—— 环境未就绪，不是「检查通过」' % ', '.join(paths))
        return 2, [], 0, len(skipped)
    all_hits, scanned = [], 0
    for f in files:
        try:
            hits, _has = scan_file(f)
        except Exception as exc:
            skipped.append('%s（读取失败：%s）' % (f, type(exc).__name__))
            continue
        scanned += 1
        for lineno, text, fix in hits:
            all_hits.append((f, lineno, text, fix))
    if verbose:
        print('扫描 %d 个 shell 脚本｜跳过 %d' % (scanned, len(skipped)))
        for f in skipped:
            print('  SKIP %s' % f)
        for f, lineno, text, fix in all_hits:
            print('FAIL-EXITCODE-FALLTHROUGH %s:%d :: %s :: 修法：%s' % (f, lineno, text, fix))
        drift = (EXPECTED_HITS is not None and len(all_hits) != EXPECTED_HITS)
        if drift:
            print('BOUNDARY-DRIFT 命中数 %d ≠ 常量 %d —— 有意变更请同步 EXPECTED_HITS' % (len(all_hits), EXPECTED_HITS))
        if all_hits:
            rc, label = 1, 'FAIL'
        elif skipped or drift:
            rc, label = 3, 'INCOMPLETE'
        else:
            rc, label = 0, 'OK'
        print('RESULT=%s（命中 %d / 跳过 %d）REVISION=%s · 指纹 %s · 运行 %s' % (label, len(all_hits), len(skipped), REVISION, _fingerprint(), RUN_STAMP))
        print('契约：exit 0=OK 1=FAIL 2=ENV 3=INCOMPLETE')
    if all_hits:
        return 1, all_hits, scanned, len(skipped)
    if skipped:
        return 3, all_hits, scanned, len(skipped)
    return 0, all_hits, scanned, len(skipped)

def _selftest():
    ok = True
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, 'bad.sh')
        good = os.path.join(d, 'good.sh')
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env bash\nset -euo pipefail\npython3 foo.py > /tmp/x.log 2>&1\nrc=$?\necho \"$rc\"\n")
        with open(good, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env bash\nset -euo pipefail\npython3 foo.py > /tmp/x.log 2>&1 || rc=$?\necho \"$rc\"\nif python3 bar.py; then rc=$?; fi\n")
        bad_hits, _ = scan_file(bad)
        good_hits, _ = scan_file(good)
        good1 = len(bad_hits) == 1 and ('|| rc=$?' in bad_hits[0][2])
        good2 = len(good_hits) == 0
        ok = ok and good1 and good2
        print('SELFTEST %s %-24s（坏模式命中 %d，含修法=%s）' % ('PASS' if good1 else 'FAIL', 'bad_pattern_reddens', len(bad_hits), bool(bad_hits and ('|| rc=$?' in bad_hits[0][2]))))
        print('SELFTEST %s %-24s（好模式命中 %d，期望 0）' % ('PASS' if good2 else 'FAIL', 'good_pattern_clean', len(good_hits)))
    with tempfile.TemporaryDirectory() as d2:
        nb = os.path.join(d2, 'nonascii_bad.sh')
        ng = os.path.join(d2, 'nonascii_good.sh')
        with open(nb, 'w', encoding='utf-8') as fh:
            fh.write('#!/usr/bin/env bash\nset -u\nMODULES=abc\necho "x $MODULES（共）"\n')
        with open(ng, 'w', encoding='utf-8') as fh:
            fh.write('#!/usr/bin/env bash\nset -u\nMODULES=abc\necho "x ${MODULES}（共）"\n')
        nb_hits, _ = scan_file(nb)
        ng_hits, _ = scan_file(ng)
        good3 = len(nb_hits) == 1 and '${' in nb_hits[0][2]
        good4 = len(ng_hits) == 0
        ok = ok and good3 and good4
        print('SELFTEST %s %-24s（$VAR 紧跟全角：命中 %d，修法含花括号=%s）'
              % ('PASS' if good3 else 'FAIL', 'nonascii_var_reddens', len(nb_hits),
                 bool(nb_hits and '${' in nb_hits[0][2])))
        print('SELFTEST %s %-24s（\u0024{VAR} 写法：命中 %d，期望 0）'
              % ('PASS' if good4 else 'FAIL', 'braced_var_clean', len(ng_hits)))
    print('SELFTEST 总结：%s（REVISION=%s · 指纹 %s · 运行 %s）' % ('全部通过' if ok else '存在失败', REVISION, _fingerprint(), RUN_STAMP))
    return 0 if ok else 1

if __name__ == "__main__":
    argv = sys.argv[1:]
    if '--selftest' in argv:
        sys.exit(_selftest())
    targets = [a for a in argv if not a.startswith('-')] or ['scripts']
    rc, _hits, _n, _s = run(targets)
    sys.exit(rc)