# -*- coding: utf-8 -*-
"""活体注册表门禁：**库里登记**的 edu_* 模型 / 字段，**跑着的 web 进程**到底认不认识。

为什么必须有这道门禁（2026-09-21~24 生产事故，诊断已定案）
--------------------------------------------------------
事故：生产 web 容器 edu19-prod-web-1 自 2026-09-18T05:13Z 连续运行到 09-24T01:52Z（全程未重启）。
  09-21 上线 custom_addons/edu_portal/models/course_rep.py（新模型 edu.course.rep），
  09-22 上线 custom_addons/edu_portal/models/major_track.py（新模型 edu.course.subject +
  op.course 新字段 edu_level_id）。两次都是 rsync + 在一个**独立的一次性容器**里
  `docker compose run … odoo -u edu_portal` 升级，**没有重启 web 进程**。
根因：**Odoo 不会把「已导入模块里的新文件」带进一个已经在跑的进程**。注册表重载（升级）
  只更新数据库与那个一次性容器的进程；活体 web 进程仍是旧注册表 —— 菜单点得开、模型不存在。
症状（当时逐条实测，全部指向同一件事）：
  · `POST /web/dataset/call_kw model=edu.course.rep` → 404（werkzeug.exceptions.NotFound /
    JSON-RPC code 404；浏览器控制台同样是 404）⇒ 模型**不在活体注册表**；
  · 同一进程里 `op.course method=fields_get` **没有** edu_level_id 这个字段；
  · 对照模型 op.course 正常应答 ⇒ 会话/网络都没问题，缺的是注册表项；
  · 每天 01:43 的 cron「edu_portal: 课代表到期收口（实时判定结果落库）」(44) 连续三天失败：
    2026-09-22 01:43:26 / 09-23 01:43:48 / 09-24 01:43:05，`KeyError: 'edu.course.rep'`；
    同一时段日志里还有 `ERROR odoo.addons.base.models.ir_model: Missing model edu.course.rep`。
  · 那时**新开一个 odoo shell 进程却看得到这些模型** —— 新进程会重新 import 全部模块。
  ⇒ **odoo shell / 任何新进程都不能用来验证「活体注册表」**（它天然是新鲜的、必然为真）。
    能回答「现在的生产服务认不认识这个模型」的，只有**跑着的 web 进程** —— 这就是本脚本走 HTTP 的原因。
处置：`docker compose restart web`（约 16s，站点 3s 内恢复）后三个探针全部转正常。

本门禁做什么
------------
1. 取**库真相**（进程外的独立证据）：custom_addons/edu_* 这些模块在 ir_model_data 里登记的
   ir.model / ir.model.fields 行。默认用 psql 直读数据库容器；没有 docker/psql 时退回
   JSON-RPC 读同样两张表（输出会写明本次用的是哪一条通道）。
2. 取**活体真相**：对运行中的 web 进程逐模型发 `call_kw`（模型级 `read([])`；字段级 `fields_get`）。
3. 判定：**只有 werkzeug.exceptions.NotFound（HTTP/JSON code 404）才算 DARK**；
   AccessError / SessionExpiredException 等一律算 **LIVE**（模型在注册表里，只是当前身份读不到）。
   —— 2026-09-24 有人用「任何 error 都算 DARK」的写法试跑，一次报出 5 个**假红**
   （edu.alert.read / edu.alumni.job / edu.deadline / edu.download.ack / edu.tg.bot 都明明在代码里），
   根因就是拿 AccessError 当缺模型。这条判定由 --selftest 用**捕获到的真实报错样本**钉死。
4. 自证：正对照（res.users 必须 LIVE）+ 负对照（一个必然不存在的模型名必须 DARK）——
   先证明判据"能看见 DARK"，再看它报不报 DARK。缺任一条一律判 ENV（不得当结论）。

覆盖声明（覆盖 / 不覆盖，逐条明写）
----------------------------------
覆盖：① 库里有 ir_model_data 行且其模块 state=installed 的模型；② 这些模型的字段（同口径）；
③ 判定对象只有"活体 web 进程"。
不覆盖：· rsync 了新 .py 但**从未 -u 升级**的模块 —— 库里也没有行，本门禁看不见（那类由
  deploy_myedu.sh 的升级步骤保证）；· 非 edu_* 模块（基座 openeducat_erp / 第三方）；
  · **匿名会话下字段级检查跳过**（Odoo 在方法体之前就按会话拒绝，只有 NotFound 能穿过）——
  输出会明写 SKIP，不会静默当绿；· 视图/QWeb/ACL 是否落库（另有 check_view_xpath 等门禁）。
只读：全程只有 SELECT 与只读 RPC（read / fields_get / search_read），不写库、不升级、不重启。

用法
----
  # 本地克隆（默认管理员 admin/admin；容器名自动探测，通常 edu19-clone-db-1）
  python3 scripts/check_live_registry.py
  # 生产（只读；匿名会话足够做模型级判定）
  ssh prod-host 'cd /opt/edu-app && python3 scripts/check_live_registry.py'
  # 需要字段级判定时给会话（生产若没给，输出会明写 SKIP）：
  EDU_CHECK_LOGIN=admin EDU_CHECK_PASSWORD=… python3 scripts/check_live_registry.py
  # 定向核对（部署后只关心本次新上的模型/字段）：
  python3 scripts/check_live_registry.py --expect-model edu.course.rep --expect-field op.course.edu_level_id
  # 尺子自证（不连站点，只跑判定函数 + 真实报错样本）：
  python3 scripts/check_live_registry.py --selftest

退出码：0 = 全部 LIVE；1 = 有 DARK（库里有、活体进程没有）；2 = ENV/判据不可用（不得当结论）。
"""
import argparse
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

# 负对照：这个模型名在本仓**永不定义**（grep 全仓为 0 命中）。它必须被判 DARK。
NEGATIVE_CONTROL_MODEL = 'edu.__live_registry_absent_probe__'
POSITIVE_CONTROL_MODEL = 'res.users'          # 任何 Odoo 库都必然有
POSITIVE_CONTROL_FIELD = ('res.users', 'login')

LIVE, DARK, ENV = 'LIVE', 'DARK', 'ENV'

# ---------------------------------------------------------------------------
# 判定层（纯函数：--selftest 直接测这几个）
# ---------------------------------------------------------------------------

def _err_parts(body):
    """JSON-RPC 错误四元组；不是 JSON-RPC 错误就返回 (None, None, None, None)。"""
    try:
        j = json.loads(body)
    except Exception:
        return None, None, None, None
    err = j.get('error')
    if not isinstance(err, dict):
        return None, None, None, None
    data = err.get('data') if isinstance(err.get('data'), dict) else {}
    return err.get('code'), err.get('message') or '', data.get('name') or '', data.get('message') or ''


def is_model_not_found(status, body):
    """**唯一**能把「模型不在活体注册表」和「当前身份读不到」分开的判据。

    只认三件事（2026-09-24 捕获的真实样本，见 --selftest）：
      · HTTP 404（werkzeug 路由层）；
      · JSON-RPC code 404 / message "404: Not Found"；
      · data.name == 'werkzeug.exceptions.NotFound'。
    AccessError（odoo.exceptions.AccessError）/ SessionExpiredException **不算** —— 那是权限，
    模型明明在注册表里（假红就是这么来的）。
    """
    if status == 404:
        return True
    code, msg, name, _ = _err_parts(body)
    if name and 'NotFound' in name:
        return True
    if code == 404:
        return True
    if isinstance(msg, str) and msg.startswith('404'):
        return True
    return False


def classify_model_probe(status, body):
    """模型级判定 → (verdict, evidence)。"""
    try:
        j = json.loads(body)
        has_result = isinstance(j, dict) and 'result' in j
        has_error = isinstance(j, dict) and isinstance(j.get('error'), dict)
    except Exception:
        has_result = has_error = False
    if is_model_not_found(status, body):
        code, msg, name, _ = _err_parts(body)
        ev = 'HTTP %s' % status
        if name:
            ev += ' / %s' % name
        elif code == 404:
            ev += ' / code 404'
        if not name and not code:
            ev += '（HTML 路由层 404）'
        return DARK, ev
    if has_result:
        return LIVE, 'result'
    if has_error:
        code, msg, name, _ = _err_parts(body)
        return LIVE, '存在但当前身份不可读：%s' % (name or ('code %s' % code))
    return ENV, '非 JSON-RPC 响应（HTTP %s）：%s' % (status, body[:80].replace('\n', ' '))


def classify_field_missing(status, body, model, field):
    """字段级复核（fields_get 说"没有"之后的第二次意见）→ (verdict, evidence)。

    fields_get 会**按组过滤**（字段带 groups= 时不给无权用户看），所以"没看到"不等于"不存在"，
    必须复核：真不存在 → builtins.ValueError "Invalid field 'x' on 'y'"；只是无权 → AccessError。
    """
    try:
        j = json.loads(body)
        has_result = isinstance(j, dict) and 'result' in j
        has_error = isinstance(j, dict) and isinstance(j.get('error'), dict)
    except Exception:
        has_result = has_error = False
    if is_model_not_found(status, body):
        return DARK, 'HTTP %s / NotFound' % status
    if has_result:
        return LIVE, 'search_read 命中字段（fields_get 未返回，疑似按组隐藏）'
    if has_error:
        code, msg, name, emsg = _err_parts(body)
        if name == 'odoo.exceptions.AccessError':
            return LIVE, '受限：%s（字段在注册表里，当前身份无权读取）' % (emsg.splitlines()[0][:60] if emsg else 'AccessError')
        if 'Invalid field' in emsg or 'Invalid field' in msg:
            return DARK, '%s: %s' % (name or 'error', emsg.splitlines()[0][:80])
        return ENV, '无法判定：%s' % (name or msg)
    return ENV, '非 JSON-RPC 响应（HTTP %s）：%s' % (status, body[:80].replace('\n', ' '))


# ---------------------------------------------------------------------------
# 网络层（只用标准库；生产上 python3 可能是裸解释器，装不了 requests）
# ---------------------------------------------------------------------------

class Session(object):
    def __init__(self, base, db, timeout):
        self.base = base.rstrip('/')
        self.db = db
        self.timeout = timeout
        self.uid = None
        self.login = None
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar), urllib.request.ProxyHandler({}))

    def call_kw(self, model, method, args=None, kwargs=None):
        payload = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': {
            'model': model, 'method': method, 'args': args or [], 'kwargs': kwargs or {}}}).encode('utf-8')
        req = urllib.request.Request(self.base + '/web/dataset/call_kw', data=payload,
                                     headers={'Content-Type': 'application/json'})
        try:
            r = self.opener.open(req, timeout=self.timeout)
            return r.getcode(), r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'replace')
        except Exception as e:                      # 连接类失败 = ENV，不当结论
            raise EnvError('%s: %s' % (type(e).__name__, e))

    def authenticate(self, login, password):
        payload = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': {
            'db': self.db, 'login': login, 'password': password}}).encode('utf-8')
        req = urllib.request.Request(self.base + '/web/session/authenticate', data=payload,
                                     headers={'Content-Type': 'application/json'})
        try:
            r = self.opener.open(req, timeout=self.timeout)
            res = (json.loads(r.read().decode('utf-8', 'replace')) or {}).get('result') or {}
        except Exception as e:
            raise EnvError('会话建立失败（%s: %s）' % (type(e).__name__, e))
        self.uid = res.get('uid')
        self.login = login if self.uid else None
        return self.uid


class EnvError(Exception):
    """环境/判据不可用 —— 一律 exit 2，不得当结论。"""


# ---------------------------------------------------------------------------
# 库真相：psql 直读（进程外） / JSON-RPC 回退（同两张表，但经过那个进程）
# ---------------------------------------------------------------------------

def _sql_in(values):
    return ', '.join("'%s'" % v.replace("'", "''") for v in values)


def _run_psql(container, db, db_user, sql):
    cmd = ['docker', 'exec', container, 'psql', '-U', db_user, '-d', db, '-tA', '-F', '|', '-c', sql]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise EnvError('psql 失败（%s）：%s' % (container, (p.stderr or '').strip()[:200]))
    return [ln for ln in p.stdout.splitlines() if ln.strip()]


def detect_db_container(prefix_hint='edu19'):
    """自动探测数据库容器：只认 edu19*db*（避免误连别的项目的 db 容器）。"""
    try:
        p = subprocess.run(['docker', 'ps', '--format', '{{.Names}}'], capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if p.returncode != 0:
        return None
    names = [n for n in p.stdout.split() if prefix_hint in n and re.search(r'(^|[-_])db([-_]|$)', n)]
    return sorted(names, key=len)[0] if names else None


def psql_truth(args, modules):
    container = args.db_container or detect_db_container()
    if not container:
        return None
    m_in = _sql_in(modules)
    models = _run_psql(container, args.db, args.db_user, (
        "SELECT DISTINCT m.model || '|' || d.module FROM ir_model m "
        "JOIN ir_model_data d ON d.model = 'ir.model' AND d.res_id = m.id "
        "JOIN ir_module_module mm ON mm.name = d.module AND mm.state = 'installed' "
        "WHERE d.module IN (%s) ORDER BY 1" % m_in))
    fields = _run_psql(container, args.db, args.db_user, (
        "SELECT DISTINCT m.model || '|' || f.name FROM ir_model_fields f "
        "JOIN ir_model m ON m.id = f.model_id "
        "JOIN ir_model_data d ON d.model = 'ir.model.fields' AND d.res_id = f.id "
        "JOIN ir_module_module mm ON mm.name = d.module AND mm.state = 'installed' "
        "WHERE d.module IN (%s) ORDER BY 1" % m_in))
    counts = _run_psql(container, args.db, args.db_user,
                       "SELECT count(*) FROM ir_model_data WHERE model IN ('ir.model','ir.model.fields') "
                       "AND module IN (%s)" % m_in)
    return build_truth(models, fields, int(counts[0]) if counts else -1,
                       source='psql:%s' % container)


def rpc_truth(sess, modules):
    """JSON-RPC 版库真相：读的是同一批 ir_model_data 行（经过活体进程的 ORM，但表是当前表）。"""
    status, body = sess.call_kw('ir.model.data', 'search_read',
                               [[['module', 'in', modules], ['model', 'in', ['ir.model', 'ir.model.fields']]]],
                               {'fields': ['module', 'model', 'res_id'], 'limit': 0})
    if status != 200 or '"result"' not in body:
        raise EnvError('库真相（JSON-RPC）读取失败：HTTP %s %s' % (status, body[:160]))
    rows = json.loads(body)['result']
    model_ids = [r['res_id'] for r in rows if r['model'] == 'ir.model' and r.get('res_id')]
    field_ids = [r['res_id'] for r in rows if r['model'] == 'ir.model.fields' and r.get('res_id')]
    mod_of_model = {}
    if model_ids:
        st, bd = sess.call_kw('ir.model', 'read', [sorted(set(model_ids)), ['model']])
        if '"result"' not in bd:
            raise EnvError('ir.model 读取失败：%s' % bd[:160])
        id2name = {r['id']: r['model'] for r in json.loads(bd)['result']}
        for r in rows:
            if r['model'] == 'ir.model' and r.get('res_id') in id2name:
                mod_of_model.setdefault(id2name[r['res_id']], set()).add(r['module'])
    fields = {}
    if field_ids:
        st, bd = sess.call_kw('ir.model.fields', 'read', [sorted(set(field_ids)), ['name', 'model']])
        if '"result"' not in bd:
            raise EnvError('ir.model.fields 读取失败：%s' % bd[:160])
        for r in json.loads(bd)['result']:
            # read 回来的 model 是相关记录名（字符），可能是 'x' 或 [id, 'x']
            m = r.get('model')
            if isinstance(m, list):
                m = m[1] if len(m) > 1 else None
            if m:
                fields.setdefault(m, set()).add(r['name'])
    models = [('%s|%s' % (m, sorted(v)[0])) for m, v in mod_of_model.items()]
    return build_truth(models, [('%s|%s' % (m, f)) for m, fs in fields.items() for f in fs],
                       len(rows), source='jsonrpc（没有 docker/psql；注意它不是进程外证据）')


def build_truth(model_rows, field_rows, raw_rows, source):
    models, module_of = {}, {}
    for line in model_rows:
        model, _, module = line.partition('|')
        if model:
            models[model] = module
            module_of.setdefault(model, module)
    fields = {}
    for line in field_rows:
        model, _, field = line.partition('|')
        if model and field:
            fields.setdefault(model, set()).add(field)
    return {'models': models, 'fields': fields, 'raw_rows': raw_rows, 'source': source}


# ---------------------------------------------------------------------------
# 尺子自证：判定函数 + 2026-09-24 现场捕获的真实报错样本
# ---------------------------------------------------------------------------

SELFTEST_CASES = [
    # 事故现场：库里有 edu.course.rep，活体进程没有 → 必须判 DARK
    ('事故样本：缺失模型（认证或匿名都一样）', 200,
     '{"jsonrpc": "2.0", "id": null, "error": {"code": 404, "message": "404: Not Found", '
     '"data": {"name": "werkzeug.exceptions.NotFound", "message": "404 Not Found: The requested URL '
     'was not found on the server."}}}', DARK),
    # 假红样本：权限错误 ≠ 缺模型（2026-09-24 有人据此误报 edu.alert.read 等 5 个模型为 DARK）
    ('假红样本：AccessError（模型在注册表里，只是无权）', 200,
     '{"jsonrpc": "2.0", "id": null, "error": {"code": 0, "message": "Odoo Server Error", '
     '"data": {"name": "odoo.exceptions.AccessError", "message": "Sorry, you are not allowed to '
     'access this document."}}}', LIVE),
    ('正常样本：匿名会话命中已存在模型', 200,
     '{"jsonrpc": "2.0", "id": null, "error": {"code": 100, "message": "Odoo Session Expired", '
     '"data": {"name": "odoo.http.SessionExpiredException", "message": "Session expired"}}}', LIVE),
    ('正常样本：result', 200, '{"jsonrpc": "2.0", "id": null, "result": []}', LIVE),
    ('HTTP 层 404（werkzeug 路由层）', 404,
     '<!doctype html><html><title>404 Not Found</title>', DARK),
    ('非 JSON 响应（网关/HTML）', 200, '<!doctype html><html>hello</html>', ENV),
]
# 2026-09-24 现场捕获（search_read 请求一个不存在的字段）。真实报文里的单引号用 %(q)s 代入 ——
# 免得本文件出现嵌套转义。
_FIELD_INVALID = ('{"jsonrpc": "2.0", "id": null, "error": {"code": 0, "message": "Odoo Server Error", '
                  '"data": {"name": "builtins.ValueError", "message": "Invalid field %(q)sedu_zzz_absent_field'
                  '%(q)s on %(q)sop.course%(q)s"}}}') % {'q': "'"}
SELFTEST_FIELD_CASES = [
    ('字段真不存在：builtins.ValueError Invalid field', 200, _FIELD_INVALID, DARK),
    ('字段受限（组过滤）：AccessError → 存在', 200,
     '{"jsonrpc": "2.0", "id": null, "error": {"code": 0, "message": "Odoo Server Error", "data": '
     '{"name": "odoo.exceptions.AccessError", "message": "You do not have access to the field"}}}', LIVE),
    ('字段存在：search_read 命中', 200, '{"jsonrpc": "2.0", "id": null, "result": [{"id": 13, "x": false}]}', LIVE),
]


def selftest():
    bad = 0
    print('== 尺子自证 1/2：模型级判定（%d 例）==' % len(SELFTEST_CASES))
    for name, status, body, want in SELFTEST_CASES:
        got, ev = classify_model_probe(status, body)
        ok = got == want
        bad += 0 if ok else 1
        print('  %s %-46s want=%-4s got=%-4s (%s)' % ('├' if ok else '✗', name, want, got, ev[:56]))
    print('== 尺子自证 2/2：字段级复核判定（%d 例）==' % len(SELFTEST_FIELD_CASES))
    for name, status, body, want in SELFTEST_FIELD_CASES:
        got, ev = classify_field_missing(status, body, 'op.course', 'x')
        ok = got == want
        bad += 0 if ok else 1
        print('  %s %-46s want=%-4s got=%-4s (%s)' % ('├' if ok else '✗', name, want, got, ev[:56]))
    if bad:
        print('FAIL | 尺子自证失败 %d 条 —— 先修判定函数，别拿它去判生产' % bad)
        return 2
    print('PASS | 尺子自证 %d/%d：DARK 只由 NotFound/404 触发；AccessError/会话过期算 LIVE'
          % (len(SELFTEST_CASES) + len(SELFTEST_FIELD_CASES), len(SELFTEST_CASES) + len(SELFTEST_FIELD_CASES)))
    return 0


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def build_parser():
    # 允许 "ssh prod-host 'python3 -' < scripts/check_live_registry.py" 这种不落盘的跑法（__file__ 不存在时用 cwd）
    root = (os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if '__file__' in globals() else os.getcwd())
    p = argparse.ArgumentParser(description='活体注册表门禁（库真相 vs 跑着的 web 进程）',
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--base', default=os.environ.get('EDU_CHECK_BASE') or os.environ.get('AUDIT_BASE')
                   or 'http://127.0.0.1:8069', help='web 进程基址（默认本地克隆）')
    p.add_argument('--db', default=os.environ.get('EDU_CHECK_DB') or os.environ.get('EDU_DB_NAME') or 'edu19')
    p.add_argument('--login', default=os.environ.get('EDU_CHECK_LOGIN'))
    p.add_argument('--password', default=os.environ.get('EDU_CHECK_PASSWORD'))
    p.add_argument('--timeout', type=float, default=30.0, help='单次请求超时（秒）')
    p.add_argument('--root', default=root, help='仓库根（默认本脚本上一级）')
    p.add_argument('--module', action='append', default=None,
                   help='只核对指定模块（可重复；默认取 custom_addons/edu_*）')
    p.add_argument('--db-container', default=os.environ.get('EDU_DB_CONTAINER'),
                   help='数据库容器名（默认自动探测 edu19*db*）')
    p.add_argument('--db-user', default=os.environ.get('EDU_DB_USER') or 'odoo')
    p.add_argument('--no-psql', action='store_true', help='不用 psql，改走 JSON-RPC 取库真相')
    p.add_argument('--expect-model', action='append', default=[],
                   help='额外要求某个模型必须 LIVE（部署后定向核对用）')
    p.add_argument('--expect-field', action='append', default=[],
                   help='额外要求某字段必须存在，写 model.field（部署后定向核对用）')
    p.add_argument('--selftest', action='store_true', help='只跑尺子自证，不连站点')
    return p


def resolve_modules(args):
    if args.module:
        return sorted(set(args.module))
    base = os.path.join(args.root, 'custom_addons')
    if not os.path.isdir(base):
        raise EnvError('找不到 %s —— 用 --root 指定仓库根' % base)
    mods = [d for d in sorted(os.listdir(base))
            if d.startswith('edu_') and os.path.isdir(os.path.join(base, d))]
    if not mods:
        raise EnvError('custom_addons 下没有 edu_* 目录 —— 扫描面为 0，判 ENV')
    return mods


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.selftest:
        return selftest()

    print('活体注册表门禁 —— 库真相 vs 跑着的 web 进程')
    try:
        modules = resolve_modules(args)
    except EnvError as e:
        print('ENV  | %s' % e)
        return 2
    print('扫描面：模块 %d 个 —— %s' % (len(modules), ', '.join(modules)))

    sess = Session(args.base, args.db, args.timeout)
    try:
        if args.login:
            uid = sess.authenticate(args.login, args.password or '')
            print('会话：%s%s' % ('uid=%s' % uid if uid else '登录失败（%s）' % args.login,
                                 '（匿名）' if not uid else ''))
            if not uid:
                print('ENV  | 提供了 --login 但会话未建立 —— 不拿匿名结果冒充认证结果')
                return 2
        else:
            print('会话：匿名（Odoo 在方法体前按会话拒绝，匿名只够做**模型级**判定）')

        # 判据自证：先证明"能看见 DARK"，再看它报不报 DARK
        st, bd = sess.call_kw(POSITIVE_CONTROL_MODEL, 'read', [[]])
        pos, pos_ev = classify_model_probe(st, bd)
        st, bd = sess.call_kw(NEGATIVE_CONTROL_MODEL, 'read', [[]])
        neg, neg_ev = classify_model_probe(st, bd)
        print('自证：正对照 %s=%s（%s）；负对照 %s=%s（%s）'
              % (POSITIVE_CONTROL_MODEL, pos, pos_ev[:40], NEGATIVE_CONTROL_MODEL, neg, neg_ev[:40]))
        if pos != LIVE or neg != DARK:
            print('ENV  | 判据自证未通过（正对照必须 LIVE、负对照必须 DARK）—— 本工具此刻判不了 DARK，'
                  '读数作废：正=%s 负=%s' % (pos, neg))
            return 2

        # 字段级前置：能不能真的读到字段（匿名会话读不到 → 明写 SKIP）
        st, bd = sess.call_kw(POSITIVE_CONTROL_FIELD[0], 'fields_get', [], {'attributes': []})
        fields_ok, fields_why = False, 'fields_get 未返回字段（%s）' % classify_model_probe(st, bd)[1][:40]
        if st == 200 and '"result"' in bd:
            got = json.loads(bd)['result']
            if POSITIVE_CONTROL_FIELD[1] in got:
                fields_ok, fields_why = True, '%s.%s 可见' % POSITIVE_CONTROL_FIELD

        # ---- 库真相 ----
        truth = None
        if not args.no_psql:
            try:
                truth = psql_truth(args, modules)
            except EnvError as e:
                print('注意：%s —— 退回 JSON-RPC 取库真相' % e)
        if truth is None:
            truth = rpc_truth(sess, modules)
        print('库真相（%s）：ir_model_data 行 %d → 去重模型 %d、字段 %d'
              % (truth['source'], truth['raw_rows'], len(truth['models']),
                 sum(len(v) for v in truth['fields'].values())))
        if not truth['models'] and not args.expect_model:
            print('FAIL | 扫描面为 0（库里查不到任何 edu_* 登记的模型）—— 扫描面为 0 一律判 FAIL，不当绿')
            return 1

        # ---- 模型级 ----
        dark_models, env_models = [], []
        for model in sorted(truth['models']):
            st, bd = sess.call_kw(model, 'read', [[]])
            v, ev = classify_model_probe(st, bd)
            if v == DARK:
                dark_models.append((model, truth['models'][model], ev))
            elif v == ENV:
                env_models.append((model, ev))
        for model in args.expect_model:
            if model in truth['models']:
                continue
            st, bd = sess.call_kw(model, 'read', [[]])
            v, ev = classify_model_probe(st, bd)
            if v == DARK:
                dark_models.append((model, '--expect-model', ev))
            elif v == ENV:
                env_models.append((model, ev))
        print('模型级：%d/%d LIVE，%d DARK（逐模型 call_kw read([])）'
              % (len(truth['models']) - len(dark_models), len(truth['models']), len(dark_models)))

        # ---- 字段级 ----
        # --expect-field 的写法是 model.field，而**模型名自己就带点**（op.course）⇒ 必须从最后一个点切
        want_fields = dict((m, set(fs)) for m, fs in truth['fields'].items())
        for spec in args.expect_field:
            model, _, field = spec.rpartition('.')
            if not model or not field:
                print('ENV  | --expect-field 要写 model.field（例：op.course.edu_level_id），收到 %r' % spec)
                return 2
            want_fields.setdefault(model, set()).add(field)
        dark_fields, restricted_fields, unverified = [], [], []
        if not fields_ok:
            if want_fields:
                print('字段级：SKIP（%s）—— 库里有 %d 个字段，但本次会话读不到字段定义，'
                      '**这一项没有被验证**（给 --login/--password 才判）'
                      % (fields_why, sum(len(v) for v in want_fields.values())))
        else:
            checked = 0
            total_fields = sum(len(v) for v in want_fields.values())
            for model in sorted(want_fields):
                st, bd = sess.call_kw(model, 'fields_get', [], {'attributes': []})
                if st != 200 or '"result"' not in bd:
                    v, ev = classify_model_probe(st, bd)
                    if v == DARK:
                        # 连模型都不在活体注册表：整块新文件没进注册表，或 --expect-field 的模型名写错
                        dark_models.append((model, truth['models'].get(model, '--expect-field'), ev))
                    else:
                        unverified.append(('%s.*（%d 个字段整块未判定）' % (model, len(want_fields[model])), ev))
                    continue
                present = set(json.loads(bd)['result'].keys())
                checked += len(want_fields[model] & present)      # fields_get 当场就看到的
                for field in sorted(want_fields[model] - present):
                    st2, bd2 = sess.call_kw(model, 'search_read', [[], [field]], {'limit': 1})
                    v2, ev2 = classify_field_missing(st2, bd2, model, field)
                    if v2 == DARK:
                        dark_fields.append(('%s.%s' % (model, field), ev2))
                    elif v2 == LIVE:
                        restricted_fields.append(('%s.%s' % (model, field), ev2))
                    else:
                        unverified.append(('%s.%s' % (model, field), ev2))
            print('字段级：fields_get 直接核到 %d/%d 个字段（按 %d 个模型各一次）；复核后 DARK %d 个；'
                  '受限/组过滤 %d 个；未判定 %d 个（**不算通过**）'
                  % (checked, total_fields, len(want_fields), len(dark_fields),
                     len(restricted_fields), len(unverified)))
    except EnvError as e:
        print('ENV  | %s' % e)
        return 2
    except urllib.error.URLError as e:
        print('ENV  | 连不上 %s（%s）—— 生产/本地栈没起来时读数作废' % (args.base, e))
        return 2

    # ---- 报账 ----
    if restricted_fields:
        print('（以下字段 fields_get 未返回、复核确认存在 —— 登记备查，不算失败）')
        for name, ev in restricted_fields[:10]:
            print('     %s — %s' % (name, ev))
    if env_models:
        print('未判定项 %d 个（ENV，不得当结论）：' % len(env_models))
        for name, ev in env_models[:10]:
            print('     %s — %s' % (name, ev))
    if unverified:
        print('未判定项（字段级）%d 个 —— **不算通过**：' % len(unverified))
        for name, ev in unverified[:10]:
            print('     %s — %s' % (name, ev))
    if dark_models:
        print('')
        print('FAIL | %d 个模型在库里、但**跑着的 web 进程不认识**（DARK）：' % len(dark_models))
        for model, module, ev in dark_models:
            print('  DARK | %-34s module=%-12s 证据=%s' % (model, module, ev))
    if dark_fields:
        print('')
        print('FAIL | %d 个字段在库里、但**跑着的 web 进程不认识**（DARK）：' % len(dark_fields))
        for name, ev in dark_fields:
            print('  DARK | %-46s 证据=%s' % (name, ev))
    if dark_models or dark_fields:
        print('')
        print('处置：这些模型/字段是**新文件或改过的 .py 没进活体注册表** —— 注册表重载（升级）'
              '**不会 import 新文件**，必须重启 web 进程：')
        print('      cd /opt/edu-app && docker compose restart web   # 约 15-20s，然后重跑本门禁复验')
        print('      若重启后仍 DARK：查 rsync 是否漏文件、模块是否真装（-u 只在已装模块上生效）')
        return 1
    if env_models or unverified:
        print('ENV  | 有 %d 个未判定项（模型级 %d / 字段级 %d）—— 判据不可用，本次读数不得当结论'
              % (len(env_models) + len(unverified), len(env_models), len(unverified)))
        return 2
    print('')
    print('PASS | edu_* 登记的 %d 个模型%s全部存在于跑着的 web 进程（%s）'
          % (len(truth['models']),
             ('、%d 个字段' % (checked + len(restricted_fields))) if fields_ok
             else '（字段级本次未验证：匿名会话读不到字段定义）',
             args.base))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
