# -*- coding: utf-8 -*-
"""文案模板库（F6）—— 节日问候 / 生日祝福 / 会议通知。

为什么要有它：文案会随节日与人员变化。写死在代码里，改一句话都要改代码 → 跑升级 → 部署。
本模型把「文案」变成**后台可维护的数据**；F1 定时提醒 / F2 私发 / F3 广播都从它取内容。

★ 占位符纪律（三条，都属于本仓「不许静默失败」家族）
  1. 只认白名单键（见 PLACEHOLDERS）：不认识的键、以及「认识但没给值」的键**都原样保留**，
     并各自记一条日志 —— 管理员一眼看得见写错了，不会收到一条被悄悄掏空的消息；
  2. 替换**单趟完成**：re.sub 先在「原文」上把所有占位符找出来，再把值拼进去，
     替换值**不会被再次扫描** ⇒ 值里带 {date} 也只是普通文字。
     这是防注入的**结构性**保证 —— 不靠过滤字符，也不靠调用方小心；
     反例：先 replace('{name}') 再 replace('{date}') 的连环写法，在名字含 {date} 时会被二次替换；
  3. 渲染结果超过 Telegram 单条上限（4096）时**截断 + 记日志**（记模板名与实际长度），
     绝不静默丢弃正文。
"""
import logging
import re

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Telegram Bot API：sendMessage 的 text 上限 4096（口径是 UTF-16 码元，emoji 算 2，见 utf16_len）
MAX_TEXT = 4096
# 占位符白名单：键 -> 给管理员看的一句说明
PLACEHOLDERS = {
    'name': '人名（定时提醒取规则上指定的人；/tpl 里取发起人自己）',
    'date': '日期（YYYY-MM-DD）',
    'weekday': '星期（周一…周日）',
    'group': '群名（定时提醒取目标群的短名或名称）',
}
_RE_PLACEHOLDER = re.compile(r'\{(\w+)\}')
WEEKDAYS_CN = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')

# Telegram HTML 模式要求转义的三个字符。⚠ 传了 parse_mode=HTML 就**必须**由调用方转义
# （api.send_message 不代劳，见它的 docstring）；本模块把这道工序收在下面这对纯函数里。
_HTML_ESCAPE = (('&', '&amp;'), ('<', '&lt;'), ('>', '&gt;'))
# 提及链接要拼进 href ⇒ user_id 必须纯数字，否则可能把属性拼坏（注入面）。不合法就不给链接。
_RE_TG_ID = re.compile(r'^[0-9]+$')
# 先埋哨兵、整体转义、再把哨兵换回链接 —— 这样自己的标签不会被转义，正文里的 < & 又都安全
_MENTION_SENTINEL = '\x00tg-mention\x00'


def escape_html(text):
    """把正文转成 HTML 安全文本（& < > 三个）。parse_mode=HTML 的前置工序。"""
    for ch, rep in _HTML_ESCAPE:
        text = text.replace(ch, rep)
    return text


def mention_html(name, user_id):
    """生成 Telegram「真提及」链接；user_id 不是纯数字就返回 None（宁可不 @，也不拼坏标签）。"""
    uid = str(user_id or '').strip()
    if not _RE_TG_ID.match(uid):
        return None
    return '<a href="tg://user?id=%s">@%s</a>' % (uid, escape_html(name or ''))

def utf16_len(text):
    """按 UTF-16 码元数度量 —— Telegram 的上限是这个口径，按码点算会少算（emoji 算 2）。"""
    return len((text or '').encode('utf-16-le')) // 2


def render_placeholders(body, values, limit=MAX_TEXT):
    """纯函数：把 {key} 换成 values[key]。无 ORM 依赖，便于单测。

    :param body: 模板正文（可能含占位符）
    :param values: {键: 值}；值为 None 视为「没给值」
    :param limit: 输出长度上限（UTF-16 码元）；None/0 = 不截断
    :return: dict(text, truncated, unknown=[不在白名单的键], missing=[在白名单但没给值的键])
    """
    unknown, missing = set(), set()

    def _sub(m):
        key = m.group(1)
        if key not in PLACEHOLDERS:
            unknown.add(key)
            return m.group(0)          # 不认识的键：原样保留
        val = values.get(key)
        if val is None:
            missing.add(key)
            return m.group(0)          # 认识但没给值：同样原样保留（看得见）
        return str(val)

    # ★ 单趟替换：re.sub 的扫描位置只在**原文**上推进，替换串不参与后续匹配
    out = _RE_PLACEHOLDER.sub(_sub, body or '')

    truncated = False
    if limit and utf16_len(out) > limit:
        keep, total = [], 0
        for ch in out:
            n = utf16_len(ch)
            if total + n > limit - 1:   # 留 1 个码元给省略号
                break
            keep.append(ch)
            total += n
        out = ''.join(keep) + '…'
        truncated = True
    return {'text': out, 'truncated': truncated,
            'unknown': sorted(unknown), 'missing': sorted(missing)}

class EduTgAssistTemplate(models.Model):
    _name = 'edu.tg.assist.template'
    _description = 'Telegram 文案模板'
    _order = 'scene, name, id'

    name = fields.Char('模板名', required=True, index=True,
                       help='给 /tpl 与规则下拉用的短名，例如「学习日测试链接」。')
    scene = fields.Selection([
        ('festival', '节日问候'),
        ('birthday', '生日祝福'),
        ('meeting', '会议通知'),
        ('remind', '例行提醒'),
        ('other', '其他'),
    ], string='场景', default='other', required=True)
    body = fields.Text('正文', required=True,
                       help='支持占位符；不认识的占位符会原样发出并在日志里点名。')
    placeholder_help = fields.Char('正文里的占位符', compute='_compute_placeholder_help',
                                   help='自动扫出正文用到的占位符；⚠ 开头的是不认识的键。')
    active = fields.Boolean('启用', default=True)
    note = fields.Char('备注')

    _name_uniq = models.Constraint(
        'UNIQUE(name)', '模板名必须唯一（/tpl 与规则下拉都按名字找）。')

    @api.depends('body')
    def _compute_placeholder_help(self):
        for rec in self:
            keys = sorted(set(_RE_PLACEHOLDER.findall(rec.body or '')))
            known = ['{%s}' % k for k in keys if k in PLACEHOLDERS]
            bad = ['{%s}' % k for k in keys if k not in PLACEHOLDERS]
            parts = []
            if known:
                parts.append('识别：' + ' '.join(known))
            if bad:
                parts.append('⚠ 不识别（会原样发出）：' + ' '.join(bad))
            rec.placeholder_help = '；'.join(parts) or '（正文里没有占位符）'

    def render(self, values=None, mention=None):
        """渲染正文。

        :param mention: None 或 {'name': 人名, 'user_id': Telegram 数字 id}。
            给了、且正文里**真的出现** @人名 ⇒ 换成 Telegram 真提及链接并置 parse_mode='HTML'；
            没给、或正文里没有那个 @人名 ⇒ parse_mode=None，payload 与加这功能之前**逐字节相同**
            （不 @ 人的规则完全不受影响）。
        :return: render_placeholders 的 dict + parse_mode / mentioned 两个键。
        """
        self.ensure_one()
        res = render_placeholders(self.body, values or {})
        res['parse_mode'] = None
        res['mentioned'] = False
        if mention:
            link = mention_html(mention.get('name'), mention.get('user_id'))
            token = '@' + (mention.get('name') or '')
            if not link:
                _logger.warning('edu_tg_assist: 要 @ 的人 tg_user_id 不是纯数字（%r）⇒ 本次按纯文本发',
                                mention.get('user_id'))
            elif not token or token not in res['text']:
                _logger.warning('edu_tg_assist: 模板「%s」正文里没有「%s」⇒ @ 不到人（按纯文本发）',
                                self.name, token)
            else:
                # ★ 顺序：埋哨兵 → 整体转义 → 哨兵换回链接
                out = escape_html(res['text'].replace(token, _MENTION_SENTINEL))
                res['text'] = out.replace(_MENTION_SENTINEL, link)
                res['mentioned'] = True
                res['parse_mode'] = 'HTML'
        if res['truncated']:
            _logger.warning(
                'edu_tg_assist: 模板「%s」渲染后 %d 字符，超过上限 %d，已截断（正文 %d 字符）',
                self.name, utf16_len(res['text']), MAX_TEXT, utf16_len(self.body))
        if res['unknown']:
            _logger.warning('edu_tg_assist: 模板「%s」含不认识的占位符 %s（已原样保留）',
                            self.name, ', '.join('{%s}' % k for k in res['unknown']))
        if res['missing']:
            _logger.warning('edu_tg_assist: 模板「%s」的占位符 %s 没拿到值（已原样保留）',
                            self.name, ', '.join('{%s}' % k for k in res['missing']))
        return res

    @api.model
    def placeholder_doc(self):
        """一行说明，给 /tpl 与后台提示复用。"""
        return '、'.join('{%s} = %s' % (k, PLACEHOLDERS[k]) for k in sorted(PLACEHOLDERS))

    # ------------------------------------------------------------------
    # 私聊指令 /tpl
    # ------------------------------------------------------------------
    # 2026-10-08：队长已修好 bot.py 的分发（指令表改存 (注册者模型, 方法名)），
    # 功能模型注册的处理器现在能被正确取到 ⇒ /tpl 正式开放。
    @api.model
    def _tg_assist_commands(self):
        return {'/tpl': '_cmd_tpl'}

    @api.model
    def _cmd_tpl(self, person, rest, msg, chat):
        """私聊 /tpl —— 列出模板；/tpl 关键字 渲染一条给发起人看。**只读**，不发群。"""
        tpls = self.sudo().search([('active', '=', True)])
        if not tpls:
            return ('模板库里还没有启用的模板。', None)
        kw = (rest or '').strip()
        if not kw:
            lines = ['可用模板（%d 条）：' % len(tpls)]
            for t in tpls[:20]:
                lines.append('· %s（%s）' % (t.name, dict(t._fields['scene'].selection).get(t.scene)))
            if len(tpls) > 20:
                lines.append('……还有 %d 条，去后台「文案模板」看全。' % (len(tpls) - 20))
            lines += ['', '看某一条的成品：/tpl 模板名', '占位符：' + self.placeholder_doc()]
            return ('\n'.join(lines), None)
        tpl = tpls.filtered(lambda t: t.name == kw) or tpls.filtered(lambda t: kw in (t.name or ''))
        if not tpl:
            return ('没找到名字含「%s」的模板。发 /tpl 看全部。' % kw, None)
        tpl = tpl[0]
        today = fields.Date.context_today(tpl)
        res = tpl.render({
            'name': (person.name if person else None),
            'date': fields.Date.to_string(today),
            'weekday': WEEKDAYS_CN[today.weekday()],
            'group': None,
        })
        tail = []
        if res['truncated']:
            tail.append('⚠ 超过 Telegram 单条上限，已截断。')
        if res['missing']:
            tail.append('⚠ 这些占位符没值（原样显示）：' + ' '.join('{%s}' % k for k in res['missing']))
        if res['unknown']:
            tail.append('⚠ 这些占位符不认识（原样显示）：' + ' '.join('{%s}' % k for k in res['unknown']))
        text = '（渲染：%s）\n\n%s' % (tpl.name, res['text'])
        if tail:
            text += '\n\n' + '\n'.join(tail)
        return (text, None)