# batch4 后清理轮 · 遗留观察笔记
> **状态**：`归档` ｜ **主题**：`batch4 清理遗留` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 日期：2026-08-29 ｜ 范围：五项小清理（死胡同出口 / CSS 死代码 / guest 标题 / handoff 对齐 / CSS 溯源复核）
> 性质：**只记录，不修复**。每条注明出处与建议处置层级。

## 1. 学生档案守卫类「死胡同」未全覆盖（P2）

- 项 1 仅覆盖 ux-audit §二 P1 的 7 个 `/student/*` 页面（batch1.xml×4 + batch2.xml×3）。
- 同款问题仍在：`custom_addons/edu_eval/views/eval_portal.xml` L155 / L238
  「当前账号未关联学生档案…」两条警告无返回出口（ux-audit §二 已列 P2）。
- 建议：下一批 UX 整理时统一抽成共享的「角色不符」警告片段（含返回按钮），一处维护。

## 2. portal.css / enterprise.css 整段同源提取（合规决断项，P2）

- 本轮 §5 溯源复核量化确认：两文件与原站抓取 CSS 声明体逐字相同合计 **447 处**，
  其中含原站自造 `oe-*` 命名的同名选择器去重后 **201 个**，且两文件仍在 manifest assets 加载。
- 详见 `docs/compliance-audit.md` §5.1（本轮只查不改）。决断项：重命名 oe-* 选择器（需同步模板 DOM/JS）
  或整文件品牌变量化改写（custom_home.css B11 路径）。**均需专门批次 + 全量截图回归。**

## 3. custom_home.css 残留原站逐字声明（P3）

- `.oe-cat-title` 一条（文件头「首页六分组标题头」块）：`margin:0 / letter-spacing:-.01em` 仍生效，
  字号/颜色已被 B11 变量规则覆盖。若启动 §5.1 的重命名决断，可一并处理；单独改意义不大。

## 4. custom_home.css 头部块与 B11 段存在重叠声明（P3，重构备忘）

- 文件头 L1-28（.oe-cat-head / .oe-qa-side / oe-cat-dot / oe-cat-title / oe-cat-count）与 B11 段
  L294 起的同名规则部分重叠：仅 `flex:none`、`margin:0`、`letter-spacing` 等少数声明仍靠头部块生效。
- 本轮项 2 已确认其**非死代码**（保守保留）。后续若做 CSS 重构可将两段合并，注意保留仍生效的声明。

## 5. 工程备忘：门户模板无法在 odoo shell 直接渲染验证

- `edu_portal.edu_page` 外壳使用 `request.env` / `request.uid`（如 `b11_fac` 的 t-set），
  shell 里 `ir.qweb._render` 报 `RuntimeError: object is not bound`。
- 涉及外壳的模板改动验证走两条路：a) HTTP 登录态 curl；b) 临时探针用户（建→验→删，零残留，
  本轮项 3 即用此法验证 guest 分支）。

## 6. 已在案老观察（本轮复现，不新增条目）

- shell 启动时 `edu.job.posting.salary_range: unknown parameter 'placeholder'` 警告仍出现——
  已归档于 `docs/compliance-audit.md` §五第二条与 jobs-design.md，无需重复登记。
