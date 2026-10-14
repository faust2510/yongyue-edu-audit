# -*- coding: utf-8 -*-
"""学号登录的**纯函数**部分 —— 不 import odoo，能被 tests/unit 离线单测。

背景（用户 2026-10-12 原话：「你最好这样做，让这个机器人呢有一套完整的新手教程，
要引导用户注册和登录使用。根据：学号+密码来登录注册。」）：
网站注册用邀请码、登录名是**邮箱**（register.py 把 `login` 写成 email）。
学生记不住邮箱、但记得住学号 ⇒ 登录页额外接受「学号 + 密码」。
本文件只管三件可以离线验证的事：
  ① 什么输入算「学号」（判据窄到不可能误伤邮箱登录）；
  ② 限速键怎么算（IP + 输入）；
  ③ 失败限速的**策略计算**（计数窗口 / 封禁时长）—— 真正落库在
     models/login_throttle.py。
「学号 → 登录名」的查库逻辑在 models/login_alias.py，控制器只做改写。

⚠ 硬边界 B15：**不改注册流程、不取消邀请码**（「谁能注册」的闸门必须留着）；
   邮箱登录逐字不变 —— 本文件的所有判据都在「输入不像邮箱」时才可能生效。
"""
import math

# 学号判据（生产实测 2026-10-12：45 个有学号的档案全是纯数字，长度 7 或 10；
# 另有 6 个学生没有学号 ⇒ 他们只能用邮箱登录，这是**必须保留**的兼容路径）。
GR_MIN_LEN = 4
GR_MAX_LEN = 20

# 失败限速：同一 IP + 同一输入，15 分钟内失败 8 次 ⇒ 封 15 分钟。
# 只统计**失败**（成功登录立刻清零），所以正常用户不会被误伤 —— 这点很关键：
# 学校出口常是同一个 NAT IP，按「尝试次数」限速会连坐整个学校。
# 取值比仓内既有先例（controllers/search.py 的搜索建议桶 15 次 / 6 次每秒）更紧，
# 因为登录比搜索敏感。
LOGIN_FAIL_LIMIT = 8
LOGIN_WINDOW_SECONDS = 900
LOGIN_BLOCK_SECONDS = 900


def looks_like_gr_no(value):
    """这个输入是不是「像学号」（纯数字、4–20 位、不含 @）。

    刻意窄：只要含 @ 或出现非 ASCII 数字（全角「１２３」）就**不是**学号，
    于是邮箱登录与任何正常用户名都不会走到学号解析那一步。
    """
    s = (value or '').strip()
    if not s or '@' in s:
        return False
    if not (GR_MIN_LEN <= len(s) <= GR_MAX_LEN):
        return False
    return s.isascii() and s.isdigit()


def bucket_key(remote_addr, login):
    """限速键：IP + 输入（同一个 IP 换着学号试也要被限）。"""
    return '%s|%s' % ((remote_addr or '?')[:64], (login or '').strip().lower()[:64])


def next_failure_state(failures, window_start, now,
                       limit=LOGIN_FAIL_LIMIT, window=LOGIN_WINDOW_SECONDS,
                       block=LOGIN_BLOCK_SECONDS):
    """记一次失败之后的新状态：(failures, window_start, blocked_until)。

    纯函数：三个时间参数都是 Unix 秒（float），由调用方喂 —— 不读时钟、不碰全局。

    · 窗口过期（或本来没有窗口）⇒ 从 1 重新数，窗口起点重置为 now；
    · 数到 limit ⇒ 计数器清零、封到 now + block（清零是为了「封禁解除后重新给
      limit 次机会」，而不是一解封就又被历史计数立刻封回去）；
    · 其余情况只加一，窗口起点**不动**（滑动窗口从第一次失败起算）。
    """
    now = float(now)
    if window_start is None or now - float(window_start) > float(window):
        return 1, now, 0.0
    count = int(failures or 0) + 1
    if count >= int(limit):
        return 0, now, now + float(block)
    return count, float(window_start), 0.0


def blocked_seconds(blocked_until, now):
    """还要等几秒（0 = 没被封）。"""
    if not blocked_until:
        return 0
    return max(0, int(math.ceil(float(blocked_until) - float(now))))
