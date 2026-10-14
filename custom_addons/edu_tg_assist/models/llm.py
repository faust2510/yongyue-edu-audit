# -*- coding: utf-8 -*-
"""F7 的大模型客户端（OpenAI 兼容 `/chat/completions`）—— 本模块**唯一**的大模型出网口。

纪律与 api.py（Telegram 出网口）逐条对齐：
  · **不抛异常**：失败只回报 (False, 原因)，由 material.py 落进 llm_error；
  · **绝不把 api_key 写进日志**（只记方法名与异常类型）；
  · **默认零出网**：base_url / model / api_key 任一为空 ⇒ configured() 为假，一个包都不发（B9）；
  · 送出去的正文由调用方**先脱敏**（B10，纯函数在 mattext.py）；
  · 超时默认 20s：这是 cron 里跑的活，但仍要有界，不能让一次抖动卡住整批。

为什么不让 Odoo 自己接模型：本机 Odoo 19 社区版没有 addons/ai（直取 404，见
docs/research/ai-archive-and-notion.md §2），官方 AI 字段还要 Studio —— 只能自己写这一层薄客户端。
"""
import logging

import requests

from odoo import api, models
from odoo.addons.edu_tg_assist.mattext import extract_json

_logger = logging.getLogger(__name__)

BASE_PARAM = 'edu_tg_assist.llm_base_url'
KEY_PARAM = 'edu_tg_assist.llm_api_key'
MODEL_PARAM = 'edu_tg_assist.llm_model'
TIMEOUT_PARAM = 'edu_tg_assist.llm_timeout'
MAX_CHARS_PARAM = 'edu_tg_assist.llm_max_chars'

DEFAULT_TIMEOUT = 20
DEFAULT_MAX_CHARS = 4000
TIMEOUT_CAP = 90
MAX_ERROR = 500

# 提示词刻意把「必须是 JSON」写在最前面，并给出九个键的英文名 —— 中文键也认（mattext 别名表）。
SYSTEM_PROMPT = (
    '你是学校行政材料归档助手。阅读用户给的材料（可能是转发的通知、聊天记录、公文），'
    '只输出一个 JSON 对象，不要任何解释、不要代码围栏。字段：'
    'title（不超过40字的标题）、summary（一句话摘要，不超过200字）、'
    'category（只能是 notice/material/report/finance/personnel/schedule/other 之一）、'
    'urgency（只能是 low/normal/high/urgent 之一）、deadline（YYYY-MM-DD，没有就给空串）、'
    'amount（金额原文，没有就空串）、people（相关人名数组）、tags（3个以内关键词数组）、'
    'todo（需要谁在什么时候做什么，没有就空串）。判断不了就留空，不要编造。'
)


class EduTgAssistLlm(models.AbstractModel):
    _name = 'edu.tg.assist.llm'
    _description = '大模型客户端（OpenAI 兼容，edu_tg_assist 专用）'

    @api.model
    def _param(self, key, default=''):
        return (self.env['ir.config_parameter'].sudo().get_param(key) or default).strip()

    @api.model
    def configured(self):
        """三个参数全配齐才算「配了」—— 少一个就退规则抽取，绝不半配着发。"""
        return bool(self._param(BASE_PARAM) and self._param(MODEL_PARAM) and self._param(KEY_PARAM))

    @api.model
    def model_name(self):
        return self._param(MODEL_PARAM)

    @api.model
    def endpoint(self):
        """按 base_url 拼出 chat/completions 完整地址（容忍结尾斜杠与已带路径）。"""
        base = self._param(BASE_PARAM).rstrip('/')
        if not base:
            return ''
        if base.endswith('/chat/completions'):
            return base
        return base + '/chat/completions'

    @api.model
    def _timeout(self):
        raw = self._param(TIMEOUT_PARAM)
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT
        if value <= 0:
            return DEFAULT_TIMEOUT
        return min(value, TIMEOUT_CAP)

    @api.model
    def max_chars(self):
        raw = self._param(MAX_CHARS_PARAM)
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            return DEFAULT_MAX_CHARS
        return value if value > 0 else DEFAULT_MAX_CHARS

    @api.model
    def prepare(self, text):
        """按上限截断待送文本。:return: (文本, 是否截断)"""
        raw = text if isinstance(text, str) else ''
        limit = self.max_chars()
        if len(raw) <= limit:
            return raw, False
        return raw[:limit], True

    @api.model
    def extract(self, text):
        """把材料文本送去抽取。:return: (ok, payload)

        ok=True 时 payload = {'data': 归一前 dict, 'raw': 模型原文, 'model': 模型名, 'truncated': bool}；
        ok=False 时 payload = 错误字符串（**不含 key**）。
        """
        endpoint = self.endpoint()
        key = self._param(KEY_PARAM)
        model = self.model_name()
        if not (endpoint and key and model):
            return False, '未配置 %s / %s / %s' % (BASE_PARAM, MODEL_PARAM, KEY_PARAM)
        body = {
            'model': model,
            'temperature': 0,
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': text or ''},
            ],
        }
        headers = {'Authorization': 'Bearer %s' % key, 'Content-Type': 'application/json'}
        try:
            resp = requests.post(endpoint, json=body, headers=headers, timeout=self._timeout())
        except requests.RequestException as exc:
            # 注意：**绝不**把 endpoint 带 key 的查询串或 header 写进日志
            _logger.warning('edu_tg_assist: LLM 调用失败（网络）：%s', type(exc).__name__)
            return False, '%s: %s' % (type(exc).__name__, str(exc)[:MAX_ERROR])
        if resp.status_code != 200:
            detail = (resp.text or '')[:200]
            _logger.warning('edu_tg_assist: LLM 返回 HTTP %s', resp.status_code)
            return False, 'HTTP %s: %s' % (resp.status_code, detail)
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            return False, '响应不是 JSON'
        choices = (data or {}).get('choices') or []
        content = ''
        if choices and isinstance(choices[0], dict):
            content = ((choices[0].get('message') or {}).get('content') or '')
        parsed = extract_json(content)
        if parsed is None:
            return False, '模型没有给出可解析的 JSON：%s' % (content or '')[:200]
        used = (data.get('model') if isinstance(data, dict) else '') or model
        return True, {
            'data': parsed,
            'raw': (content or '')[:2000],
            'model': str(used)[:64],
            'truncated': False,
        }
