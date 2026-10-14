#/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T7 independent verification lib (READ-ONLY).

Conventions:
- trust_env=False to bypass the host system proxy.
- Read-only: HTTP GET + Odoo read methods (search/read/load_menus).
  Data checks only via docker exec psql SELECT.
- Role menus cross-checked with two lenses:
  A. ORM: ir.ui.menu.search() executed as that user.
  B. Frontend: GET /web/webclient/load_menus.
"""
import json
import os
import subprocess

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

BASE = os.environ.get("AUDIT_BASE", "http://127.0.0.1:8069")
DBC = os.environ.get("EDU_DB_CONTAINER", "edu19-clone-db-1")
DBN = os.environ.get("EDU_DB_NAME", "edu19")


def sess():
    import requests
    s = requests.Session()
    s.trust_env = False
    s.proxies = {"http": None, "https": None}
    return s


def login(user, pwd):
    s = sess()
    r = s.post(BASE + "/web/session/authenticate", json={
        "jsonrpc": "2.0", "method": "call",
        "params": {"db": DBN, "login": user, "password": pwd}}, timeout=30)
    res = r.json().get("result") or {}
    if not res.get("uid"):
        return s, None, json.dumps(r.json(), ensure_ascii=False)[:300]
    return s, res["uid"], None


def kw(s, model, method, args=None, kwargs=None, timeout=90):
    r = s.post(BASE + "/web/dataset/call_kw", json={
        "jsonrpc": "2.0", "method": "call",
        "params": {"model": model, "method": method,
                   "args": args or [], "kwargs": kwargs or {}}}, timeout=timeout)
    j = r.json()
    if "error" in j:
        raise RuntimeError(json.dumps(j["error"], ensure_ascii=False)[:400])
    return j.get("result")


def menus(s, root_only=False):
    dom = [["parent_id", "=", False]] if root_only else []
    ids = kw(s, "ir.ui.menu", "search", [dom])
    if not ids:
        return []
    recs = kw(s, "ir.ui.menu", "read",
              [ids, ["id", "name", "parent_id", "action", "complete_name"]])
    return [{"id": r["id"], "name": r["name"],
             "parent_id": r["parent_id"][0] if r.get("parent_id") else None,
             "action": r.get("action") or None,
             "complete_name": r.get("complete_name")} for r in recs]


def load_menus(s):
    r = s.get(BASE + "/web/webclient/load_menus?unique=audit", timeout=60)
    try:
        return r.json()
    except Exception:
        return {"_status": r.status_code, "_head": r.text[:200]}


def get(s, path, follow=False):
    r = s.get(BASE + path, allow_redirects=follow, timeout=60)
    return r.status_code, r.headers.get("Location"), r.url


def sql(q):
    o = subprocess.run(["docker", "exec", DBC, "psql", "-U", "odoo",
                        "-d", DBN, "-tAc", q], capture_output=True,
                       text=True, timeout=120)
    if o.returncode != 0:
        raise RuntimeError("psql: " + o.stderr.strip()[:300])
    return o.stdout.strip()


def cnt(table, where="true"):
    return int(sql("SELECT count(*) FROM %s WHERE %s" % (table, where)))


def has_table(t):
    q = ("SELECT count(*) FROM information_schema.tables "
         "WHERE table_name = " + chr(39) + t + chr(39))
    return int(sql(q)) > 0

def save(path, obj):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    print("[write] " + path)
    return path


ROLES = [("admin", "admin", "admin"),
         ("backoffice", "backoffice@local", "demo123"),
         ("faculty", "faculty@local", "demo123"),
         ("student", "stu@local", "demo123"),
         ("parent", "parent@local", "demo123")]
def rows(sql_text, sep="|"):
    """按行取多列结果（只读 SELECT）。"""
    o = subprocess.run(["docker", "exec", DBC, "psql", "-U", "odoo", "-d", DBN,
                        "-tA", "-F", sep, "-c", sql_text],
                       capture_output=True, text=True, timeout=120)
    if o.returncode != 0:
        raise RuntimeError("psql: " + o.stderr.strip()[:300])
    return [ln.split(sep) for ln in o.stdout.strip().splitlines() if ln]

