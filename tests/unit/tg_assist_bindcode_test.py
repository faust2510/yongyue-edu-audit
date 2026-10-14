# -*- coding: utf-8 -*-
"""身份绑定码纯函数的回归用例 —— **不需要数据库、不需要 Odoo**。

为什么值得单测：
  · 码的形状是**手抄接口**：老师会把码念给别人 / 手打进聊天框，多一个 0/O 就废；
  · 深链格式被 edu_tg_gate 用来判「这条 /start 是不是我们签发的」——
    格式一旦漂移，老师点深链会被当成学生领码流，身份永远绑不上；
  · 角色词认错会把学生消息判给班务助手（前门判据看 person.role），
    所以「认不出就别猜」必须有用例钉住。

用法：python3 tests/unit/tg_assist_bindcode_test.py   （退出码 0=全通过 / 1=有失败）
"""
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist', 'bindtext.py')

_spec = importlib.util.spec_from_file_location('tg_assist_bindtext', SPEC)
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


# ---------- 1) 码的形状：可手抄、够长、无易混字符 ----------
codes = [B.random_code() for _ in range(200)]
check('码前缀 BIND-', all(c.startswith('BIND-') for c in codes))
check('码长固定', all(len(c) == len('BIND-') + B.CODE_LEN for c in codes))
check('码体全在大写码表内', all(set(c[5:]) <= set(B.ALPHABET) for c in codes))
check('码表不含易混字符 0/O/1/I/L',
      not (set('01OIL') & set(B.ALPHABET)))
check('200 张码不重复（随机性下限）', len(set(codes)) > 190)
check('码体是字母数字', all(re.match(r'^[A-Z0-9]+$', c[5:]) for c in codes))

# ---------- 2) 格式判据与深链 ----------
check('PAYLOAD_RE 认标准码', bool(re.match(B.PAYLOAD_RE, 'BIND-7KQ2ZM')))
check('PAYLOAD_RE 位数不对就不认',
      not re.match(B.PAYLOAD_RE, 'BIND-7KQ2Z') and not re.match(B.PAYLOAD_RE, 'BIND-7KQ2ZM9'))
check('is_bind_payload 大写', B.is_bind_payload('BIND-7KQ2ZM'))
check('is_bind_payload 小写（手输）', B.is_bind_payload('bind-7kq2zm'))
check('is_bind_payload 前后空格', B.is_bind_payload('  BIND-7KQ2ZM  '))
check('is_bind_payload 拒绝学生邀请码', not B.is_bind_payload('STU-7KQ2ZM'))
check('is_bind_payload 拒绝空值', not B.is_bind_payload('') and not B.is_bind_payload(None))
check('is_bind_payload 坏正则回落自身格式（不静默失效）',
      B.is_bind_payload('BIND-7KQ2ZM', pattern='([unclosed'))
check('is_bind_payload 自定义正则生效',
      B.is_bind_payload('XX-9', pattern=r'^XX-[0-9]$') and not B.is_bind_payload('YY-9', pattern=r'^XX-[0-9]$'))
check('normalize_code 去空格转大写', B.normalize_code('  bind-7kq2zm ') == 'BIND-7KQ2ZM')
check('deep_link 标准形态',
      B.deep_link('sctrs_bot', 'BIND-7KQ2ZM') == 'https://t.me/sctrs_bot?start=BIND-7KQ2ZM')
check('deep_link 容忍 @ 前缀', B.deep_link('@sctrs_bot', 'bind-7kq2zm') == 'https://t.me/sctrs_bot?start=BIND-7KQ2ZM')
check('deep_link 空用户名回落默认', B.deep_link('', 'BIND-7KQ2ZM').startswith('https://t.me/sctrs_bot?start='))
check('deep_link 的载荷能被 PAYLOAD_RE 认出来',
      B.is_bind_payload(B.deep_link('sctrs_bot', 'BIND-7KQ2ZM').split('start=')[1]))

# ---------- 3) 角色词：认不出就不猜 ----------
check('教师 张三 → teacher/张三', B.split_role_and_name('教师 张三') == ('teacher', '张三'))
check('老师 → teacher', B.split_role_and_name('老师 李四') == ('teacher', '李四'))
check('行政 → admin', B.split_role_and_name('行政 王五') == ('admin', '王五'))
check('管理员 → admin', B.split_role_and_name('管理员 王五') == ('admin', '王五'))
check('宿舍长 → dorm_head', B.split_role_and_name('宿舍长 赵六') == ('dorm_head', '赵六'))
check('姓名带空格全保留', B.split_role_and_name('教师 张 三') == ('teacher', '张 三'))
check('缺姓名 → (None, "")', B.split_role_and_name('教师') == (None, ''))
check('空串 → (None, "")', B.split_role_and_name('') == (None, '') and B.split_role_and_name(None) == (None, ''))
check('认不出的角色不猜（王老师 ≠ 教师）', B.split_role_and_name('王老师 张三') == (None, ''))
check('学生不是可签发角色（防误发身份）', '学生' not in B.ROLE_WORDS)
check('ROLE_WORDS 的值与 person.role 口径一致',
      set(B.ROLE_WORDS.values()) <= {'admin', 'teacher', 'dorm_head'})

# ---------- 4) 取码只认第一段（老师会把码和别的话一起发过来）----------
check('单发一张码', B.first_code_token('BIND-ABC123') == 'BIND-ABC123')
check('小写 / 带空白也认', B.first_code_token('  bind-abc123 ') == 'BIND-ABC123')
check('码后面跟着话 ⇒ 只取第一段',
      B.first_code_token('BIND-ABC123 @sarah1212love 谢谢') == 'BIND-ABC123')
check('码后面换行也认', B.first_code_token('BIND-ABC123\n@x') == 'BIND-ABC123')
check('空 / None ⇒ 空串（回落到用法提示）',
      B.first_code_token('') == '' and B.first_code_token(None) == '')
check('不是码就说不是码（交给 redeem 判定，不做格式预判）',
      B.first_code_token('多谢') == '多谢')

# ---------- 5) 用法文案 ----------
check('USAGE_BIND 提到 /bind', '/bind' in B.USAGE_BIND)
check('USAGE_BINDCODE 提到三种角色词',
      all(w in B.USAGE_BINDCODE for w in ('行政', '教师', '宿舍长')))

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    if not ok:
        print('FAIL  %s  %s' % (name, detail))
print('tg_assist_bindcode_test: %s/%s 通过' % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
