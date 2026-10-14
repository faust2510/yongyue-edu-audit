# t12 评审报告：t6「一条龙服务」
> **状态**：`归档` ｜ **主题**：`一条龙服务评审` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

> 评审人：flow-eng ｜ 日期：2026-09-12 ｜ 被评审任务：t6（一条龙服务，study-eng 交付）
> 方法：不看交付说明自证，全部结论以**独立复现**为准（HTTP 四角色实测、DB 直查、cron 干跑、模板/源码定位）。
> 结论：**verdict = pass**（5/5 acceptance 独立核验通过）；另附 5 条**非阻塞**观察，供后续加固排期。

## 一、五条 acceptance 的独立核验

| # | acceptance | 判定 | 独立证据（本轮实测） |
|---|---|---|---|
| 1 | /my/study 四角色可见；每门在修科目含教师/课节/入会/资料/成绩/出勤 | **通过** | student / faculty / parent / backoffice 四个账号实测 /my/study 均 200/303；/my/study/46 单科目页实测六要素齐（任课教师、课节与入会、资料、我的成绩、出勤概况） |
| 2 | 课节级 Zoom 链接可保存 + 一键入会；课前提醒 cron 已注册且有干跑证据；ics 含课节 | **通过** | cron id=37「edu_schedule: 课节课前提醒（每 5 分钟）」active=true；干跑 `cron_session_reminder()`：首跑 sent=1 且 reminder_sent_at 落时间，二跑 sent=0（幂等）；课节未到窗口 → join 200 等待页，改到 5 分钟后 → join 303 跳 https://zoom.us/j/…（与 videocall_location 一致）；教师 POST link/save → 303 且 videocall_location 更新，学生同路由被挡（链接未变）；/my/calendar/ics/<token> 200 且含 BEGIN:VEVENT |
| 3 | 学生首页高度：桌面 ≤1800px、375 ≤2600px（附前后数字） | **通过** | 官方脚本 `scripts/shoot_ux_v3.py --role student --page home --no-shots` 实测：1280→**1469**、768→1537、375→**1552**（阈值 1800/2600，余量充足）。注：交付说明报的是 1366/1449，本轮复测 1469/1552，均达标；差异见观察 O3 |
| 4 | /my/apps 承接全部功能卡且 .o_portal_index_card 保留；收藏编辑可用 | **通过** | /my/apps 200；`.o_portal_index_card` 出现 **45** 次（≥10 的功能卡承接）；课表/成绩/资料(/downloads)/公告入口均在页内；`/my/favorites/save` 路由存在（controllers 内 grep 命中） |
| 5 | 报课确认页「下一步四件事」；档案成绩三层且历史学期默认折叠 | **通过** | /student/subjects 含「下一步四件事」；成绩三层在运行期实测：L1 得分/及格线、L2「科目条目 1 项」+ 考试名/权重/得分、L3「教师反馈：论述结构清晰，注意引用格式。」；历史折叠 `<details class="ux3-details ux3-history">` **无 open 属性**（默认折叠），summary「历史学期（1 门）」 |

> 核验方法说明（第 5 条）：演示库中唯一可登录学生（王小明）的 result_line 指向 subject 35，而他**在修科目只有 46** → 不造数据时三层块在运行期不可观测。评审按「先把样本造对」的原则，用【冒烟】夹具（subject 46 的一次考试 + 上一学年 marksheet 行）复现三层与折叠，验证后已全部清理（见下）。

## 二、契约 verify 的三条（评审侧复跑）

- `docker compose exec web odoo … -u edu_portal,edu_schedule --stop-after-init`：**字面命令在本环境不可执行**（exec 绕过 ENTRYPOINT 无 --db_host；--stop-after-init 仍会 bind 8069）——与本轮 t5/t7/t23/t34 同一环境缺陷，交付已如实披露，评审接受等价证据：`bash scripts/safe_upgrade.sh -u edu_portal,edu_schedule` 实测 **EXIT=0**（无失败特征 + 就绪探活 302）。
- `python3 tests/smoke/ux_v3_route_matrix.py`：**EXIT=0**，检查点 500：PASS 497 / WARN 3（/my/checkin/board 404，与本任务无关）/ FAIL(真红) 0。
- `python3 scripts/shoot_ux_v3.py`：本轮以 `--role student --page home --no-shots` 复跑成功（9.6s），高度见 acceptance #3。

## 三、非阻塞观察（不构成 needs_revision，建议排期加固）

- **O1（low-medium）提醒失败被静默吞掉**：`edu_schedule/models/session_ext.py:247-248`（站内信）与其后 Telegram 段均 `except Exception: pass`。cron 的返回值 sent 是「本次发送条数」，但异常被吞后，**「没有到点课节」与「通知发送失败」在日志与返回值上无法区分**。建议改为 `_logger.warning(..., exc_info=True)` 后继续——这与本周反复治理的「静默失败」是同一家族。
- **O2（low）三层成绩在演示环境不可见**：演示学生的 result_line 指向未选科目，导致 acceptance #5 的界面在交付环境里点不出来（需造数据才能看到）。建议补一条【演示】成绩（在修科目 + 一场考试），让功能在演示站可见。
- **O3（low）高度数字与交付说明不一致**：交付报 1366/1449，本轮复测 1469/1552（均达标）。差值与数据/字体/页面微调有关；建议记录「测量脚本 + viewport + 数据快照」三要素，便于下次比对。
- **O4（low）未选科目直链返回 200 空页**：`/my/study/35`（学生未选的科目）200 且无该科目数据。当前**不泄露数据**（只有通用骨架），故不阻塞；建议按「不存在」处理或给明确空态。
- **O5（process）提交粒度**：t6 与 t4/t5/t7/t8/t20 揉在同一个聚合提交 `7b43a49` 里，无法按任务归因；本次「超出 inScope 的文件」只能按 t6 声明涉及的路径逐一核对，结论：**t6 涉及的路径全部落在其 inScope 内**（含 `edu_schedule/` 通配、models/downloads.py、models/lms.py、models/calendar_event.py、static/src/css/ux_v3.css）。建议集成期按任务分提交。

## 四、inScope 越界检查

- 被评审改动涉及的路径：study.py / study.xml / edu_portal_templates.xml / batch2.py+xml / edu_schedule/**（session_ext.py + data/cron.xml）/ models/downloads.py / models/lms.py / models/calendar_event.py / models/__init__.py / __manifest__.py / static/src/css/ux_v3.css —— **均在 t6 的 inScope 列表内**（含通配项）。
- 未发现越界文件；受 O5 的提交粒度所限，本结论仅对「t6 交付说明中列明的改动路径」成立。

## 五、清理

- 【冒烟】夹具已清理：2 条 op.marksheet.line、2 条 op.result.line、2 场【冒烟】考试、1 节课节（含其 calendar.event）、以及干跑产生的 2 条【冒烟】课前提醒站内信；复核残留 = 0（详见任务 output 的清理计数）。
