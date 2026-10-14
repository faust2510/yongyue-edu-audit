# -*- coding: utf-8 -*-
"""教务后台可达性收口：把「教务看得见、但点进去打不开」的原生菜单收回到它真正需要的业务组。

背景（2026-09-17 权限分层 d2c41de）：教务组解除隐含的 base.group_system 之后，
网站（website 应用树）下有三个面教务**看得见但打不开** —— 动作能解析、视图能取到，
但客户端渲染要读的数据被 ACL 挡住，动作加载失败后前端回落到 /apps 应用面板：

  · 网站 / 活动（event.menu_event_event）：看板按 stage 分组 → 要读 event.stage，
    ACL 只给 活动/管理员 与 活动/登记处；
  · 网站 / 配置 / 电子商务 / 付款方式（website_sale.menu_ecommerce_payment_methods）：
    要读 payment.provider，ACL 只给「角色 / 管理员」；
  · 网站 / 技术 / 进行中的通话会话 · 由客服处理 · 由机器人处理
    （spreadsheet_dashboard_im_livechat.*）：要读 im_livechat.channel.member.history，
    ACL 只给「在线聊天 / 用户」。

处置 = **按业务补组**：把菜单收回到它真正需要的业务组 + 超管。
不是把系统管理员加回教务组，也不是放宽到 base.group_user ——
教务的校历活动入口是自研「时间表 / 校历活动」（edu.event），
电子商务 / 在线聊天的管理面本来就不是教务业务。

为什么用 <function> 而不是声明式 <record ... forcecreate="0">：
记录键是**别的模块**的 xmlid，声明式写法在某部署没装该模块时会抛
"Cannot update missing record" 把升级打断；这里按 xmlid 查、查不到就跳过并记日志，
升级永不因此失败。改写幂等（值相同就不写）。

判据与实测证据：docs/plans/perm-split-audit.md §6.1 / §6.4；复跑：
  python3 tests/smoke/backoffice_reachability.py --all-menus --skip-flows
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# (菜单 xmlid, 收回后的组 xmlid 列表, 为什么要收)
NARROW_RULES = [
    ('event.menu_event_event',
     ['event.group_event_manager',
      'event.group_event_registration_desk',
      'base.group_system'],
     '看板按 stage 分组 → 需读 event.stage'),
    ('website_sale.menu_ecommerce_payment_methods',
     ['base.group_system'],
     '需读 payment.provider（仅 角色/管理员）'),
    # 2026-09-17 F-1：嵌套同名菜单穿透 —— 教务看不到名为「应用」的根，却能经
    # 网站/配置 下的同名入口进 ir.module.module 模块列表（731 条）⇒ 收成仅系统管理员。
    # 注意：本菜单在「网站」子树内，seed_teacher_menus.py §3 会整棵写成全开组，
    # 故该脚本已加 SEED_GROUP_EXCEPTIONS 例外，两处必须同时存在。
    ('website.menu_website_add_features',
     ['base.group_system'],
     '系统管理面（ir.module.module 全局模块列表），只应给开发者'),
    ('spreadsheet_dashboard_im_livechat.ongoing_sessions_agents_in_call_menu',
     ['im_livechat.im_livechat_group_user',
      'im_livechat.im_livechat_group_manager',
      'base.group_system'],
     '需读 im_livechat.channel.member.history（仅 在线聊天/用户）'),
    ('spreadsheet_dashboard_im_livechat.ongoing_sessions_handle_by_agent_menu',
     ['im_livechat.im_livechat_group_user',
      'im_livechat.im_livechat_group_manager',
      'base.group_system'],
     '同「进行中的通话会话」'),
    ('spreadsheet_dashboard_im_livechat.ongoing_sessions_handle_by_bot_menu',
     ['im_livechat.im_livechat_group_user',
      'im_livechat.im_livechat_group_manager',
      'base.group_system'],
     '同「进行中的通话会话」'),
]


class IrUiMenuReachability(models.Model):
    """ir.ui.menu 上的可达性收口动作（由 data/menu_reachability.xml 的 <function> 调用）。"""

    _inherit = 'ir.ui.menu'

    @api.model
    def edu_apply_reachability_groups(self):
        """按 NARROW_RULES 收组。幂等；缺模块 / 缺组一律跳过，绝不让升级失败。"""
        changed, unchanged, skipped = [], [], []
        for menu_xmlid, group_xmlids, why in NARROW_RULES:
            menu = self.env.ref(menu_xmlid, raise_if_not_found=False)
            if not menu:
                skipped.append('%s（菜单不存在）' % menu_xmlid)
                continue
            groups = [self.env.ref(g, raise_if_not_found=False)
                      for g in group_xmlids]
            gids = sorted({g.id for g in groups if g})
            if not gids:
                skipped.append('%s（组都取不到）' % menu_xmlid)
                continue
            if sorted(menu.group_ids.ids) == gids:
                unchanged.append(menu_xmlid)
                continue
            menu.write({'group_ids': [(6, 0, gids)]})
            changed.append('%s(%s)' % (menu_xmlid, why))
        _logger.info(
            '[edu_portal] 后台可达性收口：改写 %d 条菜单组 %s；已是目标值 %d 条；跳过 %s',
            len(changed), changed or '无', len(unchanged), skipped or '无')
        return True
