# 公开面（未登录可访问）复核 —— 2026-10-03 第 53 轮

> 缘起：第 38 轮验的是**已登录**下的跨角色越权；**从未验过「不登录能拿到什么」**。本轮补上。
> 结论：**未发现缺陷**。本文件登记方法与读数，免得下一个人再跑一遍。

## 方法

1. 静态枚举 `auth='public'` 的路由（脚本：解析 `@http.route` 块，取含 `public` 的）：**39 条**；
2. 用 **Playwright 的 request（无 cookie、未登录）** 逐条打，看状态码 / content-type / Location，
   并在响应体里找 `姓名 学号 电话 邮箱 成绩 ¥ 家长 王小明` 这类泄漏特征；
3. 对**公开写口**（POST）读码确认有没有门禁与反机器人。

## 读数

| 路由 | 匿名结果 | 判读 |
|---|---|---|
| `/apps`、`/openeducat/apps_menu` | **303 → /my/home** | ✅ 需登录 |
| `/digital-library/material/<id>` | **303 → /digital-library** | ✅ 不泄漏资料 |
| `/telegram/report/<token>`（错 token） | **404** | ✅ |
| `/my/calendar/ics/<token>`（错 token） | **404** | ✅ |
| `/register`、`/apply` | 200（只含**表单标签**：姓名/学号/邮箱/电话/家长） | ✅ 表单本就公开 |
| `/about` `/courses` `/online-exams` `/help` `/alumni` `/booking` 等 | 200，命中的「邮箱」是**页脚联系邮箱** | ✅ 非泄漏（写脚本时注意这个假阳性） |

## 公开写口的两道防线

· **注册**：`edu_portal/controllers/register.py:88` 要求**有效邀请码**（`edu.invite.code`），
  另有 `_validate_view()` / `_validate_identity()` / `_used_by_login()`（一码一账号）；
  并依赖 Odoo 自身设置 **`website.auth_signup_uninvited = 'b2b'`**（取证见 `docs/research/invite-code-tiers.md` §1.2）
  ⇒ **不是开放注册** ✅；
· **两个公开表单都有蜜罐** ✅ —— `edu_apply/controllers/main.py:70`（「蜜罐：正常用户不可见必为空」+
  `views/templates.xml:45` 的 `d-none` 输入框）、`edu_public/controllers/main.py:186-190`（同法，注释写明 honeypot）。

## 未做的（留给裁定，不是缺陷）

· **限流**：两个表单都有蜜罐与必填校验，但**没有**频率限制/验证码 ⇒ 被针对性刷仍可能产生垃圾申请；
  属产品口径（要不要上 captcha / 同 IP 限流），本轮**未改**。
· `/online-exams` 是 `auth='public'` 的**全站考试目录**（`Exam.search([])`），
  即**学校的考试安排对匿名可见** —— 属产品口径，未改（第 45 轮已登记过它与首页 KPI 口径不同）。