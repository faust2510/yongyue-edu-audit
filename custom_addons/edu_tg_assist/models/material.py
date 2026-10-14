# -*- coding: utf-8 -*-
"""F7 —— 材料智能归档（老师私聊转发的材料 → 自动抽取 → 可选导出 Notion）。

设计原文见 docs/plans/tg-assist-bot-design.md §9.11。三件事按顺序：
  1. **先落库**：老师转发的第一条消息先建 edu.tg.assist.material（state=new）再出网回执；
  2. **异步分析**：cron 每分钟（或后台按钮）跑规则抽取；配了大模型才再跑一次 LLM，
     出网前**先脱敏**（mattext.mask_sensitive）；
  3. **可选导出**：notion_enabled=1 且 token+库 id 配齐才发，失败只落库（B9/B11）。

边界（不许破）：
  · B11 材料原文只存本库；送 Notion 默认只有摘要与关键信息；
  · B12 归档只对「角色 ∈ admin/teacher/dorm_head」的私聊生效 —— 学生流一字不变；
  · 文件本体**按需取回**（2026-10-13 用户要求：老师转来的文件要能在后台下载、再转给教务）；
  · webhook 里先只记 file_name / mime / file_id / caption（不拖慢回执），本体交每分钟的 cron 或后台「⬇️ 取回文件」按钮取；
  · 取回后存进 file_data（ir.attachment），后台点开就能下载 / 转发；上限见 edu_tg_assist.material_max_mb（默认 10）—— Telegram 官方 getFile 只给 20 MB 以内的文件。
"""
import base64
import logging
import re
from datetime import datetime, timedelta

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.edu_tg_assist import mattext

_logger = logging.getLogger(__name__)


def _too_big(size, cap):
    """超上限的文案（MB 保留一位小数，方便老师判断要不要单独要文件）。"""
    return '文件 %s MB 超过上限 %s MB，未取回（可在 Telegram 里直接看）。' % (
        round(float(size or 0) / 1048576.0, 1), cap // 1048576)


STAFF_ROLES = ('admin', 'teacher', 'dorm_head')
KIND_MAX = 16
KEEP_DAYS_PARAM = 'edu_tg_assist.material_keep_days'
AUTO_ANALYZE_PARAM = 'edu_tg_assist.material_auto_analyze'
DEFAULT_KEEP_DAYS = 365
ANALYZE_BATCH = 20
DOWNLOAD_PARAM = 'edu_tg_assist.material_download'
MAX_MB_PARAM = 'edu_tg_assist.material_max_mb'
DEFAULT_MAX_MB = 10
FILE_URL_TMPL = 'https://api.telegram.org/file/bot%s/%s'

KIND_SELECTION = [
    ('text', '文字'),
    ('document', '文件'),
    ('photo', '图片'),
    ('voice', '语音'),
    ('other', '其他'),
]
CATEGORY_SELECTION = [
    ('notice', '通知'), ('material', '材料'), ('report', '汇报'),
    ('finance', '财务'), ('personnel', '人事'), ('schedule', '日程'),
    ('other', '其他'),
]
URGENCY_SELECTION = [
    ('low', '不急'), ('normal', '一般'), ('high', '紧急'), ('urgent', '特急'),
]
AI_STATE_SELECTION = [
    ('none', '未分析'), ('rule', '规则抽取'), ('llm', '大模型抽取'),
    ('llm_failed', '大模型失败（已降级规则）'),
]
NOTION_STATE_SELECTION = [
    ('off', '未启用'), ('pending', '待推送'), ('ok', '已推送'), ('failed', '推送失败'),
]
STATE_SELECTION = [('new', '待分析'), ('analyzed', '已分析')]


class EduTgAssistMaterial(models.Model):
    _name = 'edu.tg.assist.material'
    _description = '班务材料归档（F7）'
    _order = 'create_date desc, id desc'

    name = fields.Char('标题', required=True, default='（未命名材料）')
    source_person_id = fields.Many2one('edu.tg.assist.person', '来自', ondelete='set null',
                                       index=True)
    source_chat_id = fields.Char('来源私聊 chat_id', index=True)
    message_id = fields.Char('Telegram 消息 id')
    kind = fields.Selection(KIND_SELECTION, '类型', default='text', required=True)
    raw_text = fields.Text('原文（只存本库）')
    file_name = fields.Char('文件名')
    file_mime = fields.Char('文件类型')
    file_id = fields.Char('Telegram file_id')
    file_size = fields.Integer('文件大小')
    file_data = fields.Binary('文件本体', attachment=True)
    file_fetched_at = fields.Datetime('取回时间')
    file_error = fields.Char('取回错误')
    category = fields.Selection(CATEGORY_SELECTION, '分类', default='other', index=True)
    urgency = fields.Selection(URGENCY_SELECTION, '紧急度', default='normal', index=True)
    deadline = fields.Date('截止')
    summary = fields.Text('摘要')
    key_points = fields.Text('关键信息')
    tags = fields.Char('标签（逗号分隔）')
    todo = fields.Char('待办')
    ai_state = fields.Selection(AI_STATE_SELECTION, '抽取方式', default='none', index=True)
    llm_model = fields.Char('模型')
    llm_error = fields.Char('模型错误')
    llm_raw = fields.Text('模型原始返回')
    notion_state = fields.Selection(NOTION_STATE_SELECTION, 'Notion', default='off', index=True)
    notion_page_id = fields.Char('Notion 页面 id')
    notion_url = fields.Char('Notion 链接')
    notion_error = fields.Char('Notion 错误')
    notion_fallback = fields.Boolean('Notion 用了保底属性')
    state = fields.Selection(STATE_SELECTION, '状态', default='new', required=True, index=True)
    analyzed_at = fields.Datetime('分析时间')
    active = fields.Boolean('启用', default=True)

    # ---------- 取用 ----------
    @api.model
    def _param(self, key, default=''):
        return (self.env['ir.config_parameter'].sudo().get_param(key) or default).strip()

    @api.model
    def _is_staff(self, person):
        """B12：只有教职工的私聊才归档（学生与未知角色走原路）。"""
        return bool(person and person.active and person.role in STAFF_ROLES)

    @api.model
    def _kind_of(self, msg):
        """消息类型 → 归档类型（不下载本体，只看 Telegram 给的元数据）。"""
        if msg.get('document'):
            return 'document'
        if msg.get('photo'):
            return 'photo'
        if msg.get('voice') or msg.get('audio') or msg.get('video_note') or msg.get('video'):
            return 'voice'
        if (msg.get('text') or msg.get('caption') or '').strip():
            return 'text'
        return 'other'

    @api.model
    def _file_meta(self, msg):
        """文件名/类型/id/大小 —— 兼容 document 与 photo（photo 是尺寸数组）。"""
        doc = msg.get('document') or {}
        if doc:
            return doc
        for key in ('voice', 'audio', 'video_note', 'video'):
            if msg.get(key):
                return msg.get(key) or {}
        photos = msg.get('photo') or []
        if photos:
            best = photos[-1] if isinstance(photos[-1], dict) else {}
            # 图片没有文件名，就用「图片 + 宽x高」当个可读的称呼
            best = dict(best)
            best.setdefault('file_name', '图片 %sx%s' % (best.get('width') or '?', best.get('height') or '?'))
            return best
        return {}

    @api.model
    def _text_of(self, msg):
        return (msg.get('text') or msg.get('caption') or '').strip()

    # ---------- 入口：老师私聊转发（bot.py 自动发现本挂点）----------
    @api.model
    def _tg_assist_note_private_message(self, msg, chat, person, text):
        """私聊消息挂点：是教职工就归档。返回 (reply_text, None) 让 bot 替他回执。

        不是教职工一律返回 None —— 学生流一字不变（B12）。异常也返回 None，
        绝不因为归档出问题就把「我不认识这条指令」这条路弄坏。
        """
        try:
            if not self._is_staff(person):
                return None
            rec = self.ingest(msg, person, chat)
            if not rec:
                return None
            return (self._receipt_text(rec), None)
        except Exception as exc:  # noqa: BLE001
            _logger.warning('edu_tg_assist: 材料归档入口失败：%s', type(exc).__name__)
            return None

    @api.model
    def ingest(self, msg, person, chat):
        """先落库（state=new），马上回执，分析交给 cron/按钮。"""
        meta = self._file_meta(msg)
        text = self._text_of(msg)
        kind = self._kind_of(msg)
        title = text.splitlines()[0][:120] if text else (meta.get('file_name') or '（未命名材料）')
        if not text and not meta:
            return False
        rec = self.sudo().create({
            'name': title[:120] or '（未命名材料）',
            'source_person_id': person.id,
            'source_chat_id': str(chat.get('id') or person.chat_id or ''),
            'message_id': str(msg.get('message_id') or '')[:64],
            'kind': kind,
            'raw_text': text,
            'file_name': (meta.get('file_name') or '')[:200],
            'file_mime': (meta.get('mime_type') or '')[:80],
            'file_id': (meta.get('file_id') or '')[:120],
            'file_size': int(meta.get('file_size') or 0),
            'state': 'new',
        })
        # 没有任何出网动作时（没配大模型、没开 Notion、或正处试运行），立刻本地分析：
        # 老师当场看到结果，且回执只有一条（见 _receipt_text）。
        if not self._external_configured():
            rec._analyze_one(send_receipt=False)
        return rec

    @api.model
    @api.model
    def _dry_run(self):
        """全局试运行开关（edu_tg_assist.dry_run=1）—— 试运行时 LLM 与 Notion 都不出网。"""
        return self.env['edu.tg.assist.api'].sudo()._dry_run()

    @api.model
    def _external_configured(self):
        """**会不会出网**：配了 LLM 或 Notion，且没在试运行。

        没有出网动作时，ingest 会立刻本地分析 —— 让老师当场看到归档结果，
        而不是等 cron 一分钟（本地零依赖时的体验差别很大）。
        """
        if self._dry_run():
            return False
        llm = self.env['edu.tg.assist.llm'].sudo()
        notion = self.env['edu.tg.assist.notion'].sudo()
        return bool(llm.configured() or notion.configured())

    def _receipt_text(self, rec):
        """回执文案。本地能立刻分析完就**把结果并进这一条**（避免两条消息次序颠倒）。"""
        lines = ['已收下：%s' % (rec.file_name or rec.name)]
        if rec.state == 'analyzed':
            lines.append('（已归档 · 第 %s 条 · %s）' % (
                rec.id, dict(AI_STATE_SELECTION).get(rec.ai_state, rec.ai_state)))
            lines.extend(['', ''] + mattext.digest_lines(rec._digest_data()))
            lines.append('（后台「班务机器人 → 材料归档」可改。）')
        else:
            lines.append('（第 %s 条，正在分类归档…分析完我再回你一条。）' % rec.id)
        if rec.file_id and not rec.file_data:
            lines.append('文件我会替你去取，存到后台「班务机器人 → 材料归档」，'
                         '到时候可以直接下载、或转发给教务。')
        return chr(10).join(lines)

    def _digest_data(self):
        """字段 → 回执用的九个键（金额从 key_points 里回捞）。"""
        self.ensure_one()
        amount = ''
        hit = re.search(r'金额：([^\n]+)', self.key_points or '')
        if hit:
            amount = hit.group(1).strip()
        return {
            'title': self.name,
            'summary': self.summary or '',
            'category': self.category,
            'urgency': self.urgency,
            'deadline': self.deadline.isoformat() if self.deadline else '',
            'amount': amount,
            'people': [],
            'tags': self.tag_list(),
            'todo': self.todo or '',
        }

    def _send_receipt(self, text, kind='material'):
        """回执一律走 Telegram 出网口；失败只落 send_log，不抛。"""
        self.ensure_one()
        if not self.source_chat_id:
            return False
        return self.env['edu.tg.assist.api'].sudo().send_message(
            self.source_chat_id, text, kind=kind)

    # ---------- 文件本体取回 ----------
    @api.model
    def _max_bytes(self):
        """单文件上限（MB → 字节）。默认 10 MB，显式配 0 或非法值一律回落默认。

        Telegram 官方 getFile 只允许下载 20 MB 以内的文件；默认再留一半余量，
        因为文件本体是存在学校自购机器的数据库里（附件与备份都跟着涨）。
        """
        raw = self._param(MAX_MB_PARAM)
        try:
            mb = int(float(raw)) if raw else DEFAULT_MAX_MB
        except (TypeError, ValueError):
            mb = DEFAULT_MAX_MB
        if mb <= 0:
            mb = DEFAULT_MAX_MB
        return mb * 1024 * 1024

    def _fetch_file(self, send_receipt=False):
        """把 Telegram 上的文件本体取回本库（已有本体直接算成功，幂等）。

        为什么不在 webhook 里下载：那个钩子必须一秒内回 200，10 MB 的附件会把
        回执拖到 Telegram 超时重投（= 同一条材料重复归档两次）。所以钩子里只记
        file_id，本体交给每分钟的 cron 或后台「⬇️ 取回文件」按钮慢慢取。
        """
        self.ensure_one()
        api = self.env['edu.tg.assist.api'].sudo()
        if self.file_data:
            return True
        if not self.file_id:
            return False
        if (self._param(DOWNLOAD_PARAM, '1') or '1') == '0':
            return False
        cap = self._max_bytes()
        if self.file_size and self.file_size > cap:
            self.sudo().write({'file_error': _too_big(self.file_size, cap)})
            return False
        ok, data = api.call('getFile', {'file_id': self.file_id})
        path = (data or {}).get('file_path') if ok else ''
        if not path:
            self.sudo().write({'file_error': 'getFile 失败：%s' % str(data)[:200]})
            return False
        try:
            resp = requests.get(FILE_URL_TMPL % (api._token(), path), timeout=(5, 30))
        except Exception as exc:  # noqa: BLE001
            self.sudo().write({'file_error': '下载失败：%s' % type(exc).__name__})
            return False
        if resp.status_code != 200:
            self.sudo().write({'file_error': '下载失败：HTTP %s' % resp.status_code})
            return False
        blob = resp.content or b''
        if len(blob) > cap:
            self.sudo().write({'file_error': _too_big(len(blob), cap)})
            return False
        self.sudo().write({
            'file_data': base64.b64encode(blob),
            'file_fetched_at': fields.Datetime.now(),
            'file_error': '',
        })
        _logger.info('edu_tg_assist: 材料 %s 取回 %s 字节', self.id, len(blob))
        if send_receipt:
            self._send_receipt('📎 文件已存到后台：%s（后台「材料归档」里可以下载，或直接转发给教务。）'
                               % (self.file_name or self.name), kind='material_file')
        return True

    # ---------- 分析 ----------
    def _analyze_one(self, send_receipt=True):
        """规则抽取（必做）+ 可选 LLM（配了才做）+ 可选 Notion 导出。"""
        self.ensure_one()
        today = fields.Date.today().isoformat()
        source = self.raw_text or self.file_name or ''
        rule = mattext.rule_extract(source, today=today)
        llm_raw = None
        vals = {'ai_state': 'rule', 'llm_error': '', 'llm_raw': ''}
        llm = self.env['edu.tg.assist.llm'].sudo()
        if llm.configured() and not self._dry_run():
            # B10：出网前脱敏（手机号/身份证/银行卡/邮箱/邀请码）
            masked, hits = mattext.mask_sensitive(source)
            masked, truncated = llm.prepare(masked)
            ok, payload = llm.extract(masked)
            if ok:
                llm_raw = payload.get('data')
                vals.update({'ai_state': 'llm', 'llm_model': payload.get('model') or '',
                             'llm_raw': payload.get('raw') or ''})
                if truncated or hits:
                    vals['llm_error'] = '已脱敏%s%s' % (
                        ('、截断' if truncated else ''),
                        ('（%s 处敏感信息）' % hits if hits else ''))
            else:
                vals['ai_state'] = 'llm_failed'
                vals['llm_error'] = str(payload)[:200]
                _logger.warning('edu_tg_assist: 材料 %s 大模型抽取失败，已降级规则', self.id)
        merged = mattext.merge_extract(rule, llm_raw)
        vals.update(self._merged_vals(merged))
        vals['state'] = 'analyzed'
        vals['analyzed_at'] = fields.Datetime.now()
        self.sudo().write(vals)
        self._push_notion(send_receipt=send_receipt)
        if send_receipt:
            self._send_receipt(chr(10).join(mattext.digest_lines(merged)) + chr(10) +
                               '（后台「材料归档」可改；要改完重推 Notion 就点「重推 Notion」。）',
                               kind='material_done')
        return True

    def _merged_vals(self, merged):
        """抽取结果 → 字段值（日期非法就不写，避免 Odoo 读日期炸）。"""
        self.ensure_one()
        points = []
        if merged.get('todo'):
            points.append('待办：%s' % merged['todo'])
        if merged.get('amount'):
            points.append('金额：%s' % merged['amount'])
        if merged.get('people'):
            points.append('相关人：%s' % '、'.join(merged['people']))
        return {
            'name': (merged.get('title') or self.file_name or '（未命名材料）')[:120],
            'category': merged.get('category') or 'other',
            'urgency': merged.get('urgency') or 'normal',
            'deadline': merged.get('deadline') or False,
            'summary': merged.get('summary') or '',
            'key_points': chr(10).join(points),
            'tags': ','.join(merged.get('tags') or []),
            'todo': (merged.get('todo') or '')[:300],
        }

    def tag_list(self):
        self.ensure_one()
        return [t for t in (self.tags or '').split(',') if t]

    # ---------- Notion（可选）----------
    def _notion_data(self):
        self.ensure_one()
        return {
            'title': self.name,
            'summary': self.summary or '',
            'category': self.category,
            'urgency': self.urgency,
            'deadline': self.deadline.isoformat() if self.deadline else '',
            'tags': self.tag_list(),
        }

    def _notion_body(self):
        """送 Notion 的正文：默认只有摘要/关键信息/来源，**不含原文**（B11）。"""
        self.ensure_one()
        notion = self.env['edu.tg.assist.notion'].sudo()
        lines = []
        if self.summary:
            lines.append(self.summary)
        if self.key_points:
            lines.append(self.key_points)
        if self.todo:
            lines.append('待办：%s' % self.todo)
        lines.append('来源：Telegram 私聊归档（%s）／系统编号 %s' % (self.kind, self.id))
        if notion.include_raw() and self.raw_text:
            lines.append('原文：%s' % self.raw_text)
        return chr(10).join(lines)

    def _push_notion(self, send_receipt=True):
        """把这一条推去 Notion。未启用就标 off；失败只落库（B9/B11）。"""
        self.ensure_one()
        notion = self.env['edu.tg.assist.notion'].sudo()
        if not notion.configured() or self._dry_run():
            self.sudo().write({'notion_state': 'off', 'notion_error': ''})
            return False
        masked_data = dict(self._notion_data())
        masked_data['summary'] = mattext.mask_sensitive(masked_data.get('summary') or '')[0]
        body = mattext.mask_sensitive(self._notion_body())[0]
        ok, result = notion.create_page(masked_data, body_text=body)
        if ok:
            self.sudo().write({
                'notion_state': 'ok',
                'notion_page_id': result.get('id') or '',
                'notion_url': result.get('url') or '',
                'notion_error': '属性名对不上目标库，已用保底 title+正文' if result.get('fallback') else '',
                'notion_fallback': bool(result.get('fallback')),
            })
            if send_receipt and self.source_chat_id:
                self._send_receipt('已导到 Notion：%s' % (result.get('url') or '（链接没回来）'),
                                   kind='material_notion')
        else:
            self.sudo().write({'notion_state': 'failed', 'notion_error': str(result)[:200]})
            if send_receipt and self.source_chat_id:
                self._send_receipt('Notion 导出失败（材料已留在本地，不丢）：%s' % str(result)[:150],
                                   kind='material_notion')
        return ok

    # ---------- cron / 按钮 ----------
    @api.model
    def _cron_analyze(self):
        """每分钟扫一遍：没分析的先分析，Notion 首批失败的（pending）补推。"""
        if (self._param(AUTO_ANALYZE_PARAM, '1') or '1') == '0':
            return 0
        done = 0
        pending = self.sudo().search([('state', '=', 'new')], limit=ANALYZE_BATCH, order='id')
        for rec in pending:
            try:
                rec._analyze_one(send_receipt=True)
                done += 1
            except Exception as exc:  # noqa: BLE001
                _logger.warning('edu_tg_assist: 材料 %s 分析失败：%s', rec.id, type(exc).__name__)
        # 文件本体：只取「已分析、有 file_id、既没本体也没报过错」的。
        # 报过错的（太大 / 已过期）留给后台按钮人工重试，免得每分钟去撞同一面墙。
        to_fetch = self.sudo().search([('state', '=', 'analyzed'),
                                       ('file_id', '!=', False),
                                       ('file_data', '=', False),
                                       ('file_error', '=', False)],
                                      limit=ANALYZE_BATCH, order='id')
        for rec in to_fetch:
            try:
                if rec._fetch_file(send_receipt=True):
                    done += 1
            except Exception as exc:  # noqa: BLE001
                _logger.warning('edu_tg_assist: 材料 %s 取回文件失败：%s', rec.id,
                                type(exc).__name__)
        for rec in self.sudo().search([('notion_state', '=', 'pending')], limit=ANALYZE_BATCH,
                                      order='id'):
            try:
                rec._push_notion(send_receipt=True)
                done += 1
            except Exception as exc:  # noqa: BLE001
                _logger.warning('edu_tg_assist: 材料 %s 补推 Notion 失败：%s', rec.id,
                                type(exc).__name__)
        return done

    @api.model
    def _cron_prune(self):
        """按 material_keep_days 清理老归档（0 = 永久保留）。"""
        raw = self._param(KEEP_DAYS_PARAM)
        try:
            days = int(float(raw)) if raw else DEFAULT_KEEP_DAYS
        except (TypeError, ValueError):
            days = DEFAULT_KEEP_DAYS
        if days <= 0:
            return 0
        limit = datetime.now() - timedelta(days=days)
        old = self.sudo().search([('create_date', '<', limit)])
        count = len(old)
        if count:
            old.unlink()
        return count

    def action_analyze_now(self):
        """表单按钮：立刻分析这一条。"""
        for rec in self:
            try:
                rec._analyze_one(send_receipt=True)
            except Exception as exc:  # noqa: BLE001
                raise UserError('分析失败：%s' % type(exc).__name__) from exc
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': '材料归档', 'message': '已重新分析。', 'type': 'success',
                       'sticky': False},
        }

    def action_fetch_file(self):
        """后台按钮：立刻取回文件本体（上次失败的一并重试一次）。"""
        fetched, failed = 0, 0
        for rec in self:
            if not rec.file_id or rec.file_data:
                continue
            if rec.file_error:
                rec.sudo().write({'file_error': ''})
            try:
                if rec._fetch_file(send_receipt=True):
                    fetched += 1
                else:
                    failed += 1
            except Exception as exc:  # noqa: BLE001
                _logger.warning('edu_tg_assist: 材料 %s 取回文件失败：%s', rec.id,
                                type(exc).__name__)
                failed += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': '取回文件',
                       'message': '已取回 %s 条；失败 %s 条（失败原因见「取回错误」栏）。'
                                  % (fetched, failed),
                       'type': 'success' if not failed else 'warning', 'sticky': False},
        }

    def action_open_forward(self):
        """表单按钮「📤 转发给…」：弹一个对话框，把这一条转给某人/某个群。

        2026-10-13 用户要求（选项 c）。实际发送在 edu.tg.assist.forward.action_send：
        文件走 Telegram file_id（不重传），纯文本材料就发文本；只发本模块登记过的目标。
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '转发这份材料',
            'res_model': 'edu.tg.assist.forward',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_material_id': self.id},
        }

    def action_push_notion(self):
        """表单按钮：手动把这一条推 Notion（配了才推）。"""
        self.ensure_one()
        notion = self.env['edu.tg.assist.notion'].sudo()
        if not notion.configured():
            raise UserError('Notion 未启用或没配齐（notion_enabled / notion_token / notion_db_id）。')
        ok = self._push_notion(send_receipt=True)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': '推送 Notion', 'message': '已推送。' if ok else '推送失败，详情见本页错误栏。',
                       'type': 'success' if ok else 'danger', 'sticky': False},
        }

    def action_retry_notion(self):
        """列表批量按钮：把失败的重新排进 pending（cron 一分钟内补推）。"""
        count = len(self)
        if self:
            self.sudo().write({'notion_state': 'pending'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': '推送 Notion', 'message': '已排入待推送：%s 条。' % count,
                       'type': 'success', 'sticky': False},
        }
