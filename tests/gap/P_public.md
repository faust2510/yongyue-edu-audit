# P · 交互对齐审计报告 —— 公开页 + 全站导航（游客视角）

- 审计人：交互对齐审计代理 P
- 日期：2026-02-14（审计执行日）
- 目标：http://localhost:8069（Odoo19，db=edu19），自研复刻 vs 原站存档 `reference/web__login.html`、`reference/public/*.html`
- 方法：Python requests，`s.trust_env=False`，不带任何 cookie；读存档提取 `<a>/<button>/<form>/<input>` 交互元素并去重，再抓本地同页逐项核对。可达性以 GET 判定，**303→/web/login 对需登录目标计 OK**。演示登录按钮用「取 csrf → POST /web/login」实测提交链路。
- 已知正常勿报（已遵守）：`/jobs` 路由本身、`/journal/page/N` 均未作为死链上报。

## 对照结果

| 页面 | 元素(标签) | 原站行为 | 本地现状 | 分类 | 建议 |
|---|---|---|---|---|---|
| /web/login | 演示快捷登录·Student(`a.demo-login-btn`) | student@openeducat.com/student 一键填充提交 | stu@local/demo123；POST 实测 302→/my/home+session ✓ | OK | — |
| /web/login | 演示快捷登录·Admin(`a.demo-login-btn`) | admin/admin | admin/admin；POST 实测 302→/openeducat/apps_menu ✓ | OK | — |
| /web/login | 演示快捷登录·Faculty/Parent/Backoffice ×3(`a.demo-login-btn`) | 共 5 个角色按钮 | 仅剩 Student、Admin 两个按钮 | 缺失 | 补 faculty/parent/backoffice 演示账号按钮 |
| /web/login | 「还没有账户？」→/web/signup(`a`) | 登录页提供注册入口 | 登录页无此链接；直接 GET /web/signup 返回 **404** | 缺失 | 启用注册路由或在登录页移除该概念 |
| /web/login | 表单字段 csrf_token/login/password/type/webauthn_response/redirect + 密码眼睛(`button.o_show_password`) + passkey 链接 | 与存档一致 | 全部存在，结构一致 | OK | — |
| /web/login | 重置密码(`a[href=/web/reset_password]`) | 跳重置密码页 | 200，含重置表单与 OAuth 按钮 | OK | — |
| /web/login | 语言切换（原站 12 语言 + 简体中文按钮） | 可切换语言 | 本地无任何语言选择器 | 缺失(低) | 复刻单语言可接受，建议页脚注明 |
| / （首页） | 导航条原站入口 ×13（商店/现在预订/活动/论坛/博客/Course(/courses-offered)/Program(/program-offered)/Alumni Jobs/校园工作/工作/校友/Courses/展示位置） | 原站主导航 17 项全部可达 | 本地导航仅 首页/图书馆/考试/联系我们/课程 5 项；上述入口全部未挂载。其中 12 个路由本体可达（200 或 302），唯 `/website/activity/announcement` → **404** | 缺失 | 导航补齐入口；另需实现 announcement 路由 |
| / （首页） | 页脚（联系我们/电话/facebook/twitter/linkedin） | 原站页脚含联系方式与 3 个社交链接 | 本地页脚仅 mailto:scrtsschool@gmail.com + 版权，无社交/无联系链接 | 缺失 | 页脚补社交与联系块（或配置后自动渲染） |
| /jobs | 页脚「跟随我们」社交图标 ×3(`a[href=/website/social/*]`) | 原站为有效社交外链 | facebook/twitter/linkedin 三个链接 **全部 404** | 死链 | 配置 website.social 相关账号字段或移除图标 |
| / （首页） | 快捷门户入口 ×8（课表/考勤/作业/考试/成绩册/图书馆媒体/公告栏/学生档案） | —（本地新增） | 游客 GET 全部 303→/web/login?redirect=…，行为正确 | OK | — |
| /alumni | 校友卡片(`div.o_portal_index_card`，无 `<a>`) | 卡片可点击进 `/alumni/detail/ad-2017-1` 等 3+ 详情 | 仅 1 张卡（王小明·预备科），无链接、无详情路由 | 空壳 | 卡片包 `<a>` 并实现 alumni/detail 路由 |
| /courses | 课程卡片 ×6(`a[href=/courses?course=13..18]`) | 点击进入课程详情 | GET ?course=13 与列表页**逐字节相同**，参数被忽略，无详情视图 | 死链(交互无效) | 实现 course=N 详情渲染，或去掉参数改为静态展示 |
| /online-exams | 考试卡片（无链接） | 原站考试列表页（97KB 存档，多场次） | 仅 1 张【演示】卡（阶段考一·小要理问答），无任何入口 | 空壳(轻) | 补真实考试数据与详情入口 |
| /digital-library | 分类浏览 ×5(`a[href=/library/media?filterby=5..9]`) | 原站游客可浏览馆藏（570KB 存档全量媒体） | 5 个分类链接游客 GET **全部 303→登录**；29 件馆藏游客完全不可见 | 死链(游客不可达) | 馆藏列表对游客开放；若必须登录，页面应注明并隐藏链接 |
| /my-courses | 整页 | — | 303→/web/login?redirect=%2Fmy-courses%3F（符合规则判 OK） | OK | — |
| /courses-offered | 课程卡 ×6（无 `<a>`） | 导航 Course 入口对应列表页 | 6 张静态卡（CRS-MCS/BTH/BLA/BED/HSA/PRP），无任何可点元素 | 空壳 | 卡片挂接 /courses?course=N 或专业页 |
| /program-offered | 整页 | 原站导航 Program 入口 | 「培养项目信息即将发布。」占位文案 | 空壳 | 录入培养项目或与 /programs（内容完整）合并 |
| /booking | 整页 | 原站为 Odoo 预约模块（可选服务预约流程） | 「在线预约系统即将开放，敬请期待。」占位文案 | 空壳 | 接预约模块或暂时隐藏导航语义的占位说明 |
| /alumni/job/card | 职位卡 ×2(`a→/jobs`：前端开发实习生/教务系统管理员) | 原站游客访问被 303 重定向到登录页（存档即登录页） | 本地对游客直接公开（行为差异，可接受）；但点击进入 /jobs 后显示"目前没有公开的工作机会"，且无这两个职位 | 空壳(目标为空) | 在 /jobs 发布对应职位，或让卡片直达职位详情 |
| /campus/jobs | 职位卡 ×2(`a→/jobs`) | 同上（原站需登录） | 同上：页面本身公开可用，但目标列表为空、职位不存在 | 空壳(目标为空) | 同上 |
| /event | 活动列表 + 报名按钮(`a …/register`) | 原站列出 6 个活动，每场带 register 入口 | 「暂无活动安排」「暂时未找到任何已安排的活动」，仅剩 过往事务/所有活动 日期筛选 | 空壳(数据缺失) | 录入活动数据（含报名入口） |
| /forum | 论坛导航/帖子/faq/profile(`/profile/users`、`/profile/ranks_badges`) | 原站 /forum 为论坛导航页，列 10 个论坛 | 302 自动跳唯一论坛「帮助-1」；帖文详情、faq、用户、徽章页均 200 正常 | OK(偏差备注：仅 1 个论坛) | 可后续补充论坛数据 |
| /blog | 博文列表 + 标签筛选(`a /zh_CN/blog/tag/*`) | 原站 /blog 为全部博文页：5 篇博文 + 4 个标签 | 302→/blog/旅行-1，正文显示「尚未发布博文。」 | 空壳(数据缺失) | 录入博文数据；考虑恢复 /blog 全部文章聚合页 |
| /jobs | 职位列表 | 原站 3 个职位（开发/营销/顾问） | 「目前没有公开的工作机会」空态页（路由本身 200，按约定不报死链，仅报数据空） | 空壳(数据) | 与校友职位卡/校园工作卡联动补数据 |
| /contactus | 联系表单(`form#contactus_form action=/website/form/`，名称/电话/邮件/公司/主旨/描述+提交) | 表单提交 | 表单齐全，POST 端点为标准 /website/form/ | OK | — |

## 分类计数（按行）

| 分类 | 行数 |
|---|---|
| OK | 8 |
| 死链 | 3（涉及 15 个具体链接：/web/signup×1、/website/social/*×3、/library/media?filterby×5、/courses?course=N×6 中前两类为硬 404/303，course 参数为无效交互） |
| 空壳 | 10 |
| 缺失 | 5 |

> 说明：「死链」行数按表格行统计；括号内为受影响的具体链接数。最严重的游客可见硬故障：/jobs 页脚社交图标 ×3（404）、/web/signup（404）、/website/activity/announcement（404）。

## 附：GET 全量清单摘要

- 首页导航+页脚全部链接逐个 GET：无 404/500 出现在已挂载入口上（44 个 `<a>`，去重后 23 个目标全部 200 或预期 303）。
- 标准模块入口直测：/shop 200、/shop/cart 200、/shop/wishlist 200、/event 200(空)、/forum 302→唯一论坛、/blog 302→空博客、/booking 200(占位)、/jobs 200(空)、/contactus 200。
- 未挂载且异常的路由：/website/activity/announcement **404**、/web/signup **404**、/website/social/{facebook,twitter,linkedin} **404**。
- 演示登录实测（独立会话各一次）：stu@local/demo123 → 302 /my/home ✓；admin/admin → 302 /openeducat/apps_menu ✓。
