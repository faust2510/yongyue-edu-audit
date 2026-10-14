#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评估任务「换模板护栏」验收（**模型层**）—— 红 / 绿 / 控制组 + 自清。

## 它验什么（一句话）

EduAssessTask 上：**已有名单或打分 ⇒ 换评估模板必须被拒**（含 sudo 直写这条后台路径）；
**无名单 ⇒ 必须放行**（控制组）；**原值写回 ⇒ 必须放行**（防回归：后台表单保存会把当前模板
一起提交，不区分的话已发布任务全都存不了）。

## 为什么必须走 odoo shell（而不是 HTTP）

护栏分两层、都在 ORM 层：
  · EduAssessTask.write()      判**转移**（旧值 ≠ 新值 且 已有名单/打分）；
  · EduAssessTask 的 @api.constrains('template_id') 判**状态**（打分记录的评分项必须属于本任务模板）。
@api.constrains 看不到旧值 —— Odoo 的 write() 是**先改库、后跑 constrains**
（odoo/orm/models.py 的 write 与 _validate_fields），所以转移判据只能在 write() 里比新旧值。
走 HTTP 只会碰到门户控制器那条同型判据，**测不到模型层**，等于没验。

## 跑法

    python3 tests/smoke/assess_template_guard.py            # 全跑（需要本地栈在跑）
    python3 tests/smoke/assess_template_guard.py --dump     # 额外打印 shell 原始输出

## 退出码

0 = 断言全过 ｜ 1 = **判据失败**（该拦的没拦 / 不该拦的被拦 / 夹具残留）｜ 2 = ENV
（docker 不可用 / 站点不可达 / 有升级锁在跑）—— ENV 不是失败，但**也不当通过**。

## 自清

探针任务连同名单/打分一起删；结束时对拍 edu.assess.task / roster / score 三个计数
与本轮开工前一致，残留 ≠ 0 ⇒ exit 1 并打印残留 id。控制组用「同名同值对拍」而非"看着像清干净了"。
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

import requests

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = 'http://localhost:8069'
DB = 'edu19'
LOGIN = ('backoffice@local', 'demo123')
CASE_KEYS = ('1_red_有名单换模板', '2_red_有名单sudo直写', '3_green_无名单换模板',
             '4_green_有名单原值写回+改周期', '5_red_状态不变量')

PAYLOAD = '''# -*- coding: utf-8 -*-
"""模型层换模板护栏的取证载荷（由 tests/smoke/assess_template_guard.py 注入 odoo shell）。"""
import json

STAMP = 'GUARDPROBE'
Task = env['edu.assess.task'].sudo()
Tpl = env['edu.assess.template'].sudo()
Roster = env['edu.assess.roster'].sudo()
Score = env['edu.assess.score'].sudo()
Item = env['edu.assess.item'].sudo()
Student = env['op.student'].sudo()


def counts():
    return (Task.search_count([]), Roster.search_count([]), Score.search_count([]))


before = counts()
stu = Student.search([('active', '=', True)], limit=1)
res = {'before': before, 'cases': {}}


def try_create_task(tpl, period):
    try:
        with env.cr.savepoint():
            return Task.create({'template_id': tpl.id, 'period': period,
                                'scorer_kind': 'teacher'})
    except Exception as exc:
        return 'ERR: %s' % str(exc).splitlines()[0][:150]


tplA = tplB = None
for cand in Tpl.search([], order='id'):
    got = try_create_task(cand, '模板可用性探针%s' % STAMP)
    if isinstance(got, str):
        continue
    got.unlink()
    if tplA is None:
        tplA = cand
    elif tplB is None:
        tplB = cand
        break
res['tplA'] = {'id': tplA.id, 'name': tplA.name, 'target_kind': tplA.target_kind} if tplA else None
res['tplB'] = {'id': tplB.id, 'name': tplB.name, 'target_kind': tplB.target_kind} if tplB else None
res['student_pick'] = {'id': stu.id, 'name': stu.name} if stu else None

made = []


def mk(period, with_roster):
    t = try_create_task(tplA, period)
    if isinstance(t, str):
        return t
    made.append(t.id)
    if with_roster and stu:
        Roster.create({'task_id': t.id, 'student_id': stu.id,
                       'subject_ref': 's:%d' % stu.id})
    return t


def attempt(label, task, fn):
    entry = {'task_id': task.id if not isinstance(task, str) else task}
    try:
        with env.cr.savepoint():
            fn(task)
        entry['outcome'] = 'ALLOWED'
    except Exception as exc:
        entry['outcome'] = 'REJECTED'
        entry['exc_type'] = type(exc).__name__
        entry['raw_error'] = str(exc).strip()
        entry['guard_fired'] = ('不能再换评估模板' in str(exc)
                                or '属于**别的模板**' in str(exc))
    res['cases'][label] = entry
    return entry


t1 = mk('门禁探针-有名单', True)
attempt('1_red_有名单换模板', t1, lambda t: t.write({'template_id': tplB.id}))
attempt('2_red_有名单sudo直写', t1, lambda t: t.sudo().write({'template_id': tplB.id}))

t2 = mk('门禁探针-无名单', False)
attempt('3_green_无名单换模板', t2, lambda t: t.write({'template_id': tplB.id}))
if not isinstance(t2, str):
    res['cases']['3_green_无名单换模板']['template_after'] = t2.template_id.id

attempt('4_green_有名单原值写回+改周期', t1,
        lambda t: t.write({'template_id': tplA.id, 'period': '门禁探针-原值写回'}))

if not isinstance(t1, str):
    item = Item.search([('template_id', '=', tplA.id), ('item_kind', '=', 'leaf')], limit=1)
    row = Roster.search([('task_id', '=', t1.id)], limit=1)
    if item and row:
        try:
            with env.cr.savepoint():
                Score.create({'task_id': t1.id, 'roster_id': row.id,
                              'item_id': item.id, 'value': 1.0})
                env.cr.execute("UPDATE edu_assess_task SET template_id = %s WHERE id = %s",
                               (tplB.id, t1.id))
                t1.invalidate_recordset()
                try:
                    t1.write({'template_id': tplB.id})
                    res['cases']['5_red_状态不变量'] = {'outcome': 'ALLOWED'}
                except Exception as exc:
                    res['cases']['5_red_状态不变量'] = {
                        'outcome': 'REJECTED', 'exc_type': type(exc).__name__,
                        'raw_error': str(exc).strip(),
                        'guard_fired': '属于**别的模板**' in str(exc)}
        except Exception as exc:
            res['cases']['5_red_状态不变量'] = {'outcome': 'SETUP_ERR',
                                                'raw_error': str(exc).strip()}

for tid in made:
    try:
        with env.cr.savepoint():
            Task.browse(tid).unlink()
    except Exception:
        pass
env.cr.commit()
res['after'] = counts()
res['residue_tasks'] = Task.search_count([('period', 'like', STAMP)])
print('GUARD_JSON=' + json.dumps(res, ensure_ascii=False, indent=1))
'''


def lock_path():
    return os.path.join(os.environ.get('TMPDIR') or '/tmp', 'edu19_upgrade.lock')


def preflight():
    """ENV 前置：有升级锁 / docker 不可用 / 站点不可达 ⇒ 本轮作废（exit 2）。"""
    if os.path.isdir(lock_path()):
        return '有升级在进行（%s 存在）' % lock_path()
    try:
        r = subprocess.run(['docker', 'compose', 'exec', '-T', 'web', 'true'],
                           cwd=str(ROOT), capture_output=True, timeout=60)
        if r.returncode != 0:
            return 'docker compose exec web 失败（returncode=%s）' % r.returncode
    except Exception as exc:
        return 'docker 不可用：%s' % exc
    s = requests.Session()
    s.trust_env = False
    try:
        code = s.get(BASE + '/web/login?db=' + DB, timeout=15,
                     allow_redirects=False).status_code
    except Exception as exc:
        return '站点不可达（%s）：%s' % (BASE, exc)
    if code not in (200, 302, 303):
        return '站点未就绪（/web/login 返回 %s）' % code
    return None


def run_payload():
    cmd = ['docker', 'compose', 'exec', '-T', 'web', 'bash', '-lc',
           'cat > /tmp/assess_guard_probe.py && odoo shell --db_host=db '
           '--db_port=5432 --db_user=odoo --db_password=odoo '
           '-c /etc/odoo/odoo.conf -d %s --no-http < /tmp/assess_guard_probe.py' % DB]
    return subprocess.run(cmd, cwd=str(ROOT), input=PAYLOAD,
                          capture_output=True, text=True, timeout=600)


def main():
    ap = argparse.ArgumentParser(description='评估任务换模板护栏（模型层）验收')
    ap.add_argument('--dump', action='store_true', help='打印 shell 原始输出')
    args = ap.parse_args()

    env_problem = preflight()
    if env_problem:
        print('ENV：%s ⇒ 本轮作废（不是判据失败，也不当通过）' % env_problem)
        return 2

    proc = run_payload()
    out = (proc.stdout or '') + (proc.stderr or '')
    if args.dump:
        print(out)
    marker = 'GUARD_JSON='
    idx = out.find(marker)
    if idx < 0:
        print('ENV：shell 没吐出 GUARD_JSON（odoo shell 启动失败？）—— 末尾 20 行：')
        print('\n'.join(out.splitlines()[-20:]))
        return 2
    try:
        # raw_decode：JSON 之后的任何输出（shell 收尾/警告）都不算错、也不吞进来
        res, _end = json.JSONDecoder().raw_decode(out[idx + len(marker):])
    except Exception as exc:
        print('ENV：GUARD_JSON 解析失败：%s' % exc)
        print(out[idx:idx + 400])
        return 2

    fails = []
    print('== 换模板护栏（模型层）==')
    print('模板：A=%s ｜ B=%s ｜ 被评学生=%s'
          % (res.get('tplA'), res.get('tplB'), res.get('student_pick')))
    expect = {'1_red_有名单换模板': False, '2_red_有名单sudo直写': False,
              '3_green_无名单换模板': True, '4_green_有名单原值写回+改周期': True,
              '5_red_状态不变量': False}
    for key in CASE_KEYS:
        case = (res.get('cases') or {}).get(key)
        if not case:
            fails.append('%s：没有结果' % key)
            print('  %-34s ✗ 没有结果' % key)
            continue
        allowed = case.get('outcome') == 'ALLOWED'
        want_allowed = expect[key]
        ok = allowed == want_allowed and (want_allowed or case.get('guard_fired'))
        print('  %-34s %s outcome=%s%s'
              % (key, 'PASS' if ok else 'FAIL', case.get('outcome'),
                 ('  guard_fired=%s' % case.get('guard_fired')) if case.get('raw_error') else ''))
        if case.get('raw_error'):
            print('        原始报错：%s' % case['raw_error'])
        if not ok:
            fails.append('%s：期望 %s，实得 %s（guard_fired=%s）'
                         % (key, '放行' if want_allowed else '拒绝',
                            case.get('outcome'), case.get('guard_fired')))
    if not res.get('tplA') or not res.get('tplB'):
        fails.append('找不到两个可用模板（夹具起不来）')
    if res.get('before') != res.get('after'):
        fails.append('夹具残留：计数 before=%s after=%s' % (res.get('before'), res.get('after')))
    if res.get('residue_tasks'):
        fails.append('夹具残留：探针任务 %s 条' % res.get('residue_tasks'))

    print('计数对拍：before=%s ｜ after=%s ｜ 残留探针任务=%s'
          % (res.get('before'), res.get('after'), res.get('residue_tasks')))
    if fails:
        print('RESULT=FAIL')
        for f in fails:
            print('  - %s' % f)
        return 1
    print('RESULT=OK 5/5 用例符合预期（2 红必拒 / 2 绿必放行 / 1 状态不变量必拒）+ 无残留')
    return 0


if __name__ == '__main__':
    sys.exit(main())
