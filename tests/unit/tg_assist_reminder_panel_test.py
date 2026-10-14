# -*- coding: utf-8 -*-
"""面板「定时群发」（edu_tg_assist，2026-10-14）的回归用例（**不需要数据库、不需要 Odoo**）。

为什么要有它：
  · 这是「周一学习日 / 周末大扫除」这条旗舰能力第一次有用户点得到的入口：
    后台表单一直在，但模板与规则都得先在 Odoo 里手搓；面板把「选群 → 写正文 → 选星期几点」
    收成三步，后端只有一条 quick_create（正文 → 模板 + 规则，规则自带 ir.cron）。
  · 整族动作（reminders / reminder_create / reminder_toggle / reminder_run / reminder_delete）
    必须是**管理动作**：漏一条越权判断 = 任何教师都能往任意群定时广播。
  · 调度一条都不新造：规则仍然落在 edu.tg.assist.reminder 上（本用例把这条不变量钉住）。

用法：python3 tests/unit/tg_assist_reminder_panel_test.py   （退出码 0=全通过 / 1=有失败）
"""
import ast
import os
import re
import sys
from xml.dom import minidom

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist')
REMINDER_PY = os.path.join(PKG, 'models', 'reminder.py')
CTRL_PY = os.path.join(PKG, 'controllers', 'miniapp.py')
TPL_XML = os.path.join(PKG, 'views', 'miniapp_templates.xml')
MANIFEST = os.path.join(PKG, '__manifest__.py')

REM_ACTIONS = ('reminders', 'reminder_create', 'reminder_toggle', 'reminder_run', 'reminder_delete')

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def strip(src):
    """去掉三引号块与行内注释，剩下的才算「真的读了谁的库」。"""
    src = re.sub(r'"""[\s\S]*?"""', '', src)
    src = re.sub(r"'''[\s\S]*?'''", '', src)
    return '\n'.join(line.split('#')[0] for line in src.splitlines())


rem = read(REMINDER_PY)
ctl = read(CTRL_PY)
xml = read(TPL_XML)
rem_code = strip(rem)

# ---------------------------------------------------------------- 后端
check('reminder.quick_create 签名固定',
      'def quick_create(self, chat, body, weekday, hour, minute):' in rem)
check('quick_create 是 @api.model（可被面板/按钮直接调）',
      re.search(r'@api\.model\s+def quick_create', rem) is not None)
check('模板名撞名会让开（_unique_template_name）',
      'def _unique_template_name(self, base):' in rem
      and '_unique_template_name(' in rem.split('def quick_create')[1])
check('模板名唯一约束意识：撞名加序号而不是覆盖',
      'for i in range(2, 50)' in rem and 'if cand not in names' in rem)
check('空正文被拒', '正文是空的' in rem)
check('正文超长被拒（MAX_TEXT）', 'len(body) > MAX_TEXT' in rem)
check('星期取值按 selection 校验', "dict(self._fields['weekday'].selection)" in rem)
check('时间范围 0-23 / 0-59 校验', '0 <= hour <= 23' in rem and '0 <= minute <= 59' in rem)
check('群没登记好（无 chat_id / 停用）被拒',
      "not (chat.chat_id or '').strip()" in rem and 'not chat.active' in rem)
check('同一段正文复用已有模板（不刷屏建模板）',
      "Template.search([('body', '=', body)], limit=1)" in rem)
check('新模板 scene=remind 且备注写明来自面板',
      "'scene': 'remind'" in rem and '面板「定时群发」自动创建' in rem)
check('规则仍落在 edu.tg.assist.reminder（不新造调度）',
      'return self.create({' in rem and "'target_chat_id': chat.id" in rem
      and "'template_id': tpl.id" in rem)
check('规则字段逐字：weekday/send_hour/send_minute/tz',
      "'weekday': weekday" in rem and "'send_hour': hour" in rem
      and "'send_minute': minute" in rem and "'tz': 'Asia/Shanghai'" in rem)
check('规则建好即启用（active=True）', "'active': True," in rem)
check('引入 UserError 与 MAX_TEXT',
      'from odoo.exceptions import UserError' in rem
      and 'from .template import MAX_TEXT, WEEKDAYS_CN' in rem)
errs = rem.split('def quick_create')[0].count('raise UserError') + rem.split('def quick_create')[1].count('raise UserError')
check('每个拒绝分支都有中文原因（UserError 至少 6 处）', errs >= 6, str(errs))

tail = rem.split('def quick_create')[1]
check('定时群发代码段不碰 edu.feedback / edu_telegram / edu.tg.claim / edu.invite',
      not any(t in tail for t in ('edu.feedback', 'edu_telegram', 'edu.tg.claim', 'edu.invite')))
check('定时群发代码段没有新模型（只用既有提醒与模板）', '_name =' not in tail)

# ---------------------------------------------------------------- 控制器
admin_raw = re.search(r'ADMIN_ACTIONS = \(([^)]*)\)', ctl, re.S).group(1)
actions_raw = re.search(r'\nACTIONS = \(([^)]*)\)', ctl, re.S).group(1)
for name in REM_ACTIONS:
    check('控制器白名单有 %s' % name, ("'%s'" % name) in actions_raw)
    check('%s 是管理动作（越权 403 + 留痕）' % name, ("'%s'" % name) in admin_raw)
check('提醒列表含已停用规则（active_test=False，否则停用的规则会从面板消失）',
      'with_context(active_test=False).search(' in ctl)
check('列表字段够用：when/active/last_result/last_sent_at',
      all(k in ctl for k in ("'when': rec.schedule_label", "'active': bool(rec.active)",
                             "'last_result': rec.last_result", "'last_sent_at': rec.last_sent_at")))
check('立即发一次复用 _do_send（与后台那个按钮同一条路径）',
      "rule.sudo()._do_send(kind='manual')" in ctl)
check('发失败要把原因说出来（UserError 带原文）',
      "raise UserError('没发出去：%s'" in ctl)
check('删规则调 unlink（连带删规则自带的 ir.cron）', 'rule.sudo().unlink()' in ctl)
check('_int 把非数字变成人话', 'def _int(self, raw, label):' in ctl and '没填对。' in ctl)
check('新建返回里带 when/group/next 供面板回显',
      all(k in ctl for k in ("'when': rule.schedule_label", "'next': rule.cron_id")))
check('模块仍只依赖 base（面板不拖任何新模块）',
      ast.literal_eval(read(MANIFEST))['depends'] == ['base'])

# ---------------------------------------------------------------- 页面
minidom.parseString(xml)
check('面板页面是合法 XML', True)
check('主菜单有「⏰ 定时群发」（非行政灰显）',
      "bigBtn('⏰ 定时群发', me.is_admin ? null : '只有行政能设定时群发', openReminders)" in xml)
check('选群时 remind 分流到新建表单',
      "purpose === 'remind'" in xml and 'newReminderForm(row)' in xml)
for fn in ('openReminders', 'reminderRow', 'openReminder', 'newReminderForm', 'pickOpts'):
    check('面板有函数 %s' % fn, ('function %s' % fn) in xml)
for act in REM_ACTIONS:
    check('面板真的会调 %s' % act, ("call('%s'" % act) in xml)
check('删除有二次确认（window.confirm）', 'window.confirm(' in xml)
check('默认周一 8:00（weekday=0 / hour=8 / minute=0）',
      "pickOpts(WEEKDAY_OPTS, '0')" in xml and "pickOpts(HOUR_OPTS, '8')" in xml
      and "pickOpts(MINUTE_OPTS, '0')" in xml)
check('星期选项含「每天」', "['daily', '每天']" in xml)
check('建好之后引导先「立即发一次」看效果', '立即发一次' in xml)
check('停用/启用都有回话（按钮不许没反应）', '不会再自动发' in xml and '已启用' in xml)
check('空规则列表给出去哪新建的指引', '新建定时群发' in xml)
check('面板没有新增任何路由（沿用既有 /edu_tg_assist/app）',
      'http.route' not in xml and 'APP_PATH' not in xml)

js_actions = set(re.findall(r"call\('([a-z_]+)'", xml))
known = set(re.findall(r"'([a-z_]+)'", actions_raw))
missing = sorted(js_actions - known)
check('面板调用的动作名全部在控制器 ACTIONS 白名单里', not missing, ','.join(missing))

failed = [name for name, ok, _ in results if not ok]
for name, ok, detail in results:
    print(('PASS  ' if ok else 'FAIL  ') + name + (('  [' + detail + ']') if (detail and not ok) else ''))
print('')
print('定时群发面板用例：%d 条，通过 %d，失败 %d' % (len(results), len(results) - len(failed), len(failed)))
sys.exit(1 if failed else 0)
