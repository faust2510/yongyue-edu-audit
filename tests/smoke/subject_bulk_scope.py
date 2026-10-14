# -*- coding: utf-8 -*-
"""三条批量审批路由的「被忽略的行」永久断言（跑在本地 odoo shell 内）。

被测行为（t67 收窄契约 + t126 遗留）：
  教务/教师批量处理时，**被作用域丢弃的 id（越权 + 不存在）**必须被**报出来**，
  而不是静默消失；同时越权与不存在必须**不可区分**（不泄露存在性）；
  且「只有被忽略的行」时**不得**弹绿色「批量完成」横幅（那是缺陷 #24 的形状）。

三条路由与各自待处理状态：
  /leave/set_state_bulk        edu.leave                 state=request
  /grievances/set_state_bulk   edu.grievance             state in (submitted, in_progress)
  /registrar/subject/set_state_bulk  op.subject.registration  state=submitted

夹具：教师 faculty@local 的作用域 = 班级 8 → 学生 5（王小明）。
  作用域内用学生 5、越权用学生 7；不存在用 99999991 ⇒ ignored 恰为 2。
  每条夹具都是**克隆现成行**（改 student_id + state），跑完逐 id 删除并断言 leftover=0。

用法：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
        --db_host=db -r odoo -w odoo --no-http < tests/smoke/subject_bulk_scope.py
"""
import os
import re
import sys

import requests

os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
BASE = os.environ.get('EDU_BASE', 'http://127.0.0.1:8069')
LOGIN = os.environ.get('EDU_LOGIN', 'faculty@local')
PWD = os.environ.get('EDU_PWD', 'demo123')
IN_STUDENT = 5       # 教师作用域内
OUT_STUDENT = 7      # 越权
NONEXIST = 99999991  # 不存在

ok = fail = 0
created = []          # [(model, id)]，跑完必删


def check(name, cond, detail=''):
    global ok, fail
    if cond:
        ok += 1
        print('PASS | %s | %s' % (name, detail))
    else:
        fail += 1
        print('FAIL | %s | %s' % (name, detail))


def session():
    s = requests.Session()
    s.headers.update({'Accept-Language': 'zh-CN,zh;q=0.9'})
    r = s.get(BASE + '/web/login', timeout=20)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text)
    s.post(BASE + '/web/login', timeout=20,
           data={'login': LOGIN, 'password': PWD,
                 'csrf_token': m.group(1) if m else '',
                 'redirect': '/my/home'}, allow_redirects=True)
    return s


def clone(model, state, student_id):
    """克隆一条现成行当夹具（保留其业务字段），改 student_id + state。"""
    M = env[model].sudo()
    src = M.search([], limit=1, order='id')
    raise_ = '找不到可克隆的源行'
    assert src, raise_
    vals = {}
    for fname, f in src._fields.items():
        if fname in ('id', 'create_date', 'create_uid', 'write_date', 'write_uid',
                     'display_name', '__last_update'):
            continue
        if f.related or f.compute:
            continue
        try:
            val = src[fname]
        except Exception:
            continue
        if val in (False, None, ''):
            continue
        vals[fname] = val.id if f.type == 'many2one' else val
    vals['student_id'] = student_id
    vals['state'] = state
    # 2026-09-17（队长）：防呆已扩到**所有 doc_type**（校长裁定「拦住吧」）——
    # 选课单夹具必须自带科目，否则克隆出来的空 payload 单会被守卫拦下。
    # 这是设计意图，不是缺陷（见 docs/dev-workflow.md「夹具不得克隆语义字段」）。
    if model == 'op.subject.registration' and not (
            vals.get('compulsory_subject_ids') or vals.get('elective_subject_ids')):
        course = env['op.course'].sudo().browse(vals.get('course_id'))
        subj = course.subject_ids[:1] if course and course.subject_ids             else env['op.subject'].sudo().search([], limit=1)
        if subj:
            vals['compulsory_subject_ids'] = subj.ids
    # 选课单的额外业务约束：batch.course_id 必须 == course_id，否则动作抛
    # SR0008。演示数据里**确实存在**批次与课程不一致的旧行，克隆会继承它 ——
    # 这里按批次纠正（首版冒烟就栽在这，服务端判定是对的，是夹具不合规）。
    if 'batch_id' in M._fields and 'course_id' in M._fields and vals.get('batch_id'):
        b = env['op.batch'].sudo().browse(vals['batch_id'])
        if b.exists() and b.course_id:
            vals['course_id'] = b.course_id.id
    rec = M.create(vals)
    created.append((model, rec.id))
    return rec


def post(s, path, page, ids, state):
    r0 = s.get(BASE + page, timeout=20)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r0.text)
    r = s.post(BASE + path, timeout=30, allow_redirects=True, data={
        'ids': ','.join(str(i) for i in ids), 'state': state,
        'csrf_token': m.group(1) if m else ''})
    return r


def ignored_of(r):
    m = re.search(r'bulk_ignored=(\d+)', r.url)
    return int(m.group(1)) if m else None


ROUTES = [
    ('edu.leave', '/leave/set_state_bulk', '/leave/approvals',
     'request', 'approved'),
    ('edu.grievance', '/grievances/set_state_bulk', '/grievances/approvals',
     'submitted', 'resolve'),
    ('op.subject.registration', '/registrar/subject/set_state_bulk',
     '/registrar/subject/approvals', 'submitted', 'approved'),
]

s = session()
r = s.get(BASE + '/leave/approvals', timeout=20)
check('教师登录并打开审批页', r.status_code == 200 and '审批' in r.text,
      'code=%d' % r.status_code)

for model, path, page, pend_state, new_state in ROUTES:
    print('\n--- %s ---' % model)
    in_rec = clone(model, pend_state, IN_STUDENT)
    out_rec = clone(model, pend_state, OUT_STUDENT)

    # ★ 夹具必须**提交**后才对本进程之外的 HTTP 会话可见。首版冒烟漏了这一步：
    #   服务端把三个 id 全当"不存在" ⇒ ignored=3。**那是测试 bug，不是产品 bug**
    #   （最小实证：同款夹具提交后单发 → ok=1 / ignored=0）。
    env.cr.commit()

    # A. 混发：作用域内 + 越权 + 不存在 ⇒ ignored=2，作用域内行照常被处理
    resp = post(s, path, page, [in_rec.id, out_rec.id, NONEXIST], new_state)
    # 前置：请求必须真被受理（落到审批页且带回执参数），否则后面全是假绿/假红
    accepted = ('approvals' in resp.url and 'bulk_' in resp.url)
    check('%s 批量请求被受理（非 CSRF/错误页）' % model, accepted,
          'code=%s url=%s' % (resp.status_code, resp.url[:70]))
    ign = ignored_of(resp)
    check('%s 混发 ignored=2' % model, ign == 2, '实际 ignored=%s url=%s'
          % (ign, resp.url.split('?')[-1][:80]))
    check('%s 页面出现「另有 N 行」文案' % model,
          '另有 2 行不在你的处理范围内或已不存在' in resp.text,
          '未命中' if '另有' not in resp.text else '命中')
    env.invalidate_all()          # 读回服务端写入后的真实状态（清掉本进程缓存）
    in_rec2 = env[model].sudo().browse(in_rec.id)
    check('%s 正对照：作用域内行被处理（%s→%s）' % (model, pend_state, new_state),
          in_rec2.state == new_state, '实际 state=%s' % in_rec2.state)

    # B. 只有被忽略的行 ⇒ 不得出现绿色「批量完成」横幅，但要有文案
    resp_b = post(s, path, page, [out_rec.id, NONEXIST], new_state)
    check('%s 只有被忽略时 ignored=2' % model, ignored_of(resp_b) == 2,
          '实际 %s' % ignored_of(resp_b))
    # 这条要同时要求"页面确实渲染了那句话"，否则错误页会因为什么都不含而假绿
    check('%s 不弹绿色「批量完成」横幅（且页面确为审批页）' % model,
          '批量完成' not in resp_b.text
          and '另有 2 行不在你的处理范围内或已不存在' in resp_b.text,
          '横幅出现了' if '批量完成' in resp_b.text else '页面未渲染那句文案')
    check('%s 文案仍可见' % model,
          '另有 2 行不在你的处理范围内或已不存在' in resp_b.text)

    # C. 不可区分性：只越权 vs 只不存在 —— 状态码与跳转 URL 必须逐字一致
    r_out = post(s, path, page, [out_rec.id], new_state)
    r_none = post(s, path, page, [NONEXIST], new_state)
    same = (r_out.status_code == r_none.status_code
            and r_out.url == r_none.url
            and len(r_out.text) == len(r_none.text))
    check('%s 越权/不存在 响应逐字一致' % model, same,
          '越权=%s(%.0f) 不存在=%s(%.0f)'
          % (r_out.url.split('?')[-1][:60], len(r_out.text),
             r_none.url.split('?')[-1][:60], len(r_none.text)))

# 清场 + leftover=0
for model, rid in created:
    rec = env[model].sudo().browse(rid)
    if rec.exists():
        rec.unlink()
env.cr.commit()
left = sum(1 for model, rid in created
           if env[model].sudo().browse(rid).exists())
check('清场 leftover=0', left == 0, 'leftover=%d（共建 %d）' % (left, len(created)))

print('\n合计：PASS %d / FAIL %d' % (ok, fail))
if fail:
    raise SystemExit(1)
