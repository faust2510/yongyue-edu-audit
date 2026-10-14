# -*- coding: utf-8 -*-
"""按钮化界面（UI 层）的纯函数：键盘形状 / 按钮文案 / 回调数据编解码。

为什么单独立一个**纯模块**（与 tgtext.py / polls.py / mattext.py 同款口径）：
  · 键盘形状与 callback_data 编解码最容易写错、又最容易单测；
  · Telegram 对 callback_data 有 **64 字节硬限**，超了不是「按钮失灵」而是**整条消息被拒收**；
  · 不 import odoo ⇒ tests/unit/tg_assist_menu_test.py 能直接加载断言，不必起数据库。

界面口径（用户 2026-10-13 反馈：「让不擅长技术的人用斜杠命令有学习成本，
就不能搞得跟软件一样方便而且一目了然吗」）：
  · **底部常驻键盘**（ReplyKeyboardMarkup + is_persistent）：点一下 = 发出它那行文字，
    机器人把这段文字当按钮认（BUTTON_ACTIONS）⇒ 用户一个斜杠都不用记；
  · **需要做选择的步骤**（发给哪个群 / 发给谁 / 用哪条模板）一律用 inline 按钮，
    不让老师手打中文短名或姓名（打错就是「没找到」，还得再来一遍）；
  · 一条消息只能挂一种键盘：带 inline 的那条不挂底部键盘 —— 但底部键盘是 persistent 的，
    客户端会一直留着（Telegram 官方口径），所以不会「点进子菜单就找不到回家的路」。
"""

#: 回调前缀：mn = menu。与 reply 的 ck: / poll 的 p: 互不干扰（三个 parse 各自认前缀）。
CALLBACK_PREFIX = 'mn'
#: Telegram 硬限：callback_data 的 UTF-8 字节数。
CALLBACK_MAX_BYTES = 64

# ---- 行为键：**只有 ASCII**，因为它们要进 callback_data（中文会撑爆 64 字节）----
ACT_HOME = 'home'        # 回主菜单
ACT_NOTIFY = 'notify'    # 群播：列出群
ACT_GROUP = 'grp'        # grp:<群记录id>  选定了某个群
ACT_DM = 'dm'            # 私发：列出人
ACT_TARGET = 'dmp'       # dmp:<人员记录id> 选定了某个人
ACT_SEND = 'send'        # 确认发送（正文已经在 ui_draft 里）
ACT_CANCEL = 'no'        # 取消
ACT_TPL = 'tpl'          # 模板：列出模板
ACT_TPL_OPEN = 'tpo'     # tpo:<模板id>  看某条模板的成品
ACT_TPL_GROUP = 'tpg'    # tpg:<模板id>  选择要发到哪个群
ACT_TPL_SEND = 'tps'     # tps:<模板id>:<群记录id>
ACT_WHOAMI = 'whoami'
ACT_HELP = 'help'
ACT_STOP = 'stop'

#: 按钮文案 -> 行为键。**底部键盘上每个按钮都必须在这里**（单测逐字核对；缺一个就是死按钮）。
BUTTON_ACTIONS = {
    '📢 发通知到群': ACT_NOTIFY,
    '✉️ 私发给某人': ACT_DM,
    '📄 文案模板': ACT_TPL,
    '👤 我的身份': ACT_WHOAMI,
    '📚 使用说明': ACT_HELP,
    '🔕 停止私发': ACT_STOP,
}

#: 布局：一行两个 —— 手机上一屏看得全，不用滚动。
ADMIN_LAYOUT = (
    ('📢 发通知到群', '✉️ 私发给某人'),
    ('📄 文案模板', '👤 我的身份'),
    ('📚 使用说明', '🔕 停止私发'),
)
STAFF_LAYOUT = (
    ('📄 文案模板', '👤 我的身份'),
    ('📚 使用说明', '🔕 停止私发'),
)
#: 只有管理员该看到的动作（教师/宿舍长的键盘上不出现，点了也会被拒 + 留痕）。
ADMIN_ONLY = (ACT_NOTIFY, ACT_DM)

PLACEHOLDER = '点下面的按钮就行'
BACK_LABEL = '🏠 主菜单'
CONFIRM_LABEL = '✅ 确认发送'
CANCEL_LABEL = '✖️ 取消'

#: Mini App 面板（设计文档 §9.17）：底部键盘最后的「打开面板」。
#: Telegram 只在**私聊**里接受 web_app 键盘按钮；本模块的键盘只发给私聊（群消息走 /notify），
#: 所以不需要在群里做降级。
APP_PATH = '/edu_tg_assist/app'
DEFAULT_SITE_URL = 'https://edu.example.org'
WEBAPP_LABEL = '🖥 打开面板'


def layout_for(role):
    """按角色给键盘布局。**默认给教师版**（宁少给一个按钮，也不给学生/陌生人管理员按钮）。"""
    return ADMIN_LAYOUT if role == 'admin' else STAFF_LAYOUT


def button_action(text):
    """按钮文案 -> 行为键；用户手打的普通文字 -> None。"""
    return BUTTON_ACTIONS.get((text or '').strip())


def is_app_tap(text):
    """用户点了底部键盘那颗「打开面板」（纯文字按钮会把文案当消息发回来）。

    2026-10-14 改：那颗按钮原是 web_app 键盘按钮，电脑版会当普通链接打开（拿不到身份数据、
    只显示 no initData）；改成纯文字按钮后各端都发得出来，点了由机器人回一条带**内联**
    web_app 按钮的消息（内联是官方列的启动方式）。
    """
    return (text or '').strip() == WEBAPP_LABEL


def app_url(site_url=None):
    """Mini App 面板地址（末尾不留斜杠）。site_url 由调用方从 edu_tg_assist.site_url 参数取。"""
    return (site_url or DEFAULT_SITE_URL).rstrip('/') + APP_PATH


def reply_keyboard(role='teacher', site_url=None):
    """底部常驻键盘（ReplyKeyboardMarkup 形状）。

    最后一行单列一颗「打开面板」，是**纯文字按钮**（2026-10-14 改）。

    为什么不用 web_app 键盘按钮：那天用户实测，电脑版点它等于点了个普通链接，页面拿不到身份
    数据、只显示「no initData」（同一个按钮在手机版正常）。纯文字按钮是 Telegram 最基本的元素，
    任何客户端都发得出来；点了以后机器人回一条带**内联** web_app 按钮的消息 —— 代价只是多点一次，
    换来「每台设备都能进」。

    site_url 留在签名里只是为了不动 14 处调用点（这颗按钮现在不再需要网址）。
    """
    rows = [[{'text': label} for label in row] for row in layout_for(role)]
    rows.append([{'text': WEBAPP_LABEL}])
    return {
        'keyboard': rows,
        'resize_keyboard': True,
        'is_persistent': True,
        'input_field_placeholder': PLACEHOLDER,
    }


def app_inline(site_url=None):
    """内联版「打开面板」按钮（InlineKeyboardMarkup）。

    2026-10-14 用户实测：电脑版 Telegram 点底部键盘里那个 web_app 按钮，打开的是
    「没有身份数据的页面」（tg=yes 但 initData=0，location.hash 里只有 tgWebAppPlatform
    之类的启动参数）⇒ 页面只能显示「这个面板要在 Telegram 里打开」。
    内联 web_app 按钮是官方文档列出的启动方式之一，各端都认，所以两条入口都给
    （两条指向同一个地址、同一套验签，不多一个口子）。
    """
    return {'inline_keyboard': [[
        {'text': WEBAPP_LABEL, 'web_app': {'url': app_url(site_url)}},
    ]]}


def truncate(text, limit=28):
    """按钮/标题截断（按钮太宽在手机上会被压成多行）。"""
    text = (text or '').strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1] + '…'


def cb(*parts):
    """拼 callback_data；**超 64 字节返回 None**（宁可不出这个按钮，也不能让整条消息被拒收）。"""
    data = ':'.join([CALLBACK_PREFIX] + [str(p) for p in parts])
    if len(data.encode('utf-8')) > CALLBACK_MAX_BYTES:
        return None
    return data


def parse_callback(data):
    """'mn:grp:12' -> ('grp', '12')；不是本模块的 -> None（让下一个模型去认领）。"""
    data = (data or '').strip()
    parts = data.split(':')
    if len(parts) < 2 or parts[0] != CALLBACK_PREFIX:
        return None
    if not all(parts[1:]):
        return None
    return tuple(parts[1:])


def inline(rows):
    """rows = [ [(按钮文案, 行为键 或 (行为键, 参数…)), ...], ... ] -> InlineKeyboardMarkup。

    带不出合法 callback_data 的按钮**单独丢掉**（不整条失败）：一个按钮太长，
    不该把整屏按钮都毁了。
    """
    out = []
    for row in rows:
        built = []
        for label, act in row:
            parts = tuple(act) if isinstance(act, (tuple, list)) else (act,)
            data = cb(*parts)
            if data:
                built.append({'text': truncate(label), 'callback_data': data})
        if built:
            out.append(built)
    return {'inline_keyboard': out} if out else None


def back_row(label=BACK_LABEL):
    """每个子页面底部都有的「回主菜单」按钮（inline 页面没有底部键盘时的回家路）。"""
    return [(label, (ACT_HOME,))]


def confirm_rows():
    """确认 / 取消两连（发送前的最后一道闸）。"""
    return [[(CONFIRM_LABEL, ACT_SEND), (CANCEL_LABEL, ACT_CANCEL)], back_row()]
