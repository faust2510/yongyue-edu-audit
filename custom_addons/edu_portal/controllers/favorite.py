# -*- coding: utf-8 -*-
"""门户常用应用收藏（辅助增强包 3b）。

POST /my/favorites/save：整组保存当前用户常用区顺序（hrefs 列表）。
前端 home_favs.js 在本地持久化的同时 fire-and-forget 同步到本路由；
SSR 渲染时按服务端收藏直出（_build_favorites 覆盖）。
"""
import logging

from odoo import http
from odoo.http import request

from ..models.notify_pref import NOTIFY_EVENTS

_NOTIFY_EVENT_LABELS = NOTIFY_EVENTS

_logger = logging.getLogger(__name__)


class EduFavoritePortal(http.Controller):

    @http.route('/my/favorites/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def favorites_save(self, **post):
        """保存常用区（hrefs 数组整体重写；归属强制当前用户）。"""
        hrefs = [
            h.strip()[:256]
            for h in request.httprequest.form.getlist('hrefs')
            if h and h.strip()
        ]
        try:
            Fav = request.env['edu.favorite'].sudo()
            Fav.search([('user_id', '=', request.env.uid)]).unlink()
            seq = 0
            for href in hrefs:
                # 去掉可能的重复项
                if Fav.search_count([('user_id', '=', request.env.uid),
                                     ('card_href', '=', href)]):
                    continue
                Fav.create({'user_id': request.env.uid,
                            'card_href': href,
                            'sequence': seq})
                seq += 1
            return request.make_json_response({'ok': True, 'count': seq})
        except Exception:
            _logger.warning('favorites save failed', exc_info=True)
            return request.make_json_response({'ok': False}, status=200)


    # ------------------------------------------------------------------
    # 第 5 批 A：站内通知偏好（/my/notify）
    # ------------------------------------------------------------------
    @http.route('/my/notify', type='http', auth='user', website=True)
    def notify_prefs(self, **kw):
        uid = request.env.uid
        Pref = request.env['edu.notify.pref'].sudo()
        muted = set(Pref.search([('user_id', '=', uid),
                                 ('muted', '=', True)]).mapped('event_key'))
        from .favorite import _NOTIFY_EVENT_LABELS
        events = [{'key': k, 'label': label, 'muted': k in muted}
                  for k, label in _NOTIFY_EVENT_LABELS]
        return request.render('edu_portal.edu_notify_prefs', {
            'title': '通知偏好',
            'page_name': 'notify_prefs',
            'events': events,
        })

    @http.route('/my/notify/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def notify_prefs_save(self, **post):
        uid = request.env.uid
        Pref = request.env['edu.notify.pref'].sudo()
        from .favorite import _NOTIFY_EVENT_LABELS
        for key, _label in _NOTIFY_EVENT_LABELS:
            muted = not post.get('evt_' + key)
            rec = Pref.search([('user_id', '=', uid),
                               ('event_key', '=', key)], limit=1)
            if rec:
                rec.write({'muted': muted})
            else:
                Pref.create({'user_id': uid, 'event_key': key,
                             'muted': muted})
        return request.redirect('/my/notify?saved=1')
