# -*- coding: utf-8 -*-
"""可选清理器：edu_life 演示加载器在 2026-09-17 05:41:04 写入的 9 条打卡行。

背景（完整证据链见 docs/audit/checkin-merge-report.md 与
scripts/migrations/ledger/checkin-merge-row-register.md）：
  t2 在同窗口跑 `bash scripts/safe_upgrade.sh -u edu_life`，加载
  `edu_life/data/demo_life.xml` 末尾的 `<function model="edu.checkin.type"
  name="_load_demo_records"/>`，该函数按「先查重再写」补了近 7 天演示打卡，
  一次性写入 9 条（edu_checkin_record id 53-61）+ 1 条 W37 周记。

**默认 dry-run**；只有显式 --confirm 才删。删除前逐条校验
「student_id / type_id / checkin_date / note / create_date 秒级时刻」与登记表一致，
任一条不一致就整批中止（不删），避免误删迁移产物或被改动过的行。

用法（容器内）：
    docker compose exec -T -e CLEANUP_CONFIRM=1 web odoo shell … < 本文件
退出码：0 成功（含 dry-run）；1 校验不符/中止；2 参数或环境错误。
"""
import os
import sys

# 登记表（scripts/migrations/ledger/checkin-merge-row-register.md §3）里的 9 条
DEMO_BATCH = {
    'create_uid': 1,
    'create_date_prefix': '2026-09-17 05:41:04',
    'rows': [
        (53, 1, '2026-09-16'), (54, 1, '2026-09-15'), (55, 1, '2026-09-14'),
        (56, 1, '2026-09-13'),
        (57, 2, '2026-09-16'), (58, 2, '2026-09-15'), (59, 2, '2026-09-14'),
        (60, 2, '2026-09-13'), (61, 2, '2026-09-12'),
    ],
}
TYPE_ID = {1: '读经打卡', 2: '灵修打卡'}

CONFIRM = os.environ.get('CLEANUP_CONFIRM', '') == '1'


def main(env):
    Record = env['edu.checkin.record'].sudo()
    print('[清理器] 目标 = edu_life 演示加载器 05:41:04 批次（%d 条）'
          % len(DEMO_BATCH['rows']))
    print('[清理器] 模式 = %s' % ('CONFIRM 真删' if CONFIRM else 'dry-run（默认）'))

    mismatches, found = [], []
    for rid, type_id, date in DEMO_BATCH['rows']:
        rec = Record.browse(rid).exists()
        if not rec:
            mismatches.append('id=%s 不存在（可能已被清理）' % rid)
            continue
        cd = str(rec.create_date)[:19]
        if (rec.create_uid.id != DEMO_BATCH['create_uid']
                or cd != DEMO_BATCH['create_date_prefix']
                or str(rec.checkin_date) != date
                or rec.type_id.id != type_id):
            mismatches.append(
                'id=%s 与登记表不符：now(uid=%s,created=%s,date=%s,type=%s) '
                'vs 登记表(%s,%s,type=%s)' % (
                    rid, rec.create_uid.id, cd, rec.checkin_date,
                    rec.type_id.id, DEMO_BATCH['create_uid'],
                    DEMO_BATCH['create_date_prefix'], type_id))
            continue
        found.append((rid, TYPE_ID.get(type_id, '?'), date))

    for rid, tname, date in found:
        print('  [%s] id=%s %s %s' % ('删除' if CONFIRM else '将删除',
                                      rid, tname, date))
    if mismatches:
        print('[中止] 有 %d 条与登记表不符，整批不删：' % len(mismatches))
        for m in mismatches:
            print('   - %s' % m)
        return 1

    if not found:
        print('[结论] 没有需要清理的行（已清理过或库不同）')
        return 0
    if not CONFIRM:
        print('[结论] dry-run：未删除任何记录。确认无误后加 CLEANUP_CONFIRM=1 重跑。')
        return 0

    Record.browse([r[0] for r in found]).unlink()
    env.cr.commit()
    print('[结论] 已删除 %d 条演示行；edu_checkin_record 现为 %d 条'
          % (len(found), Record.search_count([])))
    print('[核对] edu_daily_checkin 未受影响：%d 条'
          % env['edu.daily.checkin'].sudo().search_count([]))
    return 0


if globals().get('env') is not None:
    _rc = main(globals()['env'])
    print('[exit] rc=%s' % _rc)
    sys.exit(_rc)
else:
    print('[清理器] 未检测到 Odoo env —— 请在 odoo shell 内执行（见文件头用法）')
    sys.exit(2)
