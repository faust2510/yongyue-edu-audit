# -*- coding: utf-8 -*-
"""教务端「报课池模式」设置页（G1，设计 §7.2）。

设计：docs/plans/scheduling-overhaul-design.md §7.2（三档开关与必修同口径）。
背景：三档开关一旦只在代码里存在、门户里没有入口，教务就只能找开发改库 ——
本文件补的就是这一条动线。数据面仍是 `ir.config_parameter`
（键 `edu.enroll.pool_mode`，单键、无新模型、无新表），语义常量与读取器
统一在 enroll.py（本文件只 import，不复制一份）。

路由（两条都是新路径，无冲突）：
- GET  /edu/enroll/pool_mode       展示三档语义 + 当前档位 + 保存入口
- POST /edu/enroll/pool_mode/save  校验后写参数，303 回本页带提示

门禁：privileged_staff()（教务组 or 系统组）——非教务**一律 303 回 /my/home**
（fail-closed，与 /registrar/curriculum、/my/availability 同一口径：教师、
学生、家长都被拦；匿名走 auth='user' 的登录流程）。写入用 sudo()：门禁已在
控制器层过，且 ir.config_parameter 的 ACL 本就只给系统组。
"""
import logging

from odoo import http
from odoo.http import request

from .enroll import (POOL_MODE_DEFAULT, POOL_MODE_KEY, POOL_MODES,
                     edu_pool_mode)
from .roles import privileged_staff

_logger = logging.getLogger(__name__)

# 档位中文名（页面与审计台账共用；页面**不显示** off/annotate/strict 原文 ——
# 可见文案一律中文，英文串会被 check_english 当 must-fix）。
POOL_MODE_LABEL = {
    'off': '关闭（零回归）',
    'annotate': '全列并标注（默认）',
    'strict': '只列已排课',
}
POOL_MODE_DESC = {
    'off': '报课页与改造前完全一致：科目全列、不加红字、不做排课过滤，'
           '也不阻断提交。仅用于临时回退（例如课表尚未导入时的救急）。',
    'annotate': '科目目录保持全列；本学期未排课的科目在卡片上给出红字'
                '「本学期未排课」并自动禁止勾选；若必修里有未排课的科目，'
                '整单不能提交并提示联系教务处确认开课安排。',
    'strict': '只列出「本学期已排课」与「已批准单里已有的」科目；'
              '若本学期一门课都还没排，报课页显示'
              '「本学期课表尚未发布，报课暂未开放；请联系教务处。」',
}
BOX_MSG = {
    'saved': '已保存：报课池档位已更新，报课页即刻按新档位生效。',
    'same': '提交值与当前档位一致，本次没有任何改动。',
    'bad': '提交的档位不合法，本次没有做任何改动（请刷新重试）。',
}
BOX_OK = ('saved', 'same')


def _url(box):
    return '/edu/enroll/pool_mode?box=%s' % box


class EduEnrollPoolMode(http.Controller):
    """报课池三档开关的门户设置页（GET 展示 / POST 保存）。"""

    @http.route('/edu/enroll/pool_mode', type='http', auth='user',
                website=True)
    def pool_mode(self, **kw):
        if not privileged_staff():
            return request.redirect('/my/home', code=303)
        env = request.env
        current = edu_pool_mode(env)
        box = (kw.get('box') or '')[:32]
        return request.render('edu_portal.edu_pool_mode_settings', {
            'title': '报课池模式',
            'page_name': 'enroll_pool_mode',
            'box': box,
            'box_ok': box in BOX_OK,
            'box_msg': BOX_MSG.get(box, ''),
            'current': current,
            'current_label': POOL_MODE_LABEL[current],
            'default_label': POOL_MODE_LABEL[POOL_MODE_DEFAULT],
            # 当前值 == 默认值（含「参数未落库」）：页面上标一个「系统默认」徽章
            'is_default': current == POOL_MODE_DEFAULT,
            'modes': [{
                'key': key,
                'label': POOL_MODE_LABEL[key],
                'desc': POOL_MODE_DESC[key],
                'current': key == current,
            } for key in POOL_MODES],
        })

    @http.route('/edu/enroll/pool_mode/save', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def pool_mode_save(self, **post):
        """保存档位。

        非法值**一律不写**（既不落库也不写审计），按 bad 提示回本页；
        与当前值相同时不写参数、不写审计（避免台账里灌入空动作）。
        """
        if not privileged_staff():
            return request.redirect('/my/home', code=303)
        env = request.env
        mode = (request.httprequest.form.get('mode')
                or post.get('mode') or '').strip()
        if mode not in POOL_MODES:
            _logger.warning('报课池档位：收到非法值 %r（用户 %s），未做改动',
                            mode, env.user.login)
            return request.redirect(_url('bad'), code=303)
        before = edu_pool_mode(env)
        if mode == before:
            return request.redirect(_url('same'), code=303)
        env['ir.config_parameter'].sudo().set_param(POOL_MODE_KEY, mode)
        env['edu.audit.log'].sudo()._log(
            '报课池档位', 'ir.config_parameter', 0,
            POOL_MODE_LABEL[mode],
            '报课池档位：%s → %s' % (POOL_MODE_LABEL[before],
                                    POOL_MODE_LABEL[mode]))
        return request.redirect(_url('saved'), code=303)
