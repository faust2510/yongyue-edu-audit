# -*- coding: utf-8 -*-
"""导航重复入口收口（t10）：把 3 个指向空页 /jobs 的「工作」入口收成 0 个，并让「工作机会」直指有效页。

## 背景（本机实测 2026-09-17）
- `website.menu` 里有 3 条名为「工作」、url=`/jobs` 的重复入口：
  191 / 197（父「更多」=4）、198（父「默认主菜单」=1；xmlid `website_hr_recruitment.website_menu_jobs`
  —— 原生招聘模块的菜单）。
- `/jobs` 实测 **HTTP 200 但内容空壳**：原生 `hr_job = 0` 条，页面正文没有职位。
  ⇒ 这类"200 空页"正是验收标准要防的形态：**可达 ≠ 有内容**。
- 有效替代：`/campus/jobs`（edu_public 自研，200，2 条在招岗位）、`/alumni/jobs`（200）。

## 玩法（宿主侧直连 JSON-RPC，不经过 odoo shell —— 避免引号/字符集嵌套坑）
    python3 scripts/fix_nav_duplicates.py --export     # 导出导航树（前后对照）
    python3 scripts/fix_nav_duplicates.py --dry-run    # 只报将删/将改
    python3 scripts/fix_nav_duplicates.py --apply      # 先备份，再删 3 条 + 188 改指 /campus/jobs
    python3 scripts/fix_nav_duplicates.py --rollback   # 依备份重建被删记录 + 还原 188
    python3 scripts/fix_nav_duplicates.py --status     # 只读：导航条数 / /jobs 入口 / 188 与 189 的 url

## 凭据（t81 收口）
- **唯一声明点**在 ADMIN_LOGIN / ADMIN_PASSWORD，可用 EDU_ADMIN_LOGIN /
  EDU_ADMIN_PASSWORD 覆盖；口令不出现在任何输出里（打印只出现登录名）。
- 旧值写死 ('admin','admin')，而**本库 admin 的口令是 demo123** ⇒ 实测登录被拒。
  本脚本原本就会 SystemExit（属"响亮"，不是静默失效），但凭据本身仍是错的：
  每次调用都会重新登一次、每次都失败；现在改为**登录一次并复用**。
- 写操作脚本的纪律：**没登上绝不写**（下面的 _session() 会在第一次 kw 前就退出）。

## 红线
- 只动 website.menu 里 **url=/jobs 的入口** + 容器 188；**不碰 ir.ui.menu**（菜单收口另有工具）。
- 收口口径按 **url 全量识别**（不写死 id）：实测出现过 rollback 试错留下的孤儿（203/204 指向 /jobs
  却不在原清单里），只按 id 收口会漏网。
- 删除前必备份；`--rollback` 能据备份**重建**（会实测一次）。
- 不动任何业务数据（`hr.job` 表、岗位记录都不动）。
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tests/audit'))
import audit_lib as A  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, 'docs/audit/menu-consolidation')
BACKUP = os.path.join(OUTDIR, 'nav-menu-backup.json')
DROP_IDS = [191, 197, 198]
KEEP_ID = 188
KEEP_URL = '/campus/jobs'
FIELDS = ['id', 'name', 'url', 'parent_id', 'sequence', 'website_id', 'page_id']
MODE = sys.argv[1] if len(sys.argv) > 1 else '--dry-run'


# ---- 凭据：**唯一声明点**（t81）----
# 口令只在这里出现，且**不打印**（打印只出现登录名）。旧值 ('admin','admin') 在
# 本库是**失效凭据**（admin 的口令是 demo123，实测 AccessDenied）。
ADMIN_LOGIN = os.environ.get('EDU_ADMIN_LOGIN', 'admin')
ADMIN_PASSWORD = os.environ.get('EDU_ADMIN_PASSWORD', 'demo123')

_SESSION = None


def _session():
    """登录一次并复用。失败**响亮退出**：本脚本是写操作脚本，没登上就绝不写。

    （旧实现每次 kw() 都重新 A.login —— 凭据错时"第一次调用即退出"，行为上是响亮的，
    但把失败点散在每个调用里；改成单点后，凭据问题与写入问题不再混在一起。）
    """
    global _SESSION
    if _SESSION is None:
        s, uid, err = A.login(ADMIN_LOGIN, ADMIN_PASSWORD)
        if not uid:
            raise SystemExit(
                '登录失败（login=%s）：%s\n'
                '—— **任何写入动作都不会执行**。口令用 EDU_ADMIN_PASSWORD 覆盖'
                '（口令不会被打印）。' % (ADMIN_LOGIN, err))
        _SESSION = s
    return _SESSION


def kw(model, method, args=None, kwargs=None):
    return A.kw(_session(), model, method, args, kwargs)


def dump_tree():
    recs = kw('website.menu', 'search_read', [[], FIELDS], {'order': 'id'})
    for r in recs:
        r['parent_id'] = r['parent_id'][0] if r.get('parent_id') else None
        r['website_id'] = r['website_id'][0] if r.get('website_id') else None
        r['page_id'] = r['page_id'][0] if r.get('page_id') else None
    return recs



def _fix_id(cur_id, want_id):
    """把 website_menu 记录 id 改成原值（ORM 不支持显式 id，只能 SQL）。"""
    import subprocess
    sql = ("UPDATE website_menu SET id = %d WHERE id = %d; "
           "UPDATE website_menu SET parent_id = %d WHERE parent_id = %d AND %d IS NOT NULL;"
           % (want_id, cur_id, want_id, cur_id, want_id))
    # 父指针也要跟着改（被删记录的子项若有引用）
    sql = ("UPDATE website_menu SET id = %d WHERE id = %d;" % (want_id, cur_id))
    r = subprocess.run(['docker', 'exec', 'edu19-clone-db-1', 'psql', '-U', 'odoo', '-d', 'edu19',
                        '-v', 'ON_ERROR_STOP=1', '-c', sql], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write('改 id %d→%d 失败：%s\n' % (cur_id, want_id, r.stderr[:300]))
        sys.exit(1)
    r2 = subprocess.run(['docker', 'exec', 'edu19-clone-db-1', 'psql', '-U', 'odoo', '-d', 'edu19',
                         '-v', 'ON_ERROR_STOP=1', '-c',
                         "UPDATE website_menu SET parent_id = %d WHERE parent_id = %d;" % (want_id, cur_id)],
                        capture_output=True, text=True)
    # 序列可能落后，补齐（避免后续 create 撞 id）
    subprocess.run(['docker', 'exec', 'edu19-clone-db-1', 'psql', '-U', 'odoo', '-d', 'edu19', '-c',
                    "SELECT setval('website_menu_id_seq', GREATEST((SELECT MAX(id) FROM website_menu), %d));"
                    % want_id], capture_output=True, text=True)







def jobs_entries(tree):
    """**按 url 找**全部指向 /jobs 的入口 —— 不写死 id。
    为什么：实测出现过"无名孤儿"（rollback 试错留下的 203/204，指向 /jobs 却不在原清单里）。
    只按 id 收口会让这类记录漏网；按 url 收口才是"这个空页入口彻底清掉"的正确口径。"""
    return [m for m in tree if (m['url'] or '') == '/jobs']

if MODE in ('--status',):
    tree = dump_tree()
    by_id = {m['id']: m for m in tree}
    print('website.menu = %d ｜ 指向 /jobs 的入口 = %s' % (
        len(tree), [m['id'] for m in jobs_entries(tree)] or '无'))
    for i in (188, 189):
        m = by_id.get(i)
        print('  %-4s %-10s url=%s' % (i, (m or {}).get('name', '?'), (m or {}).get('url')))
    sys.exit(0)

if MODE == '--export':
    tree = dump_tree()
    p = os.path.join(OUTDIR, 'nav-tree-after.json')
    io.open(p, 'w', encoding='utf-8').write(json.dumps(tree, ensure_ascii=False, indent=1))
    print('已导出导航树 %s（%d 条）' % (p, len(tree)))
    print('指向 /jobs 的：%s' % [(m['id'], m['name'], m['parent_id']) for m in tree
                             if (m['url'] or '') == '/jobs'])
    sys.exit(0)

if MODE == '--dry-run':
    tree = dump_tree()
    by_id = {m['id']: m for m in tree}
    print('将删除的重复入口（按 url=/jobs 全量识别，含孤儿）：')
    for m in jobs_entries(tree):
        tag = '' if m['id'] in DROP_IDS else '  ← 孤儿（不在原备份清单内）'
        print('   %-4s name=%-8s url=%s parent=%s%s' % (m['id'], m['name'], m['url'], m['parent_id'], tag))
    if not jobs_entries(tree):
        print('   （无：/jobs 入口已为 0）')
    m = by_id.get(KEEP_ID)
    print('将改指的容器：%s（当前 url=%s → %s）' % (
        ('%s id=%s' % (m['name'], KEEP_ID)) if m else KEEP_ID,
        m['url'] if m else '?', KEEP_URL))
    sys.exit(0)

if MODE == '--apply':
    tree = dump_tree()
    by_id = {m['id']: m for m in tree}
    keep = by_id.get(KEEP_ID) or {}
    bak = {'note': 'apply 之前的 website.menu 快照（rollback 依此重建被删记录）',
           'drop': jobs_entries(tree),
           'keep': {'id': KEEP_ID, 'url_before': keep.get('url'),
                    'parent_id': keep.get('parent_id'), 'sequence': keep.get('sequence')}}
    # ⚠ 备份策略：**不要用"次要 apply"覆盖掉有效备份**。
    #   实测教训：rollback 之后再 apply 时 by_id 里已无 191/197/198 ⇒ drop=0，
    #   若直接覆盖，备份就退化成"没有东西可还原"，回滚能力被静默摧毁。
    #   规则：仅当**新备份能提供更多可还原内容**（drop 条数不减少）时才覆盖；否则写 .bak 留档。
    if os.path.exists(BACKUP):
        old_bak = json.load(io.open(BACKUP, encoding='utf-8'))
        if len(bak['drop']) < len(old_bak.get('drop', [])):
            alt = BACKUP + '.new'
            io.open(alt, 'w', encoding='utf-8').write(json.dumps(bak, ensure_ascii=False, indent=1))
            print('保留原备份（drop=%d 条）不动；本次快照写入 %s（drop=%d 条）'
                  % (len(old_bak.get('drop', [])), alt, len(bak['drop'])))
            bak = old_bak
        else:
            io.open(BACKUP, 'w', encoding='utf-8').write(json.dumps(bak, ensure_ascii=False, indent=1))
            print('已写备份 %s（drop=%d 条）' % (BACKUP, len(bak['drop'])))
    else:
        io.open(BACKUP, 'w', encoding='utf-8').write(json.dumps(bak, ensure_ascii=False, indent=1))
        print('已写备份 %s（drop=%d 条）' % (BACKUP, len(bak['drop'])))
    gone = [m['id'] for m in jobs_entries(tree)]
    if gone:
        kw('website.menu', 'unlink', [gone])
        print('已删除指向 /jobs 的入口：%s' % gone)
    else:
        print('已无 /jobs 入口（幂等）')
    kw('website.menu', 'write', [[KEEP_ID], {'url': KEEP_URL}])
    print('已把 %s 改指 %s' % (KEEP_ID, KEEP_URL))
    sys.exit(0)

if MODE == '--rollback':
    if not os.path.exists(BACKUP):
        sys.stderr.write('缺少备份 %s\n' % BACKUP)
        sys.exit(2)
    bak = json.load(io.open(BACKUP, encoding='utf-8'))
    tree = dump_tree()
    have = {m['id']: m for m in tree}
    # 清理"重建失败留下的孤儿"：与备份同名同 url 同父、但 id 不同的记录
    #   （实测：ORM create 忽略显式 id，会另起 203/204/… 的 id；重复跑会越积越多）
    for m in list(tree):
        for rec in bak['drop']:
            if (m['id'] != rec['id'] and m['name'] == rec['name'] and (m['url'] or None) == (rec['url'] or None)
                    and m['parent_id'] == rec['parent_id']):
                print('  清理孤儿重建记录 %s（"%s" url=%s）' % (m['id'], m['name'], m['url']))
                kw('website.menu', 'unlink', [[m['id']]])
    for rec in bak['drop']:
        if rec['id'] in have:
            print('  %s 已存在，跳过重建' % rec['id'])
            continue
        # 两步走（实测教训）：
        #   ① 用 ORM create 建记录 —— website_menu.name 是 **jsonb 翻译字段**，
        #      直接 SQL 插字符串会报 `invalid input syntax for type json`；
        #   ② 再用 SQL 把 id 改回原值 —— ORM create 会**忽略显式 id**（实测 191→203），
        #      不改就"回滚出的是新 id"，谈不上可逆。
        vals = {k: rec[k] for k in ('name', 'url', 'parent_id', 'sequence', 'website_id') if rec.get(k) is not None}
        new_id = kw('website.menu', 'create', [vals])
        if isinstance(new_id, list):
            new_id = new_id[0]
        if new_id != rec['id']:
            _fix_id(new_id, rec['id'])
        print('  已重建 %s（%s url=%s parent=%s）' % (rec['id'], rec['name'], rec['url'], rec['parent_id']))
    kw('website.menu', 'write', [[KEEP_ID], {'url': bak['keep'].get('url_before')}])
    print('已还原 %s 的 url 为 %s' % (KEEP_ID, bak['keep'].get('url_before')))
    sys.exit(0)

sys.stderr.write('用法：--export | --dry-run | --apply | --rollback\n')
sys.exit(2)
