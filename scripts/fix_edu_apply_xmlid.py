# -*- coding: utf-8 -*-
"""修复 edu_apply 的孤儿行映射（xmlid 丢失导致 -u / 生产部署被 UNIQUE 撞死）+ 同类孤儿普查。

背景（2026-09-12 实测）
-----------------------
edu_apply 的数据文件是 `<data noupdate="1">` 预置：`data/form_meta_data.xml:53` 定义了
`<record id="fld_name" model="edu.apply.field">`（name='name', label='姓名', ...）。
库里该行还在（id=32），但 **ir_model_data 里的 `edu_apply.fld_name` 映射丢了** →
`-u edu_apply` 走到该记录时按 CREATE 处理 → 撞 `edu_apply_field_name_uniq = UNIQUE(name)`：

    ParseError: while parsing .../edu_apply/data/form_meta_data.xml:53
    DETAIL:  Key (name)=(name) already exists.

**升级与部署双双被阻断**（deploy_myedu.sh 也跑 -u）。本脚本只做一件事：把丢失的映射补回去。

原则（与任务契约一致）
---------------------
- **只建映射，绝不删行、绝不动 label/required/locked/active 等业务字段**；
- 建映射前先校验现有行内容与 XML 声明一致，不一致就 ABORT 交人工（不猜）；
- **幂等**：映射已存在则跳过并打印（连跑两次结果一致）；
- 顺带**只列清单**地普查其他 edu_* 模块的同型孤儿（XML 有记录、xmlid 丢失、唯一键会撞），不顺手修。

用法
----
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
        -r odoo -w odoo -d edu19 --no-http < scripts/fix_edu_apply_xmlid.py

    # 只普查不修（干跑）：加环境变量
    docker compose exec -T -e FIX_DRY_RUN=1 web odoo shell ... --no-http < scripts/fix_edu_apply_xmlid.py

生产预部署步骤（**执行前需用户显式确认**）
----------------------------------------
1. 确认生产库是否受影响：在生产容器里跑一次干跑（`-e FIX_DRY_RUN=1`），看输出里
   `edu_apply.fld_name` 是 SKIP（已修好）还是 FIXED 候选；
   —— **本文档撰写时生产是否受影响：未确认**（未对生产库做任何只读探测以上动作）。
2. 若为孤儿：**先跑本脚本（不加 DRY_RUN）补映射**，看到 `FIXED` 或 `SKIP` 且无 `ABORT`；
3. **再**执行 `bash scripts/deploy_myedu.sh`；
4. 若看到 `ABORT`：停止部署，人工核对既有行与 XML 内容差异。
"""
import os
import re
import xml.etree.ElementTree as ET

env = env
DRY_RUN = os.environ.get('FIX_DRY_RUN') == '1'
ADDONS = '/mnt/custom-addons'
IMD = env['ir.model.data'].sudo()

# 需要修复的孤儿映射：(module, xmlid, model, 匹配既有行的 domain, 现有行必须与 XML 一致的字段)
FIXES = [
    ('edu_apply', 'fld_name', 'edu.apply.field',
     [('name', '=', 'name')],
     {'label': '姓名', 'type': 'char', 'required': True, 'locked': True,
      'active': True}),
]


def fix_one(module, name, model, domain, expect):
    xmlid = '%s.%s' % (module, name)
    Model = env[model].sudo()
    existing = IMD.search([('module', '=', module), ('name', '=', name),
                           ('model', '=', model)], limit=1)
    if existing:
        print('SKIP  %s：映射已存在 → %s(res_id=%s)' % (xmlid, model, existing.res_id))
        return 'skip'
    rows = Model.search(domain)
    if not rows:
        print('MISS  %s：库里找不到匹配 %s 的行 → 不建映射（交给 XML 正常创建）'
              % (xmlid, domain))
        return 'miss'
    row = rows[0]
    if len(rows) > 1:
        print('WARN  %s：匹配到 %d 行，按 id 最小者（%s）处理' % (xmlid, len(rows), row.id))
    bad = {k: (getattr(row, k), v) for k, v in expect.items()
           if getattr(row, k) != v}
    if bad:
        print('ABORT %s：既有行与 XML 声明不一致 %s → 拒绝建映射，请人工核对' % (xmlid, bad))
        return 'abort'
    if DRY_RUN:
        print('DRY   %s：将建映射 → res_id=%s（%s）'
              % (xmlid, row.id, {k: getattr(row, k) for k in expect}))
        return 'dry'
    # noupdate 与数据文件一致（form_meta_data.xml 是 <data noupdate="1">）：
    # 保持 True，避免 -u 覆盖管理员的字段调整（该模块的既定设计）。
    IMD.create({'module': module, 'name': name, 'model': model,
                'res_id': row.id, 'noupdate': True})
    print('FIXED %s → res_id=%s（%s）' % (xmlid, row.id,
                                          {k: getattr(row, k) for k in expect}))
    return 'fixed'


def _unique_cols(model_name):
    """模型表上的 UNIQUE 约束 → [(约束名, [列...])]。"""
    table = env[model_name]._table
    env.cr.execute("""SELECT conname, pg_get_constraintdef(oid)
                      FROM pg_constraint
                      WHERE conrelid = %s::regclass AND contype = 'u'""", (table,))
    out = []
    for conname, definition in env.cr.fetchall():
        m = re.search(r'UNIQUE\s*\(([^)]+)\)', definition or '')
        if m:
            out.append((conname, [c.strip().strip('"') for c in m.group(1).split(',')]))
    return out


def _xml_records(module):
    """扫描模块的 XML，产出 (xmlid, model, {field: value})（只取简单文本值）。"""
    base = os.path.join(ADDONS, module)
    found = []
    for root_dir, _dirs, files in os.walk(base):
        if os.sep + 'i18n' in root_dir or os.sep + 'tests' in root_dir:
            continue
        for fn in sorted(files):
            if not fn.endswith('.xml'):
                continue
            path = os.path.join(root_dir, fn)
            try:
                tree = ET.parse(path)
            except Exception:
                continue
            for rec in tree.getroot().iter('record'):
                rid, model = rec.get('id'), rec.get('model')
                if not rid or not model or '.' in rid:
                    continue
                vals = {}
                for f in rec.findall('field'):
                    fname, text = f.get('name'), (f.text or '').strip()
                    if fname and text and not f.get('ref') and not f.get('eval'):
                        vals[fname] = text
                found.append(('%s.%s' % (module, rid), model, vals))
    return found


def survey():
    """同类孤儿普查：XML 有记录、xmlid 丢失、且唯一键会撞 → 只列清单，不修。"""
    print('')
    print('=== 同类孤儿普查（只列清单，不修）===')
    hits = []
    modules = sorted(d for d in os.listdir(ADDONS)
                     if d.startswith('edu_') and os.path.isdir(os.path.join(ADDONS, d)))
    for module in modules:
        for xmlid, model, vals in _xml_records(module):
            if model not in env:
                continue
            _module, name = xmlid.split('.', 1)
            if IMD.search_count([('module', '=', _module), ('name', '=', name),
                                 ('model', '=', model)]):
                continue                      # 映射在 → 不是孤儿
            for conname, cols in _unique_cols(model):
                keys = [c for c in cols if c in vals]
                if len(keys) != len(cols):
                    continue                  # 该唯一键在 XML 里没给全，无法判定
                domain = [(c, '=', vals[c]) for c in keys]
                try:
                    row = env[model].sudo().search(domain, limit=1)
                except Exception:
                    continue
                if row:
                    hits.append((module, model, name,
                                 '%s%s' % (conname, keys), row.id))
    if not hits:
        print('  无同型孤儿（未发现「XML 有 + xmlid 丢失 + 唯一键会撞」的组合）')
    for module, model, name, key, res_id in hits:
        print('  %-12s %-22s %-14s 冲突键=%s 现有行 id=%s'
              % (module, model, name, key, res_id))
    return hits


print('=== edu_apply 孤儿映射修复%s ===' % ('（DRY RUN）' if DRY_RUN else ''))
results = [fix_one(*spec) for spec in FIXES]
hits = survey()
if not DRY_RUN and any(r == 'fixed' for r in results):
    env.cr.commit()
    print('')
    print('COMMITTED 修复结果：%s' % results)
else:
    print('')
    print('未提交（无 FIXED 或处于 DRY RUN）：%s' % results)
print('普查命中：%d 条（列表见上；本脚本不修它们）' % len(hits))
