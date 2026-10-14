# -*- coding: utf-8 -*-
"""edu_tg_assist 按钮层（menutext.py）的回归用例（**不需要数据库、不需要 Odoo**）。

为什么要有它：
  · 底部键盘上任何一个按钮没写进 BUTTON_ACTIONS，就是一个「按了没反应」的死按钮 ——
    用户看得到、点得动，却什么都发生不了。本文件逐字核对每个按钮都有行为键；
  · callback_data 与按钮文案一一对应，拼错/超 64 字节会让 Telegram **整条消息**被拒收，
    所以拼装与解析必须有可执行的证据；
  · 默认角色（没标角色/学生）绝不能拿到管理员按钮 —— 布局按角色分发的证据在这里。

用法：python3 tests/unit/tg_assist_menu_test.py   （退出码 0=全通过 / 1=有失败）
"""
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist', 'menutext.py')
MENU_PY = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist', 'models', 'menu.py')

spec = importlib.util.spec_from_file_location('tg_assist_menutext', SPEC)
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


ADMIN_LABELS = [label for row in M.ADMIN_LAYOUT for label in row]
STAFF_LABELS = [label for row in M.STAFF_LAYOUT for label in row]

# ---- 1) 布局：按角色分发，默认给「少按钮」的那版 ----
check('admin 拿完整版', M.layout_for('admin') == M.ADMIN_LAYOUT)
for role in ('teacher', 'dorm_head', 'other', 'student', '', None):
    check('%r 拿精简版（没有管理员按钮）' % role, M.layout_for(role) == M.STAFF_LAYOUT)
check('精简版里没有发通知按钮', M.ACT_NOTIFY not in [M.BUTTON_ACTIONS[x] for x in STAFF_LABELS])
check('精简版里没有私发按钮', M.ACT_DM not in [M.BUTTON_ACTIONS[x] for x in STAFF_LABELS])

# ---- 2) 死按钮守卫：每个布局按钮都必须有行为键 ----
for label in ADMIN_LABELS + STAFF_LABELS:
    check('按钮 %r 有行为键' % label, label in M.BUTTON_ACTIONS)
check('按钮文案不重复（重复 = 两个按钮一个行为）',
      len(set(ADMIN_LABELS)) == len(ADMIN_LABELS))
check('两版布局共用同一批按钮（admin 版只是多一行）',
      set(STAFF_LABELS).issubset(set(ADMIN_LABELS)))

# ---- 3) button_action：逐字、去空白、认不出给 None ----
for label in ADMIN_LABELS:
    check('button_action(%r)' % label, M.button_action(label) == M.BUTTON_ACTIONS[label])
check('button_action 容忍手打的空格', M.button_action('  ' + M.BACK_LABEL + ' ') is None)
check('button_action 普通文字 → None', M.button_action('明天开会') is None)
check('button_action 空/None → None', M.button_action('') is None and M.button_action(None) is None)

# ---- 4) 底部键盘形状（Telegram ReplyKeyboardMarkup）----
kb_admin = M.reply_keyboard('admin')
kb_staff = M.reply_keyboard('teacher')
check('键盘 4 行 admin / 3 行 teacher（最后一行是「打开面板」）',
      len(kb_admin['keyboard']) == 4 and len(kb_staff['keyboard']) == 3)
check('布局行内是 [{text: …}] 形状',
      all(set(b) == {'text'} for row in kb_admin['keyboard'][:-1] for b in row))
check('键盘文案与布局逐字一致',
      [b['text'] for row in kb_admin['keyboard'][:-1] for b in row] == ADMIN_LABELS
      and [b['text'] for row in kb_staff['keyboard'][:-1] for b in row] == STAFF_LABELS)
check('最后一行 = 单个「打开面板」文字按钮（2026-10-14：web_app 键盘按钮在电脑版打不开）',
      kb_admin['keyboard'][-1] == [{'text': M.WEBAPP_LABEL}]
      and kb_staff['keyboard'][-1] == kb_admin['keyboard'][-1])
check('面板地址跟随 site_url 参数（末尾不留斜杠）',
      M.app_url('https://example.org/') == 'https://example.org' + M.APP_PATH)
check('键盘 resize=true（不撑满屏幕）', kb_admin.get('resize_keyboard') is True)
check('键盘 is_persistent=true（一直看得见）', kb_admin.get('is_persistent') is True)
check('键盘带输入框提示', kb_admin.get('input_field_placeholder') == M.PLACEHOLDER)
check('默认角色（不传参）= 教师版，不是 admin 版',
      M.reply_keyboard()['keyboard'] == kb_staff['keyboard'])
check('未知角色 → 教师版', M.reply_keyboard('nonsense')['keyboard'] == kb_staff['keyboard'])

# ---- 5) callback_data 拼装：前缀唯一 + 超限返回 None ----
check('前缀是 mn（不复用 reply 的 ck / poll 的 p）',
      M.CALLBACK_PREFIX == 'mn' and M.CALLBACK_PREFIX not in ('ck', 'p'))
check('cb 单段', M.cb(M.ACT_HOME) == 'mn:home')
check('cb 多段', M.cb(M.ACT_GROUP, 12) == 'mn:grp:12')
check('cb 数字转字符串', M.cb(M.ACT_TPL_SEND, 3, 7) == 'mn:tps:3:7')
check('cb 超 64 字节 → None（宁可不出这个按钮）',
      M.cb(M.ACT_TPL_OPEN, 'x' * 70) is None)
check('cb 恰好在限内可用', M.cb(M.ACT_TPL_OPEN, 'x' * 30) is not None)
check('CALLBACK_MAX_BYTES = 64', M.CALLBACK_MAX_BYTES == 64)

# ---- 6) parse_callback：本前缀认领，别家的还给别人 ----
for parts in ((M.ACT_HOME,), (M.ACT_GROUP, '12'), (M.ACT_TPL_SEND, '3', '7'),
              (M.ACT_TARGET, '22')):
    data = M.cb(*parts)
    check('cb/parse 往返 %r' % (data,), M.parse_callback(data) == tuple(str(p) for p in parts))
check('不是本前缀 → None（交给 reply / poll）', M.parse_callback('ck:9') is None)
check('空段 → None（缺参的按钮不认）', M.parse_callback('mn:grp:') is None and M.parse_callback('mn:') is None)
check('空/None → None', M.parse_callback('') is None and M.parse_callback(None) is None)
check('只有前缀没动作 → None', M.parse_callback('mn') is None)

# ---- 7) 内联键盘：形状 + 丢坏按钮不丢整屏 ----
conf = M.inline(M.confirm_rows())
check('确认页两行', len(conf['inline_keyboard']) == 2)
check('第一行 = 确认 + 取消',
      [b['callback_data'] for b in conf['inline_keyboard'][0]] == ['mn:send', 'mn:no'])
check('第二行 = 回主菜单', [b['callback_data'] for b in conf['inline_keyboard'][1]] == ['mn:home'])
check('按钮文案逐字', [b['text'] for b in conf['inline_keyboard'][0]]
      == [M.CONFIRM_LABEL, M.CANCEL_LABEL])
check('back_row 是「回主菜单」', M.back_row() == [(M.BACK_LABEL, (M.ACT_HOME,))])
check('全空 → None（不让 Telegram 拒收）', M.inline([]) is None)
check('一行全是不合法按钮 → 整行丢掉、返回 None',
      M.inline([[(M.BACK_LABEL, 'x' * 70)]]) is None)
kept = M.inline([[(M.BACK_LABEL, (M.ACT_HOME,)), (M.BACK_LABEL, 'x' * 70)]])
check('坏按钮单独丢、好按钮留着',
      kept is not None and [b['callback_data'] for b in kept['inline_keyboard'][0]] == ['mn:home'])

# ---- 8) truncate：按钮不撑成多行 ----
check('短的原文返回', M.truncate('学习') == '学习')
long_text = M.truncate('一个很长很长的群名字' * 5, 10)
check('长的截到 limit 并以省略号结尾',
      len(long_text) == 10 and long_text.endswith('…'))
check('空/None 不炸', M.truncate('') == '' and M.truncate(None) == '')

# ---- 9) 静态守卫：menu.py 只引用 menutext 里真实存在的名字（typo = 按钮全废）----
src = open(MENU_PY, encoding='utf-8').read()
for name in sorted(set(re.findall(r'menutext\.([A-Za-z_][A-Za-z0-9_]*)', src))):
    check('menu.py 引用的 menutext.%s 存在' % name, hasattr(M, name))
check('menu.py 确实用到了 menutext（不是空引用）',
      bool(re.search(r'menutext\.[A-Za-z_]', src)))

# ---- 10) 静态守卫：bot.py 调用的「菜单方法名」必须真的存在（2026-10-13 真踩过）----
# 事故：bot.py 写的是 _menu_reply，menu.py 里叫 _tg_assist_menu_reply ——
# 单测全绿、升级全绿，直到真人点按钮才炸 AttributeError（表现为「按了没反应」）。
# 这类跨文件名字错位，只有把两边的源码放在一起核对才拦得住。
BOT_PY = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist', 'models', 'bot.py')
bot_src = open(BOT_PY, encoding='utf-8').read()
called = sorted(set(re.findall(
    r"edu\.tg\.assist\.menu'\]\.sudo\(\)\.([A-Za-z_][A-Za-z0-9_]*)", bot_src)))
check('bot.py 确实调用了菜单模型的方法', bool(called))
for name in called:
    check('bot.py 调用的 menu.%s 在 menu.py 里存在' % name,
          ('def %s(' % name) in src)
for hook in ('_tg_assist_commands', '_tg_assist_handle_callback', '_tg_assist_menu_reply'):
    check('menu.py 提供挂点 %s' % hook, ('def %s(' % hook) in src)
check('bot.py 的挂点名字用的是 menu.py 的真名（不是 _menu_reply 这类简写）',
      '_tg_assist_menu_reply' in bot_src and re.search(r"\._menu_reply\(", bot_src) is None)

# ---- 11) 打开面板的三处入口（2026-10-14 用户 m04148：自带按钮点不动）----
check('键盘整排都没有 web_app 键盘按钮（那玩意儿电脑版会被当普通链接）',
      all('web_app' not in b for row in kb_admin['keyboard'] for b in row))
check('认出「点了那颗按钮」的文案', M.is_app_tap(M.WEBAPP_LABEL)
      and not M.is_app_tap('你好') and not M.is_app_tap(None))
check('点它 → 回一条带内联 web_app 按钮的消息',
      'menutext.is_app_tap(text)' in src and 'menutext.app_inline(' in src)
check('内联按钮指向同一个面板地址',
      M.app_inline()['inline_keyboard'][0][0]['web_app']['url'] == M.app_url())
check('私人聊天那颗 Telegram 自带菜单按钮按需设成面板（有开关、只给教职工）',
      'setChatMenuButton' in src and "'edu_tg_assist.menu_button'" in src
      and "chat.get('type') != 'private'" in src and 'STAFF_ROLES' in src)
check('/menu 会顺手设那颗自带按钮', 'self._ensure_menu_button(chat, person)' in src)
check('设按钮失败不影响 /menu（包在 try 里 + 只记类型名）',
      'except Exception as exc' in src and 'type(exc).__name__' in src)

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    if not ok:
        print('FAIL  %s  %s' % (name, detail))
print('tg_assist_menu_test: %s/%s 通过' % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)