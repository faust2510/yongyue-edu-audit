# -*- coding: utf-8 -*-
"""F7 的 Notion 客户端 —— 本模块**唯一**的 Notion 出网口。

纪律（与 llm.py / api.py 同一套）：
  · **不抛异常**：失败只回报 (False, 原因)，由 material.py 落 notion_error；
  · **绝不把 token 写进日志**；
  · **默认关**：notion_enabled 必须为 '1'，且 token 与库 id 都配齐才发（B9）；
  · **保底回退**：属性名对不上目标库 schema 时 Notion 直接 400 ⇒ 用「只写 title + 正文块」
    再试一次（设计 §9.11.6），本地归档不受影响（B11：不回滚）。

Notion 侧的硬规矩（一手来源：docs/research/ai-archive-and-notion.md §4）：
  · 认证 = `Authorization: Bearer <internal integration token>` + `Notion-Version` 头；
  · `POST /v1/pages` 的 parent 只给 page / database / data_source；
  · 只读属性（formula / rollup / created_* 等）**必须省略**；
  · 目标库必须先 share 给这个 integration（Notion 侧动作，程序代办不了）。
"""
import json
import logging

import requests

from odoo import api, models
from odoo.addons.edu_tg_assist.mattext import build_notion_payload, title_only_payload

_logger = logging.getLogger(__name__)

NOTION_API = 'https://api.notion.com'
TOKEN_PARAM = 'edu_tg_assist.notion_token'
DB_PARAM = 'edu_tg_assist.notion_db_id'
ENABLED_PARAM = 'edu_tg_assist.notion_enabled'
VERSION_PARAM = 'edu_tg_assist.notion_api_version'
PARENT_TYPE_PARAM = 'edu_tg_assist.notion_parent_type'
FIELD_MAP_PARAM = 'edu_tg_assist.notion_field_map'
INCLUDE_RAW_PARAM = 'edu_tg_assist.notion_include_raw'

DEFAULT_VERSION = '2026-03-11'
DEFAULT_PARENT_TYPE = 'database'
TIMEOUT = (5, 15)
MAX_ERROR = 500
PARENT_TYPES = ('database', 'data_source')


class EduTgAssistNotion(models.AbstractModel):
    _name = 'edu.tg.assist.notion'
    _description = 'Notion 客户端（edu_tg_assist 专用）'

    @api.model
    def _param(self, key, default=''):
        return (self.env['ir.config_parameter'].sudo().get_param(key) or default).strip()

    @api.model
    def enabled(self):
        return self._param(ENABLED_PARAM) == '1'

    @api.model
    def configured(self):
        """开关 + token + 库 id 三者齐全才算配好；少一个 = notion_state=off。"""
        return bool(self.enabled() and self._param(TOKEN_PARAM) and self._param(DB_PARAM))

    @api.model
    def include_raw(self):
        return self._param(INCLUDE_RAW_PARAM) == '1'

    @api.model
    def parent_type(self):
        value = self._param(PARENT_TYPE_PARAM, DEFAULT_PARENT_TYPE) or DEFAULT_PARENT_TYPE
        return value if value in PARENT_TYPES else DEFAULT_PARENT_TYPE

    @api.model
    def parent(self):
        """数据库时代是 {'database_id': ...}；新版 data source 是 {'type':'data_source_id',...}。"""
        target = self._param(DB_PARAM)
        if self.parent_type() == 'data_source':
            return {'type': 'data_source_id', 'data_source_id': target}
        return {'database_id': target}

    @api.model
    def field_map(self):
        """属性名映射（JSON 字符串，配错了就忽略 —— 绝不让坏配置把归档搞挂）。"""
        raw = self._param(FIELD_MAP_PARAM)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            _logger.warning('edu_tg_assist: notion_field_map 不是合法 JSON，已忽略')
            return {}
        return data if isinstance(data, dict) else {}

    @api.model
    def _post(self, payload):
        """发一页。:return: (ok, result_or_error)"""
        token = self._param(TOKEN_PARAM)
        if not token:
            return False, '未配置系统参数 %s' % TOKEN_PARAM
        headers = {
            'Authorization': 'Bearer %s' % token,
            'Notion-Version': self._param(VERSION_PARAM, DEFAULT_VERSION) or DEFAULT_VERSION,
            'Content-Type': 'application/json',
        }
        try:
            resp = requests.post(NOTION_API + '/v1/pages', json=payload, headers=headers,
                                 timeout=TIMEOUT)
        except requests.RequestException as exc:
            _logger.warning('edu_tg_assist: Notion 调用失败（网络）：%s', type(exc).__name__)
            return False, '%s: %s' % (type(exc).__name__, str(exc)[:MAX_ERROR])
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {}
        if resp.status_code == 200 and isinstance(data, dict):
            return True, {
                'id': str(data.get('id') or ''),
                'url': str(data.get('url') or ''),
            }
        detail = ''
        if isinstance(data, dict):
            detail = data.get('message') or data.get('code') or ''
        if not detail:
            detail = (resp.text or '')[:200]
        return False, 'HTTP %s: %s' % (resp.status_code, str(detail)[:MAX_ERROR])

    @api.model
    def create_page(self, data, body_text=''):
        """建一页归档。:return: (ok, {'id','url','fallback'} | 错误字符串)

        先按完整属性试；被 400 拒（多半是属性名/类型对不上目标库 schema）就**保底**只写
        title + 正文块再试一次。两次都失败 ⇒ (False, 错误原文)，调用方落 notion_error。
        """
        if not self.configured():
            return False, 'off'
        parent = self.parent()
        field_map = self.field_map()
        payload = build_notion_payload(parent, data, field_map=field_map, body_text=body_text)
        ok, result = self._post(payload)
        if ok:
            result['fallback'] = False
            return True, result
        if not payload.get('properties') or len(payload.get('properties') or {}) <= 1:
            return False, result
        _logger.warning('edu_tg_assist: Notion 首次建页被拒（%s），改用保底 title+正文重试',
                        str(result)[:120])
        fallback_payload = title_only_payload(parent, (data or {}).get('title') or '', body_text=body_text)
        ok2, result2 = self._post(fallback_payload)
        if ok2:
            result2['fallback'] = True
            return True, result2
        return False, '%s ／ 保底重试也失败：%s' % (result, result2)
