# -*- coding: utf-8 -*-
"""edu_tg_gate 前门路由判据的回归用例（**不需要数据库、不需要 Odoo**）。

为什么要有它：前门判错的代价不对称 ——
  · 把学生的 /start 判给班务 ⇒ 学生**领不到邀请码**（学校招不到人）；
  · 把群消息判给领码流 ⇒ 一个群能把码池刷空（edu_tg_bind 设计 §8 的原由）。
所以「默认朝 bind」这条 fail-safe 必须有**可执行的证据**，不能只写在注释里。

用法：python3 tests/unit/tg_gate_router_test.py   （退出码 0=全通过 / 1=有失败）
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = os.path.join(ROOT, 'custom_addons', 'edu_tg_gate', 'routing.py')

spec = importlib.util.spec_from_file_location('tg_gate_routing', SPEC)
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


def msg(ctype, chat_id=1001, text=None):
    m = {'chat': {'id': chat_id, 'type': ctype}}
    if text is not None:
        m['text'] = text
    return {'message': m}


def dec(update, ready=True, staff=()):
    return R.decide(update, assist_ready=ready, staff_chat_ids=set(staff))


# ---- 1) 形状：不是 dict / 没有 message / 非 message 更新 —— 一律 ignore ----
check('非 dict → ignore', dec('not-a-dict') == R.ROUTE_IGNORE)
check('空 update → ignore', dec({}) == R.ROUTE_IGNORE)
check('my_chat_member（无 message）→ ignore',
      dec({'my_chat_member': {'chat': {'id': 1, 'type': 'private'}}}) == R.ROUTE_IGNORE)
check('chat 缺失 → ignore', dec({'message': {}}) == R.ROUTE_IGNORE)
check('channel 私域外的 chat.type → ignore',
      dec(msg('channel', text='/start')) == R.ROUTE_IGNORE)

# ---- 2) callback_query：只有班务用（bind 的按钮是 url/copy_text，不产生回调）----
check('callback_query（assist 在）→ assist',
      dec({'callback_query': {'id': 'x', 'data': 'a'}}) == R.ROUTE_ASSIST)
check('callback_query（assist 不在）→ ignore',
      dec({'callback_query': {'id': 'x'}}, ready=False) == R.ROUTE_IGNORE)

# ---- 3) 群 / 超级群：归班务；assist 不在时**忽略**（绝不能回流到 bind）----
check('群消息 → assist', dec(msg('group', text='@校长 在吗')) == R.ROUTE_ASSIST)
check('超级群消息 → assist', dec(msg('supergroup', text='hi')) == R.ROUTE_ASSIST)
check('群消息（assist 不在）→ ignore，不是 bind',
      dec(msg('group', text='hi'), ready=False) == R.ROUTE_IGNORE)

# ---- 4) 学生流逐字不变：/start 与 /help 永远走 bind ----
for text in ('/start', '/start@Scrts_bot', '/help', '/help@Scrts_bot', '你好', '在吗？', ''):
    check('私聊 %r → bind' % text, dec(msg('private', text=text)) == R.ROUTE_BIND)

# ---- 5) 教职工白名单指令 → assist（含 @botname 后缀与大小写）----
for text in ('/assist', '/name 张三', '/name@Scrts_bot 张三', '/NAME 李四',
             '/whoami', '/dm 张三 明天记得交表', '/notify 学习群 各位同事请注意',
             '/tpl'):
    check('私聊 %r → assist' % text, dec(msg('private', text=text)) == R.ROUTE_ASSIST)

# ---- 6) 已登记教职工：任何私聊内容都归班务 ----
check('教职工自由文本 → assist', dec(msg('private', text='明天开会'), staff={1001}) == R.ROUTE_ASSIST)
check('教职工 /start → assist', dec(msg('private', text='/start'), staff={1001}) == R.ROUTE_ASSIST)
check('教职工（chat_id 是字符串）→ assist',
      dec(msg('private', chat_id='1001', text='x'), staff={'1001'}) == R.ROUTE_ASSIST)
check('教职工名单为空 → 自由文本仍走 bind',
      dec(msg('private', chat_id=2002, text='明天开会'), staff={1001}) == R.ROUTE_BIND)

# ---- 7) assist 未装载：私聊一律 bind（学生流不受影响），指令也一样 ----
for text in ('/assist', '/dm 张三 交表', '/name 张三'):
    check('assist 不在：私聊 %r → bind' % text,
          dec(msg('private', text=text), ready=False) == R.ROUTE_BIND)

# ---- 8) 判据自身的守卫：白名单里绝不能出现学生最可能发的两条 ----
check('/start 不在 ASSIST_COMMANDS', '/start' not in R.ASSIST_COMMANDS)
check('/help 不在 ASSIST_COMMANDS', '/help' not in R.ASSIST_COMMANDS)
check('STAFF_ROLES 不含 student', 'student' not in R.STAFF_ROLES)

# ---- 9) command_of 的边界 ----
check('command_of 去 @botname 并小写', R.command_of('/Name@Scrts_Bot 张三') == '/name')
check('command_of 空串不炸', R.command_of('') == '' and R.command_of(None) == '')

# ---- 10) 深链载荷（2026-10-12 乙）：/start <BIND-…> 归班务，其余 /start 逐字不变 ----
def dec_p(update, pattern=R.DEFAULT_BIND_PAYLOAD_RE, ready=True, staff=()):
    return R.decide(update, assist_ready=ready, staff_chat_ids=set(staff),
                    bind_payload_re=pattern)


check('start_payload 取第二段', R.start_payload('/start BIND-ABC123') == 'BIND-ABC123')
check('start_payload 去 @botname 后缀',
      R.start_payload('/start@Scrts_bot BIND-ABC123') == 'BIND-ABC123')
check('start_payload 无载荷 → 空',
      R.start_payload('/start') == '' and R.start_payload('') == '' and R.start_payload(None) == '')
check('payload_matches 大写码', R.payload_matches('BIND-ABC123'))
check('payload_matches 小写码（手抄）', R.payload_matches('bind-abc123'))
check('payload_matches 位数不对 → False',
      not R.payload_matches('BIND-ABC12') and not R.payload_matches('BIND-ABC1234'))
check('payload_matches 空 → False', not R.payload_matches('') and not R.payload_matches(None))
check('payload_matches 坏正则 → False（宁可当学生流）',
      not R.payload_matches('BIND-ABC123', pattern='([unclosed'))
check('深链 /start BIND-… → assist', dec_p(msg('private', text='/start BIND-ABC123')) == R.ROUTE_ASSIST)
check('深链小写码 → assist', dec_p(msg('private', text='/start bind-abc123')) == R.ROUTE_ASSIST)
check('带 @botname 的深链 → assist',
      dec_p(msg('private', text='/start@Scrts_bot BIND-ABC123')) == R.ROUTE_ASSIST)
check('学生 /start（无载荷）→ bind', dec_p(msg('private', text='/start')) == R.ROUTE_BIND)
check('学生 /start 带非码载荷 → bind（不猜）',
      dec_p(msg('private', text='/start ref_12345')) == R.ROUTE_BIND)
check('学生 /start 带假格式 STU-… → bind',
      dec_p(msg('private', text='/start STU-ABC123')) == R.ROUTE_BIND)
check('assist 不在：深链 /start BIND-… → bind（回落学生流，不 500）',
      dec_p(msg('private', text='/start BIND-ABC123'), ready=False) == R.ROUTE_BIND)
check('库里给的正则生效（自定义格式）',
      dec_p(msg('private', text='/start XX-9'), pattern=r'^XX-[0-9]$') == R.ROUTE_ASSIST)
check('教职工的 /start 载荷：白名单先命中 → assist（与载荷无关）',
      dec_p(msg('private', text='/start whatever'), staff={1001}) == R.ROUTE_ASSIST)

# ---- 11) 绑定码指令本身归班务（否则老师会被回一张学生邀请码）----
for text in ('/bind BIND-ABC123', '/bindcode 教师 张三', '/bind', '/bindcode'):
    check('私聊 %r → assist' % text, dec(msg('private', text=text)) == R.ROUTE_ASSIST)
check('/bind 在 ASSIST_COMMANDS', '/bind' in R.ASSIST_COMMANDS)
check('/bindcode 在 ASSIST_COMMANDS', '/bindcode' in R.ASSIST_COMMANDS)

# ---- 12) 按钮化界面（2026-10-13）：按钮文字与「在等正文」的人都归班务 ----
BUTTONS = ('📢 发通知到群', '✉️ 私发给某人', '📄 文案模板',
           '👤 我的身份', '📚 使用说明', '🔕 停止私发')


def dec_m(update, ready=True, staff=(), menu=(), buttons=BUTTONS):
    return R.decide(update, assist_ready=ready, staff_chat_ids=set(staff),
                    menu_chat_ids=set(menu), button_texts=buttons)


for text in BUTTONS:
    check('点按钮 %r → assist' % text, dec_m(msg('private', text=text)) == R.ROUTE_ASSIST)
check('等正文的人（还没标角色）的自由文本 → assist',
      dec_m(msg('private', chat_id=3003, text='明天下午三点开会'),
            menu={3003}) == R.ROUTE_ASSIST)
check('等正文的人 chat_id 是字符串也认',
      dec_m(msg('private', chat_id='3003', text='x'), menu={'3003'}) == R.ROUTE_ASSIST)
check('没在等正文的人：自由文本仍走 bind（学生流不变）',
      dec_m(msg('private', chat_id=3004, text='明天下午三点开会')) == R.ROUTE_BIND)
check('按钮文案必须逐字相同（打错一个字仍是学生流）',
      dec_m(msg('private', text='📢发通知到群')) == R.ROUTE_BIND)
check('学生 /start 仍 bind（新判据不影响它）',
      dec_m(msg('private', text='/start')) == R.ROUTE_BIND)
check('/menu → assist', dec_m(msg('private', text='/menu')) == R.ROUTE_ASSIST)
check('/menu@Scrts_bot → assist',
      dec_m(msg('private', text='/menu@Scrts_bot')) == R.ROUTE_ASSIST)
check('/menu 在 ASSIST_COMMANDS', '/menu' in R.ASSIST_COMMANDS)
check('assist 不在：按钮文字 → bind（回落学生流，不 500）',
      dec_m(msg('private', text='📚 使用说明'), ready=False) == R.ROUTE_BIND)
check('老调用方不传 button_texts ⇒ 按钮文字仍是学生流（默认口径不变）',
      dec(msg('private', text='📚 使用说明')) == R.ROUTE_BIND)

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    if not ok:
        print('FAIL  %s  %s' % (name, detail))
print('tg_gate_router_test: %s/%s 通过' % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
