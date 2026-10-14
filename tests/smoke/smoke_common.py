#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冒烟测试公共工具：NO_PROXY / psql(docker exec) / 结果收集。

约定：
- BASE=http://localhost:8069，必须 NO_PROXY=localhost,127.0.0.1
- 数据库在 docker 容器内（端口未映射到宿主机），统一走 docker exec psql
- 每个用例结果记为 {no, name, pass, detail}，最后写 JSON 供 make_report.py 汇总
"""
import json
import os
import re
import subprocess
from pathlib import Path

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

BASE = os.environ.get("SMOKE_BASE", "http://localhost:8069")
DB_CONTAINER = os.environ.get("EDU_DB_CONTAINER", "edu19-clone-db-1")
DB_NAME = os.environ.get("EDU_DB_NAME", "edu19")
REPO = Path(__file__).resolve().parent.parent.parent
SHOTS = REPO / "shots" / "local"
RESULTS_DIR = Path(__file__).resolve().parent


def psql(sql: str) -> str:
    """在 db 容器内执行只读 SQL，返回标量/首列文本。"""
    out = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "psql", "-U", "odoo",
         "-d", DB_NAME, "-tAc", sql],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(f"psql failed: {out.stderr.strip()[:300]}")
    return out.stdout.strip()


def psql_count(table: str, where: str = "true") -> int:
    return int(psql(f"SELECT count(*) FROM {table} WHERE {where}"))


def http_get(url: str, allow_redirects=True):
    """requests GET（禁代理），返回 (status, final_url, text)。"""
    import requests
    proxies = {"http": None, "https": None}
    r = requests.get(url, timeout=30, proxies=proxies,
                     allow_redirects=allow_redirects,
                     headers={"Accept-Language": "zh-CN,zh;q=0.9"})
    return r.status_code, r.url, r.text


class Results:
    """按编号收集 PASS/FAIL 并落盘 JSON。"""

    def __init__(self, suite: str):
        self.suite = suite
        self.items = []

    def add(self, no, name, ok, detail=""):
        self.items.append({"suite": self.suite, "no": no, "name": name,
                           "pass": bool(ok), "detail": str(detail)[:800]})
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] #{no} {name}" + (f" | {detail}" if detail and not ok else ""))

    def save(self):
        path = RESULTS_DIR / f"smoke_{self.suite}_results.json"
        path.write_text(json.dumps(self.items, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        n_pass = sum(1 for i in self.items if i["pass"])
        print(f"\n== {self.suite}: {n_pass}/{len(self.items)} PASS == ({path.name})")
        return path


def shot(page, name: str):
    """截图到 shots/local/smoke_*.png。"""
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"smoke_{name}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
    except Exception:
        pass
    return path


def new_context(pw, width=1440, height=900):
    """headless chrome + zh-CN 上下文。"""
    browser = pw.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              locale="zh-CN", ignore_https_errors=True)
    return browser, ctx


def safe_text(page) -> str:
    try:
        return page.content()
    except Exception:
        return ""


def goto(page, url, tries=2, settle=1200):
    """导航到 url（domcontentloaded，避开慢资源挂起 load），失败重试一次。"""
    last = None
    for _ in range(tries):
        try:
            resp = page.goto(url, wait_until="domcontentloaded",
                             timeout=45000)
            page.wait_for_timeout(settle)
            return resp
        except Exception as e:
            last = e
    raise last


URL_RE = re.compile(r"/campus/jobs/(\d+)")
WEEK_RE = re.compile(
    r"(\d{1,2})月(\d{1,2})日\s*[–—\-]\s*(\d{1,2})月(\d{1,2})日")
