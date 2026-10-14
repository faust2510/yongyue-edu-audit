#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v3：基于 sessions_raw.csv（四 sheet 全量逐格溯源）生成最终排课清单。

核心规则（经原始 xlsx 全量核对确立）：
- 只有“时刻完全一致”的跨源行才视为同一实体课（跨部合班课在两表都写同一时刻：
  逻辑一/使徒行传/护教学/法律导论 等在 wen26 与 A 部逐课同刻 → 同课两视角）。
- A 部无时刻专属课（神论A123 密集、圣灵论A123、摩西五经、讲道法A23、改革宗讲座、
  救恩论密集等）绝不与 wen26 同名周课合并（它们是不同排期/不同受众的不同课），
  作为独立实体保留，默认时刻按裁决表填写并标 time_source=default。
- 家教 sheet 每行与 wen26 完全同刻同课（157/157 全镜像，无独有课）→ 并入 wen26 实体，
  batch 取 wen 标注，source_sheet 保留 “文26下;家教”，不单独建 session
  （默认裁决=网课学员随实体课，待用户确认；若用户要独立家教班则另建）。

输出：
  sessions.csv        主表（合并后实体课，可导入）
  full_sources.csv    逐源 433 行（183+93+157，entity_id 关联主表）
  b12_sessions.csv    B12 弃用版对照（原样 78 行）
"""
import csv
import datetime as dt
import re
from collections import OrderedDict, Counter

HERE = "/Users/qwe/Documents/文件大总管/10-项目/教务系统网站新架构/timetable_import"
SRC = HERE + '/sessions_raw.csv'
OUT = HERE + '/sessions.csv'
OUT_FULL = HERE + '/full_sources.csv'
OUT_B12 = HERE + '/b12_sessions.csv'

CN = {0: '一', 1: '二', 2: '三', 3: '四', 4: '五', 5: '六', 6: '日'}

# A 部无时刻专属课默认时段裁决（默认 10:00-12:00 上午主档；写入 catalog 待用户确认）
# key: (subject, batch, month) 若需特判；目前统一默认，个别标注例外：
#   救恩论 A123 密集（12/28 起两周内五天）→ 默认 09:00-17:00 全天密集，kind=密集课
DEFAULT_RULING = {
    '救恩论': ('09:00', '17:00'),   # A123 密集课
}
DEFAULT_START, DEFAULT_END = '10:00', '12:00'


def parse_lesson_int(s):
    if not s:
        return 0
    m = re.match(r'L(\d+)', s)
    return int(m.group(1)) if m else 0


def full_key(r):
    """仅当起止时刻齐全时使用完整键（date,subject,lesson,start,end）；无时刻行独立成实体。"""
    return (r['date'], r['subject_name'], parse_lesson_int(r['lesson_no']),
            r['start_time'], r['end_time'])


def band_tokens(lab):
    if not lab:
        return []
    return re.findall(r'([A-C]+)(\d+)', lab)


def main():
    rows = list(csv.DictReader(open(SRC, encoding='utf-8-sig')))
    by_sheet = {sh: [] for sh in ('文26下', 'A', '家教', 'B12')}
    for r in rows:
        by_sheet[r['source_sheet']].append(r)

    # ---- 实体合并：只三源，full key ----
    merged = OrderedDict()
    keyorder = []
    for r in rows:
        if r['source_sheet'] == 'B12':
            continue
        k = full_key(r)
        if k not in merged:
            keyorder.append(k)
            merged[k] = {
                'date': r['date'], 'subject_name': r['subject_name'],
                'lesson_no': r['lesson_no'], 'start_time': r['start_time'],
                'end_time': r['end_time'], 'time_expr': r['time_expr'],
                'sources': [r['source_sheet']], 'cells': [r['cell_ref']],
                'raws': [r['raw_text']],
                'labels': [r['batch_label']] if r['batch_label'] else [],
                'kinds': [r['lesson_kind']] if r['lesson_kind'] else [],
            }
        else:
            m = merged[k]
            for s2 in (r['source_sheet'],):
                if s2 not in m['sources']:
                    m['sources'].append(s2)
            if r['cell_ref'] not in m['cells']:
                m['cells'].append(r['cell_ref'])
            if r['raw_text'] not in m['raws']:
                m['raws'].append(r['raw_text'])
            if r['batch_label'] and r['batch_label'] not in m['labels']:
                m['labels'].append(r['batch_label'])
            if r['lesson_kind'] and r['lesson_kind'] not in m['kinds']:
                m['kinds'].append(r['lesson_kind'])

    # ---- 标记需要用户确认的 batch 差异 + 输出行 ----
    out_rows = []
    a_no_time = 0
    for k in keyorder:
        m = merged[k]
        # 主 batch 规则：含 A 前缀的标签优先（更全视图；如 wen B1 vs A A123B1 → A123B1）
        # 特例：使徒行传 wen CB34 vs A A123B34 → 主=A123B34（含 B34；C 未知进 diff 待确认）
        def hasA(l):
            return bool(re.match(r'A', l))
        alabs = [l for l in m['labels'] if hasA(l)]
        # 若 wen 有非 A 标签且 A 标签都不含其 token，则可能 C 班 —— 仍取 A 部全标签并记录
        main_batch = alabs[0] if alabs else (m['labels'][0] if m['labels'] else '')
        diff = sorted(set(m['labels'])) if len(set(m['labels'])) > 1 else ''
        # 无时刻实体 → 默认裁决时刻
        if not m['start_time']:
            a_no_time += 1
            if m['subject_name'] in DEFAULT_RULING:
                m['start_time'], m['end_time'] = DEFAULT_RULING[m['subject_name']]
            else:
                m['start_time'], m['end_time'] = DEFAULT_START, DEFAULT_END
            tsrc = 'default'
        else:
            tsrc = 'explicit'
        d = dt.date.fromisoformat(m['date'])
        out_rows.append({
            'date': m['date'], 'weekday': CN[d.weekday()],
            'subject_name': m['subject_name'], 'batch_label': main_batch,
            'batch_diff': ';'.join(diff) if diff else '',
            'start_time': m['start_time'], 'end_time': m['end_time'],
            'time_expr': m['time_expr'], 'lesson_no': m['lesson_no'],
            'kind': ';'.join(sorted(set(m['kinds']))) if m['kinds'] else '',
            'source_sheet': ';'.join(m['sources']),
            'cell_ref': ';'.join(m['cells']),
            'raw_text': ' ;; '.join(m['raws']),
            'time_source': tsrc,
        })

    # 排序：先日期再星期再科目
    out_rows.sort(key=lambda r: (r['date'], r['start_time'], r['subject_name']))
    with open(OUT, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=[
            'date', 'weekday', 'subject_name', 'batch_label', 'batch_diff',
            'start_time', 'end_time', 'time_expr', 'lesson_no', 'kind',
            'source_sheet', 'cell_ref', 'raw_text', 'time_source'])
        w.writeheader()
        for r in out_rows:
            w.writerow(r)

    # ---- full_sources：逐源 433，entity_id ----
    def find_entity(r):
        k = full_key(r)
        if k in merged:
            return keyorder.index(k) + 1
        # 无时刻行（A 专属）单独实体：用 date+subject+lesson+'' 键
        k2 = (r['date'], r['subject_name'], parse_lesson_int(r['lesson_no']), '', '')
        if k2 in merged:
            return keyorder.index(k2) + 1
        return 0
    with open(OUT_FULL, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=[
            'entity_id', 'source_sheet', 'date', 'weekday', 'subject_name',
            'batch_label', 'start_time', 'end_time', 'time_expr', 'lesson_no',
            'lesson_kind', 'raw_text', 'cell_ref', 'month_year'])
        w.writeheader()
        for r in rows:
            if r['source_sheet'] == 'B12':
                continue
            d = dt.date.fromisoformat(r['date'])
            w.writerow({
                'entity_id': find_entity(r), 'source_sheet': r['source_sheet'],
                'date': r['date'], 'weekday': CN[d.weekday()],
                'subject_name': r['subject_name'], 'batch_label': r['batch_label'],
                'start_time': r['start_time'], 'end_time': r['end_time'],
                'time_expr': r['time_expr'], 'lesson_no': r['lesson_no'],
                'lesson_kind': r['lesson_kind'], 'raw_text': r['raw_text'],
                'cell_ref': r['cell_ref'], 'month_year': r['month_year']})

    # ---- b12 ----
    with open(OUT_B12, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=[
            'source_sheet', 'date', 'weekday', 'subject_name', 'batch_label',
            'start_time', 'end_time', 'time_expr', 'lesson_no', 'lesson_kind',
            'raw_text', 'cell_ref', 'month_year'])
        w.writeheader()
        for r in by_sheet['B12']:
            d = dt.date.fromisoformat(r['date'])
            w.writerow({
                'source_sheet': r['source_sheet'], 'date': r['date'],
                'weekday': CN[d.weekday()], 'subject_name': r['subject_name'],
                'batch_label': r['batch_label'], 'start_time': r['start_time'],
                'end_time': r['end_time'], 'time_expr': r['time_expr'],
                'lesson_no': r['lesson_no'], 'lesson_kind': r['lesson_kind'],
                'raw_text': r['raw_text'], 'cell_ref': r['cell_ref'],
                'month_year': r['month_year']})

    # ---- 核计 ----
    src_cnt = Counter()
    for r in out_rows:
        for s2 in r['source_sheet'].split(';'):
            src_cnt[s2] += 1
    print('主表实体课总数:', len(out_rows))
    print('  显式时刻 explicit:', sum(1 for r in out_rows if r['time_source'] == 'explicit'))
    print('  默认时刻 default :', sum(1 for r in out_rows if r['time_source'] == 'default'))
    print('各源计入实体数:', dict(src_cnt))
    print('batch_diff 行(待确认):', sum(1 for r in out_rows if r['batch_diff']))
    for r in out_rows:
        if r['batch_diff']:
            print('  DIFF', r['date'], r['subject_name'], 'L' + str(r['lesson_no'] or ''),
                  r['start_time'], '->', r['batch_diff'], '主', r['batch_label'])
    print('kind 行:', sum(1 for r in out_rows if r['kind']))
    print('A 无时刻默认行:', a_no_time)
    print('输出 OK:', OUT)

if __name__ == '__main__':
    main()
