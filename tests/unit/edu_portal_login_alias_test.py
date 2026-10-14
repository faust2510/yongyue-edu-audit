# -*- coding: utf-8 -*-
"""学号登录纯函数的回归用例 —— **不需要数据库、不需要 Odoo**。

为什么值得单测（乙方案的两条红线都在这几个函数里）：
  · 判据太宽 ⇒ 邮箱登录被改写，全校老师/家长当场登不进来；
  · 限速缺失 ⇒ 「学号 + 密码」成了可枚举接口，学号是否在册、密码能不能猜都能被刷。
所以：**不像学号的输入一个字节都不许动**，以及**同一 IP 反复失败必须被封住**。

限速为什么是「失败计数窗口」而不是令牌桶（2026-10-12 实测）：
  进程内令牌桶在多 worker 下每个进程各一份，本地 workers=6 时第 9 次仍登录成功
  ⇒ 改成落库的失败计数（models/login_throttle.py），本文件只测它的**策略计算**。

用法：python3 tests/unit/edu_portal_login_alias_test.py   （退出码 0=全通过 / 1=有失败）
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = os.path.join(ROOT, 'custom_addons', 'edu_portal', 'login_alias.py')

_spec = importlib.util.spec_from_file_location('edu_portal_login_alias', SPEC)
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


# ---------- 1) 什么算学号：生产实测口径（45 个有学号的档案全是纯数字，长度 7 或 10）----------
for good in ('1234567', '20230101', '1234567890', ' 20230101 ', '0001'):
    check('像学号：%r' % good, L.looks_like_gr_no(good))

# ---------- 2) 邮箱与一切正常用户名**必须**判为「不像学号」----------
for bad in ('', None, '   ', 'abc123', 'zhang@school.edu', 'user@x.io',
            'student', '123', '1' * 21, '12 34', '１２３４', '20230101@edu.example.org',
            '-1234567', '1234567a', '1.5e7'):
    check('不像学号：%r' % bad, not L.looks_like_gr_no(bad))

check('全角数字不是学号（isascii 兜住）', not L.looks_like_gr_no('１２３４５６７'))
check('边界长度 4 收、3 不收',
      L.looks_like_gr_no('1234') and not L.looks_like_gr_no('123'))
check('边界长度 20 收、21 不收',
      L.looks_like_gr_no('1' * 20) and not L.looks_like_gr_no('1' * 21))

# ---------- 3) 限速键 ----------
check('bucket_key 稳定', L.bucket_key('1.2.3.4', '1234567') == L.bucket_key('1.2.3.4', '1234567'))
check('bucket_key 大小写/空格归一', L.bucket_key('1.2.3.4', ' 1234567 ') == L.bucket_key('1.2.3.4', '1234567'))
check('bucket_key 换 IP 就是另一个桶', L.bucket_key('1.2.3.4', '1234567') != L.bucket_key('5.6.7.8', '1234567'))
check('bucket_key 换学号就是另一个桶', L.bucket_key('1.2.3.4', '1234567') != L.bucket_key('1.2.3.4', '7654321'))
check('bucket_key 空 IP 不炸', isinstance(L.bucket_key(None, None), str))

# ---------- 4) 失败计数窗口：8 次封 15 分钟 ----------
check('限速常量就是文档写的那三个', (L.LOGIN_FAIL_LIMIT, L.LOGIN_WINDOW_SECONDS,
                                     L.LOGIN_BLOCK_SECONDS) == (8, 900, 900))

now = 1_000_000.0
fails, wstart, blocked = 0, None, 0.0
states = []
for _ in range(12):
    fails, wstart, blocked = L.next_failure_state(fails, wstart, now)
    states.append((fails, wstart, blocked))
check('第 1 次失败：计数 1、窗口起点=now、不封',
      states[0] == (1, now, 0.0))
check('第 7 次失败：计数 7、仍不封', states[6][0] == 7 and states[6][2] == 0.0)
check('第 8 次失败：计数清零并封到 now+900',
      states[7] == (0, now, now + 900.0))
check('窗口起点在前 7 次里不动（滑动窗口从第一次失败起算）',
      all(s[1] == now for s in states[:8]))

# 封禁期内继续失败不会把封禁续期（计数器已清零、窗口已重置）
check('封禁中再失败只重新计数、不叠加封禁',
      L.next_failure_state(0, now, now + 1.0)[2] == 0.0)

# 窗口过期 ⇒ 重新从 1 数
check('窗口过期后重新计数（不封）',
      L.next_failure_state(7, now, now + L.LOGIN_WINDOW_SECONDS + 1) ==
      (1, now + L.LOGIN_WINDOW_SECONDS + 1, 0.0))
check('正好等于窗口宽度不算过期（> 才算）',
      L.next_failure_state(1, now, now + L.LOGIN_WINDOW_SECONDS)[0] == 2)

# ---------- 5) blocked_seconds ----------
check('没被封 ⇒ 0', L.blocked_seconds(0, now) == 0 and L.blocked_seconds(None, now) == 0)
check('封到 now+900 ⇒ 900 秒', L.blocked_seconds(now + 900.0, now) == 900)
check('封禁已过 ⇒ 0（不为负）', L.blocked_seconds(now - 5.0, now) == 0)
check('不足 1 秒向上取整', L.blocked_seconds(now + 0.2, now) == 1)

# ---------- 6) 纯函数：不依赖全局时钟、不碰全局状态 ----------
_src = open(SPEC, encoding='utf-8').read()
check('模块不 import time（时间由调用方喂）', 'import time' not in _src)
check('模块没有进程内桶（多 worker 下会被稀释）',
      'LOGIN_BUCKET' not in _src and 'bucket_take' not in _src)

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    if not ok:
        print('FAIL  %s  %s' % (name, detail))
print('edu_portal_login_alias_test: %s/%s 通过' % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
