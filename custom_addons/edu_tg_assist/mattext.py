# -*- coding: utf-8 -*-
"""F7 材料归档的**纯函数**（不 import Odoo、不联网）—— 单测能直接加载。

三件事都在这里，别处不做：
  1. mask_sensitive()：**出网前**脱敏（手机号/身份证/银行卡/邮箱）。送 LLM 与 Notion 的
     是脱敏文本；本地 material 表仍存原文（内部管理用途，见设计 §9.11.5 B10）。
  2. extract_json() / normalize_extract()：模型回来的一坨**不保证是合法 JSON**（带 ```json
     围栏、前后废话、字段缺失、类型乱）⇒ 宽容提取 + 逐字段归一到允许值，绝不因为
     模型乱答就抛异常（设计 §9.11.6 降级表）。
  3. rule_extract()：没有 LLM（未配密钥或调用失败）时的**保底抽取** —— 纯规则也能填出
     标题/分类/紧急度/截止/金额，保证 F7 在零外部依赖下依然能用。

用法（单测直接 importlib 加载本文件，不需要 Odoo/DB）：
    python3 tests/unit/tg_assist_material_test.py
"""
import json
import re

TITLE_MAX = 120
SUMMARY_MAX = 500
TODO_MAX = 300
TAG_MAX = 10
TAG_LEN_MAX = 24
BODY_MAX = 1800
MASK_TOKEN = '【%s已脱敏】'

CATEGORY_OPTIONS = ('notice', 'material', 'report', 'finance', 'personnel', 'schedule', 'other')
URGENCY_OPTIONS = ('low', 'normal', 'high', 'urgent')
CATEGORY_LABELS = {
    'notice': '通知', 'material': '材料', 'report': '汇报', 'finance': '财务',
    'personnel': '人事', 'schedule': '日程', 'other': '其他',
}
URGENCY_LABELS = {'low': '不急', 'normal': '一般', 'high': '紧急', 'urgent': '特急'}

# 出网脱敏：顺序重要 —— 身份证 18 位会被「银行卡」规则吞掉，所以先长后短。
RE_INVITE = re.compile(r'(?<![A-Za-z0-9])(?:TGB-)?STU-[A-Z0-9]{4,16}(?![A-Za-z0-9])')
RE_IDCARD = re.compile(r'(?<!\d)\d{17}[\dXx](?!\w)|(?<!\d)\d{15}(?!\d)')
RE_BANK = re.compile(r'(?<!\d)\d{16,19}(?!\d)')
RE_PHONE = re.compile(r'(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)')
RE_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
MASK_RULES = (
    (RE_INVITE, '邀请码'),
    (RE_IDCARD, '身份证'),
    (RE_BANK, '银行卡'),
    (RE_PHONE, '手机号'),
    (RE_EMAIL, '邮箱'),
)

# LLM 可能用中文键回答（提示词里是中文语境），别名一律认。
KEY_ALIASES = {
    'title': ('title', '标题', 'subject', '主题', 'name'),
    'summary': ('summary', '摘要', '摘要内容', '概述', '简介'),
    'category': ('category', '分类', '类别', '类型'),
    'urgency': ('urgency', '紧急程度', '紧急度', '优先级', 'priority'),
    'deadline': ('deadline', '截止', '截止时间', '截止日期', 'deadline_at', 'due', 'due_date'),
    'amount': ('amount', '金额', '费用'),
    'people': ('people', '人员', '相关人', '涉及人员'),
    'tags': ('tags', '标签', '关键词', 'keywords'),
    'todo': ('todo', '待办', '下一步', 'action', 'next_step'),
}
CATEGORY_ALIASES = {
    '通知': 'notice', '公告': 'notice', '教务通知': 'notice',
    '材料': 'material', '资料': 'material', '文件': 'material',
    '汇报': 'report', '报告': 'report', '总结': 'report',
    '财务': 'finance', '报销': 'finance', '费用': 'finance', '预算': 'finance',
    '人事': 'personnel', '招聘': 'personnel', '排班': 'personnel',
    '日程': 'schedule', '安排': 'schedule', '会议': 'schedule',
    '其他': 'other', '其它': 'other',
}
URGENCY_ALIASES = {
    '低': 'low', '不急': 'low', 'low': 'low',
    '中': 'normal', '一般': 'normal', '普通': 'normal', 'normal': 'normal', 'medium': 'normal',
    '高': 'high', '紧急': 'high', '急': 'high', 'high': 'high',
    '特急': 'urgent', '十万火急': 'urgent', 'urgent': 'urgent',
}
CATEGORY_KEYWORDS = (
    ('finance', ('报销', '发票', '费用', '预算', '打款', '付款', '差旅', '采购')),
    ('schedule', ('会议', '日程', '安排', '时间', '排课', '值班', '排班')),
    ('personnel', ('入职', '离职', '招聘', '面试', '工资', '人事', '考勤', '请假')),
    ('report', ('汇报', '报告', '总结', '周报', '月报', '统计')),
    ('notice', ('通知', '公告', '须知', '提醒', '要求', '务必')),
    ('material', ('材料', '名单', '表格', '附件', '文件', '资料', '申请表')),
)
HIGH_WORDS = ('紧急', '尽快', '立刻', '马上', '今天内', '今日内', '截止今天', 'asap', '特急')
LOW_WORDS = ('不急', '有空', '下周再看', '不着急')
RE_ISO = re.compile(r'(\d{4})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})\s*日?')
RE_MD = re.compile(r'(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日')
RE_AMOUNT = re.compile(r'(?:¥|￥|RMB\s*)?(\d+(?:\.\d+)?)\s*(?:万元|元|块)')
RE_HANDLE = re.compile(r'@([A-Za-z][A-Za-z0-9_]{2,31})')
REL_DAYS = {'今天': 0, '今日': 0, '明天': 1, '明日': 1, '后天': 2}


def mask_sensitive(text):
    """出网前脱敏 —— 返回 (脱敏后文本, 命中条数)。非字符串一律当空串。"""
    if not isinstance(text, str) or not text:
        return '', 0
    out = text
    hits = 0
    for rx, label in MASK_RULES:
        token = MASK_TOKEN % label
        out, n = rx.subn(token, out)
        hits += n
    return out, hits


def _one_line(value, limit):
    """压成一行并截断（Telegram 与 Notion 都不喜欢造出来的裸换行）。"""
    if value is None:
        return ''
    if isinstance(value, (list, tuple)):
        value = '、'.join(str(v) for v in value if v)
    text = re.sub(r'\s+', ' ', str(value)).strip()
    return text[:limit]


def _as_list(value, limit=TAG_MAX, item_max=TAG_LEN_MAX):
    """任何形状都归成去重后的短字符串列表（LLM 会给字符串/数组/None）。"""
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r'[,，;；、|/\s]+', value)
    elif isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            if isinstance(item, (list, tuple, dict)):
                parts.append(str(item.get('name') if isinstance(item, dict) else (item[0] if item else '')))
            else:
                parts.append(str(item))
    else:
        parts = [str(value)]
    out = []
    for part in parts:
        one = _one_line(part, item_max)
        if one and one not in out:
            out.append(one)
        if len(out) >= limit:
            break
    return out


def _pick_enum(value, options, aliases, default):
    """把模型给的中文/大小写/空白值折叠成枚举之一，认不出就回落 default。"""
    if value is None:
        return default
    key = _one_line(value, 32).lower().strip('。.．')
    if not key:
        return default
    if key in options:
        return key
    if key in aliases:
        return aliases[key]
    for alias, mapped in aliases.items():
        if alias and alias in key:
            return mapped
    return default


def _json_candidates(raw):
    """从一坨文本里挑出可能的 JSON 对象：整串 → 首个 { 到末个 } → 每个平衡段。"""
    yield raw
    start, end = raw.find('{'), raw.rfind('}')
    if start >= 0 and end > start:
        yield raw[start:end + 1]
    depth = 0
    seg_start = None
    for idx, ch in enumerate(raw):
        if ch == '{':
            if depth == 0:
                seg_start = idx
            depth += 1
        elif ch == '}' and depth:
            depth -= 1
            if depth == 0 and seg_start is not None:
                yield raw[seg_start:idx + 1]
                seg_start = None


def extract_json(text):
    """宽容取第一个合法 JSON 对象；取不到返回 None（**不抛异常**）。"""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    fence = re.search(r'```(?:json)?\s*(.+?)```', raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    for cand in _json_candidates(raw):
        try:
            data = json.loads(cand)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _get_alias(data, field):
    for key in KEY_ALIASES.get(field, (field,)):
        if key in data and data[key] not in (None, '', [], {}):
            return data[key]
    return None


def normalize_extract(data):
    """把任意 dict 归一成九个固定字段 —— 所有下游只认这个形状。"""
    data = data if isinstance(data, dict) else {}
    return {
        'title': _one_line(_get_alias(data, 'title'), TITLE_MAX),
        'summary': _one_line(_get_alias(data, 'summary'), SUMMARY_MAX),
        'category': _pick_enum(_get_alias(data, 'category'), CATEGORY_OPTIONS, CATEGORY_ALIASES, 'other'),
        'urgency': _pick_enum(_get_alias(data, 'urgency'), URGENCY_OPTIONS, URGENCY_ALIASES, 'normal'),
        'deadline': iso_date(_get_alias(data, 'deadline')),
        'amount': _one_line(_get_alias(data, 'amount'), 32),
        'people': _as_list(_get_alias(data, 'people'), TAG_MAX, 32),
        'tags': _as_list(_get_alias(data, 'tags')),
        'todo': _one_line(_get_alias(data, 'todo'), TODO_MAX),
    }


def iso_date(value, today=None):
    """只接受能变成 YYYY-MM-DD 的东西（含 今天/明天/后天 + today），否则空串。

    Notion 的 date 属性对垃圾值直接 400 ⇒ 宁可不写这一格，也不能让整页建不出来。
    """
    if value is None:
        return ''
    raw = _one_line(value, 40)
    if not raw:
        return ''
    for word, delta in REL_DAYS.items():
        if word in raw and today:
            try:
                y, m, d = (int(x) for x in str(today).split('-')[:3])
            except (ValueError, TypeError):
                break
            import datetime as _dt
            got = _dt.date(y, m, d) + _dt.timedelta(days=delta)
            return got.isoformat()
    if raw in REL_DAYS and not today:
        return ''
    hit = RE_ISO.search(raw)
    if hit:
        y, m, d = (int(x) for x in hit.groups())
        return _safe_iso(y, m, d)
    hit = RE_MD.search(raw)
    if hit and today:
        try:
            year = int(str(today).split('-')[0])
        except (ValueError, TypeError, IndexError):
            return ''
        m, d = int(hit.group(1)), int(hit.group(2))
        got = _safe_iso(year, m, d)
        if got and today and got < str(today)[:10]:
            got = _safe_iso(year + 1, m, d)
        return got
    head = raw[:10]
    if re.match(r'^\d{4}-\d{2}-\d{2}$', head):
        return _safe_iso(*(int(x) for x in head.split('-')))
    return ''


def _safe_iso(year, month, day):
    import datetime as _dt
    try:
        return _dt.date(year, month, day).isoformat()
    except ValueError:
        return ''


def rule_extract(text, today=None):
    """纯规则保底抽取 —— 没有 LLM 也必须有东西落库。"""
    raw = text if isinstance(text, str) else ''
    lines = [_one_line(ln, TITLE_MAX) for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln]
    low = raw.lower()
    category = 'other'
    for name, words in CATEGORY_KEYWORDS:
        if any(word in raw or word in low for word in words):
            category = name
            break
    urgency = 'normal'
    if any(word in raw or word in low for word in HIGH_WORDS):
        urgency = 'high'
    elif any(word in raw for word in LOW_WORDS):
        urgency = 'low'
    amount = ''
    hit = RE_AMOUNT.search(raw)
    if hit:
        amount = ('%s 元' % hit.group(1))[:32]
    todo = ''
    for ln in lines:
        if any(word in ln for word in ('请', '记得', '需要', '务必', '尽快')):
            todo = ln[:TODO_MAX]
            break
    tags = _as_list([CATEGORY_LABELS.get(category, category)] + RE_HANDLE.findall(raw))
    return {
        'title': lines[0][:TITLE_MAX] if lines else '',
        'summary': _one_line(raw, SUMMARY_MAX),
        'category': category,
        'urgency': urgency,
        'deadline': iso_date(raw, today=today),
        'amount': amount,
        'people': _as_list(RE_HANDLE.findall(raw), TAG_MAX, 32),
        'tags': tags,
        'todo': todo,
    }


def merge_extract(rule_data, llm_raw):
    """规则结果打底、LLM 说了的格子覆盖它。

    入参 llm_raw 是**模型原始 dict**（可为 None）—— 不能先 normalize 再比，因为
    normalize_extract 会给缺失字段填 other/normal，那样就分不清「模型说是普通」
    和「模型压根没说」（后者必须让规则结果留着）。
    """
    rule_norm = normalize_extract(rule_data)
    llm_norm = normalize_extract(llm_raw)
    src = llm_raw if isinstance(llm_raw, dict) else {}
    out = {}
    for key, value in rule_norm.items():
        supplied = _get_alias(src, key) is not None
        better = llm_norm.get(key)
        out[key] = better if (supplied and better) else value
    return out


def digest_lines(data):
    """第二条私聊回执的正文行（纯文本，不含 Markdown）。"""
    data = normalize_extract(data)
    lines = ['已归档：%s' % (data['title'] or '（无标题）')]
    lines.append('分类：%s ／ 紧急度：%s' % (CATEGORY_LABELS.get(data['category'], data['category']),
                                        URGENCY_LABELS.get(data['urgency'], data['urgency'])))
    if data['deadline']:
        lines.append('截止：%s' % data['deadline'])
    if data['amount']:
        lines.append('金额：%s' % data['amount'])
    if data['people']:
        lines.append('相关人：%s' % '、'.join(data['people']))
    if data['todo']:
        lines.append('待办：%s' % data['todo'])
    if data['tags']:
        lines.append('标签：%s' % '、'.join(data['tags']))
    if data['summary']:
        lines.append('摘要：%s' % data['summary'][:200])
    return lines


def _rt(text):
    return [{'type': 'text', 'text': {'content': text}}]


DEFAULT_FIELD_MAP = {
    'title': 'Name',
    'summary': 'Summary',
    'category': 'Category',
    'urgency': 'Urgency',
    'deadline': 'Deadline',
    'tags': 'Tags',
}


def _supplied(data):
    """哪些字段是**真有人给过**的（给 '' / [] 之后要被当成没给）。

    为什么需要：normalize_extract 会给缺失字段填 other/normal，直接照着写 Notion 就会
    把「不知道」写成「其他/一般」。用原始 dict 反查一遍就分得清。
    """
    src = data if isinstance(data, dict) else {}
    return {key: _get_alias(src, key) is not None for key in KEY_ALIASES}


def build_notion_properties(data, field_map=None):
    """按「属性名 → 值」拼 Notion properties；只写有值的格子（只读属性一律不碰）。

    属性名对不上 Notion 库 schema 时 Notion 会 400 —— 调用方必须准备好「保底只写 title」
    的回退（见 notion.py），这里只负责拼对形状。
    """
    has = _supplied(data)
    data = normalize_extract(data)
    fm = dict(DEFAULT_FIELD_MAP)
    if isinstance(field_map, dict):
        for key, value in field_map.items():
            if key in fm and isinstance(value, str) and value.strip():
                fm[key] = value.strip()
    props = {}
    if data['title']:
        props[fm['title']] = {'title': _rt(data['title'])}
    if data['summary'] and fm.get('summary'):
        props[fm['summary']] = {'rich_text': _rt(data['summary'])}
    if has.get('category') and data['category'] and fm.get('category'):
        props[fm['category']] = {'select': {'name': CATEGORY_LABELS.get(data['category'], data['category'])}}
    if has.get('urgency') and data['urgency'] and fm.get('urgency'):
        props[fm['urgency']] = {'select': {'name': URGENCY_LABELS.get(data['urgency'], data['urgency'])}}
    if data['deadline'] and fm.get('deadline'):
        props[fm['deadline']] = {'date': {'start': data['deadline']}}
    if data['tags'] and fm.get('tags'):
        props[fm['tags']] = {'multi_select': [{'name': t} for t in data['tags']]}
    return props


def build_notion_payload(parent, data, field_map=None, body_text=''):
    """POST /v1/pages 的完整 payload（parent + properties + 可选正文块）。

    parent 由调用方给：数据库时代是 {'database_id': ...}，新版 data source 是
    {'type': 'data_source_id', 'data_source_id': ...} —— 见 docs/research/ai-archive-and-notion.md §4。
    """
    payload = {'parent': parent, 'properties': build_notion_properties(data, field_map)}
    body = _one_line(body_text, BODY_MAX)
    if body:
        payload['children'] = [{
            'object': 'block', 'type': 'paragraph',
            'paragraph': {'rich_text': _rt(body)},
        }]
    return payload


def title_only_payload(parent, title, body_text=''):
    """保底回退：只写 title（+正文块）。属性名对不上 schema 时用这个再试一次。"""
    payload = {'parent': parent, 'properties': {DEFAULT_FIELD_MAP['title']: {'title': _rt(_one_line(title, TITLE_MAX) or '未命名材料')}}}
    body = _one_line(body_text, BODY_MAX)
    if body:
        payload['children'] = [{
            'object': 'block', 'type': 'paragraph',
            'paragraph': {'rich_text': _rt(body)},
        }]
    return payload
