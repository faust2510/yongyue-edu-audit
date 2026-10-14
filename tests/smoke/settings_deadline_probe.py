# -*- coding: utf-8 -*-
"""settings_deadline_probe.py —— /odoo/settings 整页 500 的**服务端**判据（stdin 送进 odoo shell）。

一把尺子量三类证据（原始读数走 PROBE_JSON 一行，供前后对照）：
  红/绿   : res.config.settings 全字段 default_get + onchange（= 打开设置页服务端走的路）。
            fields.Date 在册 ⇒ 抛 "must have type 'boolean',...'datetime'"；改对 ⇒ 不抛。
  正向    : 字段类型/白名单 · 存储格式 'YYYY-MM-DD' · 表单值↔参数值 双向换算（多时区矩阵）
            · 「截止日当天仍可报名」边界谓词 · 消费方 get_raw/get_cn 读数
  控制组  : 另一个**本来正常**的 core 配置项（web_app_name）用同一套 get_values/set_values
            走一遍写→读往返；并快照全部 41 个 config 参数，证明本修复不碰别处。

⚠ 本脚本在 odoo shell 里跑，**退出即回滚**（不 commit）—— 探针不改库。
   为保险，脚本内对写过的参数都显式还原。
"""
import datetime
import json

from odoo import fields

env = env  # noqa: F821  (odoo shell 注入)

S = env['res.config.settings']
D = env['edu.deadline']
icp = env['ir.config_parameter'].sudo()
KEYS = ('edu.apply.deadline', 'edu.enroll.deadline')
FIELDS = ('edu_apply_deadline', 'edu_enroll_deadline')
WHITELIST = ('boolean', 'integer', 'float', 'char', 'selection', 'many2one', 'datetime')
out = {'checks': {}}


def check(name, ok, evidence):
    out['checks'][name] = {'ok': bool(ok), 'evidence': evidence}
    print('[%s] %s: %s' % ('PASS' if ok else 'FAIL', name, evidence))


# ---------- 1. 设置页服务端路径（红/绿主判据）----------
names = list(S._fields.keys())
try:
    vals = S.default_get(names)
    check('settings_default_get_all_fields', True,
          'default_get(%d 字段) 无异常；两条截止日 = %s'
          % (len(names), [vals.get(f) for f in FIELDS]))
except Exception as e:                                             # noqa: BLE001
    check('settings_default_get_all_fields', False,
          '%s: %s' % (type(e).__name__, e))

try:
    # ORM 侧三参形态（HTTP 层客户端载荷的另一形态由 tests/smoke/settings_page_probe.py
    # --mode rpc 逐字回放）
    S.onchange({}, [], {f: {} for f in FIELDS})
    check('settings_onchange', True, 'onchange(values, [], spec) 无异常')
except Exception as e:                                             # noqa: BLE001
    check('settings_onchange', False, '%s: %s' % (type(e).__name__, e))

try:
    rec = S.create({})
    rec.execute()
    check('settings_execute(保存动作)', True, 'create + execute 无异常')
except Exception as e:                                             # noqa: BLE001
    check('settings_execute(保存动作)', False, '%s: %s' % (type(e).__name__, e))

# ---------- 2. 字段契约：类型在白名单内 + config_parameter 未变 ----------
ftypes = {f: S._fields[f].type for f in FIELDS}
porig = {f: getattr(S._fields[f], 'config_parameter', None) for f in FIELDS}
check('field_type_in_whitelist', all(t in WHITELIST for t in ftypes.values()),
      'types=%s（白名单=%s）' % (ftypes, list(WHITELIST)))
check('config_parameter_unchanged',
      porig == {'edu_apply_deadline': 'edu.apply.deadline',
                'edu_enroll_deadline': 'edu.enroll.deadline'},
      'config_parameter=%s' % porig)

# ---------- 3. 存储格式：仍是 'YYYY-MM-DD'（消费方按它解析）----------
params = {k: icp.get_param(k) for k in KEYS}
fmt_ok = all(v and len(v) == 10 and v[4] == '-' and v[7] == '-' for v in params.values())
check('param_format_YYYY-MM-DD', fmt_ok, 'params=%s' % params)

# ---------- 4. 消费方读数（修复前后必须逐字相同）----------
raw = {k: D.get_raw(k) for k in KEYS}
cn = {k: D.get_cn(k) for k in KEYS}
check('consumer_get_raw', raw == params,
      'get_raw=%s（与库内参数逐字相同）' % raw)
check('consumer_get_cn',
      all(len(v) > 5 and v.endswith('\u65e5') for v in cn.values()), 'get_cn=%s' % cn)

# ---------- 5. 表单值 ↔ 参数值：多时区矩阵（时区只做载体）----------
TZS = ['UTC', 'Asia/Shanghai', 'Asia/Kuala_Lumpur', 'America/New_York',
       'Europe/Berlin', 'Pacific/Kiritimati', 'Pacific/Midway']
DATES = ['2026-10-01', '2026-01-01', '2026-06-15', '2026-12-31', '2028-02-29']
matrix, bad = [], []
for tz in TZS:
    De = D.with_context(tz=tz)
    for d in DATES:
        icp.set_param('edu.apply.deadline', d)
        form = De.to_form_value('edu.apply.deadline')          # 服务端发给客户端的值（朴素 UTC）
        # 客户端原样回传（Odoo 客户端把用户选的本地日期序列化成 UTC 串）
        echo = form.strftime('%Y-%m-%d %H:%M:%S')
        back = De.from_form_value(echo)                        # 服务端落库格式
        # 客户端渲染口径：收到的 UTC 值按用户时区还原 → 应显示该日本地零点
        shown = 'env.tz=%s 显示 %s' % (tz, De._utc_naive_to_local(form))
        row = {'tz': tz, 'date': d, 'form_utc': echo, 'stored': back, 'shown': shown}
        matrix.append(row)
        if back != d or De._utc_naive_to_local(form).date().isoformat() != d:
            bad.append(row)
icp.set_param('edu.apply.deadline', params['edu.apply.deadline'])   # 还原
check('form_value_roundtrip_all_tz', not bad,
      '%d 组（%d 时区 × %d 日期）全部「选什么日期就存什么日期、就显示什么日期」；不合=%s'
      % (len(matrix), len(TZS), len(DATES), bad[:2]))
out['matrix_sample'] = matrix[:3] + matrix[-2:]

# ---------- 6. 边界语义：「截止日当天仍可报名」----------
today = fields.Date.today()
boundary = []
for off, label in ((-1, '昨天（已过期）'), (0, '今天（当天）'), (1, '明天（未到）')):
    d = (today + datetime.timedelta(days=off)).isoformat()
    icp.set_param('edu.apply.deadline', d)
    raw_v = D.get_raw('edu.apply.deadline')
    # 未来任何拦截逻辑都会这么写：今天 <= 截止日 ⇒ 当天仍在窗口内
    open_now = fields.Date.to_date(raw_v) >= today
    # 再从「设置表单值」这条路走一遍，语义必须完全一致
    form_v = D.to_form_value('edu.apply.deadline')
    open_via_form = fields.Datetime.to_datetime(form_v).date() >= today
    boundary.append({'case': label, 'stored': raw_v, 'open': open_now,
                     'open_via_form_value': open_via_form,
                     'same': open_now == open_via_form})
icp.set_param('edu.apply.deadline', params['edu.apply.deadline'])
expect = [False, True, True]     # 昨天(已过期)=False / 今天(当天)=True / 明天(未到)=True
got = [b['open'] for b in boundary]
check('boundary_deadline_day_inclusive',
      got == expect and all(b['same'] for b in boundary),
      '截止日当天仍可报名=%s（期望 昨天/今天/明天 = %s）；表单值路径一致=%s'
      % (boundary, expect, all(b['same'] for b in boundary)))

# ---------- 7. 控制组：另一条**本来正常**的配置项走同一套机制 ----------
ctrl_key, ctrl_field = 'web.web_app_name', 'web_app_name'
before_ctrl = icp.get_param(ctrl_key)
try:
    c = S.create({ctrl_field: 't110-control'})
    c.set_values()
    wrote = icp.get_param(ctrl_key)
    c2 = S.create({ctrl_field: before_ctrl or False})
    c2.set_values()
    restored = icp.get_param(ctrl_key)
    check('control_other_config_roundtrip',
          wrote == 't110-control' and (restored or False) == (before_ctrl or False),
          '%s 写→读 = %r；还原后 = %r（原值 %r）'
          % (ctrl_key, wrote, restored, before_ctrl))
except Exception as e:                                             # noqa: BLE001
    check('control_other_config_roundtrip', False, '%s: %s' % (type(e).__name__, e))
if not icp.get_param(ctrl_key):
    icp.set_param(ctrl_key, False)      # 保险：把控制项恢复成"未设置"

snapshot = {n: icp.get_param(p) for n, p, _t, _s in
            [(n, getattr(f, 'config_parameter', None), f.type, f.string)
             for n, f in sorted(S._fields.items())
             if getattr(f, 'config_parameter', None)]}
out['param_snapshot'] = snapshot
out['n_config_params'] = len(snapshot)

failed = [k for k, v in out['checks'].items() if not v['ok']]
out['verdict'] = 'PASS' if not failed else 'FAIL'
out['failed'] = failed
print('PROBE_JSON=' + json.dumps(out, ensure_ascii=False, default=str))