# 评分模型机制调研：客观/主观双轨评分 + 扣分制评分

> 研究对象：`docs/plans/eval-unified-design.md` §9.7 自认「无源码级取证」的两项机制。
> 立项原因：本仓铁律 0（能装不写、能抄不造）——先查成熟实现，确实无先例才自研。
> 与既有调研的分工：本文**不重复** `docs/research/evaluation-rebuild.md` 已有的结论（Odoo spreadsheet 只读、
> survey 不能当评估引擎、OCA vertical-education 19.0 空仓、Moodle/Canvas rubric 模板→行→列三层等），
> 只补它缺的**双轨合成**与**扣分制**两块。

- 日期：2026-09-30
- 状态：**已完成**（§0–§7 + 附录 A；未验证项见 §7）
- 队长裁定已并入 §6.1 / §6.4（Canvas 主持选定语义**不纳入本期需求**，只登记接缝）

## 0. 调研范围与未验证摘要
状态：✅ 完成

### 0.1 两项机制的判据（只判"有没有同构先例"，不重新设计）

| 机制 | 判据（素材要求 → 必须找到的东西） |
|---|---|
| **机制一 · 客观/主观双轨** | ① 是否存在"**同一个被评对象 × 同一个评分项下，两路固定角色各打一个分**"的实体；② 是否有**合成规则**（等权/加权/取一路）；③ 是否有**"缺一路"的显式规则**（不是静默除 2） |
| **机制二 · 扣分制** | ① 是否存在"**默认满分、按项往下扣**"的评分模型；② 扣分额是否有**上限/地板**；③ 是否有**"扣分来源"与批量重算**的机制 |

### 0.2 一句话结论

- **机制一**：❌ 装不了，✅ **抄得到**（三处先例：Odoo 官方 `hr_recruitment_survey` 的"作答挂被评对象"、Moodle Workshop 的加权平均 + 缺一路跳过 + 教师覆盖、问卷星的分级权重 Σ=100%）。**唯一自研的是"项级双路"这一层**（§6.1）。
- **机制二**：❌ 装不了，✅✅ **有直接先例，且本文把它从"无先例自研"改判为"照先例做"** —— **Moodle 5.0 的 `core_grades` penalty 子系统**（`penalty_container` 累加 + `clamp(grade − penalty, grademin, grademax)` + `max_grade × 百分比 / 100`），以及 Canvas `LatePolicy`（满分 × 百分比 + 最低分地板）。**版本边界：Moodle 5.0 有、4.5 无**（§6.2）。
- **真正无先例的只有"这个组合"**：对象级矩阵 × 项级方向（加分/扣分）× 项级双路 × 分区小计 × Σ=100% 自校验；**为何无先例**逐系统写了机制性原因（§6.3）。

### 0.3 未验证摘要（全 15 条见 §7）

- 国内侧最弱：希沃班级优化大师只有"加分/减分"的用户评论级证据；校管家域名 DNS 失败；学邦/物思/恒谦无一手页（§5.2–5.3、§7-1..3）。
- 企业版 Odoo 模块（`hr_appraisal`/`quality`）**无公开 URL 可复核**（本地快照不是 git 仓库）⇒ 相关结论已标注（§7-10）。
- ⚠ **本仓 `edu.assess.*` 的当前实现未回读**：§6.4 接缝二的"没有被写死"依据是**设计文档的枚举规定**，实现前需自行核代码（§7-12）。

## 1. 先看仓内：既有调研与设计文档已有什么
状态：✅ 完成（2026-09-30）

### 1.1 边界声明：既有调研 `evaluation-rebuild.md` 已覆盖的（本文不复述）

| 主题 | 既有调研结论（只列边界，细节见原文） |
|---|---|
| Odoo 电子表格 | `spreadsheet` 社区版**只读**；`web_grid`/Studio/企业版 spreadsheet 编辑动作不可用 |
| survey 能否当评估引擎 | **不能**：矩阵/量表题 `_compute_is_scored_question` 落 else ⇒ 恒不计分；`survey.user_input.line` 无被评对象字段；题目列表 `create="false"` ⇒ 不能 xlsx 导入 |
| OCA | `vertical-education` 19.0 **空仓零模块**；appraisal/grade/assessment 全组织检索 0 命中；`spreadsheet_oca` 为 AGPL-3 |
| Moodle / Canvas 可抄形状 | rubric「模板 → 行(criteria) → 列(level)」三层；**权重靠分值表达**；Canvas `criterion_use_range` / `free_form_criterion_comments`；`calculation_method` 六枚举 |
| 国内 | 无一做成自由单元格；最像 Excel 的是宜搭子表单、飞书多维表格 |

**本文只补两块**：**机制一 客观/主观双轨** 与 **机制二 扣分制**。凡上面表格已有的内容，本文不再重复取证。

### 1.2 `docs/plans/eval-unified-design.md` §9.7 的缺口陈述（原文摘录）

> | **双轨（客观 + 主观）** | ❌ **未逐条取证** | 调研里最接近的是 Moodle rubric 的 `criterion_use_range` / 双档给分，**不是"两个打分角色各评一路"** |
> | **扣分制** | ❌ **未逐条取证** | 调研提到的"支持负分"（Moodle）只是负分，不等于"满分往下扣" |

同节结论原文：**"本设计在双轨 / 扣分制 / 冻结 / 粘贴 四项上调研不完整。实现前必须补一轮增量调研"**（本文只承担前两项；冻结表头与整块粘贴是另一条线，不在本文范围）。

设计侧已裁定的接口（本文据以判定"缺什么"，**不重新设计**）：
- 双轨：项级 `item.track ∈ {single,dual}`；任务级 `objective_scorer_kind`/`subjective_scorer_kind`；`edu.assess.score` 加 `track`，唯一键追加 `track`；**缺一路默认不计入**（`state=pending`）。
- 扣分：项级 `item.score_mode ∈ {add,deduct}`；**扣分额复用既有 `max_score`**，不新增字段；单元格存"实际扣掉的分数"；项得分 = `max_score − value`。

### 1.3 素材侧事实（引用 `eval-materials-inventory.md`，不重新读表）

- 双轨来源：说明表 1「子评分」列「客观评分 + 主观评分 / 各占 5%」；算式 P052「(客观评分 + 主观评分) ÷ 2 × 百分比」；xlsx `H=(F+G)/2`；只对技能类 12 项启用（[清单 §2.3、§6.1](../plans/eval-materials-inventory.md)）。
- 扣分来源：`卫生检测表` 5 区 × 32 项，每项固定扣分值，**每区各项扣分之和恰好等于区满分**（厨房 5+2+5+5+5+5+3 = 30，程序化核算见 [清单 §8.4](../plans/eval-materials-inventory.md)）；表内**无权重**。
- ⇒ 两条素材事实决定了本文的判据：机制一要判「**两个固定角色 × 同一评分项 × 合成规则（含缺一路）**」；机制二要判「**满分起扣、扣分额有上限、分区分小计**」。

## 2. Odoo 19 核心源码：有没有现成能力
状态：✅ 取证完成（源码逐行读过，非文档推测）

### 2.0 取证基线（可复现）

| 项 | 值 |
|---|---|
| 源码 | 本地快照 `~/Documents/文件大总管/30-资源/odoo源代码企业版/`（社区 + 企业共 **1467** 个模块；`odoo/release.py:15` ⇒ `version_info = (19, 0, 0, FINAL, 0, '')`） |
| 快照性质 | **非 git 仓库**（`git rev-parse` 报"不是 Git 仓库"）⇒ 无法给出快照 commit；改用上游逐行核对 |
| 上游核对 | `raw.githubusercontent.com/odoo/odoo/19.0/addons/...` 可直连（HTTP 200）；`git ls-remote` ⇒ **19.0 分支 head = `4e7b84db9455086754164db5e404987c34d48eb7`**（2026-09-30 核对）。抽样 `survey/models/survey_question.py` 三处（108 / 208-209 / 866 行）**本地快照与上游完全一致** ⇒ 本文行号对社区模块可直接引上游 URL |
| 企业版模块 | `hr_appraisal` / `quality` 只存在于企业版快照，**无公开 URL 可引**；本文凡是引用它们的地方都注明"企业版快照" |

### 2.1 结论速览

| 需求 | Odoo 19 有无 | 源码位置 |
|---|---|---|
| **一路评分一个"评分人"、多人评同一对象** | ✅ 有（两种形态） | `rating.rating`（`rating/models/rating.py:41-44`）；官方模块 `hr_recruitment_survey`（`survey.user_input.applicant_id`） |
| **多路合成规则（平均/加权）** | 🟡 只有**无权重简单平均**，且只作用于 `rating` 混入 | `rating/models/rating_mixin.py:52-59` |
| **"两个固定角色各评一路，再合成一个分"** | ❌ **无** | 见 §2.4、§2.6 |
| **背靠背填写 + 各自"发布"后才可见** | ✅ 有（但只有文本，无分值） | 企业版 `hr_appraisal/models/hr_appraisal.py:68-77` |
| **"缺一路"的规则** | 🟡 只有"低分不进平均" | `rating/models/rating_data.py:14` `RATING_LIMIT_MIN = 1` + `rating_mixin.py:55` |
| **扣分制（满分 − 逐项扣）** | ❌ **无**（只有 4 个"局部近似"：负分选项、时间衰减、加法积分、徽章 karma） | 见 §2.5 |

### 2.2 `survey`：Odoo 里唯一"有量表 + 有分"的模块，但合成规则对不上

1. **计分方向是"累加正分"，不是"满分起扣"**。`survey/models/survey_user_input.py:66-86` 原文：
   - 分母 `total_possible_score` **只累加正分**（`if score > 0`，见 :73 / :75 / :77）；
   - 分子 `score_total = sum(user_input.user_input_line_ids.mapped('answer_score'))`（:83）——**含负分**；
   - `scoring_percentage = score_total / total_possible_score * 100`，并**钳到 ≥ 0**（:86 `round(...) if score_percentage > 0 else 0`）。
   ⇒ 负分选项会**压低百分比**，但（a）语义仍是"累加"，不是"从满分扣"，（b）结果**不允许为负**，（c）分母是"所有正分之和"，**没有一个可配置的"项满分"字段**。
2. **负分只允许出现在"选项"上**：
   - `survey/models/survey_question.py:866`（`survey.question.answer.answer_score`）help 原文：`"A positive score indicates a correct choice; a negative or null score indicates a wrong answer"` ⇒ **选项分值可为负**；
   - 但 `survey_question.py:108` 的**题目级** `answer_score` 被约束死：`survey_question.py:208-209` `_positive_answer_score = models.Constraint('CHECK (answer_score >= 0)', 'An answer score for a non-multiple choice question cannot be negative!')`。
   ⇒ 想用"每题扣 X 分"表达卫生检测表，**题目级做不到**（CHECK 直接拒绝）。
3. **"多评者评同一对象"在核心 survey 里仍然不存在**，但**官方模块给出了标准扩展点**：`hr_recruitment_survey`（社区版，Odoo 官方）：
   - `hr_recruitment_survey/models/survey_user_input.py:9` `applicant_id = fields.Many2one('hr.applicant', ...)` ⇒ **被评对象挂在"一份作答"上**（不是挂在题目行上——这修正了"评估对象无处可放"的推论：核心没有，官方给的是"扩展 `survey.user_input`"）；
   - `hr_recruitment_survey/models/hr_applicant.py:9-10` `response_ids = fields.One2many('survey.user_input', 'applicant_id')` ⇒ **一个被评对象 N 份作答**（N 个面试官各填一份）；
   - `hr_recruitment_survey/models/survey_survey.py:9-10` `survey_type = fields.Selection(selection_add=[('recruitment', 'Recruitment')])` + `hr.job.survey_id` ⇒ **"模板按类型预挂到业务对象"**的官方写法。
   - ⚠ **但官方在此处没有任何合成规则**：`hr_applicant.py:15-31` `action_print_survey()` 只在 N 份里`sorted(reverse=True)` 取**最新一份**去打印。**N 份作答 → 无平均、无加权、无取舍规则**。
4. 模块级统计是"跨人平均"，不是"同人多路合成"：`survey/models/survey_survey.py:103` `answer_score_avg` + :215-251 `_compute_survey_statistic`（对每份作答的 `scoring_percentage` 求平均）。⇒ 这对应"问卷平均分报表"，**不能当双轨合成器**。

### 2.3 `rating` 混入：Odoo 唯一"多评分人 → 自动平均"的现成机制

| 事实 | 源码 |
|---|---|
| 一个评分人一条记录；`rated_partner_id` = 被评者，`partner_id` = 评分者，`rating` = 分值，`consumed` = 是否已评 | `rating/models/rating.py:41-44`、`:54` |
| 字段自带声明式聚合：`rating = fields.Float(..., aggregator="avg", default=0)` | `rating/models/rating.py:44` |
| 宿主侧的"平均分"由 `_read_group(..., aggregates=['__count','rating:avg'])` 算出 ⇒ **简单算术平均，无权重** | `rating/models/rating_mixin.py:52-59` |
| **低于阈值不进平均**：`RATING_LIMIT_MIN = 1`，`_rating_domain() & Domain('rating','>=',RATING_LIMIT_MIN)` | `rating/models/rating_data.py:14`、`rating_mixin.py:55` |

⇒ 这是我们 `edu.assess.score`（多打分人 × 多记录）**最接近的现成形状**，但只解决"平均"两个字：**没有"路"的概念、没有权重、没有"某路缺失"的规则**（它用"低分直接排除"代替）。

### 2.4 企业版 `hr_appraisal`：有"两路 + 背靠背 + 各自发布"，但**两路都是纯文本**

| 事实 | 源码（企业版快照） |
|---|---|
| 两位参与方各有一套模板 | `hr_appraisal/models/hr_appraisal.py:50-51` `employee_feedback_template` / `manager_feedback_template` |
| 两路正文相互独立 | `:68` `employee_feedback`、`:71` `manager_feedback`（均 `fields.Html`） |
| **背靠背 + 发布开关**（本设计 §5.3"两路互不可见"的现成先例） | `:72-77` `employee_feedback_published` / `manager_feedback_published`，help 原文："If greened, the manager will be able to see and edit your feedback. Otherwise, your feedback is **blurred** and visible only to you." |
| "最终评分"只是一个**取值清单**，不是分值 | `:78-79` `assessment_note = fields.Many2one('hr.appraisal.note', string="Final Rating")`；`hr_appraisal/models/hr_appraisal_note.py` **全文只有 `name` / `sequence` / `company_id`** ⇒ 无 score 字段 |
| 打分无处可放 ⇒ 官方自己把打分外挂到 survey | 企业版 appraisal 模板说明与既有调研同证：Odoo 官方文档"Appraisal templates are housed in the Surveys app"（已引于 [evaluation-rebuild.md](evaluation-rebuild.md) 行 157）；本版 `hr.appraisal` 无法直接给"路"打分 |

⇒ **结论**：Odoo 官方的"双路评估"是**两段文本 + 各自发布**，**从不合成一个数**。这正好是我们要的"可见性/发布"先例，而**不是**"合成规则"先例。

### 2.5 扣分制：Odoo 19 全树**没有**"满分 − 扣分"模型；只有 4 个局部近似

| 近似物 | 它是什么 | 源码 | 为什么不能直接用 |
|---|---|---|---|
| ① 选项负分 | 多选题选项可设负分，选错则压低百分比 | `survey/models/survey_question.py:866` + `survey_user_input.py:66-86` | 只支持"选项"粒度；题目级 `answer_score ≥ 0` 被 CHECK 拦住（`survey_question.py:208-209`）；结果钳到 ≥ 0；无"项满分"概念 |
| ② **限时题的分数时间衰减**（全仓最像"往下扣"的一处） | 直播答题里：超 2 秒开始**线性衰减**，超时或切题**直接腰斩** | `survey/models/survey_user_input.py:798-817`：`max_score_delay = 2`；`if question_remaining_time < 0 ...: answer_score /= 2`；`elif seconds_to_answer > max_score_delay: answer_score = (answer_score / 2) * (1 + score_proportion)` | 是"乘系数衰减"，不是"逐项扣固定额"；只在 live session 限时题上生效 |
| ③ 加法积分 + 派生满分 | `hr_referral`：每阶段有 `points`，`earned_points = Σ points`，`max_points = Σ 各阶段 points`（**满分是派生出来的**） | `hr_referral/models/hr_applicant.py:117-119`、`hr_referral/models/hr_job.py:41-44`、`:391` | 纯加法；满分派生这一点**与本设计"区满分 = Σ 子项"（H4）同构**，可抄的是"满分派生"而非扣分 |
| ④ 可负的积分流水 | `gamification.karma.tracking`：`new_value` / `gain = new_value - old_value`，`gain` 可为负 | `gamification/models/gamification_karma_tracking.py:20-22`、`:36-39` | 起点是 0（不是满分），是"奖惩流水"不是"评分" |

企业版 `quality`（`quality.point` / `quality.check`，`odoo/addons/quality/models/quality.py:13/23/192/314`）是**通过-失败 + 测量值**的质检，**没有分值、没有扣分**。

### 2.6 "搜过什么、为什么确认没有"（负结论取证记录，可直接复跑）

在 `~/Documents/文件大总管/30-资源/odoo源代码企业版` 下：

```bash
# 1) 扣分语义：deduct / penalty / demerit / score_mode / negative_score
grep -rni "deduct"      odoo/addons --include=*.py -l   # → 41 文件，全部为工资扣款/本地化税务/账单语义，0 处评分
grep -rni "penalty"     odoo/addons --include=*.py -l   # → 3 文件，均为 l10n_* 工资/薪酬
grep -rni "demerit|negative_score|score_mode" odoo/addons --include=*.py -l   # → 0 命中
# 2) 模型名扫描：评分/等级/量规类实体
grep -rhn "_name = '" odoo/addons --include=*.py | grep -iE "score|grade|rating|evaluat|assess|rubric|checklist"
#   → 只有 rating.rating / rating.mixin / rating.parent.mixin（评星）、res.partner.grade（客户等级）、
#     l10n_pe_reports_lib.financial.rubric（秘鲁财报科目字样，与评分无关）、若干测试模型
# 3) 字段名扫描：满分/总分类字段
grep -rn "max_score|total_score|full_score|base_score|max_points|points_possible" odoo/addons --include=*.py
#   → 仅 hr_referral 的 max_points（加法积分），其余命中都是 survey 内部局部变量 max_score_delay
```

**判定"没有"的三条理由**：① 没有"评分表/评分项"实体（`survey` 的实体是"问题"，且被 CHECK 限制死方向）；② 没有"满分"字段（`hr_referral.max_points` 是加法派生的，不是扣分基线）；③ 没有"扣分额"字段或任何 `>= 0` 之外的钳位逻辑。

## 3. 可「装」的模块（OCA 优先，逐一列 license）
状态：✅ 完成（OCA 逐仓实查 + 应用商店抽查）

> 取证方式：`gh`（本机已登录，token scopes 含 `repo`）⇒ `gh api repos/<org>/<repo>/contents?ref=<branch>` 列目录、`gh search repos/code` 检索；OCR 类站点用 `curl`。**本文不依赖 `web_search`（该工具全程 HTTP 400 insufficient credits）**。

### 3.1 OCA 逐仓实况（19.0 分支）

| 仓库 | 19.0 实况 | license | 与两项机制的关系 |
|---|---|---|---|
| `OCA/vertical-education` | **无任何模块目录**（`?ref=19.0` 只返回 `.copier-answers.yml/.github/LICENSE/README.md` 等仓务文件）；**补证 18.0 同样为空** ⇒ 不是"没迁到 19.0"，是从未有过模块 | 仓库 LICENSE = AGPL-3 | ❌ 无可装 |
| `OCA/survey` | **18 个模块**（19.0）：`partner_survey`、`survey_answer_generation`、`survey_certification_py3o`、`survey_certification_sending`、`survey_contact_generation`(+\_model_selection)、`survey_crm_generation`(+\_model_selection)、`survey_crm_sale_generation`、`survey_legal`、`survey_multi_company`、`survey_next_survey_update_partner`、`survey_partner_representative`、`survey_question_type_model_selection`、`survey_resource_booking`、`survey_result_mail`、`survey_sale_generation`、`survey_skip_start` | **18/18 = AGPL-3**（`grep -h '"license"' */__manifest__.py \| sort \| uniq -c` ⇒ `18 "license": "AGPL-3"`） | ❌ 全是"CRM/生成/多公司/法务"扩展；`grep -rni "deduct\|score_mode\|negative score" --include=*.py .` ⇒ **0 命中**；**无一个模块碰评分、多评者或扣分** |
| `OCA/hr` | 27 条目，模块仅 `hr_course`、`hr_department_code`、`hr_employee_*` 系列 ⇒ **无 `hr_appraisal_oca`** | 仓库 AGPL-3 | ❌ 证实 [evaluation-rebuild.md](evaluation-rebuild.md) 未验证项 14：**19.0 确无 appraisal 模块** |
| `OCA/e-learning` | 仅 3 个 `website_sale_slides_*` 模块（商城侧） | 仓库 AGPL-3 | ❌ 无评分/成绩 |
| OCA 组织级仓库检索 | `gh search repos education` / `school` / `university` --owner OCA ⇒ **只有 `vertical-education` 一仓**；`exam`、`skill`、`appraisal` ⇒ **0 命中**；`evaluation` ⇒ 只命中 `maintainer-tools` | — | ❌ OCA 侧没有"评估/评分/成绩册"仓库 |
| OCA 全组织代码检索 | `gh search code "deduction" --owner OCA` ⇒ 命中全是会计/付款（`account-payment:account_payment_multi_deduction`、`l10n-spain` 等） | — | ❌ **OCA 无"评分扣分"实现** |

**⇒ §3.1 结论：OCA 侧一个能装的都没有**（无评估引擎、无多评者、无扣分），且全系 AGPL-3。

### 3.2 应用商店（apps.odoo.com，非 OCA、第三方付费，**19.0 有售**）

`curl https://apps.odoo.com/apps/modules/browse?search=<词>` 逐词检索（脚本见附录 A-3），命中与两项机制相关的：

| 模块（technical name） | 标题 | 版本 | 价格 | license | 与本机制关系 |
|---|---|---|---|---|---|
| `ng_appraisal` | Employee Appraisal: Review Campaigns, **Self-Assessment, Manager Review, 360 Feedback**, Goals and Ratings | 19.0 | $10.34 | **OPL-1**（页面原文："`<b>License</b></td><td>OPL-1`"+ 全文 Odoo Proprietary License v1.0） | 🟡 **最接近机制一**：自评 + 经理评 + 360 —— 但 **OPL-1 专有**，改不了、派生不了、不能嵌进我们的引擎 |
| `aic_hrm_review` | AIConnect HRM Review - **360, Calibration & 9-Box** | 19.0 | 未取到 | 未验证 | 🟡 多评者 + 校准会语义 |
| `ob_hr_360_feedback_advanced` | HR 360 Feedback Advanced | 19.0 | $15.13 | 未验证 | 🟡 多评者 |
| `abstract_submission_review` | Call for Papers, Abstracts & **Peer Review** | 19.0 | $187.01 | 未验证 | 🟡 多评审人 + 量规评审（学术评审语义） |
| `competency_skills_matrix` | Competency Framework & **Skills Matrix** | 19.0 | $197.95 | 未验证 | 🟡 能力矩阵（非双轨） |
| `bi_employee_penalty` | Employee **Penalty** management | 19.0 | $17.24 | 未验证 | ❌ 是**工资罚款**（薪资侧扣款），不是评分扣分 |

**判定**：商店里的 360 类模块**语义是 HR 绩效**，不是"课程/学生评估表的两个固定评分角色"；且 OPL-1 专有许可**禁止**我们把它当引擎改造。⇒ **不构成可装方案**。

### 3.3 ⚠ AGPL-3 传染性：**需法务确认，本文不下结论**

OCA 全系（含 `vertical-education`、`survey`、`hr`、`e-learning`）manifest 与仓库 LICENSE 均为 **AGPL-3**。我们的系统以门户方式对外提供网络服务，一旦与 AGPL 模块形成衍生/组合作品，AGPL 第 13 条（网络交互）可能触发源码提供义务。**这一条已经超出了工程判断范围 —— 必须由法务出结论，任何人（包括本调研）不得自行下"安全/不安全"的判断。**
⇒ 工程上可先按"**AGPL 视作不可用于本仓**"处理（与本仓既有 `odoo19-debranding-i18n.md` / `evaluation-rebuild.md` 的处理一致），除非法务书面放行。

## 4. 同类开源系统源码取证
状态：✅ 完成（Moodle 4.5 / 5.0 与 Canvas master 源码逐段读过）

> **重大发现先行**：**扣分制不是"没有先例"——Moodle 5.0 有一个专门的 `core_grades` 扣分（penalty）子系统**，公式与我们的设计**同构**（见 §4.1.2）。双轨方面，Moodle Workshop 的"多评者加权平均 + 自评参与 + 教师覆盖"是最接近的现成形状（§4.1.1）。

### 4.1 Moodle（GPL-3，逐文件文件头逐字可核）

#### 4.1.1 机制一（多评者 / 自评与他评混合）：`mod/workshop`

| 事实 | 源码（`MOODLE_405_STABLE`） |
|---|---|
| 一次提交可被 N 个评阅人评，**每人有权重** | `mod/workshop/locallib.php:1491` `add_allocation($submission, $reviewerid, $weight=1, ...)`；`:1511` `$assessment->weight = $weight;`；`:3136-3137` 可改权重 |
| **合成公式 = 权重加权平均** | `locallib.php:3315` `aggregate_submission_grades_process(array $assessments)`：`$sumgrades += $assessment->grade * $assessment->weight;` / `$sumweights += $assessment->weight;`，末尾 `$finalgrade = grade_floatval($sumgrades / $sumweights)` |
| **"缺一路"的规则 = 直接不计入，且不当 0** | 同函数原文：`if (is_null($assessment->grade)) { // this was not assessed yet` → `continue;`（**未评的那路被跳过**）；另有 `if ($assessment->weight == 0)` → `continue;`；只有 `$sumweights > 0` 才算 |
| **教师可覆盖任一评分** | 字段 `gradeover`（提交分覆盖）与 `gradinggradeover`（评阅质量分覆盖）；`aggregate_grading_grades_process` 原文：`if (!is_null($assessment->gradinggradeover)) { $sumgrades += $assessment->gradinggradeover; $count++; } else {...}` ⇒ **有覆盖就用覆盖值，其余忽略** |
| **自评与同伴评进同一个平均**（= 本设计"双轨"在 Moodle 的对应物） | `mod/workshop/mod_form.php:177-180` 复选框 `useselfassessment`；`mod/workshop/lib.php:88/172` 归一化；官方语言串 `mod/workshop/lang/en/workshop.php:429` 原文："If enabled, a user **may be allocated their own submission to assess** and will receive a grade for assessment **in addition to** a grade for their submission."（:430 "Students may assess their own work"）；`locallib.php:3942` 随机分配时按 `$numofself` 分配自评 |
| **"评阅人自己的质量分"是独立一层**（我们没有） | `aggregate_grading_grades`（`locallib.php:2446`）→ `aggregate_grading_grades_process`（`:3352` 起）：对"某评阅人全部评阅"求简单平均得 `gradinggrade` |
| 四种量规形态 | `mod/workshop/form/` = `accumulative` / `comments` / `numerrors` / `rubric` |

⇒ **对机制一的判定**：Moodle 的 `workshop_assessments`（submission × reviewer × weight × grade）与本仓 `edu.assess.score`（task × item × roster × scorer × track）**同构**，可直接抄三件事：① **加权平均**（而非写死除 2）；② **缺一路 = 跳过、绝不当 0**；③ **教师覆盖值优先**。我们的设计比 Moodle 更严（缺一路不进最终分并显式标注），但方向一致。

#### 4.1.2 机制二（扣分制）：**Moodle 5.0 的 `core_grades` penalty 框架**（本文最重要的发现）

| 事实 | 源码（`MOODLE_500_STABLE`；**4.5 无此路径**：同路径 404） |
|---|---|
| 抽象接口：**扣分是可插拔插件** | `grade/classes/penalty_calculator.php:33` `abstract class penalty_calculator { abstract public static function calculate_penalty(penalty_container $container): void; }`（copyright 2025 Catalyst IT Australia，GPL-3） |
| 扣分容器：**扣分额累加 + 钳位到成绩上下限** | `grade/classes/penalty_container.php`：`private float $penalty = 0.0;`（:32）；`aggregate_penalty(float $penalty)`（:171-176）——**传入负值直接抛 `errornegativepenalty`**，否则累加；`get_grade_before_penalties()` = `gradegrade->finalgrade`（:109-110）；`get_grade_after_penalties()` = `self::clamp($this->get_grade_before_penalties() - $this->penalty, $this->get_min_grade(), $this->get_max_grade())`（:120-126，`clamp()` 见 :187） |
| 具体规则插件：**按"满分 × 百分比"扣** | `grade/penalty/duedate/classes/penalty_calculator.php:40-47`：`$deductedpercentage = self::get_penalty_from_rules($cm, $submissiondate, $duedate);` → **`$deductedgrade = $container->get_max_grade() * $deductedpercentage / 100;`** → `$container->aggregate_penalty($deductedgrade);` |
| 规则表：**阈值 + 扣分百分比 + 作用域继承** | `grade/penalty/duedate/classes/penalty_rule.php`：`const TABLE = (gradepenalty_duedate_rule)`（:33）、`define_properties()`（:38，含 `overdueby` 与 `penalty`，各带 `validate_*` :66/:79）、`get_rules(int $contextid)`（:95）、`reset_rules`（:113）、`is_overridden`/`is_inherited`（:139/:155）⇒ **规则按 context 继承/覆盖**，管理界面 `grade/penalty/duedate/manage_penalty_rule.php` |
| 规则匹配语义（阶梯封顶） | 同文件 `get_penalty_from_rules()`：规则按扣分从高到低排序，`if ($diff <= $penaltyrule->get(overdueby)) return $penaltyrule->get(penalty);`；超出最后一档则用最后一档 |
| 批量重算 | `grade/classes/penalty_recalculator.php`、`mod/assign/classes/penalty_recalculator.php`（改规则后重算既有成绩） |
| 输出/可见性 | `grade/classes/output/penalty_indicator.php`、`grade/penalty/duedate/classes/output/`、`grade/penalty/manage_penalty_plugins.php`、`grade/penalty/duedate/templates/` |

⇒ **对机制二的判定**：**"满分往下扣"在成熟 LMS 里是一等公民子系统，不是自研需求**。本设计（`score_mode=deduct`、`max_score` 即扣分上限、`项得分 = max_score − value`、钳位 `0 ≤ value ≤ max_score`）与 Moodle 5.0 `penalty_container` **完全同构**（`max_grade × pct/100` ↔ `max_score` 即扣分额；`clamp(grade − penalty, min, max)` ↔ 钳位）。**差别只在粒度**：Moodle 是"整门成绩一个扣分"，我们是"每个评分项各自可扣分"。

#### 4.1.3 附带证据（"缺一路 / 汇总方向"的既有规则）

- **求和/平均遇到空值有官方注释**：`lib/grade/grade_category.php:1477` 原文注释 `case GRADE_AGGREGATE_MEAN: // Arithmetic average of all grade items (if ungraded aggregated, NULL counted as minimum)` ⇒ Moodle 默认把**未评分当最低分**（与 Workshop 的"跳过"相反，说明这在业界是**必须显式选择**的口径）；同文件聚合枚举：:1041 MEDIAN、:1067 MIN、:1080 MAX、:1093 MODE、:1126 WEIGHTED_MEAN、:1155 WEIGHTED_MEAN2、**:1244 EXTRACREDIT_MEAN（加分项）**、:1315 SUM ⇒ "加分制/扣分制"两向在核心是一等公民。
- **确定性评分（CBM）会产生负分**：`question/behaviour/deferredcbm/behaviour.php:46-56` `get_min_fraction()` / `get_max_fraction()` 都走 `question_cbm::adjust_fraction(...)`；:100-110 `process_finish` 里 `$pendingstep->set_behaviour_var(_rawfraction, $fraction); $pendingstep->set_fraction(question_cbm::adjust_fraction($fraction, $certainty));` ⇒ 原始得分被"自信度"调整，**答错且高自信可低到负**，同时**必须有下界**（`get_min_fraction`）。

### 4.2 Canvas（AGPL-3，文件头逐字可核；**只抄形状，不装代码**）

#### 4.2.1 机制一：**Moderated Grading（主持评分）—— 第四种合并语义：不是平均，而是"选定一份"**

| 事实 | 源码（`instructure/canvas-lms`master`） |
|---|---|
| 作业级开关与"几位评分人" | `app/models/abstract_assignment.rb:54-61` 字段：`moderated_grading`、`final_grader_id`、`grader_count`、`grader_names_visible_to_final_grader`、`grader_comments_visible_to_graders`、`graders_anonymous_to_graders`；:122 `has_many :moderated_grading_selections`；:128 `belongs_to :final_grader` |
| 校验：**≥1 位评分人；非主持模式禁止匿名/主持字段** | `:249-258`：`with_options unless: :moderated_grading? do validates :graders_anonymous_to_graders, absence: true; validates :final_grader, absence: true; end`；`with_options if: -> { moderated_grading? } do validates :grader_count, numericality: { greater_than: 0 }; validate :final_grader_ok?` |
| **每位评分人一份"临时成绩"** | `app/models/moderated_grading/provisional_grade.rb:24` 字段 `score grade graded_at final source_provisional_grade_id graded_anonymously scorer_id`；:30 `belongs_to :scorer, class_name: (User)`；:54-57 作用域 `scored_by(scorer)` / `final` / `not_final` / `graded` |
| **"最终分"不是算出来的，是选出来的** | `app/models/moderated_grading/selection.rb:20-26` `class ModeratedGrading::Selection` + `belongs_to :provisional_grade, foreign_key: :selected_provisional_grade_id`；:30-36 `create_moderation_event(user)` ⇒ **选择动作留审计事件** |
| 硬前置：**没有非最终成绩就不许给最终分** | `provisional_grade.rb:43-44` `before_create :must_be_final_or_student_in_need_of_provisional_grade, :must_have_non_final_provisional_grade_to_create_final`；:65-68 抛 "Cannot give a final mark for a student with no other provisional grades" |
| 最终分落地 | `provisional_grade.rb:119-126` `publish!`：`submission.score = score; submission.graded_anonymously = graded_anonymously;`；`final` 那份可带 `source_provisional_grade_id` ⇒ **"基于某一路修订后作为最终"** |

⇒ Canvas 证明：**"多评者合并"存在第 4 种合法语义 —— 主持人在各路之间选一份（或手写一份）作为最终分**，并保留匿名与审计。这补充了本设计 §5.3 只考虑的"平均 / 缺一路"两档。

#### 4.2.2 机制二：**LatePolicy（迟交/缺失按百分比扣分）—— 语义最接近的"扣分制"实现**

| 事实 | 源码（`canvas-lms`master`） |
|---|---|
| 扣分只对可换算的分值类型生效 | `app/models/late_policy.rb:22` `POINT_DEDUCTIBLE_GRADING_TYPES = %w[points percent letter_grade gpa_scale].freeze` |
| 百分比字段钳在 0..100 | `late_policy.rb:28-36` `numericality: { greater_than_or_equal_to: 0, less_than_or_equal_to: 100 }`（含 `late_submission_minimum_percent`、`missing_submission_deduction`、`late_submission_deduction`）；:37-38 `late_submission_interval` ∈ `day` / `hour` |
| **扣分算法（含"最低分地板"）** | `late_policy.rb:41-51` `points_deducted(score:, possible:, late_for:, grading_type:)`：`intervals_late = (late_for / interval_seconds).ceil`；`minimum_percent = late_submission_minimum_percent_enabled ? ... : 0.0`；`maximum_deduct = [raw_score_percent - minimum_percent, 0.0].max`；`late_percent_deduct = late_submission_deduction * intervals_late`；**返回 `possible * [late_percent_deduct, maximum_deduct].min / 100`** |
| **"满分 − 扣分"的直接写法** | `late_policy.rb:53` `missing_points_deducted = points_possible.to_f * missing_submission_deduction.to_f / 100`；:59 `points_for_missing = points_possible.to_f - missing_points_deducted(...)` ⇒ **正是我们的 `项得分 = max_score − 扣分`** |
| 扣分**持久化**并驱动重算 | `submissions.points_deducted` 列：`lib/late_policy_applicator.rb:116` `submissions(assignment).not_late.where("submissions.points_deducted > 0")`；:76 ``course.recompute_student_scores(user_ids.uniq)` ⇒ 改策略后批量重算（与 Moodle `penalty_recalculator` 同款） |

### 4.3 可直接抄进本设计的四个形状（同行已验证的写法，不是"建议"）

1. **"缺一路"绝不等于 0**：Moodle Workshop 直接跳过未评那路；我们的设计更严（`state=pending` + 标注"缺一路"）；而 Moodle gradebook 的默认口径恰好相反（NULL 当最低分）⇒ **这一点必须显式选择并写进契约**，否则不同实现会给出不同总分。
2. **合并规则至少有三种**：加权平均（Workshop）/ 简单平均（Odoo `rating_avg`）/ **选定一份 + 覆盖**（Canvas moderation）。我们的 `(客观+主观)/2` 只是第一种的特例；建议枚举里预留"主持选定"语义（本期可只实现平均）。
3. **扣分额 = 满分 × 比例（或满分即扣分上限），且必须有地板**：Moodle 5.0 `max_grade × pct/100` + `clamp(..., grademin, grademax)`；Canvas `points_possible × pct/100` + `maximum_deduct` 地板；本设计复用 `max_score` ⇒ **三者一致**。
4. **扣分应是"可插拔规则 + 可批量重算"**：Moodle `penalty_calculator` 抽象类 + `penalty_recalculator` + 规则按 context 继承覆盖；Canvas `LatePolicy` + `LatePolicyApplicator`。⇒ 我们的 `score_mode` 若只做成布尔字段，将来加"迟到扣分 / 缺勤扣分 / 一票否决"就要动核心；**留成枚举 + 记录扣分来源**才与同行同构。

## 5. 国内同类：功能名 + 官方 URL
状态：✅ 有真实命中（问卷星）+ 3 处**未验证**（含具体原因）

### 5.0 本节取证手段与**工具故障记录**（下一个人不必再试一遍）

| 手段 | 结果 | 说明 |
|---|---|---|
| `web_search` 工具 | ❌ **全程 HTTP 400 insufficient credits** | 已知故障，未使用 |
| `apps.odoo.com` 检索 | ✅ 可用 | `curl` + 正则；见 §3.2 与附录 A-3 |
| DuckDuckGo HTML（`html.duckduckgo.com/html/?q=`） | 🟡 **首查成功、其后全部 202 + 14KB anomaly 页** | 反爬；不能依赖 |
| Bing（`www.bing.com/search`） | 🟡 200/124KB，但正文里**取不到结果块**（结构与常见 `<h2><a` 不同） | 未继续深挖 |
| **Jina Reader（`https://r.jina.ai/<URL>`）** | ✅ **可用**（能渲染 SPA 文本） | **本次国内取证的主力手段** |
| Exa（`mcporter call exa.web_search_exa`） | ❌ `Unknown MCP server (exa)` | 本机未配置该 MCP server |
| `api.github.com` 未认证额度 | ❌ 已耗尽（任务已知） | 改用已登录的 `gh`（token 含 `repo` scope）⇒ **可用** |

### 5.1 问卷星「360度评估」—— **机制一在国内已是产品化能力**（一手：官方帮助中心，Jina 可复现）

- 产品页：<https://www.wjx.cn/app/360staff.aspx>；产品介绍（`helpid=368`）：适用"绩效考核、人才盘点、**教学评估**、民主评议、人才发展、岗位竞聘"。
- **使用向导 `helpid=246`**（<https://www.wjx.cn/help/help.aspx?helpid=246>）原文摘录（逐字）：
  - 「### 1、录入"无上下级关系"的评价关系 —— **无上下级的评价关系是指，评价关系中只有被评人与评价人两个概念**」
  - 「### 2、录入"有上下级关系"的评价关系 —— **评价人又可细分为上级、下级、同级等**」
  - 「录入有上下级的评价关系后，可以**针对不同级别设置该级别所占权重**。注：**权重加总必须等于100%**。」
  - 目录结构：「二、录入评价关系」「三、问卷内容&维度设置」「四、发送测评问卷」「五、测评报告&数据下载」
- 另有「360度评估——问卷维度设置」（`helpid=367`）、「360度评估——多个权重值的设置」（`helpid=373`）两篇**标题级**证据（正文为导航+JS，未取到操作细节）。

⇒ **判定**：① "**多个评价方 + 分级权重 + Σ权重=100% 校验**"在国内成品里**有现成形态**（对应本设计的"双轨 + 占比 Σ=100%"）；② 但问卷星的粒度是"**按评价人级别**设权重"，**没有**"同一评分项下客观/主观两路各占一半"这种**项级固定双路**概念 ⇒ 机制一的"合成规则"部分可抄，**"项级双路"这一层没有直接对应物**。

### 5.2 希沃（seewo）班级优化大师 —— 扣分制的国内对应物（**证据只到"加减分"层级**）

- 官方站点：<https://care.seewo.com/app/activity/guide/>（班级优化大师官方引导页）。**该站为 SPA**：`curl` 下载 4,344,617 字节，但去掉标签后正文仅 **5,413 字节营销文案**，关键词「减分/扣分/加分/积分/评分/规则/排序」**全部 0 命中**；用 Jina 渲染后拿到 6,721 字节，仍是营销概述 ⇒ **操作级证据未取到**。
- Apple 应用商店页（<https://apps.apple.com/cn/app/id989685406>，经 Jina 取正文）：厂商描述为"老师可以在课堂对学生行为进行**点评**"；**同时命中「可以随时对学生加分、减分，家长也看得到」——但该句出自用户评论，非厂商功能说明**。
⇒ **证据强度：中**。"加分/减分"是该产品的公开可见机制，但**一手厂商文档未逐字取到** ⇒ 按本仓规矩**标注为未验证**，不得当结论用。功能名可写："班级优化大师 · 课堂点评（加减分）"。

### 5.3 校管家 / 学邦 / 希沃魔方 —— 本次**未取到**（原因逐条写明）

| 目标 | 结果 | 具体原因 |
|---|---|---|
| 校管家官网 `https://www.xiaoguanjia.com/` | ❌ 未取到 | Jina 返回 **HTTP 422 / `ERR_NAME_NOT_RESOLVED`**（域名在本机 DNS 解析失败）；DDG 二次检索此时已被反爬拦截 |
| 希沃魔方综合评价 | ❌ 未取到 | 沿用既有调研结论：产品页 `https://www.seewo.com/product/common/ZHPJ` `curl` 返回 **HTTP 000**（连接失败） |
| 学邦 / 恒谦 / 物思 | ❌ 未取到 | 本次**未找到可直连的官方功能页**；`web_search` 故障 + DDG 反爬 ⇒ 无一手来源，故不写结论 |
| 钉钉宜搭 / 企业微信 / 飞书 | 🟡 **本次未新增证据** | 既有调研 [evaluation-rebuild.md](evaluation-rebuild.md) §5 已有结论（宜搭子表单 xlsx 往返、飞书多维表格评分字段+公式字段）；本文**不重复**，也不凭记忆补充 |

⇒ **合并口径**：国内已证实存在"**多评价方 + 分级权重**"（问卷星，一手）；**未证实**任何国内教务 SaaS 提供"**扣分制 + 分区小计**"（素材《卫生检测表》的形态）——这一条保持**未验证**，不作为"国内也没有"的结论使用。

## 6. 结论
状态：✅ 完成（含队长 2026-09-30 裁定）

### 6.1 机制一（客观/主观双轨）：**能抄不能装，且不是"无先例"**

| 维度 | 结论 | 依据 |
|---|---|---|
| **能装？** | ❌ **不能** | Odoo 19 核心无"两路固定角色 + 合成"实体（§2.4/§2.6）；OCA 一个能装的都没有（§3.1）；应用商店 360 类模块为 **OPL-1 专有**（§3.2） |
| **能抄？** | ✅ **能，而且有三处** | ① **数据形状**：Odoo 官方模块 `hr_recruitment_survey` 用 `survey.user_input.applicant_id` + `response_ids` 表达"一个被评对象 N 份作答"（§2.2.3）；② **合并算法**：Moodle Workshop 的多评者**加权平均**、未评那路 `continue` 跳过、教师 `gradeover` 覆盖、自评通过 `useselfassessment` 进同一平均（§4.1.1）；③ **权重自校验**：问卷星"分级权重 + 权重加总必须等于 100%"（§5.1） |
| **必须自研的部分** | 🟡 **只有"项级固定双路"这一层** | 没有任何一家把"**同一评分项**下分客观/主观两路、且两路角色固定"做成实体：Moodle/Canvas 是"N 人评同一提交"，问卷星是"按评价人级别设权重"，Odoo 是"两段文本" ⇒ **项级 track 字段属自研，但属"把先例降维到项级"，不是无先例发明** |

**对本设计的判定**：设计稿的 `项分 = (客观 + 主观) / 2` **就是 Workshop 加权平均在"两路权重各 1"时的特例** ⇒ 有先例支撑，可以直接实现；"缺一路不进最终分并显式标注"比 Moodle 的"静默跳过"更严，属**改进而非偏离**。

**⚠ 队长裁定（2026-09-30）—— 不要抄 Canvas 的第四种语义当需求**：素材说明表 1 明写「客观评分 + 主观评分 **各占 5%**」，即**等权相加**，口径已定；Canvas Moderated Grading（主持人在多份 provisional grade 中"选定一份"）**本期不实现**。理由：**素材是规格，不用别人的产品设计覆盖用户明确写下的口径**。只做"不堵死"的两件事，见 §6.4。

### 6.2 机制二（扣分制）：**有明确先例，从"需自研"改判为"照先例做"**

| 维度 | 结论 | 依据 |
|---|---|---|
| **能装？** | ❌ 不能 | Odoo 19 全树无"满分−扣分"模型（§2.5）；OCA 无评分扣分模块（§3.1）；商店 `bi_employee_penalty` 是工资罚款语义（§3.2） |
| **能抄？** | ✅✅ **有直接先例（本次调研最大产出）** | **Moodle 5.0 `core_grades` penalty 子系统**：`penalty_container` 累加扣分 + `get_grade_after_penalties() = clamp(grade − penalty, grademin, grademax)`；`gradepenalty_duedate` 规则 = **`max_grade × 百分比 / 100`** 后 `aggregate_penalty()`（§4.1.2）。**Canvas `LatePolicy`**：`points_for_missing = points_possible − points_possible × pct/100`，且带 `maximum_deduct` 最低分地板（§4.2.2） |
| **版本边界（必须写清，别让后人以为 4.x 也有）** | **5.0 才有** | `MOODLE_500_STABLE` 的 `grade/penalty/duedate/manage_penalty_rule.php` → **HTTP 200**；`MOODLE_405_STABLE` 与 `main` 的同路径 → **HTTP 404**（`main` 已迁移到 `public/grade/...`，同路径 200）⇒ **Moodle 4.5 及更早没有这套 扣分框架**，4.x 项目要自实现同构物 |
| **必须自研的部分** | 🟡 **只有"项级扣分 + 分区小计"** | Moodle/Canvas 的扣分作用于**整门课/整次作业的成绩**（grade item / submission），**没有**"一张表 5 区 32 项、每项各自可扣、区满分=Σ项"的形态（§6.3） |

**对本设计的判定**：`score_mode=deduct` + "`max_score` 即扣分额" + "`项得分 = max_score − value`" + 钳位 `0 ≤ value ≤ max_score` **与 Moodle penalty_container 同构**（扣分额按满分比例、扣后钳位、扣分来源可插拔）。**实现时至少保留三件**：① 扣分额封顶；② 扣后钳位下界；③ **扣分来源可标识**（Moodle 用插件 + 规则表，Canvas 用 `points_deducted` 列）—— 这样"迟到扣分/缺勤扣分"将来是加规则而不是改核心。

### 6.3 明确"无先例、必须自研"的部分与**为何无先例**

**真正无先例的不是单点机制，而是这个组合**：
> **对象级矩阵（行=被评者）× 项级评分方向（加分/扣分可逐项不同）× 项级双路（客观/主观）× 分区小计（区满分由 Σ 子项派生）× 全表 Σ=100% 自校验**

各方都缺其中一环，**原因各不相同**：

| 系统 | 缺的那一环 | **为何无先例（机制性原因，不是"没人想到"）** |
|---|---|---|
| Odoo 19 | 评估实体本身 | Odoo 把"评估"拆给了三个不同域：`survey`（问卷，**没有"被评对象"**，官方只能靠 `hr_recruitment_survey` 外挂 `applicant_id`）、`rating`（对**任意记录**评星，一个评分人一行，只有平均）、企业版 `hr_appraisal`（**两路纯文本**，Final Rating 无分值）。**Odoo 的 ORM 没有"用户自定义列 = 用户自定义评分项"的实体**（列必须是字段）⇒ 项级可配置的评估表在 Odoo 里天然无法用标准模型表达 |
| OCA | 完全空白 | `vertical-education` 18.0/19.0 **两代空仓**；评估/成绩类仓库在 OCA 组织内不存在（§3.1）⇒ 社区从未接手这个垂直域 |
| Moodle | 项级（criterion 级）与"表级"的桥 | Workshop 有 rubric 形态的量规（`mod/workshop/form/rubric`）与多评者加权平均，但它的单位是"**一次提交 × N 名评阅人**"，**没有"一张多区段检查表"**；gradebook 的聚合以 **grade item（整门成绩）**为单位 ⇒ 扣分只能做在 grade item 上（这正是 5.0 penalty 的位置），做不到"项级方向" |
| Canvas | 同上 + 合成语义不同 | rubric 以 **assignment/submission** 为单位；moderation 是"选定一份"；扣分（LatePolicy）挂在 **assignment** 上并按百分比 ⇒ 同样没有"项级扣分 ± 分区小计" |
| 国内 | 数据模型层 | 问卷星把"多评价方 + 权重"做成了产品（§5.1），但**扣分制的典型载体是 Excel 模板与班级行为点评**（§5.2），**不是**可配置的评估数据模型 ⇒ 国内的做法是把这类表留在 Excel 里 |

⇒ **自研授权是成立的，但要按"降维复用"写明白**：本设计**不需要发明新机制**，只需要把①Moodle Workshop 的加权合并、②Moodle 5.0 penalty 的扣分容器、③Odoo 官方 `hr_recruitment_survey` 的"作答挂被评对象"三块**降到项级**并组合起来。这是**"能抄不造"的合规形态**，不是"自研"。

### 6.4 给设计文档的两条"不堵死"接缝（队长裁定，本文给出可直接粘贴的文本）

**接缝一 · 合成规则（建议插入 §3.5「三种算法」表 A3 行之后）**：

> **业界存在第四种合并语义（本期不实现，仅登记）**：Canvas **Moderated Grading** 不是平均，而是"每位评分人各出一份临时成绩（`ModeratedGrading::ProvisionalGrade`），由主持人**选定其中一份**（或手写一份）作为最终分"，并留 `create_moderation_event` 审计（`app/models/moderated_grading/selection.rb`、`provisional_grade.rb`，见 `docs/research/scoring-dual-track-and-deduction.md` §4.2.1）。
> **本期不实现**：素材说明表 1 已把口径写死为「客观评分 + 主观评分 **各占 5%**」（等权相加），规格优先于外部产品设计。
> **将来要加时的接缝**：① 项级合并必须**走算法枚举分派**（本设计 §5.5 N1 已规定"算法族固定为枚举"），**不得**在任何渲染/汇总路径里内联 `(a + b) / 2`；② `edu.assess.score` 的 `track` 已是行级标签，加"选定"语义只需再加一个"哪条记录是最终分"的标记位，不动唯一键；③ 结果页"缺一路"的判定逻辑与"选定"语义共用同一处 `state` 计算，不要各自实现。

**接缝二 · 「平均」是否被写死（自检结论）**：

- **已核对**：设计稿把汇总表达为 **A1 加权求和 / A2 占比加权 / A3 双轨平均** 三个**具名算法**，并明确规定"凡算法族固定为枚举，不做自由公式编辑器"（`eval-unified-design.md` §3.5 三种算法表、§5.5 N1、§6.10）⇒ **规则分派这一层没有被写死**，余量已在。
- **实现时必须守的一条**：A3 只允许在**一个**地方实现（项分合并的单一入口），**禁止**在 xlsx 导出、结果页渲染、打印报表里各自写一次 `(客观 + 主观) / 2`。设计稿 §5.4 已自带同款风险的告警（"同一张 `edu.assess.score` 表里 `value` 有两种读法，任何跨模板汇总代码都必须带上 `score_mode` 与 `track`"）——A3 与 A2/A1 的调用点必须服从同一约束。

## 7. 未验证 / 待确认清单（**不得当结论用**）
状态：✅ 15 条

| # | 未验证项 | 具体原因 |
|---|---|---|
| 1 | 希沃**班级优化大师**的"减分"是厂商明示机制 | 官方站 `care.seewo.com` 为 **SPA**：4.34 MB HTML 抽文本仅 5.4 KB、关键词 0 命中；Jina 渲染后 6.7 KB 仍是营销页；"加分、减分"字样只见于 **Apple 商店页的用户评论** ⇒ 证据强度只到"中" |
| 2 | 校管家（`xiaoguanjia.com`）的巡课/检查评分能力 | Jina 返回 **HTTP 422 / ERR_NAME_NOT_RESOLVED**（本机 DNS 解析失败），未见任何一手页 |
| 3 | 学邦 / 恒谦教育 / 物思 / 希沃魔方综合评价 | 本次未找到可直连官方功能页；`web_search` 工具 400、DDG 反爬 202 ⇒ **无一手来源，故不写结论** |
| 4 | 钉钉宜搭 / 企业微信 / 飞书 的**扣分制**证据 | 本次未新增取证（不重复既有调研 §5 的结论）；既有调研亦未涉及"扣分制" |
| 5 | 应用商店其余模块的 license（`aic_hrm_review` / `ob_hr_360_feedback_advanced` / `abstract_submission_review` / `competency_skills_matrix` / `bi_employee_penalty`） | 详情页 License 字段**部分动态渲染**，正则取到的是无关词（如 Employee / India）⇒ 只有 `ng_appraisal` 的 **OPL-1** 是逐字核实的 |
| 6 | 应用商店模块在真实 Odoo 19 上的可安装性与兼容性 | 只读了页面，**未安装实测** |
| 7 | Canvas `submissions.points_deducted` 列的迁移定义、New Quizzes 的迟交扣分路径 | 仅由 `lib/late_policy_applicator.rb:116` 的 SQL 反推列存在；迁移文件未逐行核 |
| 8 | Moodle Workshop 自评的**权重取值**（是否与同伴评同权）、`$numofself` 的语义 | `locallib.php:3942` 只见 `if ($workshop->useselfassessment and $numofself)`；权重分配路径未逐行核 |
| 9 | Moodle 5.0 penalty 框架的**全链路 UI 与是否作用于课程/类别总成绩** | 只读了 `grade/classes/` 与 `grade/penalty/duedate/classes/` 源码；未跑实例、未读其测试 |
| 10 | 本地企业版快照的确切 commit | 该目录**不是 git 仓库**（`git rev-parse` 报错）⇒ 企业版模块（`hr_appraisal`/`quality`）**无法用公开 URL 逐行复核**；社区模块已用上游 19.0 head `4e7b84db9455086754164db5e404987c34d48eb7` 抽样核对一致 |
| 11 | `hr_appraisal` 的"两路文本 + 发布开关"在 UI 上的真实行为 | 只读了模型字段与 help 文案，**未在运行实例点开界面** |
| 12 | ⚠ **本仓 C 套 `edu.assess.*` 当前实现**是否真的没有硬编码除 2 | 本文对 §6.4 接缝二的判断依据是**设计文档的枚举规定**（§3.5 / §5.5 N1），**不是回读当前代码**（本任务限定只调研、不动 custom_addons）⇒ 实现前**必须自行回读代码确认**。 **→ 2026-09-30 已回读闭环（代码级核实，落点为 `docs/plans/eval-unified-design.md` §3.5「代码级核实」）**：源码 `/2` 与 `*0.5` 均 **0 命中**、五张模型**无 `track`/dual 维度** ⇒ **无内联除 2**；但定位到 `models/assess.py:424` 与 `:432-437` 两处**通用均值**，A3 落地时须收敛到单一入口 |
| 13 | 问卷星「多个权重值的设置」（`helpid=373`）的具体交互 | 正文为导航 + JS，仅标题与 URL 可证 |
| 14 | Moodle / Canvas 官方文档的正文字句 | 沿用既有调研：`docs.moodle.org` 被 Cloudflare 403；本文所有行为结论**一律取源码**，不以文档为准 |
| 15 | DuckDuckGo / Bing 检索通道的可用性 | DDG 首查 200 成功、随后全部 202（14 KB anomaly 页）；Bing HTML 200 但结果块结构未匹配；**Jina 代理搜索引擎（`r.jina.ai/https://www.bing.com/search...`、ddg lite）返回 HTTP 000** ⇒ 均不可依赖，已记在 §5.0 与 A-4 |

## 附录 A. 可复现取证命令与排除掉的路径
状态：✅ 全部为本次实际执行过的命令（复制即可复跑）

### A-1 Odoo 19 源码（§2 全部结论）

`BASE=~/Documents/文件大总管/30-资源/odoo源代码企业版`（社区 + 企业共 1467 模块；**不是 git 仓库**）

````bash`
cd "$BASE"
# 版本基线
grep -n "version_info" odoo/release.py            # → (19, 0, 0, FINAL, 0, "")
# 扣分语义：本文负结论的依据
grep -rni "deduct"  odoo/addons --include=*.py -l | wc -l          # 41 文件，全部工资/会计/本地化
grep -rni "penalty" odoo/addons --include=*.py -l                  # 3 文件，均 l10n_* 工资
grep -rni "demerit|negative_score|score_mode" odoo/addons --include=*.py -l   # 0 命中
# 评分类实体清单（模型名）
grep -rhn "_name" odoo/addons --include=*.py | grep -iE "score|grade|rating|evaluat|assess|rubric|checklist"
# 满分类字段
grep -rn "max_score|total_score|full_score|base_score|max_points|points_possible" odoo/addons --include=*.py
# 关键行
sed -n "66,86p"   odoo/addons/survey/models/survey_user_input.py   # 计分公式 + 钳 0
sed -n "798,817p" odoo/addons/survey/models/survey_user_input.py   # 限时题时间衰减（往下扣的近似）
sed -n "108p;208,209p;866p" odoo/addons/survey/models/survey_question.py   # 题目级 CHECK >= 0 / 选项级可负
grep -n "applicant_id" odoo/addons/hr_recruitment_survey/models/*.py        # 官方"被评对象"扩展点
grep -n "assessment_note|_feedback" odoo/addons/hr_appraisal/models/hr_appraisal.py
cat odoo/addons/hr_appraisal/models/hr_appraisal_note.py           # Final Rating 只有 name/sequence
````

**上游逐行核对（把本地行号变成可点 URL 的依据）**：

````bash`
git ls-remote https://github.com/odoo/odoo refs/heads/19.0     # → 4e7b84db9455086754164db5e404987c34d48eb7
curl -s -o /tmp/sq.py https://raw.githubusercontent.com/odoo/odoo/19.0/addons/survey/models/survey_question.py
grep -n "answer_score = fields.Float|_positive_answer_score|A positive score indicates" /tmp/sq.py   # 108 / 208 / 866 行一致
````

### A-2 OCA（§3.1 负结论，逐条可复跑）

````bash`
# 组织级仓库检索：education/school/university → 只有 vertical-education；exam/skill/appraisal → 0 命中
gh search repos education --owner OCA --limit 12 --json fullName --jq ".[].fullName"
for q in appraisal exam skill competency gradebook; do gh search repos "$q" --owner OCA --limit 5; done
# 目录级实况（19.0 与 18.0 都空）
gh api "repos/OCA/vertical-education/contents?ref=19.0" --jq ".[].name"
gh api "repos/OCA/vertical-education/contents?ref=18.0" --jq ".[].name"
gh api "repos/OCA/hr/contents?ref=19.0" --jq ".[].name"                 # 无 appraisal 模块
gh api "repos/OCA/e-learning/contents?ref=19.0" --jq ".[].name"         # 仅 3 个 website_sale_slides_*
# survey 19.0：18 个模块，license 全为 AGPL-3，且与评分无关
git clone -q --filter=blob:none --depth 1 -b 19.0 https://github.com/OCA/survey /tmp/oca-survey
grep -h "license" /tmp/oca-survey/*/__manifest__.py | sort | uniq -c   # 18 行 license = AGPL-3
grep -rni "deduct\|score_mode\|negative score" --include=*.py /tmp/oca-survey | wc -l   # 0
# 全组织代码检索：deduction → 全是会计/付款
gh search code "deduction" --owner OCA --limit 15
````

### A-3 应用商店（§3.2）

````bash`
# 搜索页（服务端渲染出 h5 标题；卡片 class = loempia_panel_summary）
python3 /tmp/apps_search.py "360 feedback" "evaluation scoring" "deduction" "rubric"
# 详情页逐字核 license（ng_appraisal → OPL-1）
curl -s -A "Mozilla/5.0" "https://apps.odoo.com/apps/modules/19.0/ng_appraisal" -o /tmp/ng.html
tr "\n" " " < /tmp/ng.html | grep -o "License.\{0,80\}"
````
（`/tmp/apps_search.py` 为本次临时脚本：抓 `browse?search=` 页面 → 正则 `<a href="/apps/modules/...">` 取其内 `<h5>` 标题与 `oe_currency_value` 价格 ⇒ 输出「标题 | 价格 | URL」。）

### A-4 国内检索（§5）：**成功路径与失败路径都要记**

````bash`
# ✅ 唯一稳定可用的"渲染 + 取正文"手段：Jina Reader
curl -s "https://r.jina.ai/https://www.wjx.cn/help/help.aspx?helpid=246" -o /tmp/w246.txt   # 全文（含权重段落）
curl -s "https://r.jina.ai/https://apps.apple.com/cn/app/id989685406" -o /tmp/as.txt        # App Store 正文
curl -s "https://r.jina.ai/https://care.seewo.com/app/activity/guide/" -o /tmp/seewo_j.txt  # SPA 可渲染，但只有营销文案
# ❌ 失败路径（不要重复）
#   1) DDG HTML：首查 200 / 34 KB 成功；随后同参数连续 3 次返回 202 + 14,215 字节 anomaly 页
#   2) Bing HTML：200 / 124 KB，但正文无结果块结构 ⇒ 未取到条目
#   3) Jina 代理搜索引擎：r.jina.ai/https://www.bing.com/search?... 与 ddg lite 均 HTTP 000（连接失败）
#   4) mcporter call exa.web_search_exa → "Unknown MCP server (exa)"
#   5) Jina → https://www.xiaoguanjia.com/ → HTTP 422 / ERR_NAME_NOT_RESOLVED
#   6) curl care.seewo.com → 200 / 4,344,617 字节，抽文本仅 5,413 字节（SPA）
````

### A-5 Moodle / Canvas（§4）

````bash`
CV=https://raw.githubusercontent.com/instructure/canvas-lms/master
curl -s "$CV/app/models/late_policy.rb"                         # 扣分算法（41 / 53 / 59 行）
curl -s "$CV/lib/late_policy_applicator.rb"                     # 扣分落库 + 批量重算
curl -s "$CV/app/models/abstract_assignment.rb"                 # moderated_grading 配置（54-61 / 122-128 / 249-258）
curl -s "$CV/app/models/moderated_grading/provisional_grade.rb" # 每评者一份（24 / 30 / 43 / 54-57 / 119-126）
curl -s "$CV/app/models/moderated_grading/selection.rb"         # 选定 + 审计事件
# 定位被改名/移动的文件（api.github.com 直连偶发 TLS 超时，改用 gh 更稳）
gh api "repos/instructure/canvas-lms/contents/app/models/moderated_grading?ref=master" --jq ".[].name"

MD=https://raw.githubusercontent.com/moodle/moodle
curl -s "$MD/MOODLE_405_STABLE/mod/workshop/locallib.php"      # 加权平均聚合（3315 起）+ 自评（109 / 3942）
curl -s "$MD/MOODLE_405_STABLE/mod/workshop/mod_form.php"      # useselfassessment（177-180）
curl -s "$MD/MOODLE_405_STABLE/lib/grade/grade_category.php"   # 聚合枚举 + NULL 当最低分（1477）
curl -s "$MD/MOODLE_405_STABLE/question/behaviour/deferredcbm/behaviour.php"   # CBM 可负分 + 有下界
# ★ 扣分框架的版本边界（关键取证：5.0 有 / 4.5 无 / main 已移到 public/）
for br in MOODLE_500_STABLE MOODLE_405_STABLE main; do printf "%s " $br; \
  curl -s -o /dev/null -w "%{http_code}\n" "$MD/$br/grade/penalty/duedate/manage_penalty_rule.php"; done
curl -s "$MD/MOODLE_500_STABLE/grade/classes/penalty_container.php"                     # 累加 + clamp
curl -s "$MD/MOODLE_500_STABLE/grade/penalty/duedate/classes/penalty_calculator.php"    # max_grade × pct / 100
````

### A-6 试过并**排除掉**的路径（省下一个人重复）

1. **全仓 grep `class question_cbm`** 无果；改用 `gh search code` 命中的是 totara 等镜像仓库 ⇒ **放弃 CBM 公式的完整推导**，只保留"可负 + 有下界"两条已证结论（§4.1.3）。
2. **`apps.odoo.com` 详情页正则取 license**：License 字段部分动态渲染 ⇒ 只逐字核了 `ng_appraisal`，其余标未验证（§7-5）。
3. **`web_search` 工具**：400 insufficient credits，全程不可用 ⇒ **不要在后续任务里把它当第一手段**。
4. **`mcporter` + Exa**：本机未配置 `exa` MCP server。
5. **`timeout` 命令**：macOS 无（应使用 `gtimeout` 或工具自带超时）；一次命令因此被提升为后台作业（`bash-1936`），输出为空 ⇒ 长命令请显式设 `timeoutMs`。
6. **完全放弃的检索面**：Banner / PeopleSoft / PowerSchool 等商业 SIS —— 深挖成本远高于收益（既有调研已给同类结论）。
