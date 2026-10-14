# 门户搜索（/my/search）「完全没法用」定性 + 修复取证

日期：2026-09-28 ｜ 环境：本地克隆 edu19-clone-web-1 / edu19-clone-db-1，库 edu19
代码：`custom_addons/edu_portal/controllers/search.py`（唯一改动文件）
模板 `edu_portal/views/edu_portal_templates.xml` **未改动**（他人脏文件，全程只读）。

## 定性（五选一 → 主因 ②，伴生 ④）
| 可能 | 结论 | 依据 |
|---|---|---|
| ① 搜不出（有数据 0 命中） | 部分成立（家长·账单一面） | 家长搜「教材」0 条，而 /my/fees 的「孩子的账单」里同一张单可见 → 见 evidence_*.json |
| ② **结果错/过滤条件写错（主因）** | **成立** | 学生任何关键词都回 8 条本人申诉；且他人申诉命中关键词即出现在学生搜索页（实测越权） |
| ③ 500/报错 | **排除** | /my/search 全程 1082×200 / 1×303（未登录），零 500；容器日志无 /my/search 异常 |
| ④ 点不进去 | **成立（伴生）** | 学生/家长「课程」命中 7 条全部 303 弹回 /my/courses |
| ⑤ 输入框不可用 | **排除** | 真实 Chrome：框可见可编辑(290×40)、回车与放大镜按钮均能提交并出结果 |

## 根因
`custom_addons/edu_portal/controllers/search.py`
1. **申诉单域（主因，改前 :147-150）**：`['|', '|', name, subject, student_id=本人]` 在波兰式域里 = OR(name, subject, 归属) —— 归属限制被并进 OR。
2. **课程分组（改前 :43）**：裸 `dom_q`，非内部用户搜到未在册科目，而 `/my/courses/<id>` 自带守卫 `lms.py:117` → 303 弹回。
3. **账单分组（改前 :65-69）**：只有「student ? 本人 : 0」分支，家长侧 `current_student()` 恒 None → student_id=0 → 恒 0 条。

## 改前/改后对照（原始证据文件名）
| 观测 | 改前 | 改后 |
|---|---|---|
| 学生 q=zzz_no_such_thing | 申诉单 8 条（无「没有找到」） | 「没有找到与…相关的内容」 |
| 学生 q=账单 / 成绩 / 公告栏 | 申诉单 8 条 | 账单：无结果；成绩：申诉单 1 条「成绩复核申请」（正确命中） |
| 学生 q=ZZ越权探针（他人唯一命中的探针单） | 页面出现学生 7 的「ZZ越权探针-别人的申诉」 | 无结果（越权关闭，探针已删） |
| 家长 q=教材 | 无分组 | 账单 1 条「【演示】教材资料费」 |
| 学生/家长「课程」命中点击 | 7/7 条 HTTP 303 弹回 /my/courses | 13/13 条 HTTP 200 可打开 |
| 内部用户（教师/教务） | 课程全库、邀请码 /odoo/action-687 | 一字不变（未回归） |

文件：`evidence_before.json` `evidence_after.json` `before_leak_proof.json`
`href_reach_before.json` `course_click_after.json` `browser_check_after.json`
截图：`browser_result_after.png`（回车提交「教材」→ 只剩正确的账单 1 条）

## 未验证 / 未修
* **改前的浏览器截图未补拍**：search.py 同时含另一会话未提交的改动（邀请码 href），不愿回滚该文件重跑改前态；改前页面内容以 `evidence_before.json` 的原始 HTML 为准。
* **家长·作业/校历活动分组仍是裸域**（未按子女班级收敛）：本库 5 条作业全在同一班级，无跨班数据可证暴露；且落到 `/student/assignment/details` 对家长本就空表（页面按 `current_student()` 收敛）—— 需要产品决策，未擅自改。
* **家长搜不到子女的请假/申诉**（`if student:` 分支，原注释即「学生视角」）：落到 /my/time_off 是学生自助页，未擅自放开。
* **资料分组既有 `except Exception` 静默降级**（改前就在，非本次引入）：`_visibility_domain()` 无异常路径 ⇒ 该兜底实际走不到；本库 edu_download_file 0 行，无法观测，未动。
* **未跑全套冒烟**（F_roles_smoke / UX 门禁）：只跑了 `scripts/check_english.py`（must-fix=0）+ 本次自建探针。浏览器实测只覆盖学生桌面视口。
* 管理员（uid=2）账号未单独实测（fac=True 路径已由教师/教务覆盖）。
* 日志里 `edu.invite.code.search_read` 的 AttributeError（web 客户端传了嵌套 list 域）与本次改动无关，属邀请码后台侧，未跟踪。
