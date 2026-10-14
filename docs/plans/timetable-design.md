# 排课系统 · 设计摘要与实施方案
> **状态**：`已上线` ｜ **主题**：`排课系统` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 状态：✅ 已交付（2026-08-23，真机验证通过）｜ 工作流见 `docs/dev-workflow.md` ｜ 铁律见 `/Users/qwe/odoo-enterprise-ref/README.md`

## 一、参考来源与结论

| 来源 | 学到什么 |
|------|----------|
| OpenEduCat `openeducat_timetable`（**LGPL 基座，已装在我们库里**） | 核心实体 `op.session`（绝对起止时间的课时）、`op.timing`（第N节）、冲突四查、周看板/日历视图手法、"周模板→展开实例"策略 |
| 企业版 `planning` 模块（只读参考，未搬一行代码） | 反面教材：软警告式重叠检测、resource 分配率——对小型神学院全部过度设计 |

## 二、复用 vs 自研边界

**直接复用（LGPL 开源基座，合法）**：`op.session / op.timing / op.subject / op.faculty / op.batch / op.course / op.classroom` 及其 Python 冲突检测。

**我们自研补齐的五件事**：

1. **周课表 v2（门户）**：原 `/student/timetable` 把整学期课时挤进一张周表。升级为：按自然周过滤
   （窗口边界经 pytz 转 UTC 再比较）+ 上周/本周/下周导航；四视角——学生「我的课表」、教师「我的教学安排」、
   家长「孩子的课表」、内部员工「全校只读」；其余门户账号一律空表（不暴露全校数据）。
2. **后台排课中心（中文）**：`排课管理` 根菜单（seq64）：周课表(calendar)/全部课时(list)/教室管理/时段设置；
   自建视图 `priority=1` 压过上游英文视图；状态流转用可点击 statusbar。
3. **并发兜底**：以事务级 `pg_advisory_xact_lock` 将课时 create/write 串行化，堵住上游纯 Python
   constrains 的并发穿透。
4. **冲突开关固化**：上游冲突检查由 `timetable.is_*_constraint` 四个系统参数门控且只随 demo 数据播种；
   本库无 demo → 以 `noupdate=1` 数据记录默认全开（`data/timetable_params.xml`）。
5. **可见性打通**：ACL 追加 system 全权 + group_user 只读（session/timing/classroom）；ir.rule 为系统组开全量可见域。

**明确砍掉（调研结论）**：四类冲突开关的可配置界面、家长链路 record rule 链、mail.thread 关注者、
pivot/XLS/demo/i18n、企业版 planning 的 resource/发布流/自动派班、批量生成向导（v2 再评估）。

## 三、数据流

```
管理员在后台日历建/改 op.session ──► advisory lock ──► 冲突四查拦截（参数已固化开启）
学生  /student/timetable          ──► 本班 batch 的当周课时
教师  /student/timetable          ──► 我任教的当周课时
家长  /student/timetable          ──► 孩子们班级合集的当周课时
内部  /student/timetable          ──► 全校当周课时（只读）
裸门户账号                        ──► 空表
```

- 时段矩阵：`op.timing`（第1~3节）× 周一~周日；无 timing 归属的课时落「未分节」行。
- 时间显示统一转用户时区（`context_timestamp`）；周窗口按用户本地周一计算后转 UTC。

## 四、涉及文件

| 文件 | 动作 | 内容 |
|------|------|------|
| `models/scheduling.py` | 新增 | `_inherit op.session` advisory lock |
| `controllers/scheduling.py` | 新增 | 覆写 `student_timetable`：周过滤+导航+四视角 |
| `views/scheduling.xml` | 新增 | 后台中文 calendar/list/form(priority=1) + 菜单 + 规则 |
| `data/timetable_params.xml` | 新增 | noupdate 固化四个冲突开关 |
| `views/edu_portal_templates.xml` | 编辑 | `edu_timetable` 模板升级 |
| `controllers/main.py` | 编辑 | 删除旧 student_timetable 死代码 |
| `security/ir.model.access.csv` | 追加 | system 全权 / user 只读行 |
| manifest + 两处 `__init__.py` | 编辑 | 注册 |

## 五、验收标准（真机，2026-08-23 全部通过 ✅）

- [x] 学生 stu@local：默认本周课表显示预备科当周课时（3课×5天、每格≤1卡无堆叠），前后周切换正常
- [x] 教师 faculty@local：标题为「我的教学安排」，仅显示本人任教
- [x] 家长 parent@local：「孩子的课表」数据域正确，不受 staff 门禁影响
- [x] admin/admin：后台「排课管理」渲染中文周历（15 色块）；撞时段被 ValidationError 拦截
      （t1 复测 CONFLICT-GUARD=PASS；前置条件=四个 timetable.* 参数 noupdate 固化入库）
- [x] 截图存档 `shots/local/timetable_*.png`（6 张，MD5 互异）

> 真机验证额外抓出并修复两个静态评审盲区：scheduling.py 缺 `request` import
> （全角色 500）、Odoo19 模板 `t-options` 缺 widget 键（KeyError）——
> 已改为控制器预格式化 ses_fmt + 模板纯文本直出。

## 六、遗留与后续

- 教室字段现库中为空：种子数据补教室归属（【演示】标注）
- 「周模板一键展开学期」生成向导 → v2
- 批量调课通知学生 → 并入 LMS 阶段的站内信体系
- nit：guest 角色模板标题沿用 t-else 显示「我的课表」（应改读 title 变量）
- nit：`op.timing.hour` 为 Char selection，排序字典序 '10'<'2'（sequence 唯一时无影响，沿袭上游）
- 观察：Odoo 服务间歇性 ~30s 无响应抖动后自恢复（无 OOM 无重启），后续排查 worker 配置
