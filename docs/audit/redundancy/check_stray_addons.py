#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""散件守卫（零豁免）：custom_addons/ 根下只许有「模块目录」，不许有游离代码文件。

背景与判据见 docs/audit/redundancy/inventory.md（2026-10-02 取证）：
  · addons 根是 Odoo 的模块搜索路径，游离 .py 既不是模块、也不受 manifest 跟踪；
  · 它们曾被整树 rsync 带到生产（scripts/deploy_myedu.sh 的 rsync 只同步模块目录
    ⇒ 在本地删掉**不会**从生产消失，见 inventory §5）；
  · 10 个散件已按「有用→scripts/、一次性→删」处置，本检查器负责**防复发**。

判据（任一不满足即红；无白名单、无豁免）：
  R1 custom_addons/ 根下不得出现游离**文件**（__pycache__ 与隐藏文件除外）。
  R2 名字符合 Odoo 模块名规则的目录（^\w+$，见 odoo/modules/module.py 的 MODULE_NAME_RE）
     必须含 __manifest__.py —— 名字不符合该规则的目录 Odoo 根本不认作模块
     （例：custom_addons/.migration-ledger 是已登记的容器侧台账落点，
      见 docs/audit/checkin-merge-report.md），故不属本判据。
  R3 迁移台账里的每个文件必须**在 scripts/ 下存在**，且**不在 custom_addons/ 根下存在**。

退出码：0 = 全绿；1 = 有判据不满足；2 = 环境不可用（custom_addons 不存在）。

自证（量具本身，两条都已实跑取证，见 inventory §7）：
  cp scripts/seed_demo.py custom_addons/        → R1 红
  mv scripts/seed_demo.py /tmp/                 → R3 红
用法：python3 docs/audit/redundancy/check_stray_addons.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
ADDONS = os.path.join(ROOT, 'custom_addons')

# 与 odoo/modules/module.py:52 的 MODULE_NAME_RE 同源（Odoo 19）
MODULE_NAME_RE = re.compile(r'^\w{1,256}$')

# R3 台账：2026-10-02 从 custom_addons/ 根迁到 scripts/ 的散件（迁移前均为 git 跟踪文件）
MOVED = ['seed_demo.py', 'seed_batch1.py', 'seed_batch2.py', 'seed_batch3.py',
         'fix_user.py', 'seed_tg_demo.py', 'seed_tg_users.py']


def main():
    if not os.path.isdir(ADDONS):
        print('ENV: %s 不存在' % ADDONS)
        return 2
    bad = []
    n_mod = 0
    for name in sorted(os.listdir(ADDONS)):
        path = os.path.join(ADDONS, name)
        if name == '__pycache__' or name.startswith('.'):
            continue
        if not os.path.isdir(path):
            bad.append('R1 游离文件（不是模块）：custom_addons/%s' % name)
            continue
        if MODULE_NAME_RE.match(name):
            if not os.path.exists(os.path.join(path, '__manifest__.py')):
                bad.append('R2 名字像模块但没有 __manifest__.py：custom_addons/%s' % name)
            else:
                n_mod += 1
    for name in MOVED:
        if not os.path.exists(os.path.join(ROOT, 'scripts', name)):
            bad.append('R3 迁移台账说它在 scripts/，但找不到：scripts/%s' % name)
        if os.path.exists(os.path.join(ADDONS, name)):
            bad.append('R3 迁移台账说它已迁走，但仍在：custom_addons/%s' % name)
    if bad:
        print('散件守卫：红（%d 条）' % len(bad))
        for line in bad:
            print('  ' + line)
        return 1
    print('散件守卫：绿（custom_addons 根 0 游离文件；模块 %d 个；迁移台账 %d 项全部就位）'
          % (n_mod, len(MOVED)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
