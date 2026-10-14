# -*- coding: utf-8 -*-
"""edu_tg_assist 正文截断的回归用例（**不需要数据库、不需要 Odoo**）。

为什么要有它：Telegram 对 sendMessage.text **超过 4096 个 UTF-16 码元是整条拒收**
（400 MESSAGE_TOO_LONG），不是截断 —— 广播/催交没人盯着屏幕，整条丢就是静默失效。
截断算法的两个坑必须钉住：
  1) 长度单位是 UTF-16 码元（中文 1、emoji 2），按 len(str) 算会少算一半；
  2) 不能在代理对中间切开（那会产出非法文本，Telegram 照样拒收）。

用法：python3 tests/unit/tg_assist_text_test.py   （退出码 0=全通过 / 1=有失败）
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist', 'tgtext.py')

spec = importlib.util.spec_from_file_location('tg_assist_text', SPEC)
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


def valid_utf16(text):
    """能被 UTF-16 双向编解码 = 没有落单的代理码元。"""
    try:
        return text.encode('utf-16-le').decode('utf-16-le') == text
    except UnicodeError:
        return False


# ---- 1) 计数口径：UTF-16 码元，不是字符 ----
check('空串 → 0', T.utf16_len('') == 0)
check('None 当空串 → 0', T.utf16_len(None) == 0)
check('ASCII 3 → 3', T.utf16_len('abc') == 3)
check('中文 2 字 → 2', T.utf16_len(u'中文') == 2)
check('emoji（代理对）→ 2', T.utf16_len(u'\U0001F600') == 2)
check('中文 2 + emoji 1 → 4', T.utf16_len(u'中文\U0001F600') == 4)

# ---- 2) 不超限就原样返回 ----
raw = u'各位同事请注意：本周五下午三点开会。'
out, cut = T.clamp_telegram_text(raw)
check('短文本原样返回', out == raw and cut is False, repr((out, cut)))
out, cut = T.clamp_telegram_text('')
check('空串原样返回', out == '' and cut is False)
out, cut = T.clamp_telegram_text(None)
check('None → 空串不报错', out == '' and cut is False)

# ---- 3) 恰好等于上限：不截断 ----
exact = 'a' * T.TELEGRAM_TEXT_LIMIT
out, cut = T.clamp_telegram_text(exact)
check('恰好 4096 → 不截断', out == exact and cut is False)

# ---- 4) 超一个码元：截断到 4096 且带省略号 ----
over = 'a' * (T.TELEGRAM_TEXT_LIMIT + 1)
out, cut = T.clamp_telegram_text(over)
check('4097 → 截断', cut is True)
check('4097 → 结果长度 4096', T.utf16_len(out) == T.TELEGRAM_TEXT_LIMIT, str(T.utf16_len(out)))
check('4097 → 以省略号结尾', out.endswith(T.ELLIPSIS))
check('4097 → 保留前缀', out[:-1] == 'a' * (T.TELEGRAM_TEXT_LIMIT - 1))

# ---- 5) 代理对边界：绝不切出半个 emoji ----
emoji_exact = u'\U0001F600' * (T.TELEGRAM_TEXT_LIMIT // 2)
out, cut = T.clamp_telegram_text(emoji_exact)
check('2048 个 emoji（恰好 4096）→ 不截断', cut is False and out == emoji_exact)

emoji_over = u'\U0001F600' * (T.TELEGRAM_TEXT_LIMIT // 2 + 1)
out, cut = T.clamp_telegram_text(emoji_over)
check('2049 个 emoji → 截断', cut is True)
check('emoji 截断后 ≤ 4096 码元', T.utf16_len(out) <= T.TELEGRAM_TEXT_LIMIT, str(T.utf16_len(out)))
check('emoji 截断后没有落单代理码元', valid_utf16(out), repr(out[-3:]))
check('emoji 截断后以省略号结尾', out.endswith(T.ELLIPSIS))

# 奇偶交错的混合文本：每个可能的切口都不许切坏
mixed = (u'中文\U0001F600 ab') * 600   # 每轮 7 个码元 ⇒ 4200 > 4096
out, cut = T.clamp_telegram_text(mixed)
check('混合文本截断后 ≤ 4096 码元', T.utf16_len(out) <= T.TELEGRAM_TEXT_LIMIT, str(T.utf16_len(out)))
check('混合文本截断后是合法 UTF-16', valid_utf16(out))
check('混合文本确实被截断', cut is True)

# ---- 6) 自定义/极小 limit 不能崩 ----
out, cut = T.clamp_telegram_text('abcdef', limit=3)
check('limit=3 → ab…', out == 'ab' + T.ELLIPSIS and cut is True, repr(out))
out, cut = T.clamp_telegram_text('abcdef', limit=1)
check('limit=1 → 只有省略号', out == T.ELLIPSIS and cut is True, repr(out))
out, cut = T.clamp_telegram_text('abcdef', limit=0)
check('limit=0 → 空串（截断态）', out == '' and cut is True)
out, cut = T.clamp_telegram_text('', limit=0)
check('空串 + limit=0 → 空串不截断', out == '' and cut is False)

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(('PASS  ' if ok else 'FAIL  ') + name + (('   <- ' + detail) if (detail and not ok) else ''))
print('----')
print('共 %s 条，失败 %s 条' % (len(results), len(failed)))
sys.exit(1 if failed else 0)
