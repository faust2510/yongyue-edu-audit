# -*- coding: utf-8 -*-
"""菜单收口的加载期守卫（edu_nav）。

两层结构：
  1. **声明式主体**（data/menu_consolidation_data.xml，由 scripts/gen_menu_data.py 生成）：
     每条受影响菜单一条 <record>，只写 active / group_ids / parent_id / sequence。
     依据（本机实测 2026-09-17）：全部 605 条 ir.ui.menu 的 ir.model.data.noupdate 都是 0
     ⇒ 普通 <record> 每次 `-u` 都会重放 ⇒ 「升级后仍生效」+「幂等」天生成立。
  2. **守卫（本文件）**：把"看起来对"变成"确认对"——
     · 反查漂移：库里带 menu_state_ 前缀的菜单条数必须等于生成器写下的期望值；
       对不上说明**XML 是旧的**（计划改了没重新生成），必须报错而不是静默用旧态；
     · 反查红线：数据文件里不得出现删除类操作；
     · 装载期打印摘要进升级日志。
"""
import logging
import os

from odoo import SUPERUSER_ID, api, models

_log = logging.getLogger(__name__)

# 由 scripts/gen_menu_data.py 自动写入；守卫拿它跟库里实况比对
# 0 = 还没有生成正式数据（惰性阶段）：守卫**不**检查条数，只在日志里记为"零变化"。
# >0 = 已生成正式数据（由 scripts/gen_menu_data.py 自动写入）：守卫必须核对条数，
#      对不上说明 XML 是旧的（计划改了没重新生成）→ 报 ERROR。
#
# ⚠ **这个常量与 ir.config_parameter edu_nav.consolidated_count 必须同时改** ——
#   它们是同一份声明（生成器写下的"期望改写条数"）的两半：常量在模块代码里、参数在库里。
#   守卫 _guard() 的动作就是拿这两个值比对：只改一边 ⇒ 守卫立刻报「声明式数据漂移」
#   （真判据命中，不是噪音）。**唯一正确的改法 = 跑生成器**，它同时写三处：
#     ① 数据文件的记录与文件头计数  ② 库里的 edu_nav.consolidated_count  ③ 本常量。
#   命令（**必须带 --state=baseline**）：
#     python3 scripts/gen_menu_data.py --state=baseline
#   ⚠ 为什么不能省 --state=baseline：生成器默认只写"与库内现值不同"的字段，而收口值
#     早已落库 ⇒ 默认跑会算出 ~0 条，把整份声明式数据掏空（其 docstring 里写明了这一点）。
#   ⚠ 为什么不能直接改这个数：它是生成器**实际写出的 record 条数**（live 模式），
#     手工写一个"算出来的数"= 与数据文件脱钩，守卫下一次就会报漂移。
#   ✅ 2026-10-02 **阻断已解除**（此前这里写着「阻断项，别硬跑」，现已作废）：
#     数据文件曾引用 5 个**已卸载**模块（account_payment / hr_skills_slides / website_livechat /
#     website_slides / website_slides_forum）共 23 条 xmlid；生成器已加 `uninstalled_modules()`
#     过滤，重新生成后 353 → **330** 条，本常量与库内参数一并同步为 330。
#     实测 `bash scripts/safe_upgrade.sh edu_nav` → **EXIT=0**；反向注入 1 条陈旧引用 → 立刻 255。
#     ⚠ **但升级方式变了**：edu_nav 引用着 edu_portal 等模块的菜单 xmlid，而 Odoo 的
#     `convert.py:_test_xml_id` 只认 `state='installed'`（`to upgrade` 不算）⇒
#     **它不能与别的模块放进同一个 -u 列表**，必须由部署脚本第二趟单独跑。
#     取证：docs/audit/menu-consolidation/deploy-shipping-gap.md。
MENU_CONSOLIDATED_COUNT = 330

# 红线：数据文件里不允许出现的删除类 op 名（拼接构造，避免本文件自身命中）
BANNED_OPS = (('un', 'link'), ('del', 'ete'))


def _data_file_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, '..', 'data', 'menu_consolidation_data.xml')


def _guard(cr, registry):
    """装载后自检（只读）。任何一条不成立都报 ERROR，不留"看起来对"。"""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Menu = env['ir.ui.menu'].with_context(active_test=False)
    problems = []

    path = os.path.abspath(_data_file_path())
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as fh:
            text = fh.read()
        for parts in BANNED_OPS:
            op = parts[0] + parts[1]
            if op in text:
                problems.append('数据文件出现删除类操作 %s（违反「禁止删除菜单」红线）' % op)
    else:
        problems.append('找不到数据文件 %s' % path)

    # 漂移反查：库里带 menu_state_ 前缀的记录数 == 生成器期望值
    # 计数口径：由生成器写在 ir.config_parameter 里的**期望改写条数**。
    # 为什么不数 ir.model.data：数据文件用**目标菜单自己的规范 xmlid**（如 base.menu_administration）
    # 做记录键，这些 xmlid 仍属各自模块（base/openeducat_*/mail/…），不会留下 edu_nav 的行 ⇒
    # 数 edu_nav 的 ir.model.data 永远是 0，会让守卫"恒定报错"（第一版就是如此）。
    # 生成器：live 写实际条数、inert 写 0；守卫据此核对，口径可审计。
    got = env['ir.config_parameter'].sudo().get_param('edu_nav.consolidated_count')
    got = int(got) if got else 0
    if MENU_CONSOLIDATED_COUNT:
        if got == 0:
            problems.append('模块常量期望 %d 条收口记录，但参数声明为 0 —— '
                            '数据文件可能仍是惰性的（记录被注释）'
                            % MENU_CONSOLIDATED_COUNT)
        elif got != MENU_CONSOLIDATED_COUNT:
            problems.append(
                '声明式数据漂移：ir.config_parameter 声明 %d 条，模块常量期望 %d 条 —— '
                '很可能是计划改了但 data 文件没重新生成（跑 python3 scripts/gen_menu_data.py）'
                % (got, MENU_CONSOLIDATED_COUNT))

    roots = Menu.search([('parent_id', '=', False)])
    _log.info(
        '[edu_nav] 菜单收口守卫：声明改写 %d 条（参数表记为 %d）；'
        '根菜单 %d 条（停用 %d）；全库 %d 条（停用 %d）',
        MENU_CONSOLIDATED_COUNT, got, len(roots), len(roots.filtered(lambda m: not m.active)),
        len(Menu.search([])), len(Menu.search([('active', '=', False)])),
    )
    for p in problems:
        _log.error('[edu_nav] %s', p)
    return problems


def post_init_hook(env):
    """首装钩子。

    实测教训（本仓 2026-09-17，与 custom_addons/edu_zh/__init__.py 的批注一致）：
    `post_init_hook` **只在 install 时被调用**，`-u` 升级不会跑它
    ⇒ 依赖它做"每次升级后的守卫"会静默失效（第一次实现就是踩了这个坑：
    `-u edu_nav` 后日志里一条守卫记录都没有）。
    所以真正的每次装载守卫放在 `_register_hook`（见下），这里只是首装时先跑一次。
    """
    _guard(env.cr, env.registry)


class IrUiMenuConsolidation(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _register_hook(self):
        """每次注册表装载（含 `-u` 升级、含服务启动）都执行守卫。

        三处刻意的取舍：
          · **不判断 registry.ready / _init_modules** —— 第一次实现加了这两个条件，
            结果 `-u` 时守卫被跳过（= 静默不做自检，比不做更坏）；
          · 整段包在 try/except 里 —— 守卫是**只读自检**，绝不能把升级搞挂；
          · 异常降级为 WARNING，但**校验不通过是 ERROR**：让它显眼，但不阻塞升级。
        """
        res = super()._register_hook()
        try:
            _guard(self.env.cr, self.env.registry)
        except Exception as exc:  # noqa: BLE001 - 守卫自身不得打断升级
            _log.warning('[edu_nav] 守卫执行异常（不影响升级）：%s', exc)
        return res
