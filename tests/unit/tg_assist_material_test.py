# -*- coding: utf-8 -*-
"""F7 材料归档纯函数的回归用例 —— **不需要数据库、不需要 Odoo**。

为什么值得单测这几件事：
  · 出网脱敏是红线：手机号/身份证/邮箱必须在上行前被换掉，漏一个就是把个人信息送出境；
  · 模型回话不可信（围栏、废话、中文键、缺字段）⇒ 宽容提取与归一必须永不抛异常；
  · 没配 LLM 时全靠规则抽取保底，分类/紧急度/截止日期都要有可预期结果；
  · Notion 对垃圾值直接 400 ⇒ date 只接受能变成 YYYY-MM-DD 的东西，「不知道」的格子不许写。

用法：python3 tests/unit/tg_assist_material_test.py   （退出码 0=全通过 / 1=有失败）
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = os.path.join(ROOT, 'custom_addons', 'edu_tg_assist', 'mattext.py')

_spec = importlib.util.spec_from_file_location('tg_assist_mattext', SPEC)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))


# ---------- 1) 出网前脱敏 ----------
_m, _n = M.mask_sensitive('联系 13812345678 或 a.b@c.com')
check('手机号被换掉', '13812345678' not in _m and '【手机号已脱敏】' in _m, _m)
check('邮箱被换掉', 'a.b@c.com' not in _m and '【邮箱已脱敏】' in _m, _m)
check('命中数=2', _n == 2, str(_n))
_m2, _n2 = M.mask_sensitive('身份证 11010519491231002X 卡号 6222020200112233')
check('身份证被换掉', '11010519491231002X' not in _m2, _m2)
check('银行卡被换掉', '6222020200112233' not in _m2, _m2)
check('长数字不会互相抢', _n2 >= 2, str(_n2))
check('空输入安全', M.mask_sensitive(None) == ('', 0) and M.mask_sensitive('') == ('', 0))
check('无敏感信息时原样返回', M.mask_sensitive('明天交材料')[0] == '明天交材料')

# ---------- 2) 宽容取 JSON ----------
check('干净 JSON', M.extract_json('{"title": "x"}') == {'title': 'x'})
check('去 ```json 围栏',
      M.extract_json('```json\n{"title": "x"}\n```') == {'title': 'x'})
check('去 ``` 围栏无语言', M.extract_json('```\n{"a": 1}\n```') == {'a': 1})
check('前后有废话', M.extract_json('好的，我抽取如下：\n{"a": 1}\n以上。') == {'a': 1})
check('嵌套也认', M.extract_json('废话 {"a": {"b": 2}} 尾巴') == {'a': {'b': 2}})
check('数组不是对象 -> None', M.extract_json('[1, 2]') is None)
check('纯废话 -> None', M.extract_json('我不知道该说什么') is None)
check('空串 / None -> None', M.extract_json('') is None and M.extract_json(None) is None)

# ---------- 3) 归一（中文键 + 乱类型 + 夹断）----------
_d = M.normalize_extract({'标题': '关于迎检', '紧急程度': '高', '分类': '通知',
                          '截止': '2026-10-12', '标签': ['a', 'b', 'a']})
check('中文键认得出', _d['title'] == '关于迎检' and _d['category'] == 'notice', str(_d))
check('紧急度别名 -> high', _d['urgency'] == 'high', _d['urgency'])
check('日期归成 ISO', _d['deadline'] == '2026-10-12', _d['deadline'])
check('标签去重保序', _d['tags'] == ['a', 'b'], str(_d['tags']))
_d2 = M.normalize_extract({'title': 'x' * 300, 'category': '???', 'urgency': '???',
                           'tags': 'a,b,c,d,e,f,g,h,i,j,k,l,m', 'deadline': '不是日期'})
check('标题夹到 TITLE_MAX', len(_d2['title']) == M.TITLE_MAX, str(len(_d2['title'])))
check('认不出的分类回 other', _d2['category'] == 'other')
check('认不出的紧急度回 normal', _d2['urgency'] == 'normal')
check('标签个数有上界', len(_d2['tags']) == M.TAG_MAX, str(len(_d2['tags'])))
check('垃圾日期 -> 空串', _d2['deadline'] == '', _d2['deadline'])
check('None/non-dict 不炸', M.normalize_extract(None)['category'] == 'other'
      and M.normalize_extract('x')['urgency'] == 'normal')

# ---------- 4) 日期归一 ----------
check('ISO 直通', M.iso_date('2026-10-12') == '2026-10-12')
check('斜杠/中文年月日', M.iso_date('2026/10/12') == '2026-10-12'
      and M.iso_date('2026年10月12日') == '2026-10-12')
check('今天/明天（有 today）',
      M.iso_date('明天截止', today='2026-10-10') == '2026-10-11')
check('月日跨年（已过 -> 明年）',
      M.iso_date('1月5日', today='2026-10-10') == '2027-01-05')
check('月日不跨年', M.iso_date('12月5日', today='2026-10-10') == '2026-12-05')
check('非法日期 -> 空串', M.iso_date('2026-02-30') == '' and M.iso_date('待定') == '')
check('相对词没 today -> 空串', M.iso_date('明天') == '')
check('None -> 空串', M.iso_date(None) == '')

# ---------- 5) 规则保底抽取 ----------
_r1 = M.rule_extract('报销通知：请于 2026年10月12日 前提交发票与费用清单，金额 1280 元，务必尽快。')
check('分类=财务', _r1['category'] == 'finance', _r1['category'])
check('紧急度=high', _r1['urgency'] == 'high', _r1['urgency'])
check('抽到截止日期', _r1['deadline'] == '2026-10-12', _r1['deadline'])
check('抽到金额', _r1['amount'] == '1280 元', _r1['amount'])
check('取第一行当标题', _r1['title'].startswith('报销通知'), _r1['title'])
_r2 = M.rule_extract('下周的会议安排', today='2026-10-10')
check('分类=日程', _r2['category'] == 'schedule', _r2['category'])
check('默认紧急度=normal', _r2['urgency'] == 'normal', _r2['urgency'])
check('没有金额就是空', _r2['amount'] == '', _r2['amount'])
check('年份不会被当金额', M.rule_extract('2026 年度计划')['amount'] == '',
      M.rule_extract('2026 年度计划')['amount'])
check('「不急」-> low', M.rule_extract('这个不急，下周再看')['urgency'] == 'low')
check('空文本不炸', M.rule_extract('')['category'] == 'other' and M.rule_extract(None)['title'] == '')

# ---------- 6) 规则 + LLM 合并 ----------
_rule = M.rule_extract('报销通知：请于 2026年10月12日 前提交发票，务必尽快。')
_merged = M.merge_extract(_rule, {'标题': '迎检材料', 'tags': ['迎检']})
check('LLM 的标题覆盖规则', _merged['title'] == '迎检材料', _merged['title'])
check('LLM 没说分类时规则留着', _merged['category'] == 'finance', _merged['category'])
check('LLM 没说紧急度时规则留着', _merged['urgency'] == 'high', _merged['urgency'])
check('LLM 没说的日期留着', _merged['deadline'] == '2026-10-12', _merged['deadline'])
check('LLM 明说 normal 才算数',
      M.merge_extract(_rule, {'urgency': 'normal'})['urgency'] == 'normal')
check('llm_raw=None 时纯规则', M.merge_extract(_rule, None)['category'] == 'finance')

# ---------- 7) 回执文案 ----------
_lines = M.digest_lines({'title': 'T', 'category': 'finance', 'urgency': 'high',
                         'deadline': '2026-10-12', 'tags': ['x']})
check('回执首行带标题', _lines[0] == '已归档：T', _lines[0])
check('回执用中文标签', '财务' in _lines[1] and '紧急' in _lines[1], _lines[1])
check('回执带截止', any('2026-10-12' in ln for ln in _lines))
check('回执无 Markdown 星号', not any('*' in ln for ln in _lines))

# ---------- 8) Notion payload ----------
_props = M.build_notion_properties({'title': 'T', 'category': 'finance',
                                    'deadline': '2026-10-12', 'tags': ['x']})
check('标题写成 title 属性', _props['Name']['title'][0]['text']['content'] == 'T', str(_props))
check('分类写成 select 中文名', _props['Category']['select']['name'] == '财务')
check('日期写成 date.start', _props['Deadline']['date']['start'] == '2026-10-12')
check('标签写成 multi_select', _props['Tags']['multi_select'] == [{'name': 'x'}])
check('**没给的格子不写**（不把「不知道」写成一般）',
      'Urgency' not in _props and 'Summary' not in _props, str(list(_props)))
_props2 = M.build_notion_properties({'title': 'T', 'urgency': 'normal'})
check('明说 normal 时才写紧急度', _props2.get('Urgency') == {'select': {'name': '一般'}}, str(_props2))
_fm = M.build_notion_properties({'title': 'T', 'category': 'notice'},
                                {'title': '名称', 'category': '分类'})
check('属性名可被 field_map 覆盖', set(_fm) == {'名称', '分类'}, str(_fm))
check('field_map 里的空值被忽略',
      'Name' in M.build_notion_properties({'title': 'T'}, {'title': '  '}))
_pl = M.build_notion_payload({'database_id': 'DB'}, {'title': 'T'}, body_text='正文')
check('payload 带 parent', _pl['parent'] == {'database_id': 'DB'})
check('payload 带正文块 paragraph',
      _pl['children'][0]['type'] == 'paragraph'
      and _pl['children'][0]['paragraph']['rich_text'][0]['text']['content'] == '正文')
check('无正文时不带 children', 'children' not in M.build_notion_payload({'database_id': 'DB'}, {'title': 'T'}))
_pl2 = M.build_notion_payload({'type': 'data_source_id', 'data_source_id': 'DS'}, {'title': 'T'})
check('支持新版 data_source parent', _pl2['parent']['data_source_id'] == 'DS')
_fallback = M.title_only_payload({'database_id': 'DB'}, '', body_text='正文')
check('保底 payload 只写 title', list(_fallback['properties']) == ['Name'])
check('保底 payload 标题为空时给默认名',
      _fallback['properties']['Name']['title'][0]['text']['content'] == '未命名材料')

# ---------- 9) 常量一致性 ----------
check('分类标签覆盖全部选项' , set(M.CATEGORY_LABELS) == set(M.CATEGORY_OPTIONS))
check('紧急度标签覆盖全部选项', set(M.URGENCY_LABELS) == set(M.URGENCY_OPTIONS))
check('默认字段映射名都在白名单里', set(M.DEFAULT_FIELD_MAP) <= set(M.KEY_ALIASES))

failed = 0
for name, ok, detail in results:
    if ok:
        print('PASS  %s' % name)
    else:
        failed += 1
        print('FAIL  %s%s' % (name, ('  → %s' % detail) if detail else ''))
print('共 %d 条，失败 %d 条' % (len(results), failed))
sys.exit(1 if failed else 0)