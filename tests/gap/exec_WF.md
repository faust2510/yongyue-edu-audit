# exec_WF · 福利系统组实施报告（学生自助打卡 + 积分基础版）

日期：2026-08-23 ｜ 执行代理：WF ｜ 工作目录：`custom_addons/edu_portal`

## 新建文件（3）
| 文件 | 内容 |
|---|---|
| `models/welfare.py` | `edu.daily.checkin` + `edu.point.log` 两个模型 |
| `controllers/welfare.py` | 5 条门户/教师路由（auth='user' website=True） |
| `views/welfare.xml` | 3 个门户模板 + 后端 list/search/form/graph/pivot 视图 + 菜单 |

## 编辑文件（3，均在授权清单内）
- `models/__init__.py`：末尾加一行 `from . import welfare`
- `security/ir.model.access.csv`：追加 6 行 ACL（两模型 × portal/user/admin）
- `__manifest__.py`：data 列表追加 `'views/welfare.xml',`

## 模型
### edu.daily.checkin 学生每日打卡
- 字段：student_id(m2o op.student required)、date(Date required)、attend(Boolean 到堂)、devotion(Boolean 灵修)、devotion_note(Text)、bible_passage(Char 读经范围)、bible_note(Text)
- SQL 唯一约束：`unique_student_date unique(student_id, date)`；store 计算 name 便于后台识别

### edu.point.log 积分流水
- 字段：person_kind(Selection student/teacher)、student_id、teacher_user_id、delta(Integer)、reason(Char)、note(Text)、granted_by(m2o res.users 默认当前用户)、date(Datetime 默认 now)
- Python 约束 `_check_target`：student→必须有 student_id；teacher→必须有 teacher_user_id；delta≠0

## 权限（ACL 追加行）
| 模型 | portal | base.group_user | base.group_system |
|---|---|---|---|
| edu.daily.checkin | 读 | 读全部 | 读写删 |
| edu.point.log | 读 | 读全部 | 读写删 |
写路径全部走控制器 sudo()+归属校验（与既有 edu.leave 同模式），ACL 保持最小。

## 路由清单（5 条，归属校验齐全）
| 路由 | 方法 | 归属校验 |
|---|---|---|
| `/my/checkin` | GET | current_student() 否则 302 /my/home |
| `/my/checkin/save` | POST+csrf | 同上；student_id 强制取本人，不信 POST |
| `/my/points` | GET | current_faculty()（自 roles.py 导入）否则 302 /my/home |
| `/my/points/give` | POST+csrf | 教师校验 + student.exists() 校验 + granted_by=uid |
| `/my/points/me` | GET | current_student() 否则 302 /my/home |

## 页面行为
- **/my/checkin**：今日三开关（到堂/灵修）+读经范围输入+灵修笔记+读经笔记；当天已有记录则预填并在提交时更新。下方最近 30 天记录表（空态 oe-empty）+ 三统计卡：本月到堂天数 / 连续灵修天数 / 连续读经天数（今天有卡从今起算、否则从昨起算，遇断卡即停的简单回溯）。横幅 ?saved=1/?error=1。
- **/my/points**：学生下拉（op.student 全量，GET ?q= 姓名搜索，limit 200）+ 快捷原因按钮组（课堂表现+2/作业优秀+5/纪律提醒-3/服务奉献+3，value 编码"原因|分值"，无 JS 可用）+ 自定义原因文本（填写后覆盖快捷按钮，配分值下拉 ±10 内）→ POST 发放。下方本人最近发放流水（granted_by=uid，20 条）。横幅同上。
- **/my/points/me**：合计分大数字（正绿负红）+ 个人流水表（100 条内，含操作人/备注）。首页入口按分工由主代理统一加（未动 batch2）。

## 菜单落点（welfare.xml）
- 新根菜单 **日常管理** `menu_edu_welfare_root`（sequence=66，groups=base.group_user）
  - 全员打卡（edu.daily.checkin list，search 视图带 今天/近7天/近30天 过滤器+按学生/日期分组）— 教师可见
  - 积分流水（edu.point.log list+form；form 里 person_kind radio 切换、student/teacher 字段随类型 invisible+required 动态切换）— groups=base.group_system
  - 教师积分排行 — groups=base.group_system
- 未挂在"教务审批"下（该根菜单语义为审批流），自建根菜单更清晰，且避免与 approval_backend.xml 冲突。

## 排行实现取舍（二选一说明）
**选了轻量方案**：不做 SQL 视图，用专用 graph/pivot 视图 + action domain `[('person_kind','=','teacher')]` 按 teacher_user_id 分组对 delta 求 sum —— 即教师积分排行（柱状图+透视表可切换）。理由：零迁移成本、随流水实时更新；如后续要"净得分 Top N 列表"再升级物化汇总。

## 工程红线遵守
- 模板 `<t t-call="edu_portal.edu_page">` 包裹；QWeb 属性值内无 `<t>` 标签（脚本扫描 0 处）；动态属性一律 t-attf-*；模板内无 `%` 格式化表达式（0 处）；空态 oe-empty；写操作 POST+csrf=True；未执行 docker/odoo/curl；batch1/batch2/batch3/roles 零改动。

## ⚠️ 移交主代理的一步集成动作
铁律限定我不能改 `controllers/__init__.py`，请主代理集成时补一行：
```python
from . import welfare
```
（models/__init__.py 我已按授权加好。）补齐后升级模块即可生效；未补则 5 条路由不会注册。

## 自查结果
- py_compile：welfare.py(models/controllers) + __init__.py + __manifest__.py 全过
- XML 解析：welfare.xml minidom 解析通过；CSV 结构校验通过（追加 6 行均 8 列）
- 五条路由归属校验齐全（见上表）；unique(student_id,date) 就位；delta/person_kind 配套约束就位
