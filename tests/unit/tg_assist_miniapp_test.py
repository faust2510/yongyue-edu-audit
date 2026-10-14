# -*- coding: utf-8 -*-
"""edu_tg_assist Mini App（设计文档 §9.17）的回归用例（**不需要数据库、不需要 Odoo**）。

为什么要有它：
  · initData 验签是面板**唯一的门**：写错就是「谁都能调面板接口」或「合法用户永远进不来」。
    这里按 Telegram 官方算法**独立实现一遍**签名，用同一个 bot_token 现造真样本，
    证明「对的放行、动一个字节就拒」；
  · 面板动作分三层（admin / 教职工 / 其它）：材料归档不许外泄给非教职工，
    这层判断必须留在源码里可核对；
  · 面板页面与键盘按钮是用户在 Telegram 里唯一的入口，模板/接线缺一处 = 点开是白屏。

用法：python3 tests/unit/tg_assist_miniapp_test.py   （退出码 0=全通过 / 1=有失败）
"""
import hashlib
import hmac
import importlib.util
import json
import os
import re
import sys
import time
import xml.dom.minidom
from urllib.parse import parse_qsl, urlencode

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist')
AUTH_PY = os.path.join(PKG, 'miniapp_auth.py')
CTRL_PY = os.path.join(PKG, 'controllers', 'miniapp.py')
CTRL_INIT = os.path.join(PKG, 'controllers', '__init__.py')
TPL_XML = os.path.join(PKG, 'views', 'miniapp_templates.xml')
MENU_PY = os.path.join(PKG, 'menutext.py')
MANIFEST = os.path.join(PKG, '__manifest__.py')

spec = importlib.util.spec_from_file_location('tg_assist_miniapp_auth', AUTH_PY)
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

mspec = importlib.util.spec_from_file_location('tg_assist_menutext_for_app', MENU_PY)
MENU = importlib.util.module_from_spec(mspec)
mspec.loader.exec_module(MENU)

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def strip_comments(src):
    """去掉行内注释与三引号块，剩下的才算「真的读了谁的库」。"""
    src = re.sub(r'"""[\s\S]*?"""', '', src)
    src = re.sub(r"'''[\s\S]*?'''", '', src)
    return '\n'.join(line.split('#')[0] for line in src.splitlines())


TOKEN = '123456:TEST-TOKEN-not-a-real-one'
USER = {'id': 5592841801, 'first_name': '王佐', 'username': 'wangzuo'}


def sign(fields, token=TOKEN):
    """Telegram 官方算法：secret = HMAC_SHA256('WebAppData' 作 key、token 作消息)；
    hash = HMAC_SHA256(data_check_string 作消息、secret 作 key)。"""
    dcs = '\n'.join('%s=%s' % (k, fields[k]) for k in sorted(fields) if k != 'hash')
    secret = hmac.new(b'WebAppData', token.encode('utf-8'), hashlib.sha256).digest()
    return hmac.new(secret, dcs.encode('utf-8'), hashlib.sha256).hexdigest()


def raw_of(fields, token=TOKEN):
    """给任意字段集签名并拼成 initData 原文（可造「缺字段 / 坏字段」的样本）。"""
    fields = dict(fields)
    fields['hash'] = sign(fields, token)
    return urlencode(fields)


def init_data(token=TOKEN, auth_date=None, user=None, extra=None):
    fields = {
        'auth_date': str(int(time.time()) if auth_date is None else auth_date),
        'query_id': 'AAF-test-query',
        'user': json.dumps(USER if user is None else user, ensure_ascii=False,
                           separators=(',', ':')),
    }
    if extra:
        fields.update(extra)
    return raw_of(fields, token)


# ---- 1) data_check_string：去 hash、按 key 字母序、k=v 换行连接 ----
check('data_check_string 去掉 hash 并排序',
      A.data_check_string({'b': '2', 'a': '1', 'hash': 'x'}) == 'a=1\nb=2')
check('expected_hash 与官方算法一致（独立实现对拍）',
      A.expected_hash(init_data(), TOKEN) == sign(
          {'auth_date': A.parse_init_data(init_data())['auth_date'],
           'query_id': 'AAF-test-query',
           'user': json.dumps(USER, ensure_ascii=False, separators=(',', ':'))}))
check('parse_init_data 解出中文字段', A.parse_init_data(init_data())['user'] ==
      json.dumps(USER, ensure_ascii=False, separators=(',', ':')))
check('user_of 取出 id 与姓名',
      A.user_of(A.parse_init_data(init_data())) == USER)

# ---- 2) check：真样本放行 ----
ok, reason = A.check(init_data(), TOKEN)
check('真样本 → ok', ok and reason == 'ok', 'got %r/%r' % (ok, reason))
ok, reason = A.check(init_data(extra={'chat_type': 'private', 'chat_instance': '9'}), TOKEN)
check('多字段样本 → ok（官方示例里的 chat_type/chat_instance）',
      ok and reason == 'ok', 'got %r/%r' % (ok, reason))

# ---- 3) check：一处不对就拒（每种拒法都有独立原因码）----
# 拿一份真样本，只改 user、**hash 保持原样**（这才是「有人伪造身份」的样子）
tampered = dict(parse_qsl(init_data()))
tampered['user'] = json.dumps({'id': 1, 'first_name': '别人'}, ensure_ascii=False,
                              separators=(',', ':'))
ok, reason = A.check(urlencode(tampered), TOKEN)
check('改了 user（hash 不动）→ bad_hash', not ok and reason == 'bad_hash', 'got %r' % reason)
ok, reason = A.check(init_data(), TOKEN + 'x')
check('换一个 token → bad_hash', not ok and reason == 'bad_hash', 'got %r' % reason)
ok, reason = A.check(init_data(auth_date=int(time.time()) - 7200), TOKEN)
check('两小时前的 auth_date → stale', not ok and reason == 'stale', 'got %r' % reason)
ok, reason = A.check(init_data(auth_date=int(time.time()) + 3600), TOKEN)
check('未来一小时 → future', not ok and reason == 'future', 'got %r' % reason)
ok, reason = A.check('', TOKEN)
check('空 init_data → empty', not ok and reason == 'empty', 'got %r' % reason)
ok, reason = A.check('x' * 9000, TOKEN)
check('超长 init_data → too_long', not ok and reason == 'too_long', 'got %r' % reason)
ok, reason = A.check(init_data(), '')
check('没配 token → no_token', not ok and reason == 'no_token', 'got %r' % reason)
ok, reason = A.check(urlencode({'auth_date': str(int(time.time()))}), TOKEN)
check('没有 hash → no_hash', not ok and reason == 'no_hash', 'got %r' % reason)
ok, reason = A.check(raw_of({'auth_date': 'not-a-number', 'query_id': 'q'}), TOKEN)
check('auth_date 不是数字 → bad_date', not ok and reason == 'bad_date', 'got %r' % reason)
ok, reason = A.check(raw_of({'auth_date': str(int(time.time())), 'query_id': 'q'}), TOKEN)
check('没有 user 字段 → no_user', not ok and reason == 'no_user', 'got %r' % reason)
check('原因码都在 REASONS 闭集里', all(r in A.REASONS for r in
      ('ok', 'empty', 'too_long', 'no_token', 'no_hash', 'bad_hash', 'bad_date',
       'stale', 'future', 'no_user')))
check('默认有效期 1 小时（TTL 常量可查）', A.DEFAULT_TTL == 3600)

# ---- 4) 控制器：路由、验签、三层权限 ----
ctrl = read(CTRL_PY)
plain = strip_comments(ctrl)
check('页面路由 = /edu_tg_assist/app（常量式，见 surface 门禁的已知形态）',
      "APP_PATH = '/edu_tg_assist/app'" in ctrl)
check('接口路由 = /edu_tg_assist/app/api', "API_PATH = '/edu_tg_assist/app/api'" in ctrl)
check('两条路由都 auth=public / csrf=False / save_session=False',
      ctrl.count("auth='public', csrf=False") == 2 and ctrl.count('save_session=False') == 2)
check('GET 出页面、POST 进接口',
      ctrl.count("methods=['GET']") == 1 and ctrl.count("methods=['POST']") == 1)
check('接口第一件事是验签（miniapp_auth.check + 服务端 token）',
      'miniapp_auth.check(payload.get(' in ctrl and "_token()" in ctrl)
check('验签失败回 403 unauthorized（不泄露细节原因，只记日志）',
      "self._fail('unauthorized', BAD_IDENTITY, 403" in ctrl
      and '_logger.warning' in ctrl)
check('未登记的人 → 403 not_registered', "self._fail('not_registered', NOT_REGISTERED, 403" in ctrl)
check('未知 action → 400 bad_action', "self._fail('bad_action'" in ctrl)
# ADMIN_ACTIONS 是多行元组（2026-10-14 加了定时群发族）⇒ 按集合核对，不再逐字比一整行。
admin_block = re.search(r"ADMIN_ACTIONS = \(([^)]*)\)", ctrl, re.S)
admin_set = set(re.findall(r"'([^']+)'", admin_block.group(1))) if admin_block else set()
check('admin 动作集合 = notify/dm/staff/reminders 族',
      {'notify', 'dm', 'staff'} <= admin_set
      and {'reminders', 'reminder_create', 'reminder_toggle', 'reminder_run',
           'reminder_delete'} <= admin_set)
check('材料与转发限教职工（教师/宿舍长可用，其他人 403）',
      "STAFF_ACTIONS = ('materials', 'forward')" in ctrl
      and "if action in STAFF_ACTIONS and person.role not in STAFF_ROLES:" in ctrl)
check('越权动作留痕（写 dm 表的 denied 行）',
      '_audit_denied' in plain and "'面板:' + action" in ctrl)
check('动作异常兜底：UserError 与未知异常都不甩给用户',
      'except UserError' in ctrl and 'except Exception' in ctrl)
check('转发复用后台同一条路径（建 forward 记录再 action_send）',
      "env['edu.tg.assist.forward'].sudo().create(" in ctrl and '.action_send()' in ctrl)
check('私发同样写审计（kind 口径与 /dm 一致）',
      "'面板私发'" in ctrl and 'target_chat_id' in ctrl)
check('面板源码不碰意见箱/领码模块（注释之外零引用）',
      'edu_telegram' not in plain and 'edu.feedback' not in plain and 'edu.tg.claim' not in plain)
check('正文长度上限 3500（与 Telegram 的 4096 留余量）', 'MAX_TEXT = 3500' in ctrl)
check('controllers/__init__.py 装载了 miniapp', 'from . import miniapp' in read(CTRL_INIT))

# ---- 5) 模板：页面真能给 Telegram 打开 ----
tpl = read(TPL_XML)
check('模板 id 与控制器 render 的名字一致',
      '<template id="miniapp_page"' in tpl
      and "request.render('edu_tg_assist.miniapp_page'" in ctrl)
SDK_JS = os.path.join(PKG, 'static', 'vendor', 'telegram-web-app.js')
check('SDK 改为**自托管**（不再直连 telegram.org —— 那个域名在很多网络里打不开，'
      ' 直链失败会让面板只剩一句「no initData」）',
      '/edu_tg_assist/static/vendor/telegram-web-app.js' in tpl
      and 'https://telegram.org/js/telegram-web-app.js' not in tpl)
check('自托管 SDK 真的在仓里，且是官方那份（定义 initData / Webview bridge）',
      os.path.exists(SDK_JS) and 'initData' in read(SDK_JS) and 'TelegramWebviewProxy' in read(SDK_JS))
check('initData 三层兜底：SDK → URL hash(tgWebAppData) → 明确提示',
      'function hashInitData' in tpl and "'tgWebAppData'" in tpl
      and 'function currentInitData' in tpl and 'function showNoIdentity' in tpl)
check('等 SDK 最多 2 秒再决定（自托管脚本可能慢一拍）',
      'function waitSdk' in tpl and 'sdkWaited >= 2000' in tpl)
check('面板页自带诊断信息（tg/platform/version/initData 长度），出问题一眼能定位',
      "' platform=' " in tpl or 'platformInfo' in tpl)
check('接口路径用 data 属性传给 JS（QWeb 不解析 CDATA）',
      't-att-data-api="api_path"' in tpl and 'data-api' in tpl)
check('JS 用验签后的身份串调接口（currentInitData 的结果，不再是裸 tg.initData）',
      'currentInitData()' in tpl and 'init_data: data' in tpl)
check('没有 JS 模板字符串（QWeb 会先吃掉 $ 后的花括号）', ('$' + '{') not in tpl)
check('模板 XML 能被解析', bool(xml.dom.minidom.parseString(tpl.encode('utf-8'))))
check('manifest 装载模板且排在 security 之后',
      "'views/miniapp_templates.xml'" in read(MANIFEST)
      and read(MANIFEST).index('security/ir.model.access.csv')
      < read(MANIFEST).index('views/miniapp_templates.xml'))

# ---- 6) 入口：底部键盘上的「打开面板」 ----
check('menutext 有 web_app 按钮常量',
      MENU.WEBAPP_LABEL.startswith('🖥') and MENU.APP_PATH == '/edu_tg_assist/app')
check('面板路径与控制器逐字一致',
      MENU.APP_PATH == re.search(r"APP_PATH = '([^']+)'", ctrl).group(1))
check('app_url 跟随 site_url 且不留双斜杠',
      MENU.app_url('https://example.org/') == 'https://example.org/edu_tg_assist/app'
      and MENU.app_url() == 'https://edu.example.org/edu_tg_assist/app')
for role in ('admin', 'teacher', 'dorm_head', 'other'):
    kb = MENU.reply_keyboard(role)['keyboard']
    check('%s 的键盘最后一行是「打开面板」文字按钮' % role,
          kb[-1] == [{'text': MENU.WEBAPP_LABEL}])
check('bot 用配置的站点地址生成面板链接（不是硬编码）',
      'menutext.reply_keyboard(self._keyboard_role(person), self._site_url())'
      in read(os.path.join(PKG, 'models', 'bot.py')))

# ---- 7) 电脑版兜底：内联入口 + 可分辨的诊断（2026-10-14）----
check('menutext 提供内联「打开面板」按钮（各端都认的启动方式）',
      MENU.app_inline() == {'inline_keyboard': [[
          {'text': MENU.WEBAPP_LABEL, 'web_app': {'url': MENU.app_url()}}]]})
check('内联按钮跟随 site_url',
      MENU.app_inline('https://example.org/')['inline_keyboard'][0][0]['web_app']['url']
      == 'https://example.org/edu_tg_assist/app')
menu_src = read(os.path.join(PKG, 'models', 'menu.py'))
check('点键盘那颗「打开面板」→ 回内联按钮（不再靠 web_app 键盘按钮）',
      MENU.is_app_tap(MENU.WEBAPP_LABEL) and 'menutext.is_app_tap(text)' in menu_src)
check('私人聊天那颗 Telegram 自带菜单按钮按需设成面板',
      'setChatMenuButton' in menu_src and "'edu_tg_assist.menu_button'" in menu_src)
check('/menu 会补发内联面板按钮',
      'def _send_app_button(' in menu_src and 'menutext.app_inline(' in menu_src
      and 'self._send_app_button(chat)' in menu_src)
check('诊断里带 hash 的键名（区分「没给数据」和「我们没解析」）',
      'function hashKeys()' in tpl and "' hkeys=' + hashKeys()" in tpl)
check('诊断不打印 hash 的值（只列键名，签名不进截图）',
      "parts[i].slice(0, j)" in tpl and 'location.hash' in tpl)
check('打不开的提示同时给手机版与电脑版两条路',
      '/menu' in tpl and '电脑版' in tpl)

failed = [name for name, ok, _ in results if not ok]
for name, ok, detail in results:
    print(('PASS  ' if ok else 'FAIL  ') + name + (('  [' + detail + ']') if (detail and not ok) else ''))
print('')
print('Mini App 用例：%d 条，通过 %d，失败 %d' % (len(results), len(results) - len(failed), len(failed)))
sys.exit(1 if failed else 0)
