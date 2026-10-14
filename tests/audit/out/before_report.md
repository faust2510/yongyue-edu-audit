# T7 独立验证原始读数（before）

- 生成时间：2026-09-17 13:17:47
- 口径 A（DB parent_id is null）：40 条
- 口径 B（角色前端 load_menus 根菜单数）见下表

## 1. 四角色可见根菜单（口径 B）

| 角色 | B根菜单数 | 前端菜单节点 | ORM ACL | ORM根菜单 | 验收线 | 判定 |
|---|---|---|---|---|---|---|
| admin | 38 | 436 | OK | 39 | 20 | FAIL |
| backoffice | 31 | 315 | OK | 39 | 12 | FAIL |
| faculty | 19 | 90 | OK | 39 | - | - |
| student | 0 | 0 | DENIED | None | - | - |
| parent | 0 | 0 | DENIED | None | - | - |

## 2. 重复入口（每个重复组内对教务可见根菜单数，>1 = 仍重复）

| 角色 | 组 | 可见成员 id | 个数 | 判定 |
|---|---|---|---|---|
| admin | op.student 双根 | 257,278 | 2 | DUP |
| admin | 打卡双入口(根) | 543,593 | 2 | DUP |
| admin | 评估双根 | 588,597 | 2 | DUP |
| admin | 考勤多根 | 349,529 | 2 | DUP |
| admin | 招生双根 | 300,591 | 2 | DUP |
| admin | 原生噪音组 | 121,142,214,75,566,15,196,388,547,529 | 10 | DUP |
| admin | 合并候选组 | 504,288,325,357,83,507,372,542,606 | 9 | DUP |
| backoffice | op.student 双根 | 257,278 | 2 | DUP |
| backoffice | 打卡双入口(根) | 543,593 | 2 | DUP |
| backoffice | 评估双根 | 588,597 | 2 | DUP |
| backoffice | 考勤多根 | 349 | 1 | ok |
| backoffice | 招生双根 | 591 | 1 | ok |
| backoffice | 原生噪音组 | 121,142,214,75,196,388 | 6 | DUP |
| backoffice | 合并候选组 | 504,325,357,83,507,372,542,606 | 8 | DUP |
| faculty | op.student 双根 | 257,278 | 2 | DUP |
| faculty | 打卡双入口(根) | 543,593 | 2 | DUP |
| faculty | 评估双根 | 588,597 | 2 | DUP |
| faculty | 考勤多根 | 349 | 1 | ok |
| faculty | 招生双根 | 300,591 | 2 | DUP |
| faculty | 原生噪音组 | 196 | 1 | ok |
| faculty | 合并候选组 | 504,288,325 | 3 | DUP |
| student | op.student 双根 |  | 0 | ok |
| student | 打卡双入口(根) |  | 0 | ok |
| student | 评估双根 |  | 0 | ok |
| student | 考勤多根 |  | 0 | ok |
| student | 招生双根 |  | 0 | ok |
| student | 原生噪音组 |  | 0 | ok |
| student | 合并候选组 |  | 0 | ok |
| parent | op.student 双根 |  | 0 | ok |
| parent | 打卡双入口(根) |  | 0 | ok |
| parent | 评估双根 |  | 0 | ok |
| parent | 考勤多根 |  | 0 | ok |
| parent | 招生双根 |  | 0 | ok |
| parent | 原生噪音组 |  | 0 | ok |
| parent | 合并候选组 |  | 0 | ok |

## 3. 保留功能可达性（38 条，逐条 HTTP 码）

| 角色 | 路径 | 说明 | 状态 | Location |
|---|---|---|---|---|
| anon | / | 首页品牌 | 200 |  |
| anon | /campus/jobs | 公开岗位列表 | 200 |  |
| anon | /campus/jobs/1 | 岗位详情+投递表单 | 200 |  |
| anon | /help | 帮助中心入口 | 200 |  |
| anon | /web/login | 登录页(302->/login) | 302 | /login |
| anon | /my/home | 未登录受保护->303 | 303 | /web/login?redirect=%2Fmy%2Fhome%3F |
| anon | /downloads/manage | 未登录受保护->303 | 303 | /web/login?redirect=%2Fdownloads%2Fmanage%3F |
| student | /my/home | 学生门户首页 | 200 |  |
| student | /my/apps | 功能卡网格 | 200 |  |
| student | /my/checkins | 打卡(edu_life 留) | 200 |  |
| student | /my/checkin | 打卡旧入口(收口后应303->/my/checkins) | 200 |  |
| student | /my/courses | 我的课程 | 200 |  |
| student | /my/study | 在线学习 | 200 |  |
| student | /my/marks | 我的成绩 | 200 |  |
| student | /my/fees | 缴费 | 200 |  |
| student | /my/documents | 我的文档 | 200 |  |
| student | /my/evaluation | 综合评估(门户) | 200 |  |
| student | /eval/my | 评估待办 | 200 |  |
| student | /my/journals | 周记 | 200 |  |
| student | /my/points | 积分(学生303->/my/home) | 303 | /my/home |
| student | /my/assets | 我的资产 | 200 |  |
| student | /my/time_off | 请假/调课 | 200 |  |
| student | /student/timetable | 学生周课表 | 200 |  |
| student | /student/attendance | 学生出勤 | 200 |  |
| student | /student/subjects | 学生科目 | 200 |  |
| student | /student/exam | 学生考试 | 200 |  |
| student | /downloads | 资料下载列表 | 200 |  |
| student | /downloads/mine | 我的下载 | 200 |  |
| student | /my/help | 帮助中心(学生) | 200 |  |
| student | /help/student | 帮助中心(学生页) | 200 |  |
| faculty | /checkins/stats | 教师打卡统计 | 200 |  |
| faculty | /eval/review | 评估评审 | 200 |  |
| faculty | /help/faculty | 帮助中心(教师) | 200 |  |
| faculty | /my/rollcall | 点名 | 200 |  |
| faculty | /my/checkin/board | 全员到堂看板(教师200) | 200 |  |
| parent | /my/child | 家长查看子女 | 200 |  |
| parent | /help/parent | 帮助中心(家长) | 200 |  |
| backoffice | /help/registrar | 帮助中心(教务) | 200 |  |

