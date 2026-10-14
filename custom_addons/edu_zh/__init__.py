# -*- coding: utf-8 -*-
"""edu_zh：只做译文覆盖，不定义任何模型。

Odoo 19 的翻译加载路径（源码取证）：
  odoo/modules/loading.py:232
      overwrite = tools.config["overwrite_existing_translations"]
      module._update_translations(overwrite=overwrite)
  odoo/addons/base/models/ir_module.py:880 _update_translations
      -> mod_names = topological_sort({mod: mod.dependencies_id})
      -> _load_module_terms(mod_names, langs, overwrite)
  odoo/addons/base/models/ir_module.py:971 _load_module_terms
      -> get_po_paths(module, lang) 取 i18n/ 与 i18n_extra/ 下的 <lang>.po
      -> TranslationImporter(...).load_file(...).save(overwrite=overwrite)

两条结论决定了本模块的写法：
1) 「-u」会按 --i18n-overwrite 决定 overwrite，所以升级时必须带该开关，
   否则数据库里已有的机翻值优先，覆盖不生效。
2) post_init_hook **只在 install 时被调用**（loading.py:241 是
   'if update_operation == "install"'），升级时不会跑；它只是首次
   安装的兜底。
"""
import logging

_logger = logging.getLogger(__name__)

# 本模块提供译文的语言；不在 res.lang 或未激活的语言会被 load_file 跳过。
LANGS = ('zh_CN', 'zh_TW')


def post_init_hook(env):
    """首次安装时用 overwrite=True 灌一次译文（升级走 --i18n-overwrite）。"""
    langs = env['res.lang'].sudo().search([
        ('code', 'in', list(LANGS)),
        ('active', '=', True),
    ]).mapped('code')
    if not langs:
        _logger.info(
            'edu_zh: 未启用 %s，跳过译文覆盖', ' / '.join(LANGS))
        return
    # 只加载 edu_zh 自己，不把依赖闭包一起灌，避免误覆盖 base 等模块译文。
    env['ir.module.module'].sudo()._load_module_terms(
        ['edu_zh'], langs, overwrite=True)
    _logger.info('edu_zh: 已用 overwrite=True 载入 %s 术语覆盖', ', '.join(langs))
