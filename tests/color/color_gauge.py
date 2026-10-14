#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""向后兼容别名 —— 量具本体已更名为 color_audit.py。

为什么留这个文件：captain 先前要求把取色器固化到 tests/color/color_audit.py，
我据此改了名；但 eng-backend 已按旧名 color_gauge.py 定位并引用过本工具。
为了让他的引用不至于断掉，这里保留一个**纯转发**入口。

请新代码一律用 tests/color/color_audit.py；本文件不含任何逻辑，只在原地转发。
"""
import os
import runpy
import sys

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'color_audit.py')
sys.argv[0] = TARGET
runpy.run_path(TARGET, run_name='__main__')
