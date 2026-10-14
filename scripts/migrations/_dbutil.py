# -*- coding: utf-8 -*-
"""t9 \u5de5\u5177\u51fd\u6570\uff1a\u4ece\u4efb\u610f\u73af\u5883\u8bfb\u4e00\u4e2a\u6807\u91cf\u3002

\u8bbe\u8ba1\u7ea6\u675f\uff08\u4e00\u4e2a\u5751\u8bb2\u6e05\u695a\uff0c\u4e0d\u518d\u91cd\u8e29\uff09
----------------------------------
\u672c\u4ed3\u7684 **db \u5bb9\u5668\u7aef\u53e3\u6ca1\u6709\u6620\u5c04\u5230\u5bbf\u4e3b**\uff0c
\u5bbf\u4e3b localhost:5432 \u4e0a\u7684\u90a3\u4e2a Postgres \u662f\u53e6\u4e00\u4e2a\u5b9e\u4f8b
\uff08\u5b9e\u6d4b\uff1arole "odoo" does not exist\uff09\uff0c**\u4e0d\u662f** compose \u8fd9\u4e2a\u5e93\u3002
\u6240\u4ee5\u8bfb\u6570\u53ea\u80fd\u8d70 `docker exec`\uff1b\u800c\u8d70 `docker exec` \u7684\u524d\u63d0\u662f
\u201c\u811a\u672c\u8dd1\u5728\u5bbf\u4e3b\u4e0a\u3001\u4e14\u5bbf\u4e3b\u6709 docker CLI\u201d\u3002

\u4e3a\u4ec0\u4e48\u8981\u5199\u6210\u591a\u8def\u56de\u9000\uff1a
verifier \u5b9e\u6d4b\u628a `verify_checkin_board.py` \u653e\u5230 **odoo \u5bb9\u5668\u5185** \u8dd1\uff0c
\u6700\u540e\u4e00\u6761\u201c\u52fe\u6570 == \u5e93\u5185\u201d\u56e0\u4e3a\u5bb9\u5668\u91cc\u6ca1\u6709 docker \u547d\u4ee4
\u800c\u62a5 FileNotFoundError\uff0c\u6574\u811a\u672c rc=1 \u2014\u2014 \u90a3\u4e0d\u662f app \u7f3a\u9677\uff0c
\u662f\u811a\u672c\u7684\u73af\u5883\u5047\u8bbe\u592a\u7a84\u3002\u73b0\u5728\u5b83\u4f1a\uff1a
  1) \u5148\u8bd5 CHECKIN_VERIFY_DB_DSN \uff08\u67d0\u4e9b\u73af\u5883\u91cc\u53ef\u4ee5\u76f4\u8fde\uff09\uff1b
  2) \u518d\u8bd5 psycopg2 \u76f4\u8fde localhost/127.0.0.1:5432\uff1b
  3) \u6700\u540e\u8bd5 `docker compose exec -T db psql`\uff08\u5bbf\u4e3b\u8def\u5f84\uff09\u3002
\u4e09\u6761\u90fd\u4e0d\u901a\u5c31\u629b\u9519\uff0c\u5e76\u5728\u9519\u8bef\u91cc\u5199\u6e05\u695a\u8be5\u600e\u4e48\u505a\u2014\u2014
**\u4e0d\u7528\u201c\u8df3\u8fc7\u8fd9\u6761\u65ad\u8a00\u201d\u6765\u88c5\u7eff**\u3002
"""
import os
import subprocess
import sys


class DBUnavailable(RuntimeError):
    """\u4e09\u6761\u8bfb\u5e93\u8def\u5f84\u5168\u4e0d\u901a\u3002"""


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _psycopg(host, dbname, user, password):
    try:
        import psycopg2
    except ImportError:
        return None, 'psycopg2 \u672a\u5b89\u88c5'
    try:
        conn = psycopg2.connect(host=host, port=5432, dbname=dbname,
                                user=user, password=password, connect_timeout=5)
        cur = conn.cursor()
        cur.execute('SELECT 1')
        cur.fetchone()
        cur.close()
        conn.close()
        return True, ''
    except Exception as e:                       # noqa: BLE001
        return None, '%s: %s' % (type(e).__name__, str(e)[:120])


def scalar_by_dsn(sql, dsn=None):
    """\u76f4\u8fde DSN\uff08CHECKIN_VERIFY_DB_DSN \u6216\u663e\u5f0f\u4f20\u5165\uff09\u3002"""
    dsn = dsn or os.environ.get('CHECKIN_VERIFY_DB_DSN', '')
    if not dsn:
        return None, 'CHECKIN_VERIFY_DB_DSN \u672a\u8bbe\u7f6e'
    try:
        import psycopg2
    except ImportError:
        return None, 'psycopg2 \u672a\u5b89\u88c5'
    try:
        conn = psycopg2.connect(dsn, connect_timeout=5)
        cur = conn.cursor()
        cur.execute(sql)
        val = cur.fetchone()[0]
        cur.close()
        conn.close()
        return val, ''
    except Exception as e:                       # noqa: BLE001
        return None, '%s: %s' % (type(e).__name__, str(e)[:120])


def scalar_by_local_pg(sql, dbname='edu19', user='odoo', password='odoo'):
    last = ''
    for host in ('localhost', '127.0.0.1'):
        ok, err = _psycopg(host, dbname, user, password)
        last = err
        if not ok:
            continue
        import psycopg2
        conn = psycopg2.connect(host=host, port=5432, dbname=dbname,
                                user=user, password=password, connect_timeout=5)
        cur = conn.cursor()
        cur.execute(sql)
        val = cur.fetchone()[0]
        cur.close()
        conn.close()
        return val, ''
    return None, 'psycopg2 \u76f4\u8fde\u4e0d\u901a\uff08%s\uff09' % (last or '\u672a\u77e5')


def scalar_by_docker(sql, container=None, dbname=None):
    """\u5bbf\u4e3b\u8def\u5f84\uff1adocker compose exec -T db psql\u3002"""
    root = _repo_root()
    container = container or os.environ.get('EDU_DB_CONTAINER', '')
    dbname = dbname or os.environ.get('EDU_DB_NAME', 'edu19')
    cmd = (['docker', 'exec', container, 'psql', '-U', 'odoo', '-d', dbname,
            '-tAc', sql] if container else
           ['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U', 'odoo',
            '-d', dbname, '-tAc', sql])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=60, cwd=root)
    except FileNotFoundError:
        return None, '\u672c\u73af\u5883\u6ca1\u6709 docker \u547d\u4ee4'
    except Exception as e:                       # noqa: BLE001
        return None, '%s: %s' % (type(e).__name__, str(e)[:120])
    if out.returncode != 0:
        return None, 'docker psql rc=%s %s' % (out.returncode,
                                               out.stderr.strip()[:120])
    txt = out.stdout.strip()
    if not txt:
        return None, 'psql \u8fd4\u56de\u7a7a'
    try:
        return int(txt.splitlines()[-1]), ''
    except ValueError:
        return txt.splitlines()[-1], ''


def scalar(sql, quiet=False):
    """\u6309\u4e0a\u8ff0\u987a\u5e8f\u56de\u9000\uff0c\u8fd4\u56de (value, how)\u3002\u5168\u4e0d\u901a\u629b DBUnavailable\u3002"""
    attempts = (
        ('dsn', scalar_by_dsn),
        ('local-pg', scalar_by_local_pg),
        ('docker', scalar_by_docker),
    )
    errs = []
    for how, fn in attempts:
        val, err = fn(sql)
        if err:
            errs.append('%s: %s' % (how, err))
            continue
        if not quiet:
            sys.stderr.write('[db] via %s\n' % how)
        return val, how
    raise DBUnavailable(
        '\u8bfb\u5e93\u5168\u90e8\u5931\u8d25\uff1a\n  ' + '\n  '.join(errs) +
        '\n\u8bf7\u5728\u5bbf\u4e3b\u8dd1\uff08\u6709 docker CLI\uff09\uff0c'
        '\u6216\u8bbe CHECKIN_VERIFY_DB_DSN=postgresql://user:pwd@host:5432/edu19')
