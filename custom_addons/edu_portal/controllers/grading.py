# -*- coding: utf-8 -*-
"""「成绩簿」（/grade-book）按身份分流：教务 / 超管 / **教师**看到的是**成绩录入**（2026-10-03）。

用户原话（2026-10-03 第一轮）：
  「我希望教务人员的这个成绩薄页面，可以改成给学生录入成绩。」
用户原话（2026-10-03 第二轮，校长裁定）：
  「**直连**，可以录也可以改，合并后叫做**我的主页**。」
  ⇒ 三条里只有「直连」要改代码：「可以录也可以改」= 现行引擎就是（允许覆盖 + 每次落
     edu.grade.history 留痕）⇒ **不加闸门**；「叫我的主页」= 现状就是 ⇒ 不动。

改之前实测（本地 edu19，2026-10-03）：
  教务 / 教师打开 /grade-book 拿到的是「该页面仅面向学生账号。您当前登录的不是学生身份……」
  的拒止文案 —— 同一条「成绩簿」入口对两种身份都是死路（教师侧另有 /grade-entry，但仍要绕）。

改之后（判据都落在渲染后的页面上，见 tests/smoke/gradebook_registrar_entry.py）：
  · 教务 / 超管（roles.privileged_staff()）打开 /grade-book = **整班成绩录入网格**（全校班级）；
  · **教师（roles.current_faculty()）打开 /grade-book = 同一张录入网格**，
    但**范围由既有引擎自己收敛到「本人任教班级」**（本文件不另写范围逻辑）；
  · 学生 = 原来的成绩簿页（一字未动）；
  · **家长 = 原行为不变**（拒止文案）—— 用户只说了教务与教师，没提家长，不擅自扩大。

## 复用，不新造第二套录入实现

教务要的「给整班录分」在 2026-09-29 已交付并实测过：controllers/grade_entry.py 的
/grade-entry（整班矩阵 + 留痕 edu.grade.history + 写侧 op.exam.attendees 与读侧
op.result.line 双写，学生端立即可见）。本文件**只做入口分流**，录入逻辑直接调用那个
控制器方法，因此不存在「两个录入口径」。

## 为什么用「控制器继承 + 重新 @route」而不是直接改 batch2.py

这是 Odoo 19 **官方**的控制器覆写机制 —— odoo/http.py 的 Controller 文档字符串：
"To *override* a controller, inherit from its class, override relevant methods and
re-expose them with :func:`~odoo.http.route`"。实现见同文件 _generate_routing_rules()：
它取继承树上的**叶子类**、把各层 @route 参数**自祖先向子孙合并**，端点取最派生的那个；
所以 `@http.route()` 不带参数 = 路径 / type / auth / website 全部沿用父类。

用它而不是改 batch2.py 的理由：controllers/batch2.py 是另一张卡（task-19「老师的我的主页与
应用面板合并」）的写作用域，同仓并行改同一个文件会互相覆盖。

## 为什么是「同一 URL 两态」而不是 303 跳转

用户说的是「这个成绩簿页面……改成……」，所以打开的就是这个地址。同一 URL 按身份显示不同
形态是本仓既有做法（/downloads 普通态 / 教务处管理模式同页两态）。跳转会把教务眼里的
「成绩簿」变成一次转发，且需要在别处再登记一条兼容跳转。
"""
from odoo import http

from .batch2 import EduStudentBatch2
from .grade_entry import EduGradeEntry
from .roles import current_faculty, privileged_staff


class EduGradebookByRole(EduStudentBatch2):
    """EduStudentBatch2 的**叶子子类**：只覆写 /grade-book 一个端点（其余原样继承）。"""

    @http.route()   # 不带参数：路径 / type / auth / website 全部沿用父类（odoo/http.py 合并规则）
    def grade_book(self, **kw):
        # 教务 / 超管（全校）与教师（本人任教班级）——成绩簿这条线给他们的是「录入」。
        # 直接把请求交给既有录入页：同一份名单、同一套范围收敛、同一份留痕。
        # ⚠ 教师的「只看本人任教班」**不在本文件实现**：那是 grade_entry._scope_pairs() 的职责
        #   （教务 privileged → None = 全校；教师 → op.session 的 (faculty,batch,subject) 三元组）。
        #   这里再写一遍范围判断 = 长出第二份口径，两处迟早分叉。
        if privileged_staff() or current_faculty():
            return EduGradeEntry().grade_entry(**kw)
        return super().grade_book(**kw)
