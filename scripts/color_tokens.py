#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""color_tokens.py —— 唯一颜色令牌源的机械提取器与门禁。

依据：docs/plans/color-system-v4.md §6.2 / §6.3 / §6.4

用法：
    python3 scripts/color_tokens.py                  # 摘要（不写文件）
    python3 scripts/color_tokens.py --write          # 重新生成 color_tokens.json
    python3 scripts/color_tokens.py --check          # 门禁（棘轮），退出码 0/1
    python3 scripts/color_tokens.py --check --strict # 全量复核（全部目标文件视为已收口）

设计要点：
  · 令牌集**只**从 SCSS 单源机械提取，不从任何 CSS 抓（§6.2 令牌集来源）。
  · 通道令牌一律「派生」（#{red($x)} #{green($x)} #{blue($x)}），
    因此提取器只需认派生模式，不需要 SCSS 求值器（§2.7）。
  · 门禁判据「是不是真的静默覆盖」而非「谁在哪个模块」（§6.3）。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_SRC = os.path.join(ROOT, "custom_addons/edu_brand/static/src/scss/brand_tokens.scss")
JSON_PATH = os.path.join(ROOT, "scripts/color_tokens.json")
SCAN_DIR = os.path.join(ROOT, "custom_addons")
SCAN_EXT = (".css", ".scss")
BG_TOKEN = "--bg"

# §6.4 豁免白名单（脚本常量，t9 直接复用）
EXEMPT = {"#ffffff", "#fff", "#000000", "#000", "transparent", "rgba(0,0,0,0)"}
DISABLED_EXEMPT_CONTRAST = {"--text-disabled"}
NON_TEXT_TOKENS = {"--shadow", "--focus-ring", "--border", "--border-strong"}

# 本次已收口文件（棘轮，§6.3 item 5）。各任务收口完自行追加自己的文件。
# 棘轮（§6.3）：只有列在这里的文件才参与「令牌外裸色 ⇒ FAIL」。
# t3 的初始集；**后续各任务请把文件追加到 scripts/adopted_files.txt（一行一个路径）**，
# 不要改这个常量 —— 该文本文件是**追加式共享数据**，t4/t5 并发收口时不会互相冲突。
ADOPTED_FILES = [
    "custom_addons/edu_brand/static/src/scss/brand_tokens.scss",
]

# 追加式共享清单（一行为一个 workspace 相对路径，# 开头与空行忽略）。
ADOPTED_FILES_EXTRA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "adopted_files.txt")


def load_adopted():
    """ADOPTED_FILES ∪ scripts/adopted_files.txt（后者供 t4/t5/t7/t8 各自追加）。"""
    out = list(ADOPTED_FILES)
    if os.path.exists(ADOPTED_FILES_EXTRA):
        for line in open(ADOPTED_FILES_EXTRA, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and line not in out:
                out.append(line)
    return out


# --------------------------------------------------------------------------
# 颜色工具
# --------------------------------------------------------------------------
def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminance(h):
    r, g, b = hex_to_rgb(h)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def norm_hex(h):
    return "#" + "".join("%02x" % c for c in hex_to_rgb(h))


RX_ROOT_SEL = re.compile(r"(^|,)\s*(:root|html|body)\s*($|,)|\[data-bs-theme\][^,{]*\bbody\b", re.I)


# 规范 §1.4 规则 1 的保留命名空间：只有这些名字才作为「令牌」参与判重与作用域覆盖计数。
RESERVED_RX = re.compile(
    r"^--(brand|text|border|fill|surface|success|warning|danger|info|neutral"
    r"|gold|shadow|focus-ring|bg)(-|$)")


def is_reserved(name):
    return bool(RESERVED_RX.match(name or ""))


def is_root_selector(sel):
    """只有 :root / html / body / [data-bs-theme] body 这一级参与令牌判重。

    组件作用域的局部变量（如 .ux3-page{--ux3-gold:...}）是**局部**声明，
    不是全局令牌，不参与判重；但它们的字面值仍按「令牌外色」计（判据5）。
    依据：captain 本轮口径细化。
    """
    return bool(RX_ROOT_SEL.search(sel or ""))


def canon_value(v):
    """把声明值归一成可比形式；返回 None 表示「不是字面值」（var() 别名等，判据4 不计数）。"""
    if v is None:
        return None
    v = v.strip()
    if v.startswith("var(") or v.startswith("#{"):
        # #{...} 插值在令牌源里由提取器单独解析，别处出现一律视作引用
        return None
    m = RX_HEX.search(v)
    if m:
        try:
            return norm_hex(m.group(0))
        except Exception:
            return None
    for rx in (RX_COMMA_TRIPLE, RX_SPACE_TRIPLE):
        m = rx.match(v)
        if m:
            return "%d %d %d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


# --------------------------------------------------------------------------
# 1. 从 SCSS 单源机械提取令牌
# --------------------------------------------------------------------------
RX_SCSS_VAR = re.compile(r"^\s*\$([A-Za-z0-9_-]+)\s*:\s*(#[0-9A-Fa-f]{3,8})\s*;", re.M)
# 规范 §2.7 规则 1（r4 反转）：通道令牌一律**逗号分隔**。
# 三种写法都收：", " / "," / 无分隔（后者由判据 6 判 FAIL，这里仍要能提取以便报错）
RX_CH_DERIVED = re.compile(
    r"--([A-Za-z0-9_-]+)-rgb\s*:\s*#\{red\(\$([A-Za-z0-9_-]+)\)\}\s*,?\s*"
    r"#\{green\(\$([A-Za-z0-9_-]+)\)\}\s*,?\s*#\{blue\(\$([A-Za-z0-9_-]+)\)\}\s*;"
)
# 注意：不能用 [^;}]+ —— 派生式里含 #{} 插值的 }，会把值截断成 "#{red($x)"
# 从而看不到后面的逗号。按行取到分号为止。
RX_CH_DEF = re.compile(r"(--[A-Za-z0-9_-]+-rgb)\s*:\s*([^;\n]+);", re.M)
RX_PROP_SLASH = re.compile(r"([A-Za-z-]+)\s*:\s*[^;{}]{0,200}rgb\(var\(")
# 裸变量赋自定义属性（--x: $y; 无 #{}）。不能只锚行首：声明常跟在 { 或 ; 之后。
# 同时排除 --x: #{...} 与 --x: var(...)。
RX_BARE_VAR = re.compile(
    r"(?:^|[;{}])\s*(--[A-Za-z0-9_-]+)\s*:\s*\$[A-Za-z0-9_-]+\s*;", re.M)
RX_CH_DIRECT = re.compile(
    r"--([A-Za-z0-9_-]+)-rgb\s*:\s*(\d{1,3})\s*,?\s*(\d{1,3})\s*,?\s*(\d{1,3})\s*;")
RX_EMIT = re.compile(r"^\s*--([A-Za-z0-9_-]+)\s*:\s*#\{\$([A-Za-z0-9_-]+)\}\s*;", re.M)
# 别名：SCSS 级（$neutral: $text-3;）与 CSS 级（--neutral: var(--text-3);）。
# 令牌源大量用别名，必须能解析，否则「--neutral-rgb 由 $neutral 派生」
# 会被误判成「基色未定义」，而判据 8 也会把合法的别名令牌判 FAIL。
RX_SCSS_ALIAS = re.compile(r"^\s*\$([A-Za-z0-9_-]+)\s*:\s*\$([A-Za-z0-9_-]+)\s*;", re.M)
RX_CSS_ALIAS = re.compile(r"^\s*--([A-Za-z0-9_-]+)\s*:\s*var\(\s*--([A-Za-z0-9_-]+)\s*\)\s*;", re.M)


class ExtractError(Exception):
    pass


def extract_tokens():
    if not os.path.exists(TOKEN_SRC):
        raise ExtractError("令牌源不存在: %s" % TOKEN_SRC)
    raw = open(TOKEN_SRC, encoding="utf-8").read()
    # ⚠ 必须先剥注释再提取：否则注释里的**示例**（如文档中写的
    #   "--x-rgb: 14 123 242;"）会被当成真的通道令牌，进而让判据 8
    #   报「--x-rgb 缺同名基色 --x」——实测踩过（2026-09-15，给注释加 A/B/C 例子时暴露）。
    src = strip_comments(raw, TOKEN_SRC.endswith(".scss"))
    scss_vars = {}
    for m in RX_SCSS_VAR.finditer(src):
        scss_vars[m.group(1)] = m.group(2)
    if not scss_vars:
        raise ExtractError("未从令牌源提取到任何 $name: #hex; 声明")

    # --- 解析 SCSS 别名链（含多级）-----------------------------
    alias = {m.group(1): m.group(2) for m in RX_SCSS_ALIAS.finditer(src)}

    def _resolve_scss(name, seen=()):
        if name in scss_vars:
            return scss_vars[name]
        if name in alias and name not in seen:
            return _resolve_scss(alias[name], seen + (name,))
        return None

    scss_aliases = {}
    for k in list(alias):
        v = _resolve_scss(k)
        if v:
            scss_vars.setdefault(k, v)
            scss_aliases[k] = v

    tokens = {}   # --name -> {"value","scss","white","bg"}
    bg = scss_vars.get("bg", "#F4F7FA")
    for m in RX_EMIT.finditer(src):
        name, var = m.group(1), m.group(2)
        if var not in scss_vars:
            raise ExtractError("--%s 引用了未定义的 $%s" % (name, var))
        val = scss_vars[var]
        tokens["--" + name] = {
            "value": val.upper(),
            "scss": "$" + var,
            "white": contrast(val, "#FFFFFF"),
            "bg": contrast(val, bg),
        }

    # --- CSS 级别名也要进 token 表（判据 8 靠它找同名基色）---------
    for m in RX_CSS_ALIAS.finditer(src):
        name, base = m.group(1), m.group(2)
        bt = tokens.get("--" + base)
        if bt is None:
            continue
        tokens.setdefault("--" + name, {
            "value": bt["value"],
            "scss": bt["scss"],
            "alias_of": "--" + base,
            "white": bt["white"],
            "bg": bt["bg"],
        })

    channels = {}  # --name-rgb -> {"value","base"}
    for m in RX_CH_DERIVED.finditer(src):
        ch, b1, b2, b3 = m.group(1), m.group(2), m.group(3), m.group(4)
        if not (b1 == b2 == b3):
            raise ExtractError("通道令牌 --%s-rgb 的派生式三个变量不一致" % ch)
        if b1 not in scss_vars:
            raise ExtractError("通道令牌 --%s-rgb 的基色 $%s 未定义" % (ch, b1))
        r, g, b = hex_to_rgb(scss_vars[b1])
        channels["--%s-rgb" % ch] = {
            "value": "%d, %d, %d" % (r, g, b),
            "value_normalized": "%d %d %d" % (r, g, b),
            "base": "--" + b1,
        }
    for m in RX_CH_DIRECT.finditer(src):
        name = "--%s-rgb" % m.group(1)
        channels[name] = {
            "value": "%s, %s, %s" % (m.group(2), m.group(3), m.group(4)),
            "value_normalized": "%s %s %s" % (m.group(2), m.group(3), m.group(4)),
            "base": "--" + m.group(1),
        }
    return tokens, channels, src


# --------------------------------------------------------------------------
# 2. 声明点扫描（按 (令牌名, 选择器) 二元组）
# --------------------------------------------------------------------------
RX_COMMENT = re.compile(r"/\*.*?\*/", re.S)
# SCSS 的 // 行注释。用 (?<!:) 避开 https:// 这类 URL。
RX_LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")
RX_HEX = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
RX_COMMA_TRIPLE = re.compile(r"^(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})$")
RX_SPACE_TRIPLE = re.compile(r"^(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})$")


def strip_comments(text, is_scss):
    """注释里的色值不是字面值，必须先剥离再扫。"""
    text = RX_COMMENT.sub(" ", text)
    if is_scss:
        text = RX_LINE_COMMENT.sub(" ", text)
    return text
RX_RGBFUNC = re.compile(r"\brgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")
RX_RGBSPACE = re.compile(r"\brgba?\(\s*(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})")


def iter_files():
    for dirpath, _dirnames, filenames in os.walk(SCAN_DIR):
        for fn in sorted(filenames):
            if fn.endswith(SCAN_EXT):
                yield os.path.join(dirpath, fn)


def scan_declarations(path):
    """产出 (name, selector, value) —— 只含自定义属性声明。"""
    raw = open(path, encoding="utf-8", errors="replace").read()
    text = strip_comments(raw, path.endswith(".scss"))
    out = []
    stack = []
    buf = []
    for ch in text:
        if ch == "{":
            sel = "".join(buf).strip()
            sel = re.sub(r"\s+", " ", sel).split("}")[-1].strip()
            stack.append(sel if sel else ":root")
            buf = []
        elif ch == "}":
            buf = []
            if stack:
                stack.pop()
        elif ch == ";":
            decl = "".join(buf)
            buf = []
            if stack:
                m = re.match(r"\s*(--[A-Za-z0-9_-]+)\s*:\s*(.+?)\s*$", decl, re.S)
                if m:
                    out.append((m.group(1), stack[-1], re.sub(r"\s+", " ", m.group(2)).strip()))
        else:
            buf.append(ch)
    return out


def scan_literals(path):
    """产出文件里所有颜色字面量（hex 与 rgb()/rgba()），归一为小写 hex。

    返回 {颜色: 出现次数}。**注意是 dict 不是 set** —— 棘轮需要同时知道
    「多少个不同的令牌外颜色」与「总共出现多少处」，两者量纲不同（见 run_check）。
    """
    raw = open(path, encoding="utf-8", errors="replace").read()
    text = strip_comments(raw, path.endswith(".scss"))
    found = {}
    for m in RX_HEX.finditer(text):
        k = norm_hex(m.group(0))
        found[k] = found.get(k, 0) + 1
    for rx in (RX_RGBFUNC, RX_RGBSPACE):
        for m in rx.finditer(text):
            k = norm_hex("#%02x%02x%02x" % (int(m.group(1)), int(m.group(2)), int(m.group(3))))
            found[k] = found.get(k, 0) + 1
    return found


# --------------------------------------------------------------------------
# 3. 门禁
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 2b. 计数口径 S1/S2/S3（规范 §4.2.1，r8 定案）
#   S1 全仓：custom_addons/** 的 css/scss/xml/js/py          （规范默认口径）
#   S2 门户 CSS：custom_addons/edu_portal/static/src/css/*.css
#   S3 单一家族：某一 base 的 α 分布（逐族输出直方图）
# 规范要求：必须以 --scope S1|S2|S3 支持，且输出必须带口径标签。
# --------------------------------------------------------------------------
SCOPE_DESC = {
    "S1": "全仓 custom_addons/** 的 css/scss/xml/js/py",
    "S2": "门户 9 个 CSS：custom_addons/edu_portal/static/src/css/*.css",
    "S3": "单一家族（某一 base 的 α 分布）",
}

# 规范 §4.2.1 L792 点名的 8 个族
FAMILIES = ["brand-500", "text-1", "success", "danger", "warning",
            "neutral", "gold-500", "shadow"]

RX_ALPHA_COMMA = re.compile(
    r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([0-9.]+)\s*)?\)")
RX_ALPHA_SPACE = re.compile(
    r"rgba?\(\s*(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})\s*/\s*([0-9.]+)\s*\)")
SCAN_EXT_S1 = (".css", ".scss", ".xml", ".js", ".py")


def scope_files(scope):
    if scope == "S2":
        d = os.path.join(SCAN_DIR, "edu_portal/static/src/css")
        return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".css")] \
            if os.path.isdir(d) else []
    out = []
    for dp, _dn, fn in os.walk(SCAN_DIR):
        for f in sorted(fn):
            if f.endswith(SCAN_EXT_S1):
                out.append(os.path.join(dp, f))
    return out


def alpha_histogram(scope):
    """产出 {family: {alpha: count}} 与总计数。α 一律按千分位整数比较（规范 §4.2.1 / 浮点边界教训）。"""
    base_rgb = {}
    for fam, tok in (("brand-500", "--brand-500"), ("text-1", "--text-1"),
                     ("success", "--success"), ("danger", "--danger"),
                     ("warning", "--warning"), ("neutral", "--neutral"),
                     ("gold-500", "--gold-500"), ("shadow", "--shadow")):
        base_rgb[fam] = (tok, None)
    tokens, channels, _src = extract_tokens()
    fam_rgb = {}
    for fam, (tok, _x) in base_rgb.items():
        m = re.match(r"^--(.+)-rgb$", tok + "-rgb")
        ch = channels.get(tok + "-rgb") or channels.get("--%s-rgb" % tok.lstrip("-"))
        if ch:
            nums = [int(x) for x in re.split(r"[,\s]+", ch["value"].strip()) if x]
            fam_rgb[fam] = tuple(nums[:3])
    hist = {f: {} for f in FAMILIES}
    tot = 0
    for path in scope_files(scope):
        txt = strip_comments(open(path, encoding="utf-8", errors="replace").read(),
                             path.endswith(".scss"))
        for rx in (RX_ALPHA_COMMA, RX_ALPHA_SPACE):
            for m in rx.finditer(txt):
                rgb = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
                a = m.group(4)
                if a is None:
                    continue
                for fam, frgb in fam_rgb.items():
                    if frgb and rgb == frgb:
                        key = "%.3f" % float(a)
                        hist[fam][key] = hist[fam].get(key, 0) + 1
                        tot += 1
    return hist, tot, fam_rgb


def print_scope(scope):
    hist, tot, fam_rgb = alpha_histogram(scope)
    print("计数口径 %s = %s" % (scope, SCOPE_DESC.get(scope, "?")))
    if scope == "S3":
        print("%-12s %10s %10s  %s" % ("family", "uses(S3)", "distinct α", "α 直方图"))
        for fam in FAMILIES:
            h = hist[fam]
            if not h:
                continue
            detail = " ".join("%s×%d" % (k, v) for k, v in sorted(h.items()))
            print("%-12s %10d %10d  %s" % (fam, sum(h.values()), len(h), detail))
            print("%-12s %10s %10s  → 按族逐行输出（规范 §4.2.1 要求）" % ("", "", ""))
    else:
        union = {}
        for fam in FAMILIES:
            for k, v in hist[fam].items():
                union[k] = union.get(k, 0) + v
        print("  令牌族 α 命中合计 %d 处（%s）" % (tot, scope))
        print("  α 并集 %d 个（%s）：%s" % (len(union), scope,
              " ".join("%s×%d" % (k, v) for k, v in sorted(union.items()))))
    return 0


def run_check(strict=False):
    fails, warns, info = [], [], []
    tokens, channels, src = extract_tokens()
    token_hex = {v["value"].lower() for v in tokens.values()}

    # 判据 8：每个 --x-rgb 必须有同名 --x 基色
    for ch, meta in sorted(channels.items()):
        base = meta["base"]
        if base not in tokens:
            fails.append("判据8 通道令牌 %s 的基色 %s 未在令牌源里定义" % (ch, base))

    # 判据 1/2/3：按 (令牌名, 选择器) 二元组计数。
    # 令牌源自身的规范定义先入表 —— 否则「令牌源用 #{$var} 插值、别处再写字面值」
    # 这类真·静默覆盖会被整条漏掉（首版实现即栽在这里）。
    src_rel = os.path.relpath(TOKEN_SRC, ROOT).replace(os.sep, "/")
    decls = {}
    for name, meta in list(tokens.items()) + list(channels.items()):
        decls.setdefault((name, ":root"), []).append(
            (src_rel, canon_value(meta["value"]) or meta["value"].lower()))
    token_names = set(tokens) | set(channels)
    scoped = {}   # 令牌名 -> {selector: files}（组件作用域覆盖，判据2）
    for path in iter_files():
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        for name, sel, val in scan_declarations(path):
            c = canon_value(val)
            if c is None:
                continue          # var() 别名 / 引用 → 不计数（判据4）
            if not is_root_selector(sel):
                # 局部变量不参与判重；仅**规范保留命名空间**里的令牌名记作用域覆盖。
                # 非保留名（--body-color/--secondary-color/--covenant-gold 等桥接/兼容别名）
                # 不是 §2 令牌，报出来只会是噪声。
                if name in token_names and is_reserved(name):
                    scoped.setdefault(name, {}).setdefault(sel, set()).add(rel)
                continue
            decls.setdefault((name, sel), []).append((rel, c))

    by_name = {}
    for (name, sel), entries in sorted(decls.items()):
        byfile = {}
        for f, v in entries:
            byfile.setdefault(f, set()).add(v)
        by_name.setdefault(name, []).append((sel, byfile))
        if len(byfile) < 2:
            continue
        files = sorted(byfile)
        allvals = sorted({v for vs in byfile.values() for v in vs})
        if len(allvals) > 1:
            fails.append("判据1 静默覆盖: %s 在 %s 上跨文件重复且值不同 (%s)"
                         % (name, sel, "; ".join(
                             "%s=%s" % (f, ",".join(sorted(byfile[f]))) for f in files)))
        else:
            warns.append("判据3 冗余声明: %s @ %s 跨文件同值 (%s)" % (name, sel, ", ".join(files)))

    # 判据 2：令牌名出现在 :root 以外的选择器 = 作用域覆盖（合法），WARN + 计数（t6 待办）。
    # 只报**令牌名**，组件自己的局部变量（--ux3-* 等）不报。
    for name, sels in sorted(scoped.items()):
        where = "; ".join("%s{%s}" % (sel, ",".join(sorted(f))) for sel, f in sorted(sels.items()))
        warns.append("判据2 作用域覆盖: 令牌 %s 在非 :root 选择器被重新声明 (%s)" % (name, where))
    for name, groups in sorted(by_name.items()):
        sels = sorted({sel for sel, _ in groups})
        if len(sels) > 1:
            where = "; ".join("%s{%s}" % (sel, ",".join(sorted(byfile)))
                              for sel, byfile in groups)
            warns.append("判据2 作用域覆盖: %s 出现在 %d 个不同根级选择器 (%s)"
                         % (name, len(sels), where))

    # 判据 6（规范 2.7 四条硬规则；r4 反转后口径，三子项任一命中即 FAIL）：
    #   6a 空格通道定义（--x-rgb 值里没有逗号）—— 喂进逗号式消费会静默失效
    #   6b 普通属性上的斜杠式 rgb(var(    —— libsass 直接编译报错（自定义属性值内允许）
    #   6c 裸变量赋给自定义属性（--x: $y; 无 #{}）—— libsass 不解析、原样输出、不报错
    for path in iter_files():
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        text = strip_comments(open(path, encoding="utf-8", errors="replace").read(),
                              path.endswith(".scss"))
        for m in RX_CH_DEF.finditer(text):
            val = m.group(2)
            # var() 别名不计（判据 4：别名/引用合法）——例如
            #   --shadow-rgb: var(--shadow-ink-rgb);   ← 这是兼容别名，不是空格通道
            if "var(" in val:
                continue
            if "," not in val:
                fails.append("判据6a %s 空格通道定义 %s（规范要求逗号分隔）"
                             % (rel, m.group(1)))
        for m in RX_PROP_SLASH.finditer(text):
            if not m.group(1).startswith("--"):
                fails.append("判据6b %s 普通属性上的斜杠式 rgb(var(（编译直接报错）: %s"
                             % (rel, m.group(1)))
        for m in RX_BARE_VAR.finditer(text):
            fails.append("判据6c %s 裸变量赋自定义属性 %s（必须写 #{} 插值）"
                         % (rel, m.group(0).strip()[:48]))

    # 判据 5：逐批棘轮 —— 已收口文件里的集外裸色 = FAIL；未收口 = 债务 INFO
    adopted = set(load_adopted())
    # 两个量纲**不可混用**（eng-portal 2026-09-15 指出）：
    #   distinct_per_file_sum = Σ_文件 |该文件的令牌外颜色集合|   ← 同一色出现在两个文件会算两次
    #   occurrences           = Σ_文件 Σ_颜色 出现次数            ← 与 captain 报告行的「出现处数」同量纲
    debt_distinct = 0
    debt_occ = 0
    outside_all = set()   # 全仓去重（captain 要的 distinct_outside_colors 必须真按全仓去重算）
    for path in iter_files():
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        lits = scan_literals(path)
        outside = sorted(c for c in lits if c not in token_hex and c not in EXEMPT)
        if not outside:
            continue
        if strict or rel in adopted:
            fails.append("判据5 %s 有 %d 个令牌外裸色: %s"
                         % (rel, len(outside), ", ".join(outside[:12])))
        else:
            occ = sum(lits[c] for c in outside)
            debt_distinct += len(outside)
            debt_occ += occ
            outside_all.update(outside)
            info.append("债务 %s: %d 个令牌外裸色 / %d 处" % (rel, len(outside), occ))

    debt = {
        "distinct_outside_colors": len(outside_all),   # 全仓去重：captain 指定名，语义已对齐
        "distinct_per_file_sum": debt_distinct,        # 逐文件去重后求和（同色跨文件计两次）
        "occurrences": debt_occ,                       # 出现处数
    }
    return fails, warns, info, tokens, channels, debt


def summary(tokens, channels):
    print("令牌源: %s" % os.path.relpath(TOKEN_SRC, ROOT))
    print("不透明令牌: %d    通道令牌: %d" % (len(tokens), len(channels)))
    print()
    print("%-22s %-9s %7s %7s  %s" % ("令牌", "值", "白底", "--bg 上", "备注"))
    for name in sorted(tokens):
        t = tokens[name]
        note = ""
        if name in DISABLED_EXEMPT_CONTRAST:
            note = "禁用态豁免"
        elif name in NON_TEXT_TOKENS:
            note = "非文本(3:1)"
        elif t["white"] < 4.5:
            note = "禁作正文/链接"
        print("%-22s %-9s %7.2f %7.2f  %s" % (name, t["value"], t["white"], t["bg"], note))
    print()
    for name in sorted(channels):
        c = channels[name]
        print("%-22s %-14s base=%s" % (name, c["value"], c["base"]))


def write_json(tokens, channels, debt):
    data = {
        "generated_by": "scripts/color_tokens.py",
        "source": os.path.relpath(TOKEN_SRC, ROOT).replace(os.sep, "/"),
        "note": "令牌集唯一机读输入；不得手工维护（§6.2）。",
        "tokens": tokens,
        "channels": channels,
        "exempt": sorted(EXEMPT),
        "disabled_exempt_contrast": sorted(DISABLED_EXEMPT_CONTRAST),
        "non_text_tokens": sorted(NON_TEXT_TOKENS),
        "adopted_files": load_adopted(),
        # 旧名 "files" 是错的（值从来不是文件数）—— 2026-09-15 按 eng-portal 的核对更正；
        # 旧字段已删除，避免 t9 按名字误读。两个量纲都给，用哪个由报告格式指定。
        "debt": {
            "distinct_outside_colors": debt["distinct_outside_colors"],
            "distinct_per_file_sum": debt["distinct_per_file_sum"],
            "occurrences": debt["occurrences"],
            "note": "未收口文件的令牌外裸色（INFO，不阻断）。**三个量纲不同，不可混用**："
                    "distinct_outside_colors=全仓去重后的令牌外颜色数（棘轮单调性建议用它）；"
                    "distinct_per_file_sum=Σ_文件 该文件的不同色数（同色跨文件计两次）；"
                    "occurrences=出现处数（与报告行的『出现处数』同量纲）。",
        },
    }
    with open(JSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return JSON_PATH


def main(argv):
    strict = "--strict" in argv
    scope = "S1"
    for i, a in enumerate(argv):
        if a == "--scope" and i + 1 < len(argv):
            scope = argv[i + 1].upper()
        elif a.startswith("--scope="):
            scope = a.split("=", 1)[1].upper()
    if scope in ("S1", "S2", "S3") and ("--scope" in argv or any(a.startswith("--scope=") for a in argv)):
        try:
            return print_scope(scope)
        except ExtractError as exc:
            print("判据9 FAIL: 令牌源提取失败: %s" % exc)
            return 1
    if "--check" in argv:
        try:
            fails, warns, info, tokens, channels, debt = run_check(strict)
        except ExtractError as exc:
            print("判据9 FAIL: 令牌源提取失败: %s" % exc)
            return 1
        for w in warns:
            print("WARN  %s" % w)
        for i in info:
            print("INFO  %s" % i)
        print()
        if fails:
            for f in fails:
                print("FAIL  %s" % f)
            print("\n门禁结果: FAIL (%d)  [%s]" % (len(fails), "strict" if strict else "ratchet"))
            return 1
        print("门禁结果: PASS  [%s]  令牌 %d / 通道 %d / WARN %d / 债务 令牌外色 %d 个（去重）/ 出现 %d 处"
              % ("strict" if strict else "ratchet", len(tokens), len(channels), len(warns),
                 debt["distinct_outside_colors"], debt["occurrences"]))
        return 0

    try:
        tokens, channels, _src = extract_tokens()
    except ExtractError as exc:
        print("提取失败: %s" % exc)
        return 1
    summary(tokens, channels)
    if "--write" in argv:
        _fails, _w, _i, _t, _c, debt = run_check(strict=False)
        path = write_json(tokens, channels, debt)
        print("\n已写入 %s" % os.path.relpath(path, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
