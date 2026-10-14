#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报告「静态资产比 web 进程还新」—— **提示型检查**，用来防止**验的是旧资产**。

## 为什么立它（2026-10-03 实测踩到）

改 `custom_addons/edu_portal/static/src/css/*.css` 后跑升级、再量页面，**改动完全没生效**：
服务端下发的仍是旧资产包（`717b303`，含目标类名 40 次但**不含**新规则）。
**重启 web 后**资产包哈希才变成 `0867e66`、规则才生效。

⇒ 后果不是「页面坏了」，而是**更坏的一种：你验的是旧资产，却以为在验新代码**。
  本仓对这类问题的既有口径叫「样本有效性」（见 `check_ui_usability.py` 的 `样本有效=False`）。

## 判据

① 取 web 容器的启动时刻 `StartedAt`（**服务器时钟**）；
② 取 `custom_addons/*/static/**` 下 css/scss/js 的**最新修改时间**（**本机时钟**）；
③ 前者早于后者 ⇒ **资产可能陈旧**（Odoo 的资产包在 web 启动时构建）。

**两处时钟一致性要先证明**：本容器与宿主机的 `date -u` 实测**逐秒一致**（2026-10-03），
故可直接比较；若在有偏移的机器上跑，本检查会先打印两侧时刻再判断。

## 退出码语义（**调用方注意：1 不是「代码错」，是「验证前提不成立」**）

  0 = 资产比进程新（可放心验渲染）
  1 = **资产陈旧** ⇒ 验 CSS/JS 前请 `docker restart <web 容器>`
  2 = ENV（拿不到容器/目录）——**不是通过**

玩法：
    python3 scripts/check_asset_freshness.py
    python3 scripts/check_asset_freshness.py --container edu19-clone-web-1
"""
import argparse
import glob
import os
import re
import subprocess
import sys

SUFFIX = (".css", ".scss", ".js")


def newest_asset(root="custom_addons"):
    newest, where = 0.0, None
    for pat in ("*/static/**/*" + s for s in SUFFIX):
        for p in glob.glob(os.path.join(root, pat), recursive=True):
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m > newest:
                newest, where = m, p
    return newest, where


def container_started(name=None):
    """返回 (epoch 秒, 容器名)。找不到就 (None, None)。"""
    if not name:
        try:
            out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                                 capture_output=True, text=True, timeout=20).stdout
        except Exception:
            return None, None
        cands = [l.strip() for l in out.splitlines() if re.search(r"web", l)]
        if not cands:
            return None, None
        name = cands[0]
    try:
        raw = subprocess.run(["docker", "inspect", "-f", "{{.State.StartedAt}}", name],
                             capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return None, None
    if not raw:
        return None, None
    # 2026-10-02T17:48:28.540617925Z → epoch（用容器自己的 date 换算，避免本机时区干扰）
    try:
        sec = subprocess.run(["docker", "exec", name, "date", "-u", "-d", raw, "+%s"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        return int(sec), name
    except Exception:
        return None, name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", default=None)
    a = ap.parse_args()
    newest, where = newest_asset()
    if not newest:
        print("SKIP-ENV：custom_addons 下没找到静态资产 —— 这不是通过")
        return 2
    started, name = container_started(a.container)
    if started is None:
        print("SKIP-ENV：拿不到 web 容器启动时刻（docker 不可用？容器名不对？）—— 这不是通过")
        return 2
    import datetime
    fmt = lambda t: datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    print("  web 容器 %s 启动于 %s" % (name, fmt(started)))
    print("  最新静态资产 %s（%s）" % (fmt(newest), where.replace("custom_addons/", "")))
    if newest > started:
        print("  ⚠ 资产比 web 进程**新** ⇒ 服务端下发的资产包可能仍是旧的")
        print("RESULT=STALE（验 CSS/JS 前请先 docker restart %s）" % name)
        return 1
    print("RESULT=OK（静态资产不晚于 web 进程，可放心按渲染结果验收）")
    return 0


if __name__ == "__main__":
    sys.exit(main())