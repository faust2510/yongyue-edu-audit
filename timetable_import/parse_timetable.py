#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析 2+6排课表.xlsx 四个 sheet（家教/文26下/A/B12），产出归一化排课清单 sessions.csv。

背景契约（团队 t1 裁决背景，来自队目标与既有资料）：
- sheet 名 = 家教 / 文26下 / A / B12
- A = A神学部（全日制，A1/A2/A3 年级，标注 A123/A1/A23 等）；文26下 = 人文部(B1-B4)唯一权威源；
  家教 = 网课学员（无班级标注）；B12 = 已弃用（仅作差异对照，不产出）
- L1-L18 = 课次编号（lesson #），不是周次
- 表格结构：左右两个镜像网格；月份列对 = B/C(2026-07), D/E(08), F/G(09), H/I(10),
  K/L(11), M/N(12), O/P(2027-01), Q/R(2027-02)；每列对中偶数列(前)=当月日期(1~31 整数)，
  奇数列(后)=该行日期对应的事件文本（多行 \n 分隔）；A/J 列为星期标签（一~日）。
- 事件列文本每行 = 一次课次：可选 `L<课次号>` 前缀 + 课程名 + 班级标注(如 B34/A123B234/A23 或空)
  + （起-止时间）+ 可选「考试/讲座」等词；另有些格是实践周/节日/周末图例文本（须丢弃）。

本脚本输出 timetable_import/sessions_raw.csv（UTF-8 with BOM，含表头），每条记录 = 一次课次，
列：source_sheet,date,weekday,subject_name,batch_label,start_time,end_time,time_expr,
     lesson_no,lesson_kind,raw_text,cell_ref,month_year
其中 date 由「所在月份列 + 同行前一偶数列的日期整数」推导（2026-07~2027-02），
weekday 由该日实际星期推算（中国习惯 周一=一 … 周日=日）。
"""
import csv
import datetime as dt
import re
import sys

import openpyxl

XLSX = "/Users/qwe/Documents/文件大总管/20-工作/公司事务/课程表/2+6排课表.xlsx"
OUT = "sessions_raw.csv"  # 四 sheet 全量、逐格可溯源（供 normalize_sessions.py 合并成主表）
HERE = "/Users/qwe/Documents/文件大总管/10-项目/教务系统网站新架构/timetable_import"

CN_WEEKDAY = {0: '一', 1: '二', 2: '三', 3: '四', 4: '五', 5: '六', 6: '日'}

# 月份表：列字母 -> (year, month)
PAIRS = {
    'B': (2026, 7), 'C': (2026, 7),
    'D': (2026, 8), 'E': (2026, 8),
    'F': (2026, 9), 'G': (2026, 9),
    'H': (2026, 10), 'I': (2026, 10),
    'K': (2026, 11), 'L': (2026, 11),
    'M': (2026, 12), 'N': (2026, 12),
    'O': (2027, 1), 'P': (2027, 1),
    'Q': (2027, 2), 'R': (2027, 2),
}
# 每个列对的首字母=日期列（含该月日期 1~31），次字母=事件列
DATE_COLS = {'B', 'D', 'F', 'H', 'K', 'M', 'O', 'Q'}    # 2026-07..2027-02 每月首列
EVENT_COLS = {'C', 'E', 'G', 'I', 'L', 'N', 'P', 'R'}

# 非课次文本（节日/图例/作息区）——全量识别后丢弃
NON_SESSION_MARKERS = [
    '实践周', '元旦', '平安夜', '圣诞节', '春节', '除夕', '假期', '周末',
    '重要节日', '日期不确定', '基础信仰', '专文写作', '福音与中国传统文化',
    '圣经课程 1', '圣经课程 2', '信仰与文化', '专门写作法', '到达上班场地',
    'dg/灵修分享', '神论/救恩论', '吃饭午休', '英语', '文学2B2', '逻辑学 1',
    '自习', '晚饭', '熄灯休息', '法律B2', '圣经课程',
]

def colnum(s):
    n = 0
    for ch in s:
        n = n * 26 + ord(ch) - 64
    return n

def parse_time(expr):
    """从时间表达式抽取起止 HH:MM；失败返回 (None, None, 原文)。"""
    expr = expr.strip()
    # 优先：括号内 H[-:点]H 模式（允许 '（10-12点）'、'（19:15-21:15 ）'、'(10-12点）' 混用括号）
    m = re.search(r'[（(]\s*([0-9]{1,2}(?::[0-9]{1,2})?)\s*[-–~至]\s*([0-9]{1,2}(?::[0-9]{1,2})?)\s*[点:]?\s*[）)]', expr)
    if not m:
        m = re.search(r'([0-9]{1,2}(?::[0-9]{1,2})?)\s*[-–~至]\s*([0-9]{1,2}(?::[0-9]{1,2})?)', expr)
    if m:
        def norm(t):
            t = t.strip()
            if ':' in t:
                hh, mm = t.split(':', 1)
                return "%02d:%02d" % (int(hh), int(mm))
            return "%02d:%02d" % (int(t), 0)
        return norm(m.group(1)), norm(m.group(2)), expr
    return None, None, expr

def parse_lesson_line(line):
    """解析事件列内单行课次文本，返回 dict 或 None（非课次/无法识别）。"""
    raw = line.strip()
    if not raw:
        return None
    # 纯数字 = 日历日期误入事件格
    if re.fullmatch(r'\d+', raw):
        return None
    # 节日/图例/作息文本整词命中直接丢弃
    for mk in NON_SESSION_MARKERS:
        if raw == mk:
            return None
    # 课次特征判定：L\d 前缀、时刻（点/冒号）、班标注、课程关键词
    has_L = bool(re.match(r'\s*L\d', raw))
    has_time = bool(re.search(r'点\s*$|[（(]?\s*\d{1,2}[:：]\d{1,2}', raw))
    has_band = bool(re.search(r'A\d|B\d', raw))
    has_kw = bool(re.search(r'考试|互动|讲座|救恩论|信仰|写作|福音|课程|圣约|摩西|讲道|使徒|圣灵|神论|逻辑|希伯来|英语|护教|法律|课堂管理', raw))
    if not (has_L or has_time or has_band or has_kw):
        return None

    text = raw
    # L 课次号（行首，可能带空格）
    lesson_no = ''
    m = re.match(r'\s*L(\d{1,2})\s*', text)
    if m:
        lesson_no = 'L' + m.group(1)
        text = text[m.end():]
    text = text.strip()

    # 类型词：考试/讲座/师生互动（先剥离「考试」以免混入课名）
    kind = ''
    if re.search(r'师生互动', text):
        kind = '师生互动'
    elif re.search(r'讲座', text):
        kind = '讲座'
    elif re.search(r'考试', text):
        kind = '考试'
    text = re.sub(r'考试', '', text, count=1).strip()

    # 定位时间括号（全/半角内出现时段数字）→ 之前为「课名+班标注」区
    tm = re.search(r'[（(]\s*\d{1,2}(?::\d{1,2})?\s*[-–~至]\s*\d{1,2}(?::\d{1,2})?[^（）()]*?[）)]', text)
    time_expr_raw = tm.group(0).strip() if tm else ''
    name_zone = text[:tm.start()].strip() if tm else text

    # 无时间括号时，若尾部存在注释性全角括号（如「（两周内五天课程）」「（密集）」）则先剥离，
    # 使班标注可落在行尾被识别。
    if not tm:
        mz = re.search(r'[（(][^（）()]*[）)]\s*$', name_zone)
        if mz and not re.search(r'\d{1,2}\s*[-–~至]\s*\d{1,2}', mz.group(0)):
            name_zone = name_zone[:mz.start()].strip()

    # 班标注 = 名称区尾部连续「字母+数字」段；课程名内全角括号（如「（二）」）不是班标注
    batch_label = ''
    m = re.search(r'([ABC]+\d+(?:[ABC]+\d+)*)\s*$', name_zone)
    if m:
        batch_label = m.group(1)
        name_zone = name_zone[:m.start()].rstrip(' （(（、,，· \t')
    subject_name = re.sub(r'\s+', '', name_zone.strip())

    # 无时间括号但有课程+班标注（A 部如「神论 A123」「救恩论 A123（两周内五天课程）」）
    if not time_expr_raw:
        time_expr = ''
        st = en = ''
        # 尝试整行直接解析时段（如行内无括号但有裸 7:45-9:45）
        st_t, en_t, _ = parse_time(text)
        if st_t and not tm:
            time_expr = text[text.find(str(st_t)):]
            st, en = st_t, en_t
        else:
            st, en, _ = parse_time('')
    else:
        time_expr = time_expr_raw
        st, en, _ = parse_time(time_expr)

    if not subject_name:
        return None
    return {
        'raw': raw,
        'subject_name': subject_name,
        'batch_label': batch_label,
        'lesson_no': lesson_no,
        'lesson_kind': kind,
        'time_expr': time_expr,
        'start_time': st or '',
        'end_time': en or '',
    }

def col_letter(i):
    s = ''
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s

def main():
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    wanted = {'家教': '家教', '文26下': '文26下', 'A': 'A', 'B12': 'B12'}
    rows = []
    notes = []
    per_sheet = {}
    for ws in wb.worksheets:
        sh = ws.title
        if sh not in wanted:
            continue
        count = 0
        for row in ws.iter_rows(min_row=4, max_row=45):
            # 先找该行日期列值映射
            # 遍历事件列
            for cell in row:
                col = col_letter(cell.column)
                if col not in EVENT_COLS:
                    continue
                v = cell.value
                if v is None:
                    continue
                txt = str(v).strip()
                if not txt or txt == '\n':
                    continue
                # 同月内的前一列=日期列（同一列对，偶数列在前）
                cnum = colnum(col)
                dcol = col_letter(cnum - 1)
                dcell = ws[f"{dcol}{cell.row}"]
                dv = dcell.value
                # 取日期：数值且当月内合法 1~31
                if isinstance(dv, (int, float)) and not isinstance(dv, bool):
                    day = int(dv)
                    yy, mm = PAIRS[dcol]  # dcol 必为 B/D/F/... 同月
                    try:
                        d = dt.date(yy, mm, day)
                    except ValueError:
                        d = None
                else:
                    d = None
                if d is None:
                    # 事件格同行没有日期值——可能是该月列对只有事件格而无日期（如 12 月行只放日期在相邻列）
                    # 向前找最近有日期的日期列
                    d = None
                    for cc in range(cnum - 2, 1, -1):
                        cl2 = col_letter(cc)
                        if cl2 not in DATE_COLS:
                            continue
                        dv2 = ws[f"{cl2}{cell.row}"].value
                        if isinstance(dv2, (int, float)) and not isinstance(dv2, bool):
                            yy2, mm2 = PAIRS[cl2]
                            try:
                                d2 = dt.date(yy2, mm2, int(dv2))
                                if d2.month == PAIRS[dcol][1] and d2.year == PAIRS[dcol][0]:
                                    d = d2
                            except ValueError:
                                pass
                            if d:
                                break
                if d is None:
                    notes.append(f"[{sh}] {col}{cell.row} 无日期可定，跳过格: {txt[:60]!r}")
                    continue
                # 该格内多行课次
                for line in txt.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    parsed = parse_lesson_line(line)
                    if parsed is None:
                        # 非课次格（节日等）
                        continue
                    weekday = CN_WEEKDAY[d.weekday()]
                    rows.append({
                        'source_sheet': sh,
                        'date': d.isoformat(),
                        'weekday': weekday,
                        'subject_name': parsed['subject_name'],
                        'batch_label': parsed['batch_label'],
                        'start_time': parsed['start_time'],
                        'end_time': parsed['end_time'],
                        'time_expr': parsed['time_expr'],
                        'lesson_no': parsed['lesson_no'],
                        'lesson_kind': parsed['lesson_kind'],
                        'raw_text': parsed['raw'],
                        'cell_ref': f"{col}{cell.row}",
                        'month_year': f"{d.year}-{d.month:02d}",
                    })
                    count += 1
        per_sheet[sh] = count
    # 汇总
    total = sum(per_sheet.values())
    with open(HERE + '/sessions_raw.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=[
            'source_sheet', 'date', 'weekday', 'subject_name', 'batch_label',
            'start_time', 'end_time', 'time_expr', 'lesson_no', 'lesson_kind',
            'raw_text', 'cell_ref', 'month_year'])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("每 sheet 课次计数:", per_sheet)
    print("总课次:", total)
    print("notes:", len(notes))
    for n in notes[:30]:
        print(" NOTE", n)

if __name__ == '__main__':
    main()
