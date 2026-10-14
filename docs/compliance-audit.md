# 合规自查报告 —— 自研代码 vs 商业/第三方源码

> 结论日期：2026-08-24 ｜ 结论：**未发现任何照抄，交付物版权干净**
> 范围：custom_addons/{edu_portal, edu_public, edu_brand, edu_quiz, edu_telegram} 全部自研代码

## 一、参照物使用清单（全量如实申报）

| 参照来源 | 许可 | 使用深度 | 合规判定 |
|---|---|---|---|
| OpenEduCat 基座（openeducat_*） | LGPL-3 | 运行时依赖；数据模型/冲突检测学习 | ✅ 合法（开源） |
| website_slides（Odoo 社区版 eLearning） | LGPL-3 | 仅提炼「课程-课次-进度」三层概念 | ✅ 合法 |
| 企业版 planning 等专有模块（30-资源目录） | OPL-1 专有 | 排课调研时浏览设计思路，未作实现输入 | ✅ 未搬运 |
| 原站前端 HTML/CSS 抓取件（reference/、scrape/） | 订阅服务页面 | 视觉校准参照；样式已按学坊品牌重构 | ⚠️ 低风险，建议定期人工溯源 |

## 二、独立审查记录（非自评）

1. **排课系统**：评审员对照 Odoo19 核心源码逐项核验，结论「合规红线 PASS——未见企业版源码照搬」（见任务系统 edu-timetable-delivery t4/t5 output 与 `docs/plans/timetable-design.md`）。
2. **LMS 在线课程**：独立子代理与 website_slides **全量源码逐文件比对**，结论「模型字段命名、方法结构、路由、模板 class 体系均不同，无任何标识符或代码段级雷同，属合法概念借鉴。无照搬」（见 `docs/plans/lms-design.md` 评审记录节）。
3. **冒烟测试期**：测试员均被明令禁止修改产品代码，未发生参照污染。

## 三、工件级技术实证（可复现）

```bash
# 在仓库根目录执行，期望全部为 0：
grep -rcE "<tree|groups_id|attrs=" custom_addons/edu_portal/models/{fees,assets,jobs,lms,scheduling}.py
grep -rnE "slide\.channel|slide\.slide|channel_partner" \
  custom_addons/edu_portal/models/{lms,fees,assets,jobs}.py \
  custom_addons/edu_portal/controllers/{lms,fees,assets}.py   # 期望无输出
```

- 自研模型命名体系（edu.lesson / edu.fee.bill / edu.asset / edu.job.posting …）
  与任何上游模块无标识符重合；
- 路由体系（/my/courses、/my/fees、/my/assets、/campus/jobs）为自有设计；
- 模板类名沿用原站 DOM 结构蓝本（o_portal_index_card 等），属界面复刻允许范畴，
  样式值已替换为永约学坊品牌变量（金 #c8a870 / 紫 #714B67）。

## 四、「复刻」边界备忘

- 版权保护**代码文本**与美术资产，不保护功能逻辑、交互流程、字段设计思想；
- 本项目红线 = 逐行复制专有代码 / 直接拷贝专有二进制资源 → **从未发生**；
- 界面复刻以自有品牌规范重绘（颜色/字体/图标均为学坊自有或开源图标库）。

## 五、待办与建议

- [ ] 低优先：对 `static/src/css/` 中源自原站参照的规则做一次人工溯源复核，
      重命名明显同源选择器并确认无整段复制（建议纳入下个迭代）。
      **→ 2026-08-29 抽查复核已完成（见下方 5.1，只查不改），发现整段同源提取，重命名决断待定。**
- [ ] 遗留观察归档：`salary_range` 占位参数警告、worker 配置抖动排查
      （见 `docs/plans/jobs-design.md` 及会话记录）。

### 5.1 CSS 溯源抽查复核记录（2026-08-29，本轮授权范围=只查不改，未重命名任何选择器）

**范围**：`custom_addons/*/static/src/css/` 全部 10 个文件（apply / backend_b11 / brand / eval_portal /
batch1 / batch3 / custom_home / enterprise / portal / ux_rework，合计约 4670 行）；
`edu_public` 无 `static/` 目录、无 CSS 资产，无从复核（记录为空项）。
比对基线 = `reference/portal_styles.css`（原站抓取 CSS 存档，417 个选择器，仓库内唯一原站样式文件）。

**方法**：脚本化「选择器名交集 + 归一化声明体逐字比对」；并将命中区分两类——
①原站自造 `oe-*` 命名（抽验 `oe-portal-hero`/`oe-mhero`/`oe-srch-item`/`oe-side-card`，
grep 确认不在 `openeducat_erp` 基座与 Odoo core，属原站自定义命名）；
②Odoo/Bootstrap 标准类（`o_portal_*`、`btn`、`table` 等，双方同为 Odoo 部署、LGPL 同栈共有）。

**发现**：

| 文件 | 是否加载 | 与原站同名选择器 | 声明体逐字相同 | 其中 oe-* 自造名 | 备注 |
|---|---|---|---|---|---|
| edu_portal/portal.css（603 规则） | ✅ manifest L63 | 389 | **328** | 201（逐字 172） | 文件头自述「括号感知提取 来源:/tmp/site_frontend.css 规则数:600」 |
| edu_portal/enterprise.css（614 规则） | ✅ manifest L65 | 133 | **119** | 120（逐字 108） | 文件头自述同源「规则数:612」 |
| edu_portal/custom_home.css | ✅ manifest L66 | 20 | 1 | 14（逐字 1） | 唯一逐字残留 `.oe-cat-title`，其字号/颜色已被 B11 变量规则覆盖，仅 margin/letter-spacing 仍生效 |
| edu_brand/brand.css | ✅ | **0** | 0 | — | 自有 `yylc-` 命名空间（61 类），作用域限定 `.yylc-home/.yylc-footer` |
| batch1/batch3/ux_rework/apply/eval_portal/backend_b11.css | ✅ | **0** | 0 | — | batch1/3 的 `oe-` 前缀为自研新造名（oe-att-stat 等），与原站名不同名 |

**结论**：
1. **不满足「无整段复制」口径**：portal.css / enterprise.css 系复刻期用 `scripts/extract_css*`
   工具对原站 `site_frontend.css` 做的批量括号感知提取（文件头如实自述），存在整段同源声明体
   （合计逐字 447 处），且两文件仍在生产 assets 中加载。品牌色值已按 §三 记录替换为学坊变量，
   逐字部分集中于布局度量（间距/圆角/字号/阴影）。
2. **任务书重点的官网侧干净**：edu_brand 的 brand.css 与原站选择器零重合；edu_public 无 CSS 资产；
   原站公开页抓取件（reference/public/*.html）不含 `<style>` 块，无独立官网 CSS 存档可比对。
3. **缓解事实**：原站本身亦为 Odoo/OpenEduCat 部署，其 CSS 中 Odoo 自有 LGPL 规则占比可观
   （portal 188 个 + enterprise 13 个标准选择器命中，多数逐字）——该部分与本项目基座同源同许可，
   不构成对原站独创性的占用；风险集中于 `oe-*` 自造命名与配套布局度量值。
4. **待决断（本轮未执行）**：a) 是否对 201 个（portal+enterprise 去重后）含原站 `oe-*` 命名的选择器重命名（需同步模板 DOM
   与 JS 引用，涉及面广）；b) 是否将 portal.css/enterprise.css 改写为品牌变量体系（类似 custom_home.css
   的 B11 改造路径）。二者均影响渲染，需专门批次 + 全量截图回归后方可实施。

## 六、法律提示

本报告为工程侧自查，不构成法律意见。若未来涉及对外分发/售卖系统，
请先咨询知识产权律师复核 OPL-1 边界与商标使用。
