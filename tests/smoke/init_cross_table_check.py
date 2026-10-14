# -*- coding: utf-8 -*-
"""init() 跨表回填静态门禁 —— 防 2026-09-28 生产事故家族复发。

## 它防的是什么（事故原文）

Odoo 的 Registry.init_models() 是**逐模型**跑 model._auto_init() → model.init()
（odoo/orm/registry.py 的 init_models）。因此某个模型的 init() 里**写死别的表名**时，
"那张表的新列已经建好"这件事**没有任何保证** —— 处理顺序不利时就是：

    psycopg2.errors.UndefinedColumn: column "item_kind" does not exist
    ERROR odoo.registry: Failed to load registry
    CRITICAL odoo.service.server: Failed to initialize database …

⇒ **整站升级失败**（生产实测退出码 255）。

本仓实测现场：edu_assess 第 2 期的三条 item 回填 + 一条 score 回填写在
EduAssessTemplate.init() 里 ⇒ 面对**第 1 期状态的库**（那些列从未存在）必炸；
本地库因为早升过一次、列早在，把这个顺序问题**掩盖**了（74 项自证全绿）。
修法是把跨表回填搬进各自模型的 init()。

## 判据（本门禁只回答一件事）

**任何一个模型的 init() 里，DML/DDL 的目标表必须就是它自己的表。**
只读引用（information_schema 的存在性守卫）不算违规 —— 那是**有意**的防御。

    OK   : EduAssessItem.init() 里 "UPDATE edu_assess_item SET item_kind = …"
    FAIL : EduAssessTemplate.init() 里 "UPDATE edu_assess_item SET item_kind = …"

"自己的表"按 Odoo 约定推导：_name 的 '.' → '_'；只有 _inherit 的扩展类用 _inherit 的
第一个值推（res.users → res_users）。这条约定正是 Odoo 自己造表名的口径。

## 用法与契约

    python3 tests/smoke/init_cross_table_check.py             # 全仓扫描
    python3 tests/smoke/init_cross_table_check.py --selftest  # 工具自证（红/绿夹具）
    python3 tests/smoke/init_cross_table_check.py --file <p>  # 只扫一个文件

退出码：0=OK（跨表回填 0 处）｜1=FAIL（有跨表回填）｜2=ENV（扫不到仓库结构）
不连库、不联网、不写文件 —— 停机也能跑。

## 复现路径（2026-09-28 实测跑通过；本地 temp 库，**不要碰 edu19 主库**）

事故的**真教训**是：原来的 74 项自证跑在一个「不可能失败」的环境里 —— 本地库早升过一次、
那些列早在，所以 init() 里的跨表回填永远成功。要复现，必须先把库退到**第 1 期状态**：

    # 0) 先备份（只读拷贝，别动主库）
    docker exec -i edu19-clone-db-1 pg_dump -U odoo -d edu19 | gzip -1 > /tmp/edu19_backup.sql.gz
    docker exec -i edu19-clone-db-1 psql -U odoo -d postgres -c "CREATE DATABASE edu19_initfix;"
    gunzip -c /tmp/edu19_backup.sql.gz | docker exec -i edu19-clone-db-1 psql -q -U odoo -d edu19_initfix

    # 1) 退到第 1 期状态 = 生产现状：DROP 掉生产上不存在的 12 列 + 还原第 1 期约束
    #    （列名清单用「生产库 information_schema」对拍得出，别凭记忆写）
    docker exec -i edu19-clone-db-1 psql -U odoo -d edu19_initfix <<'SQL'
    BEGIN;
    ALTER TABLE edu_assess_item
      DROP COLUMN IF EXISTS item_kind, DROP COLUMN IF EXISTS track,
      DROP COLUMN IF EXISTS score_mode, DROP COLUMN IF EXISTS parent_id;
    ALTER TABLE edu_assess_score  DROP COLUMN IF EXISTS track;
    ALTER TABLE edu_assess_template
      DROP COLUMN IF EXISTS excellent_enabled, DROP COLUMN IF EXISTS weight_mode,
      DROP COLUMN IF EXISTS scale_anchors, DROP COLUMN IF EXISTS scale_rule;
    ALTER TABLE edu_assess_roster DROP COLUMN IF EXISTS summary;
    ALTER TABLE edu_assess_task
      DROP COLUMN IF EXISTS objective_scorer_kind, DROP COLUMN IF EXISTS subjective_scorer_kind;
    DELETE FROM ir_model_fields WHERE model LIKE 'edu.assess.%' AND name IN
      ('item_kind','track','score_mode','parent_id','excellent_enabled','weight_mode',
       'scale_anchors','scale_rule','summary','objective_scorer_kind','subjective_scorer_kind');
    ALTER TABLE edu_assess_score DROP CONSTRAINT IF EXISTS edu_assess_score_score_uniq;
    ALTER TABLE edu_assess_score ADD CONSTRAINT edu_assess_score_score_uniq
      UNIQUE (task_id, item_id, roster_id, scorer_ref);          -- 第 1 期定义（无 track）
    ALTER TABLE edu_assess_item DROP CONSTRAINT IF EXISTS edu_assess_item_item_name_uniq;
    ALTER TABLE edu_assess_item ADD CONSTRAINT edu_assess_item_item_name_uniq
      UNIQUE (template_id, name);                                 -- 第 1 期定义
    COMMIT;
    SQL

    # 2) 在该状态跑升级（与生产同一条命令，只换 -d）
    docker compose exec -T web odoo --db_host=db --db_port=5432 --db_user=odoo \
      --db_password=odoo --no-http -c /etc/odoo/odoo.conf -d edu19_initfix \
      -u edu_assess --stop-after-init

改前那份（git show HEAD:custom_addons/edu_assess/models/assess.py）在第 16 行 UPDATE 上炸：

    psycopg2.errors.UndefinedColumn: column "item_kind" does not exist
    ERROR odoo.registry: Failed to load registry
    CRITICAL odoo.service.server: Failed to initialize database `edu19_initfix`.
    （退出码 255；栈顶 = registry.py 的 init_models → model.init()）

改后同一状态 → 退出码 0、无失败特征。**控制组**（不改库、直接 -u）改前改后都绿 ——
这正是「本地曾经全绿」的假绿来源，必须两组都跑才算证完。

想看得更细：给升级命令加 `--log-handler=odoo.sql_db:DEBUG`，日志里能直接看到
`ALTER TABLE "edu_assess_item" ADD COLUMN "item_kind"` 紧跟着
`UPDATE edu_assess_item SET item_kind = 'leaf' …`（= 守卫放行、顺序成立）；
改前那份 6 条语句则是**连续**跑在 Template 的 init 里，中间没有 ADD COLUMN。

## ⚠ 它**不**覆盖什么（别把绿当完整保证）

- 只认 SQL 字面量里的表名。表名/列名由变量拼出来、或走 ORM 的间接跨表写，
  本门禁看不见（本仓 init() 里目前没有这种写法）。
- 不判断回填**值**对不对（那是等值迁移，靠人工与复现脚本）。
- 不做顺序推理 —— 它挡的是"根本不该跨表"，不是"顺序恰好正确"。
"""
import argparse
import ast
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
ADDONS = ROOT / 'custom_addons'

#: 只读引用白名单：出现在这些表名上的 SELECT 不算跨表写。
READ_ONLY_TABLES = {'information_schema', 'pg_class', 'pg_attribute',
                    'pg_constraint', 'pg_index', 'pg_namespace'}

#: 写操作（DML/DDL）的目标表捕获。
WRITE_PATTERNS = (
    ('UPDATE', r'\bUPDATE\s+([A-Za-z_][A-Za-z0-9_]*)'),
    ('ALTER TABLE', r'\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)'),
    ('DELETE FROM', r'\bDELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)'),
    ('INSERT INTO', r'\bINSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)'),
)


def _sql_literals(func_node):
    """取一个函数体里所有 *execute("SQL") 的 SQL 字面量（行列号一并带出）。"""
    out = []
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else None
        if name != 'execute' or not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.append((node.lineno, arg.value))
    return out


def _own_table(class_node):
    """按 Odoo 造表约定推该类自己的表名；推不出返回 None。"""
    name = inherit = None
    for stmt in class_node.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            tgt = stmt.targets[0]
            key = tgt.id if isinstance(tgt, ast.Name) else None
            if key in ('_name', '_inherit') and isinstance(stmt.value, ast.Constant) \
                    and isinstance(stmt.value.value, str):
                if key == '_name':
                    name = stmt.value.value
                else:
                    inherit = stmt.value.value
    src = name or inherit
    return src.replace('.', '_') if src else None


def scan_source(text, path='<string>'):
    """返回违规清单 [(行号, 模型, 自己的表, 语句类型, 被写的表, SQL 片段)]。"""
    tree = ast.parse(text)
    bad = []
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        own = _own_table(cls)
        if not own:
            continue                      # 不是模型类 / 推不出表名 ⇒ 不判
        for stmt in cls.body:
            if not (isinstance(stmt, ast.FunctionDef) and stmt.name == 'init'):
                continue
            for lineno, sql in _sql_literals(stmt):
                for label, pat in WRITE_PATTERNS:
                    import re
                    m = re.search(pat, sql, re.IGNORECASE)
                    if not m:
                        continue
                    target = m.group(1).lower()
                    if target == own.lower() or target in READ_ONLY_TABLES:
                        continue
                    bad.append((lineno, cls.name, own, label, target,
                                ' '.join(sql.split())[:100]))
    return bad


def scan_tree(addons_dir):
    """扫 custom_addons/*/models/*.py。"""
    files = sorted(addons_dir.glob('*/models/*.py'))
    if not files:
        return None, 0
    bad, seen = [], 0
    for f in files:
        seen += 1
        try:
            text = f.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        try:
            hits = scan_source(text)
        except SyntaxError as exc:
            print('  SKIP(语法解析失败，不静默当绿) %s: %s' % (f, exc))
            continue
        for lineno, cls, own, label, target, sql in hits:
            bad.append((str(f.relative_to(ROOT)), lineno, cls, own, label,
                        target, sql))
    return bad, seen


# ---------------------------------------------------------------------------
# 自证：三条反例必报红、两条正例不许报红（工具本身被改坏时本门禁必须自己报警）
# ---------------------------------------------------------------------------
SELFTEST_RED = '''
class EduAssessTemplate(models.Model):
    _name = 'edu.assess.template'

    def init(self):
        self.env.cr.execute(
            "UPDATE edu_assess_item SET item_kind = 'leaf' "
            "WHERE item_kind IS NULL")
'''
SELFTEST_RED_ALTER = '''
class EduAssessTemplate(models.Model):
    _name = 'edu.assess.template'

    def init(self):
        self.env.cr.execute(
            "ALTER TABLE edu_assess_item DROP CONSTRAINT IF EXISTS x")
'''
SELFTEST_RED_INHERIT = '''
class ResUsers(models.Model):
    _inherit = 'res.users'

    def init(self):
        self.env.cr.execute("DELETE FROM res_partner WHERE id = 0")
'''
SELFTEST_GREEN_OWN = '''
class EduAssessItem(models.Model):
    _name = 'edu.assess.item'

    def init(self):
        if column_exists(self.env.cr, 'edu_assess_item', 'item_kind'):
            self.env.cr.execute(
                "UPDATE edu_assess_item SET item_kind = 'leaf' "
                "WHERE item_kind IS NULL")
'''
SELFTEST_GREEN_PROBE = '''
class EduDownload(models.Model):
    _name = 'edu.download.file'

    def init(self):
        self.env.cr.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'edu_download_file'")
        self.env.cr.execute("UPDATE edu_download_file SET active = true")
'''


def run_selftest():
    cases = [
        ('red_item_backfill_from_template', SELFTEST_RED, True),
        ('red_alter_other_table', SELFTEST_RED_ALTER, True),
        ('red_inherit_extension_other_table', SELFTEST_RED_INHERIT, True),
        ('green_own_table_guarded', SELFTEST_GREEN_OWN, False),
        ('green_information_schema_probe', SELFTEST_GREEN_PROBE, False),
    ]
    ok = True
    for name, src, expect_red in cases:
        hits = scan_source(src, name)
        got_red = bool(hits)
        verdict = 'PASS' if got_red == expect_red else 'FAIL'
        if got_red != expect_red:
            ok = False
        print('  SELFTEST %-5s %-38s 期望%s 实得%s（命中 %d）'
              % (verdict, name, '红' if expect_red else '绿',
                 '红' if got_red else '绿', len(hits)))
    # 对照：夹具与真实文件的判据必须一致（真实文件现在应为绿）
    real = ADDONS / 'edu_assess' / 'models' / 'assess.py'
    if real.exists():
        hits = scan_source(real.read_text(encoding='utf-8'))
        verdict = 'PASS' if not hits else 'FAIL'
        ok = ok and not hits
        print('  SELFTEST %-5s %-38s 期望绿 实得%s（命中 %d）'
              % (verdict, 'real:_edu_assess/models/assess.py',
                 '红' if hits else '绿', len(hits)))
    return ok


def main():
    ap = argparse.ArgumentParser(description='init() 跨表回填静态门禁')
    ap.add_argument('--selftest', action='store_true', help='只跑工具自证')
    ap.add_argument('--file', help='只扫这一个文件')
    args = ap.parse_args()

    if args.selftest:
        print('init() 跨表回填静态门禁 —— 自证')
        ok = run_selftest()
        print('SELFTEST 总结：%s' % ('全部通过' if ok else '**有断言失败**'))
        return 0 if ok else 1

    if args.file:
        p = pathlib.Path(args.file)
        if not p.exists():
            print('ENV: 文件不存在 %s' % p)
            return 2
        bad = [(str(p), ln, c, o, l, t, s) for (ln, c, o, l, t, s)
               in scan_source(p.read_text(encoding='utf-8'))]
        seen = 1
    else:
        bad, seen = scan_tree(ADDONS)
        if bad is None:
            print('ENV: 扫不到 %s/*/models/*.py —— 请从仓库根或 tests/smoke 下跑' % ADDONS)
            return 2

    print('init() 跨表回填静态门禁 —— 扫描 %d 个模型文件' % seen)
    if bad:
        print('FAIL: 发现 %d 处「init() 写别的表」（事故家族，见本文件 docstring）：' % len(bad))
        for path, lineno, cls, own, label, target, sql in bad:
            print('  %s:%s  %s.init() 自己的表=%s，却 %s %s'
                  % (path, lineno, cls, own, label, target))
            print('        %s' % sql)
        print('RESULT=FAIL 修法：把该语句搬进 **目标表所属模型** 的 init()，'
              '并加 information_schema 存在性守卫。')
        return 1
    print('RESULT=OK 跨表回填 0 处（每个模型的 init() 只碰自己的表）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
