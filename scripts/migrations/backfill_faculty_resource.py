# -*- coding: utf-8 -*-
"""回填器：给已存在的 op.faculty 行补上 resource_id（教师不可用时间的宿主资源）。

背景（设计稿 docs/plans/scheduling-overhaul-design.md §10.1「数据实体」）：
  「教师不可用时间」不新建模型、不新建表 —— 直接落在 Odoo 原生
  resource.calendar.leaves 上，按 resource_id 挂到该教师的资源
  （resource.resource）上。models/faculty_ext.py 会在**新建**教师档案时
  自动建资源（create 钩子），但库里**已有**的教师行不会被钩子碰到，
  所以需要本脚本补一次。

为什么默认 dry-run：resource_id 为空只影响「教师不可用」这一档判定
（未登记 ⇒ 一律按可用处理），不会让任何数据变坏；但回填会新建
resource.resource 行，属于写库动作，按本目录惯例先看清单再动手。

本地量级：2 行 op.faculty；生产：1 行（id=20，占用教师名「待定」）。
两处都应该「跑一次、看到 0 行待补」即可。

用法（容器内；需先 -u edu_schedule 让钩子/助手方法存在）：
    docker compose exec -T web odoo shell -d <库名> < scripts/migrations/backfill_faculty_resource.py
    docker compose exec -T -e BACKFILL_CONFIRM=1 web odoo shell -d <库名> < scripts/migrations/backfill_faculty_resource.py
退出码：0 成功（含 dry-run）；1 校验不符/中止；2 参数或环境错误。
"""
import os
import sys

CONFIRM = os.environ.get('BACKFILL_CONFIRM', '') == '1'


def check_company_delegation(env, Faculty):
    """§10.1 必需断言：写 op.faculty.company_id 仍同步到 res_partner.company_id。

    只读做法：在 SAVEPOINT 内写入**它自己已有的公司值**再回滚
    ⇒ 即便回滚失败也没有任何数据变化。
    返回 True/False；False = company_id 已变成「资源公司」的镜子，
    多公司规则会被破坏（那就说明有人改成了接 resource.mixin 的写法）。
    """
    target = Faculty.search([('partner_id', '!=', False)], limit=1)
    if not target:
        print('[断言] 库里没有带联系人的教师行，跳过 company_id 委派检查')
        return True
    cr = env.cr
    cr.execute('SAVEPOINT edu_faculty_company_probe')
    try:
        probe = Faculty.browse(target.id)
        before_partner_company = probe.partner_id.company_id.id
        probe.write({'company_id': probe.company_id.id or env.company.id})
        probe.invalidate_recordset()
        ok = probe.partner_id.company_id.id == probe.company_id.id
        if not ok:
            print('[断言] 失败：写 op.faculty.company_id 之后 '
                  'res_partner.company_id=%s 与 op.faculty.company_id=%s 不一致'
                  % (probe.partner_id.company_id.id, probe.company_id.id))
        else:
            print('[断言] 通过：op.faculty.company_id 仍委派 res_partner.company_id'
                  '（教师 #%s，公司 #%s；改写的是同一值，且已回滚）'
                  % (probe.id, before_partner_company))
        return ok
    finally:
        cr.execute('ROLLBACK TO SAVEPOINT edu_faculty_company_probe')
        cr.execute('RELEASE SAVEPOINT edu_faculty_company_probe')


def main(env):
    if not hasattr(env['op.faculty'], '_get_or_create_resource'):
        print('[回填器] op.faculty 上找不到 _get_or_create_resource() —— '
              '请先升级本模块：bash scripts/safe_upgrade.sh -u edu_schedule')
        return 2

    Faculty = env['op.faculty'].sudo()
    Leaver = env['resource.calendar.leaves'].sudo()
    rows = Faculty.search([], order='id asc')
    missing = rows.filtered(lambda f: not f.resource_id)

    print('[回填器] 目标 = op.faculty 的 resource_id')
    print('[回填器] op.faculty 共 %d 行；缺 resource_id 的 %d 行' % (len(rows), len(missing)))
    for faculty in missing[:20]:
        print('  · 教师 #%s「%s」公司=%s' % (
            faculty.id, faculty.name or '（无名）',
            (faculty.partner_id.company_id or env.company).name))
    if len(missing) > 20:
        print('  · …另有 %d 行' % (len(missing) - 20))
    print('[回填器] 现有 resource.calendar.leaves 行数：%d'
          % Leaver.search_count([]))

    if not missing:
        print('[结论] 没有需要回填的行')
    elif not CONFIRM:
        print('[结论] dry-run：未写入任何记录。确认清单无误后加 '
              'BACKFILL_CONFIRM=1 重跑。')
    else:
        created = 0
        for faculty in missing:
            resource = faculty._get_or_create_resource()
            if resource:
                created += 1
        env.cr.commit()
        print('[结论] 已回填 %d 行（新建/关联 resource.resource 各一条）' % created)

    # ---- 回填后校验（不达标即中止，退出码 1）----
    rows = Faculty.search([], order='id asc')
    still = rows.filtered(lambda f: not f.resource_id)
    if still:
        print('[校验] 不符：仍有 %d 行没有 resource_id：%s'
              % (len(still), still.ids[:20]))
        return 1

    bad_company = []
    for faculty in rows:
        want = faculty.partner_id.company_id or env.company
        if faculty.resource_id.company_id != want:
            bad_company.append(
                '教师 #%s 资源公司=%s 期望=%s' % (
                    faculty.id, faculty.resource_id.company_id.name, want.name))
    if bad_company:
        print('[校验] 不符：资源公司归属与教师联系人公司不一致：%s' % '；'.join(bad_company))
        return 1
    print('[校验] 通过：%d 行教师全部有资源，且资源公司与联系人公司一致' % len(rows))

    if not check_company_delegation(env, Faculty):
        return 1

    print('[结论] 回填完成。教师未登记不可用时间时仍按「可用」处理，'
          '后台在「时间表 → 教师不可用时间」代填。')
    return 0


if globals().get('env') is not None:
    _rc = main(globals()['env'])
    print('[exit] rc=%s' % _rc)
    sys.exit(_rc)
else:
    print('[回填器] 未检测到 Odoo env —— 请在 odoo shell 内执行（见文件头用法）')
    sys.exit(2)
