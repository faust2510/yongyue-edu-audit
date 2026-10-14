# -*- coding: utf-8 -*-
"""学号登录失败限速探针（edu.portal.login.throttle）。

怎么跑（与 scripts/check_all.sh 里 E2E 段同一形状）：
    docker cp tests/smoke/login_throttle_probe.py edu19-clone-web-1:/tmp/throttle_probe.py
    docker exec -i edu19-clone-web-1 sh -c \
      "cd /mnt && odoo shell -d edu19 --db_host=db --db_user=odoo --db_password=odoo --no-http --log-level=error < /tmp/throttle_probe.py"

成败信号：**退出码**。有任何一条 FAIL ⇒ sys.exit(1)。

这个探针守的是什么（2026-10-12 生产探针实测到的真 bug）：
  第 8 次失败会写 failures=0 + blocked_until=now+900；紧接着的第 9 次
  next_failure_state 看到 failures 已是 0 ⇒ 算出 (1, now, 0)，把刚封上的
  blocked_until **覆盖成 0** —— 等于攻击者多试一次就自己解锁。
  修法：_bump 先看这行是否正在封禁中，是则只刷新 last_attempt_at、不改任何计数。

隔离与自清：键名全部带 probe- 前缀（合成），末尾 env.cr.rollback() ⇒ 不留行。
"""
import sys
from datetime import timedelta

from odoo import fields

TH = env['edu.portal.login.throttle'].sudo()

R = []


def check(name, cond, detail=''):
    R.append((name, bool(cond)))
    print('%s | %s | %s' % ('PASS' if cond else 'FAIL', name, detail))


def key_of(tag):
    return '10.0.0.1|probe-%s' % tag


def row(tag):
    return TH.search([('bucket_key', '=', key_of(tag))], limit=1)


# ---- 0) 清掉本探针可能残留的合成行（正常跑完会回滚，这里只防前人异常中断）----
for tag in ('limit', 'fresh', 'other', 'expire', 'stale'):
    TH.search([('bucket_key', '=', key_of(tag))]).unlink()

# ---- 1) 前 7 次不封，第 8 次封 ----
for i in range(7):
    TH._bump(key_of('limit'))
r = row('limit')
check('7 次失败不封', TH.blocked_seconds(key_of('limit')) == 0 and r.failures == 7,
      'failures=%s' % r.failures)
TH._bump(key_of('limit'))
r.invalidate_recordset()
check('第 8 次失败即封', TH.blocked_seconds(key_of('limit')) > 0, 'blocked_s=%s' % TH.blocked_seconds(key_of('limit')))
check('封禁时计数清零', r.failures == 0, 'failures=%s' % r.failures)

# ---- 2) 回归：封禁中再失败**不许解锁、不许续期** ----
before = TH.blocked_seconds(key_of('limit'))
TH._bump(key_of('limit'))
r.invalidate_recordset()
after = TH.blocked_seconds(key_of('limit'))
check('封禁中再失败仍封着（回归）', after > 0, 'before=%s after=%s' % (before, after))
check('封禁中再失败不叠加计数', r.failures == 0, 'failures=%s' % r.failures)
check('封禁中再失败不续期', after <= before, 'before=%s after=%s' % (before, after))
TH._bump(key_of('limit'))
check('连打 10 次仍封着', TH.blocked_seconds(key_of('limit')) > 0)

# ---- 3) 成功一次即清零（clear 删行）----
TH.clear(key_of('limit'))
check('clear 后无行', TH.search_count([('bucket_key', '=', key_of('limit'))]) == 0)
check('clear 后放行', TH.blocked_seconds(key_of('limit')) == 0)

# ---- 4) 键之间互不影响（另一个 IP/学号不受连坐）----
for i in range(8):
    TH._bump(key_of('other'))
check('别的键被封', TH.blocked_seconds(key_of('other')) > 0)
check('本键仍放行', TH.blocked_seconds(key_of('fresh')) == 0)
TH._bump(key_of('fresh'))
check('另一个键只算自己的 1 次', row('fresh').failures == 1)

# ---- 5) 封禁到期 / 窗口过期后重新计数 ----
#    两件事分开：blocked_until 过期只是「放行」，failures 窗口（15 分钟）仍开着
#    ⇒ 下一次失败是 2 而不是 1。只有 window_start 也过期才重新从 1 数。
TH._bump(key_of('expire'))
r = row('expire')
r.write({'blocked_until': fields.Datetime.now() - timedelta(seconds=5)})
check('封禁到期即放行', TH.blocked_seconds(key_of('expire')) == 0)
TH._bump(key_of('expire'))
check('封禁到期但窗口未过 ⇒ 计数继续累加', row('expire').failures == 2,
      'failures=%s' % row('expire').failures)
r.write({'window_start': fields.Datetime.now() - timedelta(seconds=1000),
         'blocked_until': False})
TH._bump(key_of('expire'))
check('窗口过期后重新从 1 数', row('expire').failures == 1,
      'failures=%s' % row('expire').failures)

# ---- 6) 空键安全 ----
check('空键不炸', TH.blocked_seconds('') == 0 and TH.blocked_seconds(None) == 0)

env.cr.rollback()

failed = [n for n, ok in R if not ok]
print('RESULT=%s %d/%d' % ('FAIL' if failed else 'OK', len(R) - len(failed), len(R)))
if failed:
    print('失败项：%s' % '；'.join(failed))
sys.exit(1 if failed else 0)
