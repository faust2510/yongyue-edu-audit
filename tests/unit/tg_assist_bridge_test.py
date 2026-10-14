# -*- coding: utf-8 -*-
"""edu_tg_assist「站内通知桥」（对接选项 b）的静态回归用例（**不需要数据库、不需要 Odoo**）。

为什么要有它（用户 2026-10-13 问「能不能把机器人的功能和教务网站对接上」，2026-10-14「继续干吧」）：
  · 网站的通知引擎是门户的 edu.message（edu_portal），桥**只读**它、按 id 水位轮询 ⇒
    本模块仍然零依赖（manifest depends 只有 base），不挂钩子、不改对方一行代码；
  · B9：绝不读 edu.feedback / edu_telegram / edu.tg.claim / edu.tg.bot / edu.invite ⇒
    禁读清单必须在，而且 cron 每轮开头 fail-closed 检查；
  · 水位只前进、桥接记录 unique(rule_id, message_id) ⇒ 同一条站内信绝不会转两次；
  · 收件人对不上网站账号就跳过并留痕，绝不猜人。

用法：python3 tests/unit/tg_assist_bridge_test.py   （退出码 0=全通过 / 1=有失败）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADDON = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist')
BRIDGE = os.path.join(ADDON, 'models', 'bridge.py')
PERSON = os.path.join(ADDON, 'models', 'person.py')
INIT = os.path.join(ADDON, 'models', '__init__.py')
MANIFEST = os.path.join(ADDON, '__manifest__.py')
CRON = os.path.join(ADDON, 'data', 'ir_cron_data.xml')
VIEW = os.path.join(ADDON, 'views', 'assist_bridge_views.xml')
PERSON_VIEW = os.path.join(ADDON, 'views', 'assist_views.xml')
ACL = os.path.join(ADDON, 'security', 'ir.model.access.csv')
DESIGN = os.path.join(ROOT, 'docs', 'plans', 'tg-assist-bot-design.md')
CODEMAP = os.path.join(ROOT, 'docs', 'code-map.md')
HOWTO = os.path.join(ROOT, 'docs', 'ops', 'tg-assist-bot-howto.md')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


BRIDGE_SRC = _read(BRIDGE)
PERSON_SRC = _read(PERSON)
INIT_SRC = _read(INIT)
MANIFEST_SRC = _read(MANIFEST)
CRON_SRC = _read(CRON)
VIEW_SRC = _read(VIEW)
PERSON_VIEW_SRC = _read(PERSON_VIEW)
ACL_SRC = _read(ACL)
DESIGN_SRC = _read(DESIGN)
CODEMAP_SRC = _read(CODEMAP)
HOWTO_SRC = _read(HOWTO)

results = []


def check(name, cond, detail=''):
    results.append((bool(cond), name, detail))


def body_only(src):
    """去掉 docstring 与行内注释：边界断言只看真实代码。"""
    src = re.sub(r'"""(?:.|\n)*?"""', '', src)
    src = re.sub(r'^\s*#.*$', '', src, flags=re.M)
    return src


# ---------- 源表与水位 ----------

check('源表就是 edu.message', "SOURCE_MODEL = 'edu.message'" in BRIDGE_SRC)
check('一次最多处理 BATCH=50', 'BATCH = 50' in BRIDGE_SRC)
check('单条正文上限 BODY_MAX=1500', 'BODY_MAX = 1500' in BRIDGE_SRC)
check('源表探活不靠 depends：先看模型在不在',
      'if SOURCE_MODEL not in self.env:' in BRIDGE_SRC)
check('源表探活第二探：真能 select 才算就绪',
      'search_count([(\'id\', \'=\', 0)])' in BRIDGE_SRC)
check('水位只取 id 更大的新记录', "domain = [('id', '>', self.last_message_id or 0)]" in BRIDGE_SRC)
check('水位推进写 max(msgs.ids)', "'last_message_id': max(msgs.ids)," in BRIDGE_SRC)
check('查源记录带 order=id 且 limit=BATCH',
      "order='id'" in BRIDGE_SRC and 'limit=BATCH' in BRIDGE_SRC)
check('新规则不回放历史（create 里推水位）',
      "vals['last_message_id'] = self._source_max_id()" in BRIDGE_SRC)
check('重新启用也不回放历史（write 里推水位）',
      'rec.last_message_id = self._source_max_id()' in BRIDGE_SRC)

# ---------- B9 禁读清单 ----------

for bad in ('edu.feedback', 'edu.telegram', 'edu.tg.claim', 'edu.tg.bot', 'edu.invite'):
    check('B9 禁读清单含 %s' % bad, ("'%s'" % bad) in BRIDGE_SRC)
check('B9 是前缀匹配而不是全等', 'for bad in DENY_MODELS:' in BRIDGE_SRC
      and 'startswith' in BRIDGE_SRC)
check('cron 每轮开头 fail-closed 检查禁读清单',
      re.search(r'def _cron_bridge.*?_check_source_allowed\(SOURCE_MODEL\)', BRIDGE_SRC,
                re.S) is not None)
check('命中禁读清单时一条都不发（提前 return 0）',
      re.search(r'命中禁读清单，已停发.*?return 0', BRIDGE_SRC, re.S) is not None)
check('真实代码里没有直接访问禁读模型',
      re.search(r"env\[['\"]edu\.(feedback|telegram|tg\.claim|tg\.bot|invite)", body_only(BRIDGE_SRC)) is None)

# ---------- 目标与文案 ----------

check('四个目标：收件人本人/某人/某群/管理员',
      all(("'%s'" % t) in BRIDGE_SRC for t in ('recipient', 'person', 'group', 'owner')))
check('管理员目标读 edu_tg_assist.owner_user_id',
      "OWNER_PARAM = 'edu_tg_assist.owner_user_id'" in BRIDGE_SRC)
check('收件人靠人员映射的网站账号找（person.user_id）',
      "user_id', '=', message.recipient_id.id" in BRIDGE_SRC)
_target_src = BRIDGE_SRC.split('def _target_chat')[1].split('def _render')[0]
check('收件人对不上网站账号时跳过并给原因（不猜人）',
      "if not person or not person.chat_id:" in _target_src
      and '还没把网站账号接到人员映射上' in _target_src)
check('四个目标每个都校验过 chat_id 才发',
      _target_src.count("return '', '") >= 4)
check('渲染有前缀+正文，且有兜底文案',
      "def _render" in BRIDGE_SRC and '（站内信没有正文）' in BRIDGE_SRC)

# ---------- 出网与留痕 ----------

check('出网走本模块 api.send_message，kind=bridge',
      "send_message(" in BRIDGE_SRC and "kind='bridge'" in BRIDGE_SRC)
check('桥不自己发 HTTP（不 import requests）', 'import requests' not in BRIDGE_SRC)
check('桥接记录表有 rule_id / message_id / ok / error',
      all(k in BRIDGE_SRC for k in ("rule_id = fields.Many2one", "message_id = fields.Integer",
                                    "ok = fields.Boolean", "error = fields.Char")))
check('同一条站内信对同一条规则只转一次（唯一约束）',
      'unique(rule_id, message_id)' in BRIDGE_SRC)
check('记录函数永不抛异常（吞掉唯一约束冲突）',
      re.search(r'def _log.*?except', BRIDGE_SRC, re.S) is not None)

# ---------- 模型名与视图 ----------

check('两个模型名固定', "_name = 'edu.tg.assist.bridge'" in BRIDGE_SRC
      and "_name = 'edu.tg.assist.bridge_log'" in BRIDGE_SRC)
check('bridge 是普通模型（不是瞬态）', 'TransientModel' not in BRIDGE_SRC)
check('models/__init__.py 已导入 bridge',
      re.search(r'^from \. import bridge', INIT_SRC, re.M) is not None)
check('manifest 的 data 里有新视图文件', "'views/assist_bridge_views.xml'," in MANIFEST_SRC)
check('视图排在 assist_bindcode_views.xml 之后',
      MANIFEST_SRC.index("'views/assist_bindcode_views.xml'")
      < MANIFEST_SRC.index("'views/assist_bridge_views.xml'"))
_dep = re.search(r"'depends':\s*\[(.*?)\]", MANIFEST_SRC, re.S)
_dep_code = re.sub(r'#.*', '', _dep.group(1)) if _dep else ''
check('manifest 的 depends 里只有 base',
      _dep is not None and "'base'" in _dep_code and 'edu_portal' not in _dep_code
      and 'edu_telegram' not in _dep_code)

check('cron 记录存在且指向 bridge 模型',
      'id="cron_bridge_edu_message"' in CRON_SRC
      and 'ref="model_edu_tg_assist_bridge"' in CRON_SRC)
check('cron 调 model._cron_bridge()', 'model._cron_bridge()' in CRON_SRC)
check('cron 每 2 分钟一次且默认开',
      '<field name="interval_number">2</field>' in CRON_SRC
      and '<field name="interval_type">minutes</field>' in CRON_SRC
      and CRON_SRC.count('active" eval="True"') >= 1)

check('视图有两个菜单：站内通知桥 / 桥接记录',
      'menu_assist_bridge"' in VIEW_SRC and 'menu_assist_bridge_log"' in VIEW_SRC)
check('菜单挂在 menu_assist_root 下', VIEW_SRC.count('parent="menu_assist_root"') == 2)
check('规则表单有测试发送与跳过现有消息两个按钮',
      'name="action_test_send"' in VIEW_SRC and 'name="action_adopt_watermark"' in VIEW_SRC)
check('规则表单字段齐全',
      all(('name="%s"' % f) in VIEW_SRC for f in
          ('name', 'event_key', 'target', 'person_id', 'chat_id', 'prefix',
           'include_body', 'last_message_id', 'active')))
check('两个 act_window 都在', VIEW_SRC.count('model="ir.actions.act_window"') == 2)
check('桥接记录视图只读列表',
      'view_assist_bridge_log_list' in VIEW_SRC
      and re.search(r'view_assist_bridge_log_list.*?</list>', VIEW_SRC, re.S).group(0).count('<field') >= 6)

check('人员映射表单加了「网站账号」', 'name="user_id"' in PERSON_VIEW_SRC)
check('person.user_id 指向 res.users 且删除时置空',
      "fields.Many2one('res.users', '网站账号'" in PERSON_SRC and "ondelete='set null'" in PERSON_SRC)
check('person.user_id 有索引（桥按它查人）',
      re.search(r"user_id = fields\.Many2one\([^)]*index=True", PERSON_SRC, re.S) is not None)

check('ACL 给 bridge 管理组 1,1,1,1',
      re.search(r'access_assist_bridge_manager,.*group_assist_manager,1,1,1,1', ACL_SRC) is not None)
check('ACL 给 bridge_log 管理组只读',
      re.search(r'access_assist_bridge_log_manager,.*group_assist_manager,1,0,0,0', ACL_SRC) is not None)

# ---------- 文档 ----------

check('设计文档有 §9.18', '## 9.18 站内通知桥' in DESIGN_SRC)
check('设计文档写明 B9/B10', 'B9' in DESIGN_SRC and 'B10' in DESIGN_SRC)
check('设计文档写明「不挂钩子」的理由', '不挂钩子' in DESIGN_SRC)
check('code-map 记了站内通知桥', '站内通知桥（对接选项 b' in CODEMAP_SRC)
check('howto 有大白话一节', '网站的通知也能转到 Telegram' in HOWTO_SRC)

failed = [r for r in results if not r[0]]
for ok, name, detail in results:
    if not ok:
        print('FAIL %s %s' % (name, detail))
print('== %d/%d 通过 ==' % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
