# 冒烟测试 E：测验全流程 + 铃铛/首页搜索横切面

- 时间: 2026-09-17 09:41　目标: http://localhost:8069（Odoo 19, docker edu19-clone, db edu19）
- 账号: stu@local　方法: requests.Session + POST /web/session/authenticate；CSRF 正则截取
- 测验提交为**已造数**（每次运行向 edu_quiz_attempt 新增 submitted 记录；
  正确答案经演示库只读 SELECT 获取用于满分判分验证）。

| 项目 | 方法 | 预期 | 实际 | 结果(PASS/WARN/FAIL) | 证据 |
|---|---|---|---|---|---|
| 0 登录 stu@local | POST /web/session/authenticate | 200 且 uid>0 | HTTP 200, uid=8 | PASS | session cookie: True |
| A2 GET /quiz 列表 | GET /quiz | 200 渲染（≥0 张卡） | HTTP 200, 卡片数=0, 空态提示=True | PASS | 标题样本=[] |
| B6 铃铛徽标结构 | GET /my/home | 存在 oe-notif-mirror 徽标 | 页面未见徽标元素 | WARN | 实际结构未找到 .oe-notif-mirror |
| B7 首页搜索接线 | GET /my/home | searchBox 存在 | searchBox=False, 首卡=None | WARN | home_search.js 为纯前端实现：input 时按文本过滤 .o_portal_docs 内卡片、Enter 跳转首个可见卡 href；不发起任何网络请求（无服务端搜索路由可打） |
| B8 日志巡检(45m) | docker logs grep ERROR\|Traceback | 测试窗口内无新增错误（排除 webhook/telegram/worker 噪音） | 30 行新增错误日志 | FAIL | Traceback (most recent call last):; 2026-09-17 01:37:17,048 20 ERROR edu19 odoo.http: Exception during request handling. ; Traceback (most recent call last): |

## 备注

## 统计：共 5 项 — PASS 2 / WARN 2 / FAIL 1
