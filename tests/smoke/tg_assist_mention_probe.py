# -*- coding: utf-8 -*-
"""W3 探针：F4 按钮回填 + F5 @提醒（edu_tg_assist）。

怎么跑（与 scripts/check_all.sh 里 E2E 段同一形状）：
    docker cp tests/smoke/tg_assist_mention_probe.py edu19-clone-web-1:/tmp/w3probe.py
    docker exec -i edu19-clone-web-1 sh -c \
      "odoo shell -d edu19 --db_host=db --db_user=odoo --db_password=odoo --no-http --log-level=error < /tmp/w3probe.py"

成败信号：**退出码**。有任何一条 FAIL ⇒ sys.exit(1)（门禁靠这个变红）。
⚠ 只打印 PASS/FAIL 而不改退出码的脚本，在 check_all 里是**永久绿**的假门禁——
  本文件因此显式 sys.exit。仓里 scripts/test_timetable_conflict.py 就是反例（它只打印）。

隔离与自清：
  · 全部数据用**合成 id**（-9900001/-9900002 群、9900001 校长…），断言只按这些 id 统计，
    ⇒ 库里已经有真实 @提醒数据也不会把探针搞红（不依赖「全表计数为 0」）。
  · dry_run=1 ⇒ send_message 绝不出网。
  · 末尾 env.cr.rollback() ⇒ 不留一行测试数据、也不改任何系统参数。
"""
from datetime import timedelta

from odoo import fields

CHAT_A = '-9900001'
CHAT_B = '-9900002'
OWNER = '9900001'
OTHER = '9900002'
UNREG = '9900003'

Mention = env['edu.tg.assist.mention'].sudo()
Reply = env['edu.tg.assist.reply'].sudo()
Person = env['edu.tg.assist.person'].sudo()
ICP = env['ir.config_parameter'].sudo()

R = []


def check(name, cond, detail=''):
    R.append((name, bool(cond)))
    print('%s | %s | %s' % ('PASS' if cond else 'FAIL', name, detail))


def in_a(domain=None):
    return Mention.search_count([('chat_id', '=', CHAT_A)] + list(domain or []))


def in_b(domain=None):
    return Mention.search_count([('chat_id', '=', CHAT_B)] + list(domain or []))


def msg_to_owner(mid, text='@校长 请确认'):
    return {'message_id': mid, 'from': {'id': 555, 'first_name': '宿舍长'}, 'text': text,
            'entities': [{'type': 'text_mention', 'offset': 0, 'length': 3,
                          'user': {'id': int(OWNER)}}]}


# ---- 清掉本探针可能残留的合成数据（正常跑完会回滚，这里只防前人异常中断）----
for chat in (CHAT_A, CHAT_B):
    Mention.search([('chat_id', '=', chat)]).unlink()
for uid in (OWNER, OTHER, UNREG):
    Person.search([('tg_user_id', '=', uid)]).unlink()
Reply.search([('tg_user_id', 'in', [OWNER, UNREG])]).unlink()

ICP.set_param('edu_tg_assist.dry_run', '1')
ICP.set_param('edu_tg_assist.owner_user_id', '')
ICP.set_param('edu_tg_assist.owner_username', '')
ICP.set_param('edu_tg_assist.mention_timeout_minutes', '15')

# ============ F5 ============
r = Mention._tg_assist_note_group_message(msg_to_owner(1), {'id': int(CHAT_A), 'title': '探针A'},
                                          False, '@校长 请确认')
check('F5-1 未配置 owner -> 不建待办（不猜）', r is None and in_a() == 0, 'ret=%r' % (r,))

ICP.set_param('edu_tg_assist.owner_user_id', OWNER)
r = Mention._tg_assist_note_group_message(msg_to_owner(2), {'id': int(CHAT_A), 'title': '探针A'},
                                          False, '@校长 请确认')
check('F5-2 text_mention 命中 -> 建 1 条', r and in_a() == 1, 'ret=%r' % (r,))

m = msg_to_owner(3)
m['entities'] = [{'type': 'text_mention', 'offset': 0, 'length': 3, 'user': {'id': int(OTHER)}}]
r = Mention._tg_assist_note_group_message(m, {'id': int(CHAT_A)}, False, m['text'])
check('F5-3 @ 的不是校长 -> 不建', r is None and in_a() == 1, 'ret=%r' % (r,))

m = {'message_id': 4, 'from': {'id': 555}, 'text': '@principal hi',
     'entities': [{'type': 'mention', 'offset': 0, 'length': 10}]}
r = Mention._tg_assist_note_group_message(m, {'id': int(CHAT_A)}, False, m['text'])
check('F5-4 mention 未配 username -> 不猜、不建', r is None and in_a() == 1, 'ret=%r' % (r,))

ICP.set_param('edu_tg_assist.owner_username', '@principal')
r = Mention._tg_assist_note_group_message(m, {'id': int(CHAT_A)}, False, m['text'])
check('F5-5 mention 配了 username -> 建', r and in_a() == 2, 'ret=%r' % (r,))

Mention._tg_assist_note_group_message(msg_to_owner(5), {'id': int(CHAT_B), 'title': '探针B'},
                                      False, '@校长 B群')
check('F5-6 两个群各建各的', in_a() == 2 and in_b() == 1, 'A=%d B=%d' % (in_a(), in_b()))

r = Mention._tg_assist_note_group_message({'message_id': 9, 'from': {'id': int(OWNER)}, 'text': '收到'},
                                          {'id': int(CHAT_A)}, False, '收到')
pa, pb = in_a([('replied_at', '=', False)]), in_b([('replied_at', '=', False)])
check('F5-7 校长回复只清本群（不跨群）', pa == 0 and pb == 1, 'A未回=%d B未回=%d' % (pa, pb))

old = Mention.search([('chat_id', '=', CHAT_B), ('replied_at', '=', False)], limit=1)
old.write({'mentioned_at': fields.Datetime.now() - timedelta(minutes=20)})
Person.create({'tg_user_id': OWNER, 'chat_id': '9900001', 'name': '探针校长', 'role': 'admin'})
n = Mention._cron_scan_timeouts()
old.invalidate_recordset()
check('F5-8 超时 20>15 分钟 -> 私聊提醒 1 条', n == 1 and bool(old.dm_sent_at),
      'sent=%s dm_sent_at=%s' % (n, old.dm_sent_at))
sl = env['edu.tg.assist.send_log'].sudo().search([('kind', '=', 'mention_dm')])
check('F5-8b 私聊走 send_log 且目标是校长私聊', bool(sl) and sl[0].chat_id == '9900001',
      'log=%d chat_id=%s' % (len(sl), sl[0].chat_id if sl else '-'))
n2 = Mention._cron_scan_timeouts()
check('F5-9 只发一次（第二次 0 条）', n2 == 0, 'second=%s' % n2)

Mention._tg_assist_note_group_message(msg_to_owner(6), {'id': int(CHAT_B)}, False, '@校长 刚发的')
check('F5-10 刚发的（未超时）不发', Mention._cron_scan_timeouts() == 0)

ICP.set_param('edu_tg_assist.mention_timeout_minutes', 'abc')
check('F5-11 参数非法 -> 回落 15', Mention._timeout_minutes() == 15, '%s' % Mention._timeout_minutes())
ICP.set_param('edu_tg_assist.mention_timeout_minutes', '30')
check('F5-11b 参数=30 生效', Mention._timeout_minutes() == 30, '%s' % Mention._timeout_minutes())
ICP.set_param('edu_tg_assist.mention_timeout_minutes', '15')

# ============ F4 ============
kb = Reply.build_keyboard(old)
data = kb['inline_keyboard'][0][0]['callback_data']
check('F4-1 keyboard 两按钮、data ASCII 且 <=64 字节',
      len(kb['inline_keyboard'][0]) == 2 and len(data.encode('utf-8')) <= 64 and data.isascii(),
      'data=%r bytes=%d' % (data, len(data.encode('utf-8'))))
check('F4-1b 能解析回来', Reply.parse_callback(data) == (old.id, 'done'),
      '%r' % (Reply.parse_callback(data),))

from odoo.addons.edu_tg_assist.models.api import EduTgAssistApi  # noqa: E402
CALLED = []
EduTgAssistApi.call = lambda self, method, payload: (CALLED.append((method, payload)), (True, {}))[1]

CALLED[:] = []
before = Reply.search_count([('tg_user_id', '=', UNREG)])
r = Reply._tg_assist_handle_callback({'id': 'cq-unreg', 'data': 'ck:%d:done' % old.id,
                                      'from': {'id': int(UNREG), 'first_name': '路人'},
                                      'message': {'chat': {'id': int(CHAT_B)}}})
check('F4-2 未登记 -> 不落库', Reply.search_count([('tg_user_id', '=', UNREG)]) == before, 'rows=%d' % before)
check('F4-2b 未登记 -> 仍调 answerCallbackQuery',
      bool(CALLED) and CALLED[0][0] == 'answerCallbackQuery' and '还没登记' in CALLED[0][1]['text'],
      str(CALLED[:1])[:110])

CALLED[:] = []
before = Reply.search_count([('tg_user_id', '=', OWNER)])
r = Reply._tg_assist_handle_callback({'id': 'cq-ok', 'data': 'ck:%d:done' % old.id,
                                      'from': {'id': int(OWNER), 'first_name': '校长'},
                                      'message': {'chat': {'id': int(CHAT_B)}}})
check('F4-3 已登记 -> 落 1 行 choice=done',
      Reply.search_count([('tg_user_id', '=', OWNER)]) == before + 1 and r.get('choice') == 'done',
      'ret=%r' % (r,))
check('F4-3b 已登记 -> 也 answer', bool(CALLED) and CALLED[0][0] == 'answerCallbackQuery',
      str(CALLED[:1])[:90])

r = Reply._tg_assist_handle_callback({'id': 'cq-again', 'data': 'ck:%d:abnormal' % old.id,
                                      'from': {'id': int(OWNER), 'first_name': '校长'},
                                      'message': {'chat': {'id': int(CHAT_B)}}})
row = Reply.search([('mention_id', '=', old.id), ('tg_user_id', '=', OWNER)], limit=1)
check('F4-4 重复点 -> 仍 1 行、选项改为 abnormal',
      Reply.search_count([('tg_user_id', '=', OWNER)]) == before + 1 and row.choice == 'abnormal',
      'rows=%d choice=%s' % (Reply.search_count([('tg_user_id', '=', OWNER)]), row.choice))

check('F4-5 非 ck: 前缀 -> 不认领',
      Reply._tg_assist_handle_callback({'id': 'x', 'data': 'other:1:2',
                                        'from': {'id': int(OWNER)}}) is None)

CALLED[:] = []
r = Reply._tg_assist_handle_callback({'id': 'cq-gone', 'data': 'ck:99999999:done',
                                      'from': {'id': int(OWNER)},
                                      'message': {'chat': {'id': int(CHAT_B)}}})
check('F4-6 记录不存在 -> 不落库、回话',
      r and r.get('callback') == 'missing_record' and bool(CALLED)
      and CALLED[0][0] == 'answerCallbackQuery', 'ret=%r' % (r,))

# ============ 汇总 ============
ok = sum(1 for _, c in R if c)
total = len(R)
env.cr.rollback()  # 不留测试数据、不改系统参数
print('')
print('RESULT=%s %d/%d' % ('PASS' if ok == total else 'FAIL', ok, total))
for n, c in R:
    if not c:
        print('   FAIL:', n)
if ok != total:
    import sys
    sys.exit(1)
