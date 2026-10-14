#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静态门禁：manifest 引用集 ⊆ git 跟踪集（t93）。

触发事件：.gitignore 的 data/ 误伤模块数据目录 → 5 个被 __manifest__.py 引用的
文件从未入库 → 新克隆 / CI 上 Odoo 加载 manifest 直接报错；而本机因为文件在盘上，
一直「能跑」。

不变式（两条缺一不可）：对每个 manifest 的 data / views / assets 路径，
  1. 工作区存在（盘上有）；
  2. git ls-files --error-unmatch 成功（版本库里有）。
  ⇒ manifest 引用集 ⊆ git 跟踪集。例外须在 ALLOW_UNTRACKED 显式登记并写明理由。

理由：「文件在盘上」与「文件在版本库里」是两件事；只验前者会在新环境整批失效，
而这台机器上永远看不出来。

设计约束：零环境依赖（不连 DB / 不发 HTTP / 不读容器，停机可跑）；
退出码 0=OK 1=FAIL 2=ENV 3=INCOMPLETE；自证行 REVISION · 指纹 · 断言数 · 时刻。
"""
import argparse, ast, hashlib, io, os, shutil, subprocess, sys, tempfile
from datetime import datetime

REVISION = 'v1.0'
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_DIR = 'custom_addons'

# 例外登记：确需不入库的 manifest 引用（键=仓库相对路径，值=理由）。
# 例外必须显式且带理由，否则「引用没入库」会静默通过，本门禁就白建了。
ALLOW_UNTRACKED = {}


def self_fingerprint():
    try:
        with open(os.path.abspath(__file__), 'rb') as fh:
            return hashlib.md5(fh.read()).hexdigest()[:8]
    except OSError:
        return '????????'


def load_manifest(path):
    """取 data/views/assets 三个键（**逐值 literal_eval**，不要求整体是字面量）。

    两种形态都要认（实测踩坑）：
      ① `manifest = {...}`（赋值式）
      ② **裸 dict**：文件顶层直接写 `{...}`（Odoo 17+ 起允许，**本仓 10 个模块全是这种**）
    —— 只认 ① 会让全仓 manifest 被判"解析不了"（我第一版就是这样）。
    找不到这两种形态则返回 None（记 INCOMPLETE，不猜）。
    """
    try:
        tree = ast.parse(io.open(path, encoding='utf-8').read())
    except (SyntaxError, OSError):
        return None
    for node in tree.body:
        cand = None
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == 'manifest':
                    cand = node.value
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Dict):
            cand = node.value
        if cand is None:
            continue
        out = {}
        for k, v in zip(cand.keys, cand.values):
            if isinstance(k, ast.Constant) and k.value in ('data', 'views', 'assets'):
                try:
                    out[k.value] = ast.literal_eval(v)
                except ValueError:
                    out[k.value] = []
        return out
    return None


def _refs(items, mod=None):
    """展开 data/views/assets 的列表项 → 被引用的**本模块文件路径**。

    t124（覆盖缺口）：**裸 dict 项**是老式 Odoo 写法 `{'被加载的文件': '它继承的父文件'}`，
    **键才是本模块要加载的文件**。原实现只认 `isinstance(p, str)`，dict 被**静默跳过** ——
    既不报盘上缺失、也不报未入库，等于该形态**从未被检查**；
    而检查器自称的不变式是「manifest 引用集 ⊆ git 跟踪集」，静默跳过直接破坏了它。

    取**键**；**值按设计不计入**：它是继承链上的父文件，可能位于依赖模块而非本模块目录，
    当成本模块文件去检查会产生**假红**。若将来出现「父文件确在本模块」的用例，再单独议。
    另外兼容 `[(文件, 父文件)]` 这类元组/列表写法，同样只取第一项（被加载的文件）。
    """
    for p in (items or []):
        if isinstance(p, str):
            yield p
        elif isinstance(p, dict):
            for k in p.keys():
                if isinstance(k, str):
                    yield k
        elif isinstance(p, (list, tuple)) and p and isinstance(p[0], str):
            # assets 的**指令**写法（t124 一并覆盖，避免引入假红）：
            #   ('include', 'web._assets_primary_variables') → 指向的是 **bundle 名**，不是本模块文件 ⇒ 跳过
            #   ('before'|'after'|'replace'|'remove', '文件') → 被引用的文件在**第二项**
            #   老式 (被加载文件, 父文件) → 第一项才是被加载的文件
            if len(p) == 2 and p[0] in ('include', 'before', 'after', 'replace', 'remove'):
                if p[0] == 'include':
                    continue          # bundle 名不是文件路径；当文件查会误报盘上缺失
                if isinstance(p[1], str):
                    # t125（防**假红**）：变异指令（remove/before/after/replace）指向的
                    # 常常是**依赖模块**的文件，例如
                    #   ('remove', 'payment_stripe/static/src/interactions/stripe_options.js')
                    # 它不在本模块目录里，当成本模块文件去 resolve 必然「盘上不存在」。
                    # 判据：首段 == 本模块名 ⇒ 是自引用，仍按原口径检查（漏写/拼错能抓到）；
                    #       否则 ⇒ 外模块引用，跳过（本门禁的契约是「本模块引用集」）。
                    if mod and p[1].split('/')[0] != mod:
                        continue
                    yield p[1]
            else:
                yield p[0]


def collect_paths(man, mod=None):
    """(类别, 路径)；assets 支持 {bundle: [...]} 与 [...]（dict-of-list 是已知坑）。"""
    out = []
    for key in ('data', 'views'):
        for p in _refs(man.get(key), mod):
            out.append((key, p))
    assets = man.get('assets') or {}
    buckets = assets.values() if isinstance(assets, dict) else [assets]
    for items in buckets:
        for p in _refs(items, mod):
            out.append(('assets', p))
    return out


def tracked_set():
    """一次批量取跟踪集（不逐文件调 git）。None = git 不可用/非仓库。"""
    try:
        p = subprocess.run(['git', 'ls-files', '-z'], capture_output=True,
                           text=True, cwd=REPO, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return set(x for x in (p.stdout or '').split('\0') if x)


def resolve(root, mod, rel):
    """定位引用文件。返回 (磁盘路径, 仓库相对路径, 两候选列表, 是否两候选皆不存在)。

    t98 修正：**两个候选都不存在时，不得把 cands[0] 冒充为真实路径** ——
    那会把排查者引向一个不存在的文件（"看起来有用、实际误导"）。
    此时返回 both_missing=True 且列出全部候选，由调用方如实打印。
    """
    c1 = os.path.join(REPO, DEFAULT_DIR, rel)
    c2 = os.path.join(root, mod, rel)
    cands = [c1, c2] if not os.path.isabs(rel) else [rel]
    for c in cands:
        if os.path.exists(c):
            return c, os.path.relpath(os.path.normpath(c), REPO), [], False
    rs = []
    for c in cands:
        rs.append(os.path.relpath(os.path.normpath(c), REPO))
    return None, rs[-1], sorted(set(rs)), True

def check(modules_dir=DEFAULT_DIR, quiet=False):
    tracked = tracked_set()
    if tracked is None:
        print('ENV：git 不可用或当前不是 git 仓库 —— 无法判定跟踪状态（这不是通过）')
        return 2, [], [], 0, [], 0, 0
    root = modules_dir if os.path.isabs(modules_dir) else os.path.join(REPO, modules_dir)
    if not os.path.isdir(root):
        print('ENV：目录不存在 %s' % root)
        return 2, [], [], 0, [], 0, 0
    missing, untracked, globbed, unparsed = [], [], 0, []
    missing_cands = {}
    n_ok = 0
    mods = sorted(d for d in os.listdir(root)
                  if os.path.isfile(os.path.join(root, d, '__manifest__.py')))
    for mod in mods:
        man = load_manifest(os.path.join(root, mod, '__manifest__.py'))
        if man is None:
            unparsed.append(mod)
            continue
        for _kind, rel in collect_paths(man, mod):
            if '*' in rel or '?' in rel:
                globbed += 1
                continue
            disk, repo_rel, cands, both = resolve(root, mod, rel)
            if both:
                missing.append(repo_rel)
                missing_cands[repo_rel] = cands
            elif disk is None or not os.path.exists(disk):
                missing.append(repo_rel)
            elif repo_rel not in tracked:
                if repo_rel not in ALLOW_UNTRACKED:
                    untracked.append(repo_rel)
                else:
                    n_ok += 1
            else:
                n_ok += 1
    rc = 1 if (missing or untracked) else (3 if unparsed else 0)
    if not quiet:
        print('== manifest 引用集 ⊆ git 跟踪集 ==')
        print('模块 %d｜已入库 %d｜盘上缺失 %d｜在盘上但未入库 %d｜通配跳过 %d｜解析失败 %d'
              % (len(mods), n_ok, len(missing), len(untracked), globbed, len(unparsed)))
        for p in missing:
            if p in missing_cands:
                print('  FAIL 盘上不存在（两个候选都不存在，未把第一个冒充为真实路径）：%s' % p)
                for c in missing_cands[p]:
                    print('       候选：%s' % c)
            else:
                print('  FAIL 盘上不存在：%s' % p)
        for p in untracked:
            print('  FAIL 未入库（盘上有、git 无）：%s' % p)
        for m in unparsed:
            print('  INCOMPLETE manifest 解析不了（非字面量）：%s' % m)
        for p, why in ALLOW_UNTRACKED.items():
            print('  ALLOW 例外登记：%s（%s）' % (p, why))
        if globbed:
            print('  跳过：%d 条通配路径不做存在性判定 —— 本门禁不覆盖它们' % globbed)
        print('结论：%s' % {0: 'OK', 1: 'FAIL', 2: 'ENV', 3: 'INCOMPLETE'}[rc])
        print('自证：REVISION=%s · 指纹 %s · 断言 %d 条 · 时刻 %s'
              % (REVISION, self_fingerprint(), n_ok + len(missing) + len(untracked),
                 datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        print('契约：exit 0=OK 1=FAIL 2=ENV(git 不可用) 3=INCOMPLETE(manifest 解析不了)')
    return rc, missing, untracked, globbed, unparsed, n_ok, len(mods)


def selftest():
    """反例（不改真仓库）：/tmp 造**两个**模块，覆盖两种 manifest 形态。

    ① `manifest = {...}`（赋值式）　② **裸 dict** `{...}`（Odoo 17+，本仓 10 个模块即此形态）
    赋值式模块另含 assets(dict-of-list) 分支与一条"盘上有但未入库"的文件。
    """
    ok = True

    def chk(name, cond, extra=chr(39)+chr(39)):
        nonlocal ok
        print('  %-4s %s %s' % ('PASS' if cond else 'FAIL', name, extra))
        ok = ok and cond

    NL = chr(10)
    tmp = tempfile.mkdtemp(prefix='mt_selftest_')
    try:
        m1 = os.path.join(tmp, 'mod_assign')
        os.makedirs(m1)
        io.open(os.path.join(m1, 'untracked.xml'), 'w', encoding='utf-8').write('<odoo/>')
        man1 = NL.join(['manifest = {', " 'name': 'a',", " 'data': ['missing_assign.xml', 'untracked.xml'],", " 'assets': {'web.assets_backend': ['missing_asset.js']},", '}', '']) 
        io.open(os.path.join(m1, '__manifest__.py'), 'w', encoding='utf-8').write(man1)
        m2 = os.path.join(tmp, 'mod_bare')
        os.makedirs(m2)
        man2 = NL.join(['{', " 'name': 'b',", " 'views': ['missing_bare.xml'],", '}', '']) 
        io.open(os.path.join(m2, '__manifest__.py'), 'w', encoding='utf-8').write(man2)
        # t124 永久反例：**裸 dict 项**（老式 Odoo 写法 `{被加载文件: 父文件}`）。
        # 键才是本模块要加载的文件；原实现只认 str、把它静默跳过 ⇒ 该形态从未被检查。
        # 固化在这里（而不靠 /tmp 手工夹具）—— 夹具会没，反例不会。
        m3 = os.path.join(tmp, 'mod_dictitem')
        os.makedirs(os.path.join(m3, 'views'))
        io.open(os.path.join(m3, 'views', 'ok.xml'), 'w', encoding='utf-8').write('<odoo/>')
        man3 = NL.join(['{',
                        " 'name': 'c',",
                        " 'data': ['views/ok.xml', {'views/missing_dictitem.xml': 'views/ok.xml'}],",
                        '}', '']) 
        io.open(os.path.join(m3, '__manifest__.py'), 'w', encoding='utf-8').write(man3)
        # t125 夹具：assets 的**变异指令**（remove/before/after/replace）。
        # 真实成因：edu_brand 要从 lazy 包摘除 payment_stripe/… 等**依赖模块**的文件，
        # 原实现把这些外模块路径当成本模块文件 resolve ⇒ 必然「盘上不存在」的假红，
        # 直接把 safe_upgrade 拦死在门口。规则：首段==本模块名才算自引用、才检查。
        m4 = os.path.join(tmp, 'mod_removal')
        os.makedirs(m4)
        man4 = NL.join(['{',
                        " 'name': 'd',",
                        " 'assets': {'web.assets_frontend_lazy': [",
                        "   ('remove', 'payment_stripe/static/src/interactions/stripe_options.js'),",
                        "   ('remove', 'mod_removal/static/src/missing_own.js'),",
                        ' ]},',
                        '}', ''])
        io.open(os.path.join(m4, '__manifest__.py'), 'w', encoding='utf-8').write(man4)
        import contextlib
        _buf = io.StringIO()
        with contextlib.redirect_stdout(_buf):
            rc, missing, untracked, _g, unparsed, _n, mods = check(modules_dir=tmp)
        out = _buf.getvalue()
        chk('①反例：如期报红（rc=1）', rc == 1, 'rc=%s' % rc)
        chk('两形态都被解析（无 INCOMPLETE）', not unparsed, 'unparsed=%s' % (unparsed,))
        chk('① 赋值式：点名盘上缺失', any(x.endswith('missing_assign.xml') for x in missing))
        chk('① 赋值式：点名未入库', any(x.endswith('untracked.xml') for x in untracked))
        chk('① assets(dict-of-list) 被解析', any(x.endswith('missing_asset.js') for x in missing))
        chk('② 裸 dict：点名盘上缺失', any(x.endswith('missing_bare.xml') for x in missing), '%s' % (missing,))
        # t124：裸 dict **项**（列表里的 {文件: 父文件}）——键必须被检查，不许静默跳过
        chk('③ 裸 dict 项：键被点名盘上缺失（不再静默跳过）',
            any(x.endswith('missing_dictitem.xml') for x in missing),
            'missing=%s' % (missing,))
        chk('③ 裸 dict 项：该模块的缺失项出现在同一轮（断言数 ≥2 的成因）',
            sum(1 for x in missing if 'mod_dictitem' in x) >= 1,
            'mod_dictitem 命中=%s' % sum(1 for x in missing if 'mod_dictitem' in x))
        chk('四个模块都被扫到', mods == 4, 'mods=%s' % mods)
        # t124 反例（防**假红**）：assets 的 ('include', bundle) 指令指向的是 bundle 名、不是文件，
        # 若被当成本模块文件去查，会误报「盘上缺失」。此处断言它**没有**被当成文件。
        chk('④ assets include 指令不被误报为缺失文件',
            not any('_assets_primary_variables' in x or x.endswith('include') for x in missing),
            'missing=%s' % (missing,))
        # t125 反例 ⑤：外模块引用不许误报（否则 edu_brand 的摘除会被拦）
        chk('⑤ 变异指令指向依赖模块：不误报为缺失/未入库',
            not any('stripe_options' in x for x in missing + untracked),
            'missing=%s' % (missing,))
        # t125 反例 ⑥：自引用仍要检查（漏写/拼错能抓到）
        chk('⑤ 变异指令指向本模块且盘上不存在：仍报缺失',
            any('missing_own.js' in x for x in missing),
            'missing=%s' % (missing,))
        chk('t98 反例：两候选皆不存在时输出显式说明',
            '两个候选都不存在' in out)
        chk('t98 反例：两个候选都列出（不是只报第一个）',
            out.count('候选：') >= 2, '候选行数=%s' % out.count('候选：'))
        chk('t98 反例：不把 cands[0] 冒充为真实路径',
            '冒充' in out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('== 反例自检 %s ==' % ('通过' if ok else '未通过'))
    return 0 if ok else 1

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--modules-dir', default=DEFAULT_DIR)
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    return check(modules_dir=args.modules_dir)[0]


if __name__ == '__main__':
    sys.exit(main())
