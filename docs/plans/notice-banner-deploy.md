# 公告横幅（notice-banner）实施与生产部署记录
> **状态**：`已上线` ｜ **主题**：`公告横幅` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

日期：2026-08-29 · 提交链：4515f16（后端）→ bce5ec8（前端）

## 功能
- 对标 tokenrouter 公告横幅：门户页顶部蓝底横幅，徽标胶囊 + 正文 + 下划线 CTA + 底部圆点轮播（5s 自动，悬停暂停）+ 两端 🎉 + 单条关闭（localStorage 记忆）。
- 对接公告：`edu.notice` 新增 `banner_enabled/banner_badge/banner_cta/banner_url/banner_seq`；管理员在「教务审批 → 布告栏管理」按条开关横幅；教师门户发布表单可选「同时作为横幅」。
- 接口 `/my/notice_banner`（auth=user，最多 5 条，seq 升序）；`edu_page` 外壳挂载点 + `notice_banner.js`/`banner.css`；无数据/失败时静默零变化。
- 补 `edu.notice` 的 system 组 ACL（原模型无 ACL，控制器均走 sudo）。
- 版本：edu_portal 19.0.1.9.0。

## 本地验证
- `-u edu_portal`：Modules loaded，无 ERROR；49 路由冒烟 49/49；G_messages 复跑 25/25（首跑预热噪音）；downloads_v2_smoke 42/42。
- 三角色接口 200、Playwright 交互全通（圆点切换/关闭/轮播），截图 tests/gap/shots/notice_banner_{closeup,home}.png。
- 演示公告已删，零残留。

## 生产部署（runbook 全流程）
- rsync edu_portal → chmod a+rX → stop web → `-u edu_portal --http-port=8099` → 日志仅 `Modules loaded.` 无 ERROR → start web。
- 探活：/web/login、/、/programs、/contactus 全 200（/my/home 匿名 303 正常）；check_prod_menus.py「全部菜单动作有效」。
- 端到端：生产造【演示】横幅公告 → admin 登录 /my/home 横幅渲染成功（截图 tests/gap/shots/prod_banner_{closeup,home}.png）→ 演示数据已删（残留 0）。
- 后台菜单「布告栏管理」= ir_ui_menu 611 已确认在生产。
- 本次升级随模块一并带上此前已合入本仓库、本地全绿的：批次 4（W3 角标 4608e7b / A1 审批聚合 57c9dab / 清理包）与并行 downloads v2（0a98d34 等，其冒烟 42/42）。

## 管理入口
- 后台：教务审批 → 布告栏管理 → 打开公告 → 「门户横幅」组开关横幅展示、设徽标/按钮文字/链接/排序。
- 用户点 × 仅自己隐藏该条（浏览器本地记忆）；管理员关闭开关则全员撤下。
