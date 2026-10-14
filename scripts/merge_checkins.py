# -*- coding: utf-8 -*-
"""t5 打卡两套合一：edu.daily.checkin(edu_portal) → edu.checkin.record(edu_life)。

为什么需要它
------------
多波次并行开发留下两套「学生打卡」：edu_portal 的 edu.daily.checkin（7 条，
到堂/灵修/读经三个布尔字段）与 edu_life 的 edu.checkin.record（36 条，走
edu.checkin.type 类型字典）。收口后只保留 edu_life 一套，历史事实必须无损并入。

本脚本做三件事
--------------
1) get-or-create 类型「到堂打卡」（daily、sequence=5、不带【演示】—— 它承载真实
   历史事实）。**只用 name 查找，不硬编码 id**；到堂是新类型时 checkin_date 留空，
   避免撞上 edu.checkin.record 的「日期不得晚于今天」校验。
2) 把 7 条源记录按布尔展开成「学生 × 日期 × 类型」候选行，逐条与目标表比对：
   - 目标已存在 → skipped(duplicate)，**并按 note 合并规则回填内容**（目标 note
     非空时保留原值，记 skipped(note_kept)）；
   - 目标不存在 → created（附 note）。
3) 台账：每条候选行落一行 JSONL（来源 id → 目标 id / 动作 / 原因 / 回滚配方）。
   模块重装或换库后重跑本脚本即可复现（脚本幂等，不依赖 --dry-run）。

红线
----
- **零删除**：本脚本正常运行不删任何业务记录；edu.daily.checkin 只停写不删。
- `--rollback` **只删台账里 action=created 记录**，且只删 id/内容仍与台账一致的
  （被改动过的记录进 conflicts 清单，绝不静默删）。类型用 active=False，不物删配置。
- 默认 = `--dry-run`（只打印将执行的动作，不落库）；正式执行必须显式 `--apply`。

用法
----
    # ⚠ 容器/挂载实测（2026-09-17，两条都踩过）：
    #   · compose 只把 ./custom_addons 与 ./openeducat_erp 挂进容器，容器 cwd=/，
    #     容器里没有宿主的 scripts/ 与 docs/；
    #   · `docker compose exec` 与 `docker exec` **都不支持 -v**（unknown shorthand
    #     flag: 'v'）—— 运行中的容器不能加挂载。
    #   所以台账先落在**已挂载**的宿主目录里，再用 docker cp 搬到最终位置：
    #   容器内 /mnt/custom-addons  ==  宿主 ./custom_addons
    #
    # 1) 干跑（默认，不落库；台账不落盘，所以看不看得到路径都无所谓）
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
        --db_host=db -r odoo -w odoo --no-http \
        < scripts/merge_checkins.py
    #
    # 2) 正式执行（脚本内显式 commit —— odoo shell 退出会回滚整个事务）
    docker compose exec -T -e CHECKIN_MERGE_ARGS=--apply \
        -e CHECKIN_MERGE_LEDGER=/mnt/custom-addons/.migration-ledger/checkin-merge-latest.jsonl \
        web odoo shell -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo \
        --no-http < scripts/merge_checkins.py
    #    然后搬到最终位置（宿主侧，两处内容一致）：
    docker compose cp web:/mnt/custom-addons/.migration-ledger/checkin-merge-latest.jsonl \
        scripts/migrations/ledger/checkin-merge-latest.jsonl
    #
    # 3) 回滚（必须指向同一份台账；默认路径就是宿主 scripts/ 下那份）
    docker compose exec -T -e CHECKIN_MERGE_ARGS=--rollback web odoo shell \
        -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo --no-http \
        < scripts/merge_checkins.py
    #
    # 落点解析顺序：CHECKIN_MERGE_LEDGER（显式）→ CHECKIN_MERGE_REPO（仓库根）
    # → __file__ → cwd 约定子目录 → 逐级上溯 → /mnt 与 /mnt/custom-addons/..

台账路径（固定的，报告直接引用这一个）：scripts/migrations/ledger/checkin-merge-latest.jsonl
退出码：0 成功；1 参数/环境错误；2 回滚遇到冲突（有 created 行被改过，未删）。
"""
import calendar
import json
import os
import sys

# ---------------------------------------------------------------------------
# 参数（odoo shell 会把命令行里的 --xxx 吃掉，所以优先读环境变量）
# ---------------------------------------------------------------------------

def _repo_root():
    """仓库根目录。odoo shell 里 `__file__` 不存在（实测 NameError），
    所以按「env 覆盖 → __file__ → 约定子目录存在性 → 逐级上溯」四路解析。"""
    env_root = os.environ.get('CHECKIN_MERGE_REPO', '')
    if env_root and os.path.isdir(env_root):
        return os.path.abspath(env_root)
    if '__file__' in globals():
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cur = os.path.abspath(os.getcwd())
    if os.path.isdir(os.path.join(cur, 'scripts', 'migrations')):
        return cur
    while cur != os.path.dirname(cur):
        if os.path.isdir(os.path.join(cur, 'custom_addons', 'edu_life')):
            return cur
        cur = os.path.dirname(cur)
    # 容器内实测：compose 只挂了 ./custom_addons 与 ./openeducat_erp，cwd=/。
    # 本脚本把宿主的 ./scripts 一并挂到 /mnt/scripts（见头部用法），故这条能命中。
    for cand in ('/mnt', '/mnt/custom-addons/..'):
        if os.path.isdir(os.path.join(cand, 'scripts', 'migrations')):
            return os.path.abspath(cand)
    return os.path.abspath(os.getcwd())


LEDGER_PATH = os.environ.get(
    'CHECKIN_MERGE_LEDGER',
    os.path.join(_repo_root(), 'scripts', 'migrations', 'ledger',
                 'checkin-merge-latest.jsonl'))

ATTEND_TYPE_NAME = '到堂打卡'
ATTEND_TYPE_LABEL = '到堂打卡'
ATTEND_TYPE_SEQUENCE = 5

# note 合并规则（队长裁定）：顺序固定 devotion_note → bible_passage → bible_note
NOTE_RULES = (
    ('devotion_note', '【灵修笔记】'),
    ('bible_passage', '【读经范围】'),
    ('bible_note', '【读经笔记】'),
)

DRY_RUN = True
ROLLBACK = False
_json_out = os.environ.get('CHECKIN_MERGE_JSON', '') == '1'


def _argv():
    """解析参数：命令行优先（直接 python3 跑时用），其次环境变量（odoo shell 用）。"""
    global DRY_RUN, ROLLBACK
    argv = list(sys.argv[1:])
    argv += os.environ.get('CHECKIN_MERGE_ARGS', '').split()
    for a in argv:
        if a == '--apply':
            DRY_RUN = False
        elif a == '--dry-run':
            DRY_RUN = True
        elif a == '--rollback':
            ROLLBACK = True
            DRY_RUN = False
        elif a in ('-h', '--help'):
            print(__doc__)
            sys.exit(0)


_argv()

eprint = print


def info(msg):
    if not _json_out:
        eprint(msg)


# ---------------------------------------------------------------------------
# 纯函数：note 合并（可单测，不碰 env）
# ---------------------------------------------------------------------------

def merge_note(src):
    """按固定顺序拼 note；空列不写，多段用 \\n。src 是 dict（无 env 依赖）。"""
    parts = []
    for field, prefix in NOTE_RULES:
        val = (src.get(field) or '').strip()
        if val:
            parts.append('%s%s' % (prefix, val))
    return '\n'.join(parts)


def plan_rows(src, type_ids):
    """把一条源记录展开成候选行：[(type_id, 类型名, note)]。

    布尔为真才生成候选行 —— 与旧门户「至少勾选到堂/灵修其一或填读经范围」
    的录入口径一致。到堂用 type_ids['attend']。
    """
    rows = []
    if src.get('attend'):
        rows.append((type_ids['attend'], '到堂', ''))
    if src.get('devotion'):
        rows.append((type_ids['devotion'], '灵修',
                     merge_note({'devotion_note': src.get('devotion_note')})))
    if src.get('bible_passage') or src.get('bible_note'):
        rows.append((type_ids['bible'], '读经',
                     merge_note({'bible_passage': src.get('bible_passage'),
                                 'bible_note': src.get('bible_note')})))
    return rows


# ---------------------------------------------------------------------------
# 迁移
# ---------------------------------------------------------------------------

def get_or_create_attend_type(env):
    """get-or-create「到堂打卡」。返回 (type_record|None, created: bool)。"""
    Type = env['edu.checkin.type'].sudo()
    rec = Type.search([('name', '=', ATTEND_TYPE_NAME)], limit=1)
    if rec:
        info('[类型] 已存在：%s (id=%s, active=%s) — 复用，不新建'
             % (ATTEND_TYPE_NAME, rec.id, rec.active))
        return rec, False
    rec = Type.create({
        'name': ATTEND_TYPE_NAME,
        'label': ATTEND_TYPE_LABEL,
        'frequency': 'daily',
        'weekly_target': 1,
        'deadline_weekday': 0,
        'sequence': ATTEND_TYPE_SEQUENCE,
        'active': True,
        'icon': 'fa-check-circle-o',
        'description': '每日到堂打卡（由 edu_portal 旧「每日打卡」到堂维度并入）。',
    })
    info('[类型] 新建：%s (id=%s, sequence=%s, 不带【演示】)'
         % (ATTEND_TYPE_NAME, rec.id, ATTEND_TYPE_SEQUENCE))
    return rec, True


def resolve_type_ids(env):
    """解析三种类型 id：attend 走 get-or-create，灵修/读经按 name 查 edu_life 既有记录。"""
    attend, attend_created = get_or_create_attend_type(env)
    Type = env['edu.checkin.type'].sudo()
    devotion = Type.search([('name', '=', '灵修打卡')], limit=1)
    bible = Type.search([('name', '=', '读经打卡')], limit=1)
    if not devotion or not bible:
        raise SystemExit('[FATAL] edu_life 类型字典不全：灵修打卡=%s 读经打卡=%s'
                         % (bool(devotion), bool(bible)))
    return {
        'attend': attend.id,
        'devotion': devotion.id,
        'bible': bible.id,
    }, {
        'attend': attend,
        'devotion': devotion,
        'bible': bible,
    }, attend_created


def load_source(env):
    """读全部源记录（按日期、id 稳定排序）。"""
    recs = env['edu.daily.checkin'].sudo().search([], order='date, id')
    return [{
        'id': r.id,
        'student_id': r.student_id.id,
        'student_name': r.student_id.name or '?',
        'date': str(r.date),
        'attend': bool(r.attend),
        'devotion': bool(r.devotion),
        'devotion_note': r.devotion_note or '',
        'bible_passage': r.bible_passage or '',
        'bible_note': r.bible_note or '',
    } for r in recs]


def run_migration(env):
    """核心：比对 + 写入 + 台账。返回 (ledger_rows, type_events)。"""
    type_ids, type_recs, attend_created = resolve_type_ids(env)
    srcs = load_source(env)
    Record = env['edu.checkin.record'].sudo()

    info('[源] edu.daily.checkin = %d 条；[目标] edu.checkin.record = %d 条（迁移前）'
         % (len(srcs), Record.search_count([])))
    info('[类型 id] 到堂=%s 灵修=%s 读经=%s'
         % (type_ids['attend'], type_ids['devotion'], type_ids['bible']))

    ledger = []
    n_created = n_updated = n_dup = n_kept = n_nosignal = 0

    for src in srcs:
        rows = plan_rows(src, type_ids)
        if not rows:
            n_nosignal += 1
            ledger.append({
                'action': 'skipped', 'reason': 'no_signal',
                'source': 'edu.daily.checkin', 'source_id': src['id'],
                'student_id': src['student_id'], 'student_name': src['student_name'],
                'date': src['date'], 'type': None, 'target_id': None,
            })
            info('  [跳过] 源 #%s %s %s → 三布尔全假且无文本，无信号'
                 % (src['id'], src['student_name'], src['date']))
            continue
        for type_id, type_label, note in rows:
            domain = [('student_id', '=', src['student_id']),
                      ('type_id', '=', type_id),
                      ('checkin_date', '=', src['date'])]
            exist = Record.search(domain, limit=1)
            if exist:
                old_note = exist.note or ''
                if not note:
                    action, reason, n_dup = 'skipped', 'duplicate', n_dup + 1
                    info('  [跳过] 源 #%s %s %s %s → 已存在 id=%s（无内容需合并）'
                         % (src['id'], src['student_name'], src['date'],
                            type_label, exist.id))
                elif old_note == note:
                    action, reason, n_dup = 'skipped', 'duplicate', n_dup + 1
                    info('  [跳过] 源 #%s %s %s %s → 已存在 id=%s（内容已一致）'
                         % (src['id'], src['student_name'], src['date'],
                            type_label, exist.id))
                elif old_note:
                    action, reason, n_kept = 'skipped', 'note_kept', n_kept + 1
                    info('  [跳过] 源 #%s %s %s %s → 已存在 id=%s，'
                         '目标 note 非空，保留原值（不覆盖）'
                         % (src['id'], src['student_name'], src['date'],
                            type_label, exist.id))
                else:
                    action, reason, n_updated = 'updated', 'note_backfill', n_updated + 1
                    info('  [回填] 源 #%s %s %s %s → 已存在 id=%s，写入 note=%r'
                         % (src['id'], src['student_name'], src['date'],
                            type_label, exist.id, note))
                    if not DRY_RUN:
                        exist.write({'note': note})
                ledger.append({
                    'action': action, 'reason': reason,
                    'source': 'edu.daily.checkin', 'source_id': src['id'],
                    'student_id': src['student_id'],
                    'student_name': src['student_name'],
                    'date': src['date'], 'type': type_label,
                    'type_id': type_id, 'target_id': exist.id,
                    'note_before': old_note, 'note_after': note,
                    'note_written': action == 'updated',
                })
            else:
                n_created += 1
                info('  [新增] 源 #%s %s %s %s → 目标无此行，%s note=%r'
                     % (src['id'], src['student_name'], src['date'], type_label,
                        '将创建' if DRY_RUN else '创建', note))
                new_id = None
                if not DRY_RUN:
                    new_rec = Record.create({
                        'student_id': src['student_id'],
                        'type_id': type_id,
                        'checkin_date': src['date'],
                        'note': note or False,
                    })
                    new_id = new_rec.id
                ledger.append({
                    'action': 'created', 'reason': 'missing',
                    'source': 'edu.daily.checkin', 'source_id': src['id'],
                    'student_id': src['student_id'],
                    'student_name': src['student_name'],
                    'date': src['date'], 'type': type_label,
                    'type_id': type_id, 'target_id': new_id,
                    'note_before': '', 'note_after': note,
                    'note_written': bool(note),
                })
    # 源数据完整性自检：7 条源记录必须条条出现在台账里
    covered = {r['source_id'] for r in ledger}
    missing = [s['id'] for s in srcs if s['id'] not in covered]
    if missing:
        raise SystemExit('[FATAL] 以下源记录未进台账（不应发生）：%s' % missing)

    # 关键语义（否则回滚会误停用一个不是本次建的类型）：
    #   'created'     = 本类型是**历史某次 apply** 由本脚本创建的（台账已记录，资料性）
    #   'deactivate_on_rollback' = **本次运行**才创建的 → 只有它为真，--rollback 才置
    #                              active=False。本次运行时类型已存在 ⇒ 一律不改它的
    #                              active（先到先得，避免踩掉别人的配置）。
    type_events = [{
        'name': ATTEND_TYPE_NAME,
        'type_id': type_recs['attend'].id,
        'created': attend_created,
        'deactivate_on_rollback': attend_created,
        'sequence': ATTEND_TYPE_SEQUENCE,
        'label': ATTEND_TYPE_LABEL,
        'frequency': 'daily',
    }]

    summary = {
        'mode': 'dry-run' if DRY_RUN else 'apply',
        'source_total': len(srcs),
        'target_total_before': Record.search_count(
            []) if DRY_RUN else None,
        'candidates': len(ledger),
        'created': n_created, 'updated': n_updated,
        'skipped_duplicate': n_dup, 'skipped_note_kept': n_kept,
        'skipped_no_signal': n_nosignal,
    }
    return ledger, type_events, summary


def write_ledger(ledger, type_events, summary, header):
    """台账落盘：JSONL，每行一条候选行；header 说明本次运行。"""
    if DRY_RUN:
        info('[台账] dry-run 不落盘（避免覆盖正式台账）→ 目标路径 %s' % LEDGER_PATH)
        return None
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    with open(LEDGER_PATH, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'_header': header}, ensure_ascii=False) + '\n')
        for ev in type_events:
            fh.write(json.dumps({'_type_event': ev}, ensure_ascii=False) + '\n')
        for row in ledger:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
        fh.write(json.dumps({'_summary': summary}, ensure_ascii=False) + '\n')
    info('[台账] 已写入 %s（%d 条候选行）' % (LEDGER_PATH, len(ledger)))
    return LEDGER_PATH


def read_ledger():
    if not os.path.exists(LEDGER_PATH):
        raise SystemExit('[FATAL] 台账不存在：%s —— 先跑 --apply 再回滚' % LEDGER_PATH)
    rows, header, type_events, summary = [], None, [], None
    with open(LEDGER_PATH, encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():
                continue
            obj = json.loads(line)
            if '_header' in obj:
                header = obj['_header']
            elif '_type_event' in obj:
                type_events.append(obj['_type_event'])
            elif '_summary' in obj:
                summary = obj['_summary']
            else:
                rows.append(obj)
    return rows, header, type_events, summary


def run_rollback(env):
    """只删台账 action=created 的记录；note 回填按 note_before 还原；类型 active=False。"""
    rows, header, type_events, _summary = read_ledger()
    Record = env['edu.checkin.record'].sudo()
    created = [r for r in rows if r.get('action') == 'created']
    updated = [r for r in rows if r.get('action') == 'updated']
    conflicts, deleted, restored = [], [], []

    for row in created:
        rec = Record.browse(row['target_id']).exists()
        if not rec:
            conflicts.append({'target_id': row['target_id'], 'why': '记录已不存在（幂等跳过）'})
            continue
        # 安全闸：只删「内容和台账一致」的记录 —— 迁移后被别人改过的不动
        expect_student = row['student_id']
        expect_date = row['date']
        expect_note = row.get('note_after') or ''
        if (rec.student_id.id != expect_student
                or str(rec.checkin_date) != expect_date
                or (rec.note or '') != expect_note):
            conflicts.append({
                'target_id': row['target_id'],
                'why': '内容与台账不一致（迁移后被改动），拒绝删除',
                'now': {'student_id': rec.student_id.id,
                        'date': str(rec.checkin_date),
                        'note': rec.note or ''},
                'ledger': {'student_id': expect_student,
                           'date': expect_date, 'note': expect_note},
            })
            continue
        info('  [回滚] 删除记录 id=%s（%s %s %s）'
             % (rec.id, row['student_name'], row['date'], row['type']))
        rec.unlink()
        deleted.append(row['target_id'])

    for row in updated:
        rec = Record.browse(row['target_id']).exists()
        if not rec:
            conflicts.append({'target_id': row['target_id'], 'why': '被回填的记录已不存在'})
            continue
        if (rec.note or '') != (row.get('note_after') or ''):
            conflicts.append({'target_id': row['target_id'],
                              'why': 'note 与台账不一致，拒绝还原'})
            continue
        info('  [回滚] 还原 note：id=%s ← %r'
             % (rec.id, row.get('note_before') or ''))
        rec.write({'note': row.get('note_before') or False})
        restored.append(row['target_id'])

    # 类型：只把「**本次 apply 创建**」的到堂类型置为 inactive（不物删配置）
    for ev in type_events:
        if not ev.get('deactivate_on_rollback'):
            info('  [回滚] 到堂类型 id=%s 非本次 apply 创建（created=%s）→ 保持原样，'
                 '不置 inactive' % (ev['type_id'], ev.get('created')))
            continue
        Type = env['edu.checkin.type'].sudo()
        trec = Type.browse(ev['type_id']).exists()
        if not trec:
            continue
        if Record.search_count([('type_id', '=', trec.id)]):
            info('  [回滚] 到堂类型 id=%s 仍被 record 引用 → 只置 active=False'
                 % trec.id)
        else:
            info('  [回滚] 到堂类型 id=%s 无引用 → 置 active=False' % trec.id)
        trec.write({'active': False})

    result = {'deleted': deleted, 'restored_notes': restored,
              'conflicts': conflicts}
    info('[回滚] 删除 %d 条、还原 note %d 条、冲突 %d 条'
         % (len(deleted), len(restored), len(conflicts)))
    return result


# ---------------------------------------------------------------------------
# 入口（odoo shell 里 __name__ != '__main__'，所以两个条件都判）
# ---------------------------------------------------------------------------

def main(env):
    from odoo import fields
    import datetime
    if ROLLBACK:
        info('=== 回滚模式（只删台账内 action=created）===')
        res = run_rollback(env)
        env.cr.commit()
        info('[结果] %s' % json.dumps({k: v for k, v in res.items()
                                       if k != 'conflicts'}, ensure_ascii=False))
        if res['conflicts']:
            info('[冲突清单] %s'
                 % json.dumps(res['conflicts'], ensure_ascii=False, indent=2))
            return 2
        return 0

    info('=== %s 模式 ===' % ('dry-run（不落库）' if DRY_RUN else 'apply（落库）'))
    info('[台账路径] %s' % LEDGER_PATH)
    # 只有 apply 才写台账。dry-run 不落盘，所以容器里 cwd=/（解析不到仓库根）时
    # 也不该报错 —— 否则 `--dry-run` 这条 verify 命令在容器内根本跑不通。
    if not DRY_RUN and not os.access(os.path.dirname(LEDGER_PATH) or '.', os.W_OK):
        info('[FATAL] 台账目录不可写：%s —— 用 CHECKIN_MERGE_LEDGER 指定落点'
             % os.path.dirname(LEDGER_PATH))
        return 1
    ledger, type_events, summary = run_migration(env)
    header = {
        'task': 't5 打卡两套合一',
        'mode': summary['mode'],
        'ran_at': str(datetime.datetime.now())[:19],
        'run_date': str(fields.Date.today()),
        'host_db': env.cr.dbname,
        'ledger_path': LEDGER_PATH,
        'note_rules': 'devotion_note→【灵修笔记】/ bible_passage→【读经范围】/ '
                      'bible_note→【读经笔记】；\\n 连接；空列不写；目标非空不覆盖',
    }
    record_count_after = None
    if not DRY_RUN:
        env.cr.commit()
        record_count_after = env['edu.checkin.record'].sudo().search_count([])
    summary['target_total_after'] = record_count_after
    write_ledger(ledger, type_events, summary, header)

    info('[汇总] %s' % json.dumps(summary, ensure_ascii=False))
    if not DRY_RUN:
        info('[核对] edu.checkin.record = %s 条（迁移后）；edu.daily.checkin = %s 条（只停写不删）'
             % (record_count_after,
                env['edu.daily.checkin'].sudo().search_count([])))
    return 0


_env = globals().get('env')
if _env is not None:
    # odoo shell 路径：env 由 shell 注入（见头部用法）
    _rc = main(_env)
    info('[exit] rc=%s' % _rc)
if __name__ == '__main__' and _env is None:
    # 裸 python3 路径：没有 Odoo env，只做纯函数自测（merge_note / plan_rows）
    info('（未检测到 Odoo env —— 本文件应在 odoo shell 内执行，见头部用法）')
    _demo = {'attend': True, 'devotion': True, 'devotion_note': '晨更祷告',
             'bible_passage': '约1章', 'bible_note': ''}
    info('[自测] merge_note=%r' % merge_note(_demo))
    info('[自测] plan_rows=%s' % plan_rows(_demo, {'attend': 9, 'devotion': 2, 'bible': 1}))
