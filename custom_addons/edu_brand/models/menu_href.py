# -*- coding: utf-8 -*-
"""菜单动作引用 -> 门户可点的 href（唯一实现）。

动因（用户实测缺陷）
--------------------
门户里的入口点下去会**先整屏闪一遍 Odoo 后台外壳**（蓝顶栏 + 空白 + 「正在加载」），
再由 webclient 的 JS 执行 window.location 跳到门户页。根因不是加载慢，而是
ir.actions.act_url **天然要先启动后台 webclient 才能执行跳转**；只要门户卡片把
act_url 写成后台深链 /odoo/action-<id>，这一闪就必然发生。

口径（一条规则，三处调用点共用）
--------------------------------
· 动作是 ir.actions.act_url 且 url 非空 -> **直接返回它的 url**（门户卡片 href 直达；
  url 可以是站内门户路由，也可以是外部站如 https://apps.odoo.com/...）。
· 其余动作类型（act_window / act_client / server action...）-> 原样 /odoo/action-<id>
  —— 它们本来就是后台界面，绕后台是预期行为。
· act_url 但 url 为空 -> 同样退回 /odoo/action-<id>（**不产出空 href 把用户点空**）；
  动作引用里解析不出 id -> '/odoo/action-'，与 core 原表达式逐字一致（见下）。

入参契约
--------
两种形态都真实存在，且规则完全相同：core 口径的 'model,id' 字符串（roles.py /
search.py 显式拼；website.layout 的 menu['action'] 也是字符串），以及
ir.ui.menu.action 这类 **ORM 记录对象**。非字符串入参先由 _action_ref_str()
规范成 'model,id' 再走上面三条规则 —— 2026-09-28 之前只接受字符串，记录对象
直接抛 AttributeError: 'ir.actions.act_url' object has no attribute
'rpartition'（本机已复现）；那件事若发生在模板里就是整页 500。

调用点
------
1. custom_addons/edu_portal/controllers/roles.py::_menu_href —— /apps 应用面板卡片
2. custom_addons/edu_portal/controllers/search.py —— 全站搜索的「邀请码」分组
3. custom_addons/edu_brand/views/odoo_debrand.xml —— core website.layout 浮动
   「转到您的应用」下拉里的入口（core 自己拼 /odoo/action-...，不看动作类型）

为什么放在 edu_brand：③ 必须由 edu_brand 修（它不依赖 edu_portal），而 ①② 所在的
edu_portal **依赖 edu_brand** ⇒ 这是唯一能同时被控制器与视图调用的落点（同
docs/code-map.md §6 第 13 条「身份反查只有一条口径」的选址理由）。
"""

from odoo import api, models

_ACT_URL = 'ir.actions.act_url'


def _action_ref_str(action_ref):
    """把 edu_action_href 的入参规范成 core 口径的 'model,id' 字符串。

    **为什么必须有这一步**：ir.ui.menu.action 是 Reference 列，`menu.action`
    经 ORM 读出来是**记录对象**（`ir.actions.act_url(755,)`）；而 core 的
    website.layout 传进模板的是自己拼好的字符串（website/models/ir_ui_menu.py
    的 force_action 分支写的正是 f"{actionModel},{actionID}"，core 模板对它调
    .split(',')）。两种形态都真实存在 ⇒ 入口先统一，后面只认字符串。
    少了这一步，记录对象直接进 rpartition(',') 会抛

        AttributeError: 'ir.actions.act_url' object has no attribute
        'rpartition'   （2026-09-28 本机复现）

    —— 若这件事发生在 QWeb 模板里，就是**整页 500**。

    规范只读**内存值** `_name` / `ids`（不读字段、不查库、不触发 exists）：
    已删除动作的悬空引用也照旧能走到调用处的 exists() 判定，
    不会在这里先炸「Record does not exist」，既有行为因此逐字不变。

    · 字符串      -> 原样返回（既有契约，一个字符都不动）；
    · 单条记录集  -> '<_name>,<id>'（与 core force_action 的格式逐字同构）；
    · 其余（空记录集 / 多条（有歧义）/ 无 _name 的对象 / 非字符串标量）
                  -> ''，由调用处退回 '/odoo/action-'，与 core 对空动作的产物
                     逐字一致 —— 不猜、也不在模板里抛异常把整页打 500。
    """
    if isinstance(action_ref, str):
        return action_ref
    name = getattr(action_ref, '_name', None)
    ids = getattr(action_ref, 'ids', None)
    if name and isinstance(ids, (list, tuple)) and len(ids) == 1:
        return '%s,%s' % (name, ids[0])
    return ''


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def edu_action_href(self, action_ref):
        """动作引用 -> 门户可点的 href 字符串。

        入参两种形态都接受、规则完全相同（见 _action_ref_str）：
        · core 口径的字符串 'ir.actions.act_url,755'（roles.py / search.py 显式
          拼；website.layout 的 menu['action'] 也是字符串 —— 容器根菜单会被
          website 的 force_action 换成其子孙里第一个动作，同样是字符串）；
        · ir.ui.menu.action 这种 **ORM 记录对象**（任何地方读 `menu.action`
          拿到的都是它）。非字符串入参先规范成 'model,id' 再走下面原逻辑。"""
        # 非字符串（记录对象）在这里就被规范成 'model,id'，**不进入下游**：
        # 少了这一步，一次模板调用就是整页 500（AttributeError: rpartition）。
        ref = _action_ref_str(action_ref) or ''
        model_name, _sep, act_id = ref.rpartition(',')
        if model_name == _ACT_URL and act_id.isdigit():
            # ⚠ 必须先 exists() 再读 .url：菜单的 Reference 列可能指向**已被删除**的动作
            # （browse() 本身不报错，**读字段才抛** Record does not exist —— 实测
            #  call_kw ir.ui.menu.edu_action_href('ir.actions.act_url,999999')
            #  → Record does not exist ... ir.actions.act_url(999999,)）。
            # 少这一下，一条悬空引用会让**整页 500**；而 core 原表达式（只拼 id、不读库）
            # 在那种情况下照常渲染 —— 那才是真把既有行为改坏。
            act = self.env[_ACT_URL].sudo().browse(int(act_id))
            if act.exists():
                url = act.url or ''
                if url:
                    return url
        # 其余情况**保持原行为**，一个字符都不改：
        #   · 非 act_url 的动作 -> '/odoo/action-<id>'（它们本来就是后台界面）；
        #   · act_url 但 url 为空 -> 同样退回 '/odoo/action-<id>'（不产出空 href）；
        #   · 引用里解析不出 id（根菜单整棵子树都没有动作）-> '/odoo/action-'，
        #     与 core website.layout 那行表达式的产物**逐字一致**（core 渲染的就是这个）。
        return '/odoo/action-%s' % (act_id if act_id.isdigit() else '')
