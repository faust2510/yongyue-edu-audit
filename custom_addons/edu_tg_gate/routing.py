# -*- coding: utf-8 -*-
"""前门路由判据 —— **纯 Python，不 import odoo**。

为什么单独一个文件：本文件是「这条 update 归谁」的**唯一实现**。
放在这里就能被 tests/unit/tg_gate_router_test.py 离线单测（不连库、不连网、起容器都不需要）。
模型 edu.tg.gate.router 只是把 odoo 侧的状态（assist 装没装、哪些 chat_id 是教职工）
喂给 decide()，自己不做判断。

默认方向（fail-safe）朝 **bind**：拿不准的私聊一律走学生领码流 ——
学生领不到码是「学校招不到人」，教职工多收一条码只是「看着奇怪」。

2026-10-08 用户裁定：复用 @sctrs_bot 承载行政班务机器人（原设计 §1 的
「给 edu_tg_bind 加群聊/广播会污染其安全边界」被这次裁定推翻，记录见设计文档 §9）。
"""
import re

ROUTE_ASSIST = 'assist'
ROUTE_BIND = 'bind'
ROUTE_IGNORE = 'ignore'

# 教职工角色（edu.tg.assist.person.role）——只有这些人（且 active）的私聊**任何内容**都归班务。
# 学生不在里面：学生就算被登记过（例如误发过 /name），仍然走领码流。
STAFF_ROLES = ('admin', 'teacher', 'dorm_head')

# 「第一句就该被班务接住」的指令白名单（比较前去掉 @botname 并转小写）。
# ⚠ 刻意**不包含** /start 与 /help：这两条是学生最可能发的，
#   留在领码流 ⇒ 学生体验逐字不变（设计 §9.4）。
# /name 必须在里面 —— 它是教职工登记的第一步；若走 bind，他会收到一张邀请码、根本登记不上。
ASSIST_COMMANDS = frozenset([
    '/assist', '/dm', '/name', '/notify', '/tpl', '/whoami',
    # /menu（2026-10-13）：按钮菜单入口。不加进来，没标角色的老师发 /menu 会掉进
    # 学生领码流、收到一张邀请码。
    '/menu',
    # 身份绑定码（2026-10-12）：/bind 是老师自己被邀请绑定的入口，必须归班务 ——
    # 若走 bind 他会收到一张学生邀请码、身份永远绑不上。
    # /bindcode 是管理员签发新码用的（非管理员会被回「你没有这个权限」并留痕）。
    '/bind', '/bindcode',
])

# 深链载荷兜底正则：**真正的唯一来源是 edu.tg.assist.bindcode.PAYLOAD_RE**，
# 前门在运行时通过 router._bind_payload_re() 取它；assist 没装时用这个兜底，
# 免得「模块没装」把 /start BIND-… 判成学生流（学生流本来就没有载荷）。
DEFAULT_BIND_PAYLOAD_RE = r'^BIND-[A-Z0-9]{6,6}$'

GROUP_TYPES = ('group', 'supergroup')


def command_of(text):
    """'/name@Scrts_bot 张三' → '/name'（Telegram 群里 @机器人 会带后缀）。"""
    head = (text or '').strip().partition(' ')[0]
    return head.split('@')[0].lower()


def start_payload(text):
    """'/start BIND-ABC123' → 'BIND-ABC123'；没有载荷 → ''。

    Telegram 的深链（https://t.me/sctrs_bot?start=XXX）**只能**把 XXX 变成
    「/start XXX」 —— 没有别的载体，所以前门必须在这里认出来（设计 §9.12.3）。
    """
    parts = (text or '').strip().split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ''


def payload_matches(payload, pattern=None):
    """载荷是否是我们签发的绑定码格式（大小写不敏感：手抄时容易打成小写）。

    pattern 坏掉时**返回 False**（宁可把这条 /start 当学生流，也不误判）。
    """
    if not payload:
        return False
    try:
        return bool(re.match(pattern or DEFAULT_BIND_PAYLOAD_RE, payload.strip().upper()))
    except re.error:
        return False


def decide(update, assist_ready=False, staff_chat_ids=(), bind_payload_re=None,
           menu_chat_ids=(), button_texts=()):
    """返回 ROUTE_ASSIST / ROUTE_BIND / ROUTE_IGNORE。

    :param assist_ready: edu.tg.assist.bot 是否已装载。
        未装载时：私聊全部 bind（学生流绝不受影响）；群消息与按钮**忽略**
        （bind 本来就不处理群；vs 500 或误发码，忽略是安全侧）。
    :param staff_chat_ids: role 在 STAFF_ROLES 且 active 的私聊 chat_id 集合（str）。
    :param bind_payload_re: 深链载荷正则（唯一来源 edu.tg.assist.bindcode.PAYLOAD_RE）。
    :param menu_chat_ids: 正在走按钮流程（person.ui_state 有值）的 chat_id 集合（str，
        2026-10-13 加）—— 他在等正文，下一条消息必须回班务，不能掉进领码流。
    :param button_texts: 底部键盘按钮的文案（唯一来源 edu_tg_assist.menutext.BUTTON_ACTIONS）。
        点按钮 = 发一段与按钮文案逐字相同的文字；不认出来，还没被标角色的老师
        点一下就会收到一张学生邀请码。两个新参数**默认空** ⇒ 老口径一字不变。
    """
    if not isinstance(update, dict):
        return ROUTE_IGNORE
    if update.get('callback_query'):
        # 只有 assist 用内联按钮回填（F4）；bind 的按钮是 url / copy_text，永不产生 callback_query。
        return ROUTE_ASSIST if assist_ready else ROUTE_IGNORE
    msg = update.get('message') or {}
    if not isinstance(msg, dict) or not msg:
        # edited_message / my_chat_member / channel_post …：setWebhook 的
        # allowed_updates 只开 ["message","callback_query"]，正常收不到；收到也不猜。
        return ROUTE_IGNORE
    chat = msg.get('chat') or {}
    if not isinstance(chat, dict):
        return ROUTE_IGNORE
    ctype = chat.get('type')
    if ctype in GROUP_TYPES:
        # 群消息原本被 bind 一律忽略（防一个群把码池刷空）；现在归班务（F5 @提醒要读群消息）。
        return ROUTE_ASSIST if assist_ready else ROUTE_IGNORE
    if ctype != 'private':
        return ROUTE_IGNORE
    if not assist_ready:
        return ROUTE_BIND
    # ⚠ 一律归一成 str：调用方可能给 int（Telegram 的 chat.id）也可能给 str
    #   （edu.tg.assist.person.chat_id 是 Char）。单独加「已是 set 就跳过归一」的快路径
    #   会在「set 里全是 int」时静默判错 —— 实测就是这么漏掉教职工的（单测第 6 组抓到）。
    if str(chat.get('id')) in {str(x) for x in (staff_chat_ids or ())}:
        return ROUTE_ASSIST
    # 按钮流程（2026-10-13）：他在等一条正文 —— 那条正文必须回班务，
    # 否则「点群名 → 发内容」这一步会被判成学生流、他收到一张邀请码。
    if str(chat.get('id')) in {str(x) for x in (menu_chat_ids or ())}:
        return ROUTE_ASSIST
    text = msg.get('text')
    cmd = command_of(text)
    if cmd == '/start':
        # 深链 /start <载荷>：只有载荷是我们签发的绑定码格式才归班务。
        # 学生的 /start（没有载荷）逐字不变地继续走领码流 —— 这是本条判据的**全部意义**。
        return ROUTE_ASSIST if payload_matches(start_payload(text), bind_payload_re) else ROUTE_BIND
    if cmd in ASSIST_COMMANDS:
        return ROUTE_ASSIST
    # 底部键盘按钮（2026-10-13）：点按钮来的文字与按钮文案逐字相同 —— 认出来归班务。
    # 放在 /start 与指令判据**之后**：按钮文案不以 / 开头，调换顺序也不影响学生流。
    # 代价写在设计文档 §9.13：学生若逐字抄了按钮文案，会看到一次班务菜单（不是领不到码）。
    if (text or '').strip() and (text or '').strip() in set(button_texts or ()):
        return ROUTE_ASSIST
    # fail-safe：其余一切（含 /start、/help、任意自由文本）→ 学生领码流。
    return ROUTE_BIND
