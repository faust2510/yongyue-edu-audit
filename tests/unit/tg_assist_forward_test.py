# -*- coding: utf-8 -*-
"""edu_tg_assist「一键转发材料」（选项 c）的静态回归用例（**不需要数据库、不需要 Odoo**）。

为什么要有它（用户 2026-10-13 的原话）：
  · 「在后台『材料归档』里点一下，把某份材料直接转给某人或某个群」——所以后台必须有入口，
    而且只能选中**本模块登记过**的目标（群有 chat_id、人有 chat_id），绝不让人手抄数字、绝不猜；
  · 「文件用 Telegram 的 file_id 转，不用重传」——所以发文件必须走 sendDocument + file_id，
    不能先下载到本库再上传（那会多一次出网、多一份落盘，还撞 20 MB 的 getFile 上限）；
  · 「全部在班务模块内，不碰任何边界」——所以本文件逐字断言没有引用 edu.feedback /
    edu_telegram / edu.tg.claim；
  · 出网必须留痕：send_document 与 send_message 一样无条件进 edu.tg.assist.send_log。

用法：python3 tests/unit/tg_assist_forward_test.py   （退出码 0=全通过 / 1=有失败）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist', 'models')
API = os.path.join(MODELS, 'api.py')
FORWARD = os.path.join(MODELS, 'forward.py')
MATERIAL = os.path.join(MODELS, 'material.py')
INIT = os.path.join(MODELS, '__init__.py')
VIEW = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist', 'views',
                    'assist_material_views.xml')
ACL = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist', 'security',
                   'ir.model.access.csv')

with open(API, encoding='utf-8') as fh:
    API_SRC = fh.read()
with open(FORWARD, encoding='utf-8') as fh:
    FWD_SRC = fh.read()
with open(MATERIAL, encoding='utf-8') as fh:
    MAT_SRC = fh.read()
with open(INIT, encoding='utf-8') as fh:
    INIT_SRC = fh.read()
with open(VIEW, encoding='utf-8') as fh:
    VIEW_SRC = fh.read()
with open(ACL, encoding='utf-8') as fh:
    ACL_SRC = fh.read()

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


def body(src, name):
    """取某个方法的方法体（到下一个 def/@api.model 为止）。"""
    hit = re.search(r'\n    def %s\(' % re.escape(name), src)
    if not hit:
        return ''
    rest = src[hit.end():]
    stop = re.search(r'\n    (?:@api\.model|def )', rest)
    return rest[:stop.start()] if stop else rest


# ---- 1) api.send_document：file_id 直发、不重传 ----
doc = body(API_SRC, 'send_document')
check('api.send_document 存在', bool(doc))
check('走官方 sendDocument', "call('sendDocument'" in doc)
check('document 参数吃 file_id', "'document': file_id" in doc)
check('chat_id 转成字符串', "'chat_id': str(chat_id)" in doc)
check('dry_run 不出网且记日志', '_dry_run()' in doc and 'DRY_RUN（未出网）' in doc)
check('出网后无条件记 send_log',
      "send_log'].sudo().log(" in doc and "ok, err" in doc)
check('失败只回报不抛异常', 'raise ' not in doc)
check('caption 有上限常量', 'CAPTION_LIMIT = 1024' in API_SRC)
check('caption 超长按上限截断', '[:CAPTION_LIMIT]' in doc)
check('空 caption 不加该键（逐字节可控）', "if text:" in doc and "payload['caption'] = text" in doc)

# ---- 2) forward 模型：瞬态、必填、两个目标 ----
check('模型名正确', "_name = 'edu.tg.assist.forward'" in FWD_SRC)
check('是瞬态模型（不立新表）', 'models.TransientModel' in FWD_SRC)
check('中文 _description', re.search(r"_description = '[^']*[\u4e00-\u9fff][^']*'", FWD_SRC) is not None)
check('material_id 必填', re.search(r"material_id = fields\.Many2one\([\s\S]{0,120}required=True", FWD_SRC) is not None)
check('可发群 / 可发人', "'group'" in FWD_SRC and "'person'" in FWD_SRC
      and "_name = 'edu.tg.assist.forward'" in FWD_SRC)
check('群取本模块 chat 表',
      "fields.Many2one(\n        'edu.tg.assist.chat'" in FWD_SRC)
check('人取本模块 person 表',
      "fields.Many2one(\n        'edu.tg.assist.person'" in FWD_SRC)
check('chat_id 直接取记录里的值（不让人手抄）',
      "self.chat_id.chat_id" in FWD_SRC and "self.person_id.chat_id" in FWD_SRC)
check('目标缺失就报错，不猜一个发出去',
      FWD_SRC.count('raise UserError(') >= 4)
check('没有私聊会话的人明确拒发',
      '这个人还没跟机器人说过话' in FWD_SRC and '发不出去' in FWD_SRC)

# ---- 3) 发送路径：文件走 file_id、文本走消息，都写 kind ----
send = body(FWD_SRC, 'action_send')
check('action_send 存在', bool(send))
check('有 file_id 走 send_document', 'send_document(' in send and 'rec.file_id' in send)
check('没有文件就发文本', 'send_message(' in send)
check('两条路径都不重传/不下载',
      'requests' not in FWD_SRC and '_fetch_file' not in FWD_SRC
      and 'file_data' not in FWD_SRC)
check('kind 统一为 material_forward', "'material_forward'" in send)
check('失败给操作的人看原因', "raise UserError('没发出去" in send)
check('成功回 display_notification', 'display_notification' in send)
check('转发会关闭弹窗', "'next': {'type': 'ir.actions.act_window_close'}" in send)

# ---- 4) caption 组装：附言 + 标题 + 分类/紧急度 + 摘要，且有上限 ----
cap = body(FWD_SRC, '_caption')
check('_caption 存在', bool(cap))
check('附言在最前面', 'self.note' in cap)
check('带材料标题', 'rec.name' in cap)
check('带分类与紧急度（复用模型自己的 selection）',
      "_selection_label('category')" in cap and "_selection_label('urgency')" in cap)
check('带摘要', 'rec.summary' in cap)
check('caption 上限不超过官方 1024', 'CAPTION_MAX = 900' in FWD_SRC)
check('按上限截断后再发', '[:CAPTION_MAX]' in cap)

# ---- 5) 边界：不碰别人的表/参数（B1/B2/B5） ----
def code_only(src):
    """剥掉模块 docstring 与行内注释 —— 边界名字只允许出现在「我不碰它」的说明里。"""
    hit = re.search(r'"""[\s\S]*?"""', src)
    if hit:
        src = src[:hit.start()] + src[hit.end():]
    lines = []
    for line in src.splitlines():
        cut = line.find('#')
        lines.append(line if cut < 0 else line[:cut])
    return '\n'.join(lines)


FWD_CODE = code_only(FWD_SRC)
for forbidden in ('edu.feedback', 'edu_telegram', 'edu.tg.claim', 'outbox', 'claim_for_chat'):
    check('forward.py 代码里不碰 %s' % forbidden, forbidden not in FWD_CODE)

# ---- 6) 后台入口 ----
mat = body(MAT_SRC, 'action_open_forward')
check('material.action_open_forward 存在', bool(mat))
check('打开的是转发弹窗',
      "'res_model': 'edu.tg.assist.forward'" in mat
      and "'target': 'new'" in mat)
check('带上当前材料', "'default_material_id': self.id" in mat)
check('视图有「📤 转发给…」按钮',
      'name="action_open_forward"' in VIEW_SRC and '📤 转发给…' in VIEW_SRC)
check('有转发表单视图',
      'view_assist_forward_form' in VIEW_SRC
      and 'edu.tg.assist.forward' in VIEW_SRC)
check('表单里有发送按钮', 'name="action_send"' in VIEW_SRC)
check('按目标类型切换群/人',
      "target_kind != 'group'" in VIEW_SRC
      and "target_kind != 'person'" in VIEW_SRC)

# ---- 7) 权限：新瞬态模型必须给管理组 ACL ----
check('__init__ 已注册 forward', 'from . import forward' in INIT_SRC)
check('管理组有 forward 的 ACL',
      'model_edu_tg_assist_forward,edu_tg_assist.group_assist_manager,1,1,1,1' in ACL_SRC)
check('系统管理员也有 forward 的 ACL',
      'model_edu_tg_assist_forward,base.group_system,1,1,1,1' in ACL_SRC)

failed = [n for n, ok, _ in results if not ok]
for name, ok, detail in results:
    print(('PASS  ' if ok else 'FAIL  ') + name + (('  << ' + detail) if detail and not ok else ''))
print('----')
print('%s/%s 通过' % (len(results) - len(failed), len(results)))
if failed:
    print('失败：' + '; '.join(failed))
sys.exit(1 if failed else 0)
