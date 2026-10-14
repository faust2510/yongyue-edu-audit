# -*- coding: utf-8 -*-
"""哨兵（只读）：检查导航里是否又长回指向空页 /jobs 的入口。

## 为什么要它（实测教训 2026-09-17）
`/jobs` 的入口**不是 edu_portal 定义的**，而是原生 `website_hr_recruitment` 的 `<menuitem>`；
只要该模块（或它的依赖）被 `-u`，就会**按原定义重建**指向 /jobs 的入口。
实测三次：203/204（15:24）、205/206（15:36）、以及 15:22–15:40 那波逐模块扫描期间再度出现——
名字是多维翻译值（en_US "Jobs" / zh_CN "工作" / zh_TW "職位空缺"），可据此识别"原生重建"。

## 判定
- **FAIL**：存在任何 `url == '/jobs'` 的 website.menu（且 `hr.job = 0` ⇒ 该页是空壳）；
- **PASS**：0 条，并回报当前导航条数。

## 用法（只读，不改库）
    python3 scripts/check_nav_jobs_entries.py            # 退出码 0=PASS / 1=FAIL
    python3 scripts/check_nav_jobs_entries.py --verbose   # 额外列出每条的名字与父级
    python3 tests/unit/check_nav_jobs_entries_test.py     # 回归用例（无需数据库）

## 修法（不在本脚本内执行，避免"哨兵顺手改库"）
- 清重复入口：`python3 scripts/fix_nav_duplicates.py --apply`（按 url 全量识别，含原生重建的）；
- **防再重建（推荐）**：给该菜单的 xmlid 置 `noupdate=1`（`scripts/consolidation_persist.py` 同套机制）
  —— 原生模块再跑也不会写回；它在我方库**没有 xmlid 归属**时，改由 `edu_nav` 数据按 url 覆盖/停用，
  或用幂等 `<function>` 清理。两条路都必须"再升一次"才算验过。

## 本脚本自身的两个缺陷（已修，并留回归用例）
1. 曾写 `rows.split('\n') if isinstance(rows, str) else []` —— 而 `audit_lib.rows()` 返回 **list**
   ⇒ 恒取空数组 ⇒ **恒 PASS 假绿**（当时库里实有 2 条）；
2. 逐条打印曾假设 tuple 位置固定 ⇒ IndexError。
⇒ 现在把"归一化"与"判定"抽成纯函数（`parse_entries` / `evaluate`），由
`tests/unit/check_nav_jobs_entries_test.py` 用**构造数据**证明它会 FAIL 而不是恒 PASS。
"""
import os
import sys


def parse_entries(rows):
    """把 `audit_lib.rows()` 的返回**归一化**成 [[cell, ...], ...]。

    绝不假设 rows 是 str（这是第一版假绿的根因），也不假设每行长度/位置固定。
    覆盖三种真实返回形态：list[str]、str（含换行）、以及可迭代的行序列。
    """
    if rows is None:
        return []
    if isinstance(rows, str):
        rows = [r for r in rows.split('\n') if r.strip()]
    out = []
    for r in rows:
        if isinstance(r, (list, tuple)):
            cells = [str(c) for c in r]
        else:
            s = str(r).strip()
            if not s:
                continue
            cells = s.split('|')
        if cells:
            out.append(cells)
    return out


def evaluate(entries, hr_jobs):
    """返回 (passed, reason)。判定只看两件事：有没有 /jobs 入口、该页是不是空壳。"""
    if entries:
        return False, ('导航出现 %d 条指向空页 /jobs 的入口（多为 website_hr_recruitment 升级重建）'
                       % len(entries))
    if hr_jobs == 0:
        return True, '导航无 /jobs 入口（该页数据源 hr.job=0，本就是空壳）'
    return True, '导航无 /jobs 入口'


def main(argv):
    verbose = '--verbose' in argv
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tests/audit'))
    import audit_lib as A  # noqa: E402

    rows = A.rows("select id, name, url, parent_id, sequence from website_menu where url = '/jobs' order by id")
    entries = parse_entries(rows)
    total = A.cnt('website_menu')
    hr_jobs = A.cnt('hr_job')
    passed, reason = evaluate(entries, hr_jobs)

    print('/jobs 页面数据源 hr.job = %d 条%s' % (hr_jobs, '（空壳页）' if hr_jobs == 0 else ''))
    print('website.menu 总数 = %d ｜ 指向 /jobs 的入口 = %d 条' % (total, len(entries)))
    if verbose and entries:
        for cells in entries:
            print('   ' + ' ｜ '.join(c if len(c) <= 60 else c[:57] + '…' for c in cells))
    print(('PASS | ' if passed else 'FAIL | ') + reason)
    if not passed:
        print('       处置：python3 scripts/fix_nav_duplicates.py --apply')
        print('       防复发：给该菜单 xmlid 置 noupdate=1；无 xmlid 归属时由 edu_nav 按 url 覆盖/停用')
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
