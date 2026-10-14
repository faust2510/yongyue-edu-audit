#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总 smoke_anon/smoke_student 结果 JSON → shots/local/smoke_report.md。

运行：python3 tests/smoke/make_report.py
"""
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHOTS = HERE.parent.parent / "shots" / "local"

ITEMS = [
    (1, "GET / 返回200且含「永约学坊」品牌字样"),
    (2, "/campus/jobs 列出≥2张岗位卡"),
    (3, "/campus/jobs/1 详情页含投递表单"),
    (4, "表单提交→「申请已提交」且 edu_job_application 行数+1（psql）"),
    (5, "honeypot 反机器人：website_url=spam 提交后行数不变"),
    (6, "/alumni/job/card 200"),
    (7, "未登录直接访问 /my/home → 重定向到登录页"),
    (8, "登录后落 /my/home，功能卡网格≥10 张"),
    (9, "/student/timetable 标题；?w=-1 空态文案且日期范围早7天"),
    (10, "/my/courses→课次详情；已完成课次再次标记完成不报错且 completed_date 不变"),
    (11, "/my/fees 含「2026 春季统筹费」「部分缴纳」与「待缴合计」"),
    (12, "/my/assets 重复提交申请 → 跳转含 error=dup"),
    (13, "/my/checkin 打卡一次成功；同日第二次不产生第二条记录且不500"),
    (14, "/my/points/me 有流水展示"),
    (15, "渲染巡检9页 HTTP200 且无 Traceback/Internal Error"),
]


def load():
    got = {}
    for suite in ("anon", "student"):
        p = HERE / f"smoke_{suite}_results.json"
        if p.exists():
            for it in json.loads(p.read_text(encoding="utf-8")):
                got[it["no"]] = it
    return got


def main():
    got = load()
    lines = ["# 冒烟测试报告（匿名公开面 + 学生面）", "",
             f"- 时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
             "- 环境：BASE=http://localhost:8069（docker edu19-clone，Odoo 19 + OpenEduCat）",
             "- 账号：stu@local/demo123；浏览器 Playwright channel=chrome headless zh-CN",
             "- 截图目录：shots/local/smoke_*.png", ""]
    n_pass = sum(1 for no, _ in ITEMS
                 if got.get(no, {}).get("pass"))
    lines.append(f"## 总览：{n_pass}/{len(ITEMS)} PASS")
    lines.append("")
    lines.append("| # | 用例 | 结果 | 说明 |")
    lines.append("|---|---|---|---|")
    fails = []
    for no, name in ITEMS:
        it = got.get(no)
        if not it:
            lines.append(f"| {no} | {name} | SKIP | 未执行 |")
            continue
        mark = "PASS" if it["pass"] else "**FAIL**"
        detail = it["detail"].replace("\n", " ").replace("|", "\\|")[:300]
        lines.append(f"| {no} | {name} | {mark} | {detail} |")
        if not it["pass"]:
            fails.append(it)
    if fails:
        lines += ["", "## 失败项最小复现", ""]
        for it in fails:
            lines.append(f"### #{it['no']} {it['name']}")
            lines.append(f"- 现象：{it['detail']}")
            lines.append(f"- 复现：`python3 tests/smoke/"
                         f"smoke_{'anon' if it['no'] <= 7 else 'student'}.py`"
                         f"（或按 detail 中 URL/参数手动复现）")
            lines.append("")
    out = SHOTS / "smoke_report.md"
    SHOTS.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report -> {out}")
    print(f"summary: {n_pass}/{len(ITEMS)} PASS")


if __name__ == "__main__":
    main()
