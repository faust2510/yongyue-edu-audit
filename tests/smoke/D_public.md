# 冒烟测试 D —— 未登录游客只读公开路由测试

- 时间：2026-09-17 09:41:27
- 目标：http://localhost:8069（Odoo 19 学校系统复刻，docker 容器 edu19-clone，数据库 edu19）
- 方法：python3 + requests，**不带任何 cookie**；GET 判定 = 最终 200 + 无 Traceback/Internal Server Error + 命中至少一个预期标记；守卫项 `allow_redirects=False` 检查跳转；失败自动重试一次再判 FAIL。

| # | 路由 | HTTP(最终) | 标记/行为 | 结果 | 备注 |
|---|------|-----------|-----------|------|------|
| 1 | `/courses` | 200 | 命中标记: 课程 | PASS |  |
| 2 | `/online-exams` | 200 | 命中标记: 在线考试, 考试 | PASS |  |
| 3 | `/digital-library` | 200 | 命中标记: 数字图书馆, 图书馆 | PASS |  |
| 4 | `/my-courses` | 200 | 命中标记: 我的课程 | PASS | 303->/web/login?redirect=%2Fmy-courses%3F ; 302->/login?redirect=%2Fmy-courses%3F |
| 5 | `/alumni` | 200 | 命中标记: 校友 | PASS |  |
| 6 | `/campus/jobs` | 200 | 命中标记: 工作 | PASS |  |
| 7 | `/alumni/job/card` | 200 | 正常渲染(岗位卡/列表内容); 标记:招聘,job | PASS |  |
| 8 | `/courses-offered` | 200 | 命中标记: 课程 | PASS |  |
| 9 | `/program-offered` | 200 | 命中标记: 项目, 专业, 课程 | PASS |  |
| 10 | `/booking` | 200 | 命中标记: 预订, 预约 | PASS |  |
| 11 | `/` | 200 | 导航命中:首页 | PASS |  |
| 12 | `/web/login` | 200 | class="demo-login-btn" 出现 5 次 | PASS | 302->/login |
| 13 | `/my/home` | 303 | 303 -> /web/login?redirect=%2Fmy%2Fhome%3F | PASS | 不跟随跳转 |
| 14 | `/openeducat/apps_menu` | 303 | 303 -> /my/home (非登录页) | WARN | 不跟随跳转 |
| 15 | `/quiz` | 303 | 303 重定向登录 -> /web/login?redirect=%2Fquiz%3F | PASS | 先不跟随跳转探测 |

## 统计

- 总计 **15** 项：PASS **14**、WARN **1**、FAIL **0**。
- WARN 明细：`/openeducat/apps_menu`：303 -> /my/home (非登录页)
