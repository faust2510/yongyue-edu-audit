#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《永约教务系统操作手册》docx。
依据：docs/code-map.md 路由/菜单速查 + 生产实测菜单树（/tmp/menutree.txt）。
用法：python3 scripts/gen_manual.py
"""
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT = os.path.join(os.path.dirname(__file__), '..', 'docs', 'manuals', '永约教务系统操作手册.docx')
os.makedirs(os.path.dirname(OUT), exist_ok=True)

doc = Document()
# 中文字体
style = doc.styles['Normal']
style.font.name = 'Microsoft YaHei'
style.font.size = Pt(10.5)

def h(text, lvl=1):
    doc.add_heading(text, level=lvl)

def p(text, bold=False):
    par = doc.add_paragraph()
    run = par.add_run(text)
    run.bold = bold
    return par

def bullet(text):
    doc.add_paragraph(text, style='List Bullet')

def step_table(rows):
    """rows: 首行为表头，其余为数据；列数自适应。"""
    ncol = len(rows[0])
    table = doc.add_table(rows=1, cols=ncol)
    table.style = 'Light Grid Accent 1'
    hdr = table.rows[0].cells
    for i, t in enumerate(rows[0]):
        hdr[i].text = t
    for r in rows[1:]:
        cells = table.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = v
    return table

# ============ 封面 ============
title = doc.add_heading('永约教务系统操作手册', level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
p('适用：永约学坊（Covenant Reformed Seminary）教务系统').alignment = WD_ALIGN_PARAGRAPH.CENTER
p('读者：教务处、教师；学生/家长见站内帮助中心（/help）').alignment = WD_ALIGN_PARAGRAPH.CENTER
p('最后校验：2026-08-30 ｜ 改版后必须同步更新本文档').alignment = WD_ALIGN_PARAGRAPH.CENTER

# ============ 一、登录与角色 ============
h('一、登录与角色', 1)
h('1.1 系统入口', 2)
bullet('后台管理：浏览器打开学校域名后，点右上角「登录」（或直接访问 /web/login）')
bullet('门户（学生/家长）：登录后自动进入 /my/home')
bullet('教师工作台：教师账号登录后自动进入工作台')
h('1.2 账号角色一览', 2)
step_table([
    ('角色', '典型账号', '登录后进入', '主要权限'),
    ('管理员', 'admin', 'Odoo 后台', '全部'),
    ('教务处', 'backoffice@local 等', 'Odoo 后台', '排课/审批/评估/报名表/资料/教务菜单'),
    ('教师', 'faculty@local 等', '教师工作台', '批阅/打卡统计/通讯录/资料下载'),
    ('学生', '（由教务开通）', '/my/home 门户', '课表/作业/打卡/周记/评教/下载'),
    ('家长', '（由教务开通）', '/my/home 家长视图', '看孩子档案/成绩'),
])
h('1.3 首次登录必做：修改密码', 2)
step_table([
    ('1', '登录后点击右上角头像 → 「修改密码」', '进入 /my/password'),
    ('2', '输入当前密码、新密码（至少 8 位）与确认', '两次需一致'),
    ('3', '保存后系统要求重新登录', '用新密码登录即可'),
])

# ============ 二、教务·开学准备 ============
h('二、教务·开学准备', 1)
h('2.1 建课程', 2)
p('入口：SIS → Configuration → Course Management → Courses', bold=True)
step_table([
    ('1', '打开 SIS 应用', '顶部应用切换器找到「SIS」'),
    ('2', '进入 Configuration → Course Management', '出现菜单树'),
    ('3', '点「Courses」→ 新建', '填写课程名与代码（如 BIB101）'),
    ('4', '保存', '课程出现在列表'),
])
h('2.2 建科目 Subjects', 2)
p('入口：SIS → Configuration → Subject Management → Subjects', bold=True)
step_table([
    ('1', '同上进入 Subject Management', '点「Subjects」'),
    ('2', '新建科目：名称 + 代码（如 OT101）', '类型选 Theory/Practical'),
    ('3', '保存', ''),
])
h('2.3 建班级 Batches', 2)
p('入口：SIS → Configuration → Program Management / Batches', bold=True)
step_table([
    ('1', '进入 Program Management（或 Batches）', '确认对应 Program'),
    ('2', '新建批次：名称、学期（Academic Term）、课程', '批次 = 一个班的学员集合'),
    ('3', '保存', ''),
])
h('2.4 教师档案 Faculties', 2)
p('入口：SIS → Faculties', bold=True)
step_table([
    ('1', '点「新建」', ''),
    ('2', '填教师姓名；关联登录账号（如有）', '教师登录用其账号'),
    ('3', '保存', ''),
])

h('2.5 周期排课（自动编排整学期课表）', 2)
p('入口：Time Table → 周期排课（批量）', bold=True)
p('适用：某课程固定每周在相同时间上——如每周一、三 09:00 上课，持续 16 周。', italic=True) if hasattr(p, 'italic') else None
step_table([
    ('1', '打开 Time Table → 周期排课（批量）', '进入 /timetable/bulk'),
    ('2', '选课程 / 班级 / 科目 / 教师', '四个下拉均必选'),
    ('3', '选「已有节次」或填自定义上下课时间', '已有节次例：第1节 09:00-10:00；自定义需 HH:MM'),
    ('4', '教室（可选）', '不指定则留空'),
    ('5', '勾选星期几（可多选）', '如周一、周三'),
    ('6', '填开始日期与结束日期', '跨度不超过一年'),
    ('7', '点「预览将生成的课节」', '页面列出将创建的每节课（日期/星期/时刻）'),
    ('8', '核对无误点「确认生成」', '成功提示生成 N 节课；冲突节自动跳过'),
])
h('2.6 停课管理（节假日/停课登记）', 2)
p('入口：Time Table → 停课管理', bold=True)
step_table([
    ('1', '打开 Time Table → 停课管理', ''),
    ('2', '新建：填事由、开始/结束日期', '班级留空 = 全校停课；选班级 = 仅该班'),
    ('3', '保存', '之后周期排课自动避开这些日期'),
    ('4', '临时停某节课', '到 Time Table → Sessions 找到该节课直接取消'),
])

# ============ 三、教务·日常管理 ============
h('三、教务·日常管理', 1)
h('3.1 布告通知', 2)
p('入口：教务审批 → 布告栏管理（或门户发公告）', bold=True)
step_table([
    ('1', '打开布告栏管理', ''),
    ('2', '新建布告：标题 + 正文', '可设发布对象'),
    ('3', '保存并发布', '学生门户「布告/通知」卡可见'),
])
h('3.2 请假审批', 2)
p('入口：教务审批 → 请假审批', bold=True)
step_table([
    ('1', '打开请假审批', '列出待审请假'),
    ('2', '点开一条 → 批准 / 拒绝', '拒绝需填原因'),
    ('3', '提交后学生收到通知', ''),
])
h('3.3 申诉处理', 2)
p('入口：教务审批 → 申诉处理', bold=True)
step_table([
    ('1', '打开申诉处理', '列出申诉'),
    ('2', '点开 → 处理（批准/驳回）', ''),
])
h('3.4 选课审批', 2)
p('入口：教务审批 → 选课审批', bold=True)
step_table([
    ('1', '打开选课审批', '列出学生选课申请'),
    ('2', '批准后学生科目注册生效', ''),
])
h('3.5 行政评估（已下线）', 2)
p('原「行政评估」（模块 edu_eval / 模型 edu.admin.eval.*）已于 2026-09-29 整体删除，'
  '旧后台菜单与门户 /eval/* 都不再存在。评估功能由新引擎承担：'
  '后台走「综合评估」（评估任务 / 模板与评分项），门户走 /assess'
  '（学生 /assess/my，教师与教务 /assess/review）。', bold=True)
h('3.6 综合评估（edu_portal 评教）', 2)
p('入口：综合评估 → 模板管理 / 评估任务', bold=True)
step_table([
    ('1', '综合评估 → 模板管理 → 新建/编辑模板', ''),
    ('2', '综合评估 → 评估任务 → 发布', ''),
])
h('3.7 报名表字段管理', 2)
p('入口：招生报名 → 报名表设置', bold=True)
step_table([
    ('1', '打开报名表设置', '显示报名表的分区与字段'),
    ('2', '新增字段：选分区、填标签、类型（文本框/单选等）、是否必填', '核心字段 locked 仅标注，管理员可改'),
    ('3', '保存后公开报名页即生效', ''),
    ('4', '入学申请列表查看答卷', '招生报名 → 入学申请'),
])
h('3.8 资料下载管理（上传/分类/停用）', 2)
p('入口：顶部应用「资料下载」（管理模式在页面内切换）', bold=True)
step_table([
    ('1', '打开「资料下载」应用', '进入 /downloads'),
    ('2', '页面右上切到「管理模式」', '显示文件夹/文件管理工具'),
    ('3', '新建分类（文件夹）', '如「请假表」「阅读报告」'),
    ('4', '上传文件：选文件夹、填标题、拖入文件', '支持批量；可见范围可勾选 教务/教师/学生/家长'),
    ('5', '停用/删除/移动文件', '停用后学生不可见'),
    ('6', '查看下载统计', '/downloads/stats'),
    ('7', '（可选）系统参数调大小/白名单限制', '见 code-map 说明'),
])
h('3.9 证书管理', 2)
p('入口：教务审批 → 证书管理', bold=True)
step_table([
    ('1', '新建证书：选学生、填课程与完成日期', '系统自动编号 EDU-CERT-xxxx'),
    ('2', '学生门户「证书」卡可下载 PDF', ''),
])
h('3.10 教务审计查询', 2)
p('入口：后台 → /edu/audit（教务审计）', bold=True)
step_table([
    ('1', '打开审计查询', ''),
    ('2', '按操作/对象/时间筛选', '查看谁改了什么'),
])

# ============ 四、教师 ============
h('四、教师日常', 1)
h('4.1 教师工作台', 2)
p('登录后自动进入工作台（/my/home）', bold=True)
step_table([
    ('1', '顶部问候「XX 老师您好」+ 今日日期', ''),
    ('2', '「本周我教的课」按天分组显示课程/班级/教室', ''),
    ('3', '徽标显示待批周记数、进行中评估数', ''),
    ('4', '快捷卡：周记批阅/打卡统计/通讯录/资料下载', ''),
])
h('4.2 周记批阅', 2)
p('入口：教师工作台 → 周记批阅（/journals/review）', bold=True)
step_table([
    ('1', '打开周记批阅', '列出已提交周记（submitted）'),
    ('2', '点开一篇 → 写评语', ''),
    ('3', '保存', '状态变已批阅，学生可见'),
])
h('4.3 打卡统计', 2)
p('入口：教师工作台 → 打卡统计（/checkins/stats）', bold=True)
step_table([
    ('1', '打开打卡统计', '按班级显示完成率'),
    ('2', '可导出', ''),
])
h('4.4 考勤打分（若启用）', 2)
p('入口：门户 → /attendance/take', bold=True)
step_table([
    ('1', '选班级与日期', ''),
    ('2', '逐个标记出勤/迟到/请假', ''),
    ('3', '保存', ''),
])

# ============ 五、学生/家长速查 ============
h('五、学生/家长入口速查', 1)
p('完整图文步骤见站内帮助中心（/help），此处仅列高频入口：')
step_table([
    ('功能', '入口', '说明'),
    ('课表', '首页「校历」卡 / /my/calendar', '含课程/考试/停课/活动'),
    ('每日打卡', '首页「每日打卡」/ /my/checkins', '月历点日期打卡'),
    ('写周记', '首页「我的周记」/ /my/journals', '每周一篇，提交后待批'),
    ('评教', '/assess/my', '匿名；学生在新引擎的评估页填答'),
    ('查成绩', '/grade-book', ''),
    ('费用', '/my/fees', '账单与缴费状态'),
    ('请假', '首页「请假」/ /my/time_off', '提交后教师/教务审批'),
    ('申诉', '/my/grievances', ''),
    ('资料下载', '首页「资源与学习 → 资料下载」/ /downloads', '下载教务发布的表格模板'),
    ('私信/通讯录/校历', '/my/messages /my/contacts /my/calendar', ''),
    ('改密码', '头像 → 修改密码', ''),
])

# ============ 六、FAQ ============
h('六、常见问题（FAQ）', 1)
step_table([
    ('问题', '原因 / 处理'),
    ('登录提示密码错误', '可找管理员重置；教师/学生首次登录后请改密'),
    ('门户看不到某入口卡', '可能被隐藏参数 edu.portal_hidden_cards 控制；找管理员'),
    ('排课预览显示冲突跳过', '该教师/教室/班级同时间已有课；改时间或先清冲突'),
    ('停课日没生效', '检查停课日是否 active、日期范围、是否限定了班级'),
    ('下载中心为空', '教务尚未上传资料，或文件被停用'),
    ('报名页没有新字段', '报名表设置保存后需刷新页面；核心字段 locked 可被管理员改'),
    ('忘记数据库管理员密码', '服务器端重置（需运维）'),
])

doc.save(OUT)
print('saved:', OUT)
