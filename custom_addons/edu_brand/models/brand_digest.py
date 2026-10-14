# -*- coding: utf-8 -*-
"""每周摘要（digest）的去品牌化 —— **容错版**（2026-10-04 第 66 轮）。

## 为什么要有这个文件

原先这些是写在 `data_brand/brand_debrand_data.xml` 里的 38 条 `<function>`（去重后 19 组「记录×字段」），
形如：

```xml
<function model="digest.tip" name="write" context="{'lang': 'zh_CN'}"
          eval="[[ref('digest.digest_tip_digest_0')], {'tip_description': ''}]"/>
```

这种写法在**全新库**上有两个会让整个安装中断的毛病（本机 `edu19_fresh` 实测）：

① **`ref()` 解析不到就抛异常** —— 而这 19 组引用的 xmlid 横跨 **6 个模块**
   （`digest` / `account` / `base_automation` / `hr` / `website` / `im_livechat`），
   而 `edu_brand` 的 `depends` 只声明了 3 个 ⇒ 新库上没装的模块，它的 xmlid 就是不存在；
② **`context={'lang': 'zh_CN'}` 写翻译字段时，Odoo 19 只接受 active 语言**
   （原文件上方本来就为 `zh_TW` 记过这条，2026-10-01 重建生产事故）
   ⇒ 新库里 `zh_CN` 尚未启用时同样抛异常。

实测（可原样复跑）：

```
create database edu19_fresh;
odoo -d edu19_fresh --without-demo=all -i edu_life --stop-after-init
  → ParseError: while parsing .../brand_debrand_data.xml:65
```

克隆库上看不出来，只因为生产早就装过那些模块、语言也都启用了；
**而换新服务器 / 重建库时必然踩到**（本项目已经丢过一次生产库）。

## 本方法的纪律

缺记录 ⇒ 跳过并记日志；只写**已启用**的语言；任何一条失败都不影响安装。
与 `edu_portal` 的 `edu_apply_menu_label_renames` / `_edu_apply_menu_retirements` 同一套写法。
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# (xmlid, 字段, 目标值)：由原 XML 的 <function> 逐条提取，去重后 19 组。
# 字段名即可判断模型：name → digest.digest；tip_description → digest.tip。
_BRANDING = [
    ('digest.digest_digest_default', 'name', '系统状态摘要'),
    ('digest.digest_tip_digest_0', 'tip_description', ''),
    ('digest.digest_tip_digest_1', 'tip_description', ''),
    ('digest.digest_tip_digest_2', 'name', '系统状态摘要'),
    ('digest.digest_tip_digest_2', 'tip_description', ''),
    ('digest.digest_tip_digest_3', 'tip_description', ''),
    ('digest.digest_tip_digest_4', 'tip_description', ''),
    ('digest.digest_tip_digest_5', 'tip_description', ''),
    ('digest.digest_tip_digest_6', 'tip_description', ''),
    ('account.digest_tip_account_0', 'tip_description', ''),
    ('account.digest_tip_account_1', 'tip_description', ''),
    ('base_automation.digest_tip_base_automation_0', 'tip_description', ''),
    ('hr.digest_tip_hr_0', 'tip_description', ''),
    ('website.digest_tip_website_0', 'tip_description', ''),
    ('website.digest_tip_website_1', 'tip_description', ''),
    ('website.digest_tip_website_2', 'tip_description', ''),
    ('website.digest_tip_website_3', 'tip_description', ''),
    ('website.digest_tip_website_4', 'tip_description', ''),
    ('im_livechat.digest_tip_im_livechat_0', 'tip_description', ''),
]


class DigestDigest(models.Model):
    _inherit = 'digest.digest'

    @api.model
    def _edu_brand_apply_digest_branding(self):
        """容错地给 digest 自带的文案去品牌化。幂等；缺记录/缺语言一律跳过。"""
        env = self.env
        langs = [c for c in env['res.lang'].search([]).mapped('code') if c]
        done = skipped = 0
        for xmlid, field, value in _BRANDING:
            rec = env.ref(xmlid, raise_if_not_found=False)
            if not rec:
                skipped += 1
                continue
            for code in langs:
                try:
                    rec.with_context(lang=code).write({field: value})
                    done += 1
                except Exception as e:
                    skipped += 1
                    _logger.info('edu_brand: 摘要去品牌化跳过 %s[%s,%s]: %s',
                                 xmlid, field, code, str(e)[:120])
        _logger.info('edu_brand: 摘要去品牌化完成：写入 %d 次、跳过 %d 次', done, skipped)
        return True