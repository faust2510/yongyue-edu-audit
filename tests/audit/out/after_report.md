# T7 独立验证原始读数（after）

- 生成时间：2026-09-18 09:47:57
- 口径 A（DB parent_id is null）：40 条
- 口径 B（角色前端 load_menus 根菜单数）见下表

## 1. 四角色可见根菜单（口径 B）

| 角色 | B根菜单数 | 前端菜单节点 | ORM ACL | ORM根菜单 | 验收线 | 判定 |
|---|---|---|---|---|---|---|
| admin | 14 | 361 | OK | 14 | 20 | PASS |
| backoffice | 12 | 181 | OK | 14 | 12 | PASS |
| faculty | 9 | 75 | OK | 14 | - | - |
| student | 0 | 0 | DENIED | None | - | - |
| parent | 0 | 0 | DENIED | None | - | - |

## 2. 重复入口（每个重复组内对教务可见根菜单数，>1 = 仍重复）

| 角色 | 组 | 可见成员 id | 个数 | 判定 |
|---|---|---|---|---|
| admin | op.student 双根 | 257 | 1 | ok |
| admin | 打卡双入口(根) | 593 | 1 | ok |
| admin | 评估双根 | 588 | 1 | ok |
| admin | 考勤多根 |  | 0 | ok |
| admin | 招生双根 | 300 | 1 | ok |
| admin | 原生噪音组(档2对超管=预期) | 15 | 1 | ok(expected) |
| admin | 合并候选组 |  | 0 | ok |
| backoffice | op.student 双根 | 257 | 1 | ok |
| backoffice | 打卡双入口(根) | 593 | 1 | ok |
| backoffice | 评估双根 | 588 | 1 | ok |
| backoffice | 考勤多根 |  | 0 | ok |
| backoffice | 招生双根 | 300 | 1 | ok |
| backoffice | 原生噪音组(档2对超管=预期) |  | 0 | ok |
| backoffice | 合并候选组 |  | 0 | ok |
| faculty | op.student 双根 | 257 | 1 | ok |
| faculty | 打卡双入口(根) | 593 | 1 | ok |
| faculty | 评估双根 | 588 | 1 | ok |
| faculty | 考勤多根 |  | 0 | ok |
| faculty | 招生双根 | 300 | 1 | ok |
| faculty | 原生噪音组(档2对超管=预期) |  | 0 | ok |
| faculty | 合并候选组 |  | 0 | ok |
| student | op.student 双根 |  | 0 | ok |
| student | 打卡双入口(根) |  | 0 | ok |
| student | 评估双根 |  | 0 | ok |
| student | 考勤多根 |  | 0 | ok |
| student | 招生双根 |  | 0 | ok |
| student | 原生噪音组(档2对超管=预期) |  | 0 | ok |
| student | 合并候选组 |  | 0 | ok |
| parent | op.student 双根 |  | 0 | ok |
| parent | 打卡双入口(根) |  | 0 | ok |
| parent | 评估双根 |  | 0 | ok |
| parent | 考勤多根 |  | 0 | ok |
| parent | 招生双根 |  | 0 | ok |
| parent | 原生噪音组(档2对超管=预期) |  | 0 | ok |
| parent | 合并候选组 |  | 0 | ok |

## 2b. 队长裁定判定（机器判，非人工）

- **apps_merged_303**：PASS cases={'student': {'expect': 303, 'actual': 303, 'location': '/my/home', 'ok': True}, 'parent': {'expect': 303, 'actual': 303, 'location': '/my/home', 'ok': True}, 'faculty': {'expect': 200, 'actual': 200, 'location': None, 'ok': True}, 'backoffice': {'expect': 200, 'actual': 200, 'location': None, 'ok': True}}
- **home_merged_content**：PASS
    - student：HTTP 200 / 宫格标记 45 / 旧Timeline标记 0 / 头像弹窗触发 2 / 头像 src ['/web/image/res.partner/38/avatar_128', '/web/image/res.partner/38/avatar_256']（partner id ['38']）/ 待办窄条 1
    - parent：HTTP 200 / 宫格标记 36 / 旧Timeline标记 0 / 头像弹窗触发 2 / 头像 src ['/web/image/res.partner/47/avatar_128', '/web/image/res.partner/47/avatar_256']（partner id ['47']）/ 待办窄条 0
- **checkin_redirect_303**：PASS cases={'/my/checkin': {'expect': 303, 'actual': 303, 'ok': True}, '/my/checkin/export': {'expect': 303, 'actual': 303, 'ok': True}}
- **checkin_board_200**：PASS cases={'/my/checkin/board': {'expect': 200, 'by_role': {'faculty': 200}, 'faculty': 200, 'student': None, 'ok': True}}
- **tier2_superadmin_visible**：PASS
    - 非超管 backoffice 可见档2根：[]（ok）
    - 非超管 faculty 可见档2根：[]（ok）
    - 非超管 student 可见档2根：[]（ok）
    - 非超管 parent 可见档2根：[]（ok）
    - admin 可见档2根：[1, 15]（子集判定 ok，超出 []）
- **new_type_daotang**：PASS found=[['5', '到堂打卡', '5', 't']]

## 3. 保留功能可达性（42 条，逐条 HTTP 码）

| 角色 | 路径 | 说明 | 状态 | Location |
|---|---|---|---|---|
| anon | / | 首页品牌 | 200 |  |
| anon | /campus/jobs | 公开岗位列表 | 200 |  |
| anon | /campus/jobs/1 | 岗位详情+投递表单 | 200 |  |
| anon | /help | 帮助中心入口 | 200 |  |
| anon | /web/login | 登录页(302->/login) | 302 | /login |
| anon | /my/home | 未登录受保护->303 | 303 | /web/login?redirect=%2Fmy%2Fhome%3F |
| anon | /downloads/manage | 未登录受保护->303 | 303 | /web/login?redirect=%2Fdownloads%2Fmanage%3F |
| student | /my/home | 学生门户首页(合并后=宫格) | 200 |  |
| student | /my/apps | 合并后兼容层(303->/my/home) | 303 | /my/home |
| parent | /my/apps | 合并后兼容层(303->/my/home) | 303 | /my/home |
| faculty | /my/apps | 内部用户宫格入口(须200) | 200 |  |
| backoffice | /my/apps | 教务宫格入口(须200) | 200 |  |
| student | /my/checkins | 打卡(edu_life 留) | 200 |  |
| student | /my/checkin | 打卡旧入口(收口后应303->/my/checkins) | 303 | /my/checkins |
| student | /my/checkin/export | 旧打卡导出(收口后应303) | 303 | /my/checkins/export |
| faculty | /my/checkin/board | 全员到堂看板(教师须200) | 200 |  |
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
| parent | /my/child | 家长查看子女 | 200 |  |
| parent | /help/parent | 帮助中心(家长) | 200 |  |
| backoffice | /help/registrar | 帮助中心(教务) | 200 |  |

