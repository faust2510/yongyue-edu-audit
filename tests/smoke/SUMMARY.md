# 全站冒烟测试总表（2026-08-23）

5 个并行子代理执行 · 覆盖五角色 × 全部自定义路由 × 写操作闭环 × 浏览器级断言

## 总计：71 项 → **66 PASS / 5 WARN / 0 FAIL**（修复后实质 68 PASS）

| 区域 | 项数 | PASS | WARN | FAIL | 报告 |
|---|---|---|---|---|---|
| A 学生门户（24 路由+分页） | 26 | 26 | 0 | 0 | A_student.md |
| B 提交流程+教师闭环（写操作） | 9 | 9 | 0 | 0 | B_submit_faculty.md |
| C 家长/教务后台/应用菜单 | 11 | 9 | 2 | 0 | C_parent_backoffice.md |
| D 游客公开页+鉴权守卫 | 15 | 14 | 1 | 0 | D_public.md |
| E 测验全流程+横切面 | 10 | 8 | 2 | 0 | E_quiz_cross.md |

## 发现的问题与处置

| # | 问题 | 级别 | 处置 |
|---|---|---|---|
| 1 | 测验作答页 `form action="/quiz/submit"` 与路由 `/quiz/<id>/submit` 不一致，浏览器真实提交 404（脚本直发才通过，故此前未暴露） | 功能缺陷 | ✅ 已修：模板改为 `t-attf-action="/quiz/{{ quiz.id }}/submit"`，实测 action 正确 |
| 2 | 家长请假提交成功后无「已提交」提示：redirect 用路径 `/leave/saved`，而控制器只认查询参数 `'saved' in kw` | 反馈缺失 | ✅ 已修：redirect 改 `/leave?saved=1`，横幅实测出现 |
| 3 | `/my-courses` 需登录才能看 | 合理行为 | 无需处理（守卫正确 303） |
| 4 | 校友工作列表无「新建」表单入口 | 范围外 | 记录为后续增强 |
| 5 | 日志窗口 4 行 KeyError('edu19')：16:17 容器被外部重启的 registry 冷启动竞态 | 环境噪音 | 非应用缺陷 |
| 6 | **用户实测发现**：作业卡「提交作业」按钮 404 —— 按钮指向原站企业版路由 `/submited/assignment/list/<id>`，本地从未实现（官方社区版也无此路由） | 功能缺失 | ✅ 已自研补齐：提交页+保存路由+附件上传下载+卡片状态徽章+已批阅锁定；浏览器 E2E 全通（含文件闭环） |

### 补充修复记录（2026-08-23 晚，用户反馈驱动）
- 冒烟盲区说明：B 组只测了教师"发布作业"，学生"提交作业"动作未覆盖——按钮死链因此漏网。已补浏览器级 E2E：点击→填写→提交→横幅→列表徽章「已提交」→box=submitted 计数，console 零报错。
- 新增能力：`op.assignment.sub.line` 扩展 file/filename 附件字段；`/my/assignment/sub/<id>/file` 所有权校验后下载。
- 教师侧无需改动：op.assignment 后台原生自带提交计数智能按钮与提交列表。

## 全站死链清零 + 交互对齐审计（2026-08-23 深夜，用户追问"还有没有类似情况"）

机械化对账（模板字面量/动态拼接 t-att-href/t-attf-action/控制器 redirect/JS 导航 ↔ 全部已注册路由）+ 逐条身份化验证，再修 4 处：

| # | 发现 | 根因 | 处置 |
|---|---|---|---|
| 1 | 作业标题链接 `/assignment/details/<id>` 404 | 原站企业版路由，本地无实现 | ✅ 重定向到自研的提交/详情页 `/submited/assignment/list/<id>` |
| 2 | 教师路由 `/my/rollcall`、`/my/marks`、`/my/subject-reg`、`/my/telegram` 全部 404 | **edu_telegram/controllers/__init__.py 漏导入 portal.py 与 portal_ops.py**，路由从未注册 | ✅ 补两行 import，四条路由复活（实测 200） |
| 3 | ops_templates.xml 非法 XML（把 `<t>` 写进 action 属性）一直**阻塞该模块升级** | 手写模板属性错误 | ✅ 删除冗余字面量 action（已有 t-att-action） |
| 4 | 虚惊排除：`/jobs`、`/journal/page/N`、`/my/certificate/download/N` 实测均 200 | 前缀裸测法缺陷 | 记入勿报清单 |

方法论沉淀：前缀裸测会误报带参路由；必须用完整 URL + 正确身份会话。扫描脚本模式已存于会话记录，可复跑。

第二阶段（进行中）：三个子代理按原站存档逐页对照本地交互元素，产出 死链/空壳/缺失 分级清单 → `tests/gap/{S_student,R_roles,P_public}.md`。

## 关键回归确认
- 应用菜单（今日重build）：25 张卡片图标 **25/25 真实加载**；抽样卡片深链 `/odoo/student`、`/odoo/session`、`/odoo/discuss` 均打开真后台；**`/web` 直达落在网格页不再落讨论**；console error = 0
- 教师审批全链路：学生请假 SLR000006 → 教师 set_state 批准 → 学生页显示「已批准」
- 成绩录入原值回写防污染设计有效（92→saved→回显 92）
- 测验 E2E：提交 → 判分 6.0/6=100% → 结果页可复看
- 五账号落地路由全部正确（student→/my/home、parent→/my/child、faculty/backoffice/admin→apps_menu）
- 测试窗口内应用自身零新增错误

## 环境备注（复跑必读）
macOS 系统代理(127.0.0.1:12450) 会劫持 localhost 的 requests 请求返回 502 —— 所有脚本需 `session.trust_env=False`。

## 造数清单（均标注"可删"，留在演示库）
SLR000006 请假、GRI 申诉、SR0008 换课、edu.leave id15/16/19（家长×2+教师批准确认）、冒烟测试作业(course18/batch8)、冒烟测试公告、quiz result #5(100分)、考勤表一批。
