# -*- coding: utf-8 -*-
"""对接选项 a：网站公告（edu.notice）→ Telegram 群的静态单测。

用法：python3 tests/unit/tg_assist_notice_test.py（退出码 0=全通过 / 1=有失败）

为什么是静态断言而不是跑 Odoo：本仓 tests/unit 的既有惯例（见 tg_assist_file_test.py /
tg_assist_bridge_test.py）就是在不启动 Odoo 的前提下，用文本断言把「接线位置、边界、
常量」钉死；真正跑一遍的验证在本地/生产升级后的 odoo shell 探针里做（见 design §9.19）。
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSIST = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist')
PORTAL = os.path.join(ROOT, 'custom_addons', 'edu_portal')

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def strip_code(path):
    """去掉模块 docstring 与行内注释，只留真正的代码（边界断言必须只看代码）。"""
    src = read(path)
    src = re.sub(r'^\s*#.*$', '', src, flags=re.M)
    try:
        tree = ast.parse(read(path))
    except SyntaxError:
        return src
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                            ast.AsyncFunctionDef)) and ast.get_docstring(node):
            doc = ast.get_docstring(node)
            src = src.replace(doc, '', 1)
    return src


chat_py = read(os.path.join(ASSIST, 'models', 'chat.py'))
bridge_py = read(os.path.join(ASSIST, 'models', 'bridge.py'))
bridge_code = strip_code(os.path.join(ASSIST, 'models', 'bridge.py'))
notice_py = read(os.path.join(PORTAL, 'models', 'notice.py'))
notice_code = strip_code(os.path.join(PORTAL, 'models', 'notice.py'))
views = read(os.path.join(ASSIST, 'views', 'assist_views.xml'))
assist_manifest = read(os.path.join(ASSIST, '__manifest__.py'))
portal_manifest = read(os.path.join(PORTAL, '__manifest__.py'))

# ---- 1. 群上多了一个开关 ----
check('chat 模型有 notice_enabled 字段',
      "notice_enabled = fields.Boolean" in chat_py)
check('notice_enabled 默认关闭',
      ("'接收网站公告', default=False" in chat_py
       or "'接收网站公告', default=False," in chat_py))
_chat_field = chat_py.split('notice_enabled = fields.Boolean', 1)[-1][:220]
check('notice_enabled 有索引（公告推送按它筛群）', 'index=True' in _chat_field)
check('列表视图显示 notice_enabled', '<field name="notice_enabled"/>' in views)
check('表单视图显示 notice_enabled',
      views.count('<field name="notice_enabled"/>') == 2)

# ---- 2. 出网口在班务助手里 ----
check('bridge 定义 NOTICE_KIND', "NOTICE_KIND = 'notice'" in bridge_py)
check('bridge 定义 NOTICE_MAX', 'NOTICE_MAX =' in bridge_py)
check('bridge 有 push_site_notice 方法', 'def push_site_notice(self, notice)' in bridge_py)
check('bridge 有 notice_targets 方法', 'def notice_targets(self)' in bridge_py)
check('只发给勾了「接收网站公告」的启用群',
      "('notice_enabled', '=', True)" in bridge_code
      and "('active', '=', True)" in bridge_code
      and "('chat_id', '!=', False)" in bridge_code)
check('公告走统一的 api.send_message（自动记 send_log）',
      'api.send_message(chat.chat_id, text, kind=NOTICE_KIND)' in bridge_code)
check('返回值是 (sent, failed)', 'return sent, failed' in bridge_code)
check('单群失败不抛异常（有 try/except + continue）',
      'except Exception:' in bridge_code and 'continue' in bridge_code)
check('公告正文带【公告】前缀', "'【公告】%s\\n%s'" in bridge_code)
check('公告标题/正文用 getattr 读，不写死 edu.notice 模型',
      "getattr(notice, 'name'" in bridge_code and "getattr(notice, 'content'" in bridge_code)
check('推送只发文字，不碰文件与 chat_id 拼串', 'send_document' not in bridge_code)

# ---- 3. B9/B2 边界：班务助手仍不碰诺亚与学生匿名表 ----
_notice_code = bridge_code.split('NOTICE_KIND', 1)[-1]
for bad in ('edu_telegram', 'edu.feedback', 'edu.tg.claim', 'edu.invite'):
    check('公告通道代码不出现 %s' % bad, bad not in _notice_code)
_depends = ast.literal_eval(ast.parse(assist_manifest).body[0].value)['depends']
check('班务助手 depends 仍只有 base', _depends == ['base'], str(_depends))

# ---- 4. 门户这一侧：只按模型名探在不在，不写依赖 ----
check('门户公告电报分支先探 edu.tg.assist.bridge',
      "'edu.tg.assist.bridge' in self.env" in notice_code)
check('门户调用 push_site_notice(self)', 'push_site_notice(self)' in notice_code)
check('门户保留旧路（op.telegram.chat）作回退',
      "self.env['op.telegram.chat']" in notice_code)
check('门户调用被 try/except 包住（出网失败不拖垮发布）',
      notice_code.count('except Exception:') >= 2)
check('门户没有 import edu_tg_assist',
      'edu_tg_assist' not in notice_code)
check('门户 manifest 不依赖 edu_tg_assist',
      'edu_tg_assist' not in portal_manifest.split('data')[0])
check('门户电报字段 help 指向「接收网站公告」',
      '接收网站公告' in notice_py)

# ---- 5. 静态解析 ----
for path in (os.path.join(ASSIST, 'models', 'bridge.py'),
             os.path.join(ASSIST, 'models', 'chat.py'),
             os.path.join(PORTAL, 'models', 'notice.py')):
    try:
        ast.parse(read(path))
        ok, detail = True, ''
    except SyntaxError as exc:
        ok, detail = False, str(exc)
    check('语法可解析：%s' % os.path.basename(path), ok, detail)

failed = 0
for name, ok, detail in results:
    if not ok:
        failed += 1
        print('FAIL %s%s' % (name, (' — ' + detail) if detail else ''))
print('tg_assist_notice_test: %s/%s 通过' % (len(results) - failed, len(results)))
sys.exit(1 if failed else 0)
