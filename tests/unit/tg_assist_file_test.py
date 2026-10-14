# -*- coding: utf-8 -*-
"""edu_tg_assist 文件取回（material.py）的静态回归用例（**不需要数据库、不需要 Odoo**）。

为什么要有它（用户 2026-10-13 的原话：「这个机器人能收文件吗？然后再提供给教务
sarah老师下载。」）：
  · 「能收」的判据不是钩子里下载，而是**钩子不出网、本体事后取**：webhook 一超时
    Telegram 就重投，同一条材料会重复归档。所以逐字断言 webhook 路径里没有下载；
  · 取回必须有上限，否则一个 2 GB 的视频会把学校自购的机器撑爆；
  · 取回失败要留痕（file_error）且**不能被 cron 每分钟重撞**，得靠后台按钮人工重试；
  · Token 只能从系统参数读，绝不写死在本文件里。

用法：python3 tests/unit/tg_assist_file_test.py   （退出码 0=全通过 / 1=有失败）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MATERIAL = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist', 'models', 'material.py')
VIEW = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist', 'views',
                    'assist_material_views.xml')

with open(MATERIAL, encoding='utf-8') as fh:
    SRC = fh.read()
with open(VIEW, encoding='utf-8') as fh:
    VIEW_SRC = fh.read()

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


def body(name):
    """取某个方法的方法体（到下一个 def/@api.model 为止）。"""
    hit = re.search(r'\n    def %s\(' % re.escape(name), SRC)
    if not hit:
        return ''
    rest = SRC[hit.end():]
    stop = re.search(r'\n    (?:@api\.model|def )', rest)
    return rest[:stop.start()] if stop else rest


# ---- 1) 参数与常量 ----
check('上限参数名正确',
      "MAX_MB_PARAM = 'edu_tg_assist.material_max_mb'" in SRC)
check('默认上限 10 MB', re.search(r'DEFAULT_MAX_MB = 10\b', SRC) is not None)
check('下载开关参数名正确',
      "DOWNLOAD_PARAM = 'edu_tg_assist.material_download'" in SRC)
check('文件直链模板打的是 Telegram 官方文件域',
      re.search(r"FILE_URL_TMPL = 'https://api\.telegram\.org/file/bot%s/%s'", SRC) is not None)
check('只用 token 参数拼直链（没有写死 token）',
      'api._token()' in SRC and 'bot%s' in SRC)

# ---- 2) 字段：本体要有地方放 ----
for field in ('file_data', 'file_fetched_at', 'file_error'):
    check('字段 %s 已定义' % field, re.search(r'\n    %s = fields\.' % field, SRC) is not None)
check('file_data 存成附件（附件=True）', 'fields.Binary' in SRC and 'attachment=True' in SRC)

# ---- 3) webhook 路径绝不出网（否则 Telegram 重投 = 重复归档）----
note_body = body('_tg_assist_note_private_message')
check('私聊挂点方法存在', bool(note_body))
check('钩子里不下载文件本体', 'requests.' not in note_body and '_fetch_file' not in note_body)
check('钩子里只记元数据（_file_meta）', 'ingest(' in note_body)

# ---- 4) 取回实现 ----
fetch = body('_fetch_file')
check('_fetch_file 存在', bool(fetch))
check('先 getFile 拿路径', "api.call('getFile'" in fetch)
check('再按 file_path 下载', 'requests.get(FILE_URL_TMPL' in fetch)
check('响应不是 200 就留错误', 'resp.status_code != 200' in fetch)
check('失败写 file_error 而不是抛异常', "write({'file_error'" in fetch)
check('成功写 file_data + 取回时间', "'file_data': base64.b64encode(blob)" in fetch
      and "'file_fetched_at': fields.Datetime.now()" in fetch)
check('已有本体直接算成功（幂等）', 'if self.file_data:' in fetch)
check('导入 base64', re.search(r'\nimport base64\n', SRC) is not None)
check('导入 requests', re.search(r'\nimport requests\n', SRC) is not None)

# ---- 5) 上限守卫：两个口子都要拦 ----
check('按已知大小先拦一道', 'if self.file_size and self.file_size > cap' in fetch)
check('下载后再按实际字节拦一道', 'if len(blob) > cap' in fetch)
check('_max_bytes 存在且非法值回落默认', 'def _max_bytes' in SRC and 'mb = DEFAULT_MAX_MB' in SRC)
check('超限文案带 MB', '_too_big' in SRC and '超过上限 %s MB' in SRC)

# ---- 6) cron 自动取回：只取没取过、没报过错的 ----
cron = body('_cron_analyze')
check('cron 里会取回文件', '_fetch_file(' in cron)
check('cron 只挑已分析的', "('state', '=', 'analyzed')" in cron)
check('cron 跳过已取回的', "('file_data', '=', False)" in cron)
check('cron 跳过报过错的（不每分钟重撞）', "('file_error', '=', False)" in cron)

# ---- 7) 后台按钮 + 视图 ----
act = body('action_fetch_file')
check('action_fetch_file 存在', bool(act))
check('按钮会清掉上次的错误再重试', "write({'file_error': ''})" in act)
check('按钮回 display_notification', 'display_notification' in act)
check('视图有取回按钮',
      'name="action_fetch_file"' in VIEW_SRC and '取回文件' in VIEW_SRC)
check('视图能下载本体', 'name="file_data"' in VIEW_SRC)
check('视图显示取回时间与错误',
      'name="file_fetched_at"' in VIEW_SRC and 'name="file_error"' in VIEW_SRC)

# ---- 8) 回执要告诉老师「文件会存到后台」 ----
receipt = body('_receipt_text')
check('有文件时回执提到材料归档', 'if rec.file_id and not rec.file_data' in receipt
      and '材料归档' in receipt)

failed = [n for n, ok, _ in results if not ok]
for name, ok, detail in results:
    print(('PASS  ' if ok else 'FAIL  ') + name + (('  << ' + detail) if detail and not ok else ''))
print('----')
print('%s/%s 通过' % (len(results) - len(failed), len(results)))
if failed:
    print('失败：' + '; '.join(failed))
sys.exit(1 if failed else 0)
