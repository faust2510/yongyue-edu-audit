# 「基础信仰」重名科目 —— 教务确认清单（**只出清单，不动数据**）

> **状态**：`待教务确认`｜**作者**：loss-ledger（task-3 续作）｜**日期**：2026-10-01
> **红线（三条，研究者自己先守）**：
> 1. **本文件不改任何数据**（不合并、不改名、不停用）；
> 2. **不改 `docs/curriculum/yongyue-curriculum.csv`** —— 它是导入源，改了会污染下一次重放；
> 3. 结论只由**教务**给；我们只把问题、影响面和选项摆清楚。
> **证据口径**：全部读数取自 `prod-host`（203.0.113.11）`edu19`，2026-10-01，只读 SELECT；命令见 §6。

---

## 1. 两个科目并排（实测）

| 项 | **A** | **B** |
|---|---|---|
| `op_subject.id` | **36** | **53** |
| `code` | `PRP-C02` | `BTH-FOU01` |
| `name` | **基础信仰** | **基础信仰** |
| `type` / `subject_type` | theory / compulsory | theory / compulsory |
| `active` | t | t |
| **建档时间** | **2026-08-22 12:41:08** | **2026-10-01 14:10:29** |
| 建档人 | `__system__`（uid 1，**不是某位教务手工建的**） | `__system__`（uid 1，**B5 排课导入脚本**） |
| 课程挂接（`edu_course_subject`） | **CRS-PRP**（预备科）1 条（link id 10，建于 2026-10-01 13:38） | **CRS-BED / CRS-BLA / CRS-BTH / CRS-MCS** 4 条（link 83–86，建于 2026-10-01 14:13 = B6 导入那一刻） |
| 老表挂接（`op_course_op_subject_rel`） | CRS-PRP 1 条 | **0 条** |
| **已排课时（`op_session`）** | **0 节** | **4 节** |
| 学生选课（`op_student_course_op_subject_rel`） | **0 条** | **0 条** |
| 考试 / 成绩 / 考勤引用 | 0 | 0（全库这些表当前基本为空） |

**一句话**：**A 是 8/30 快照里就有的预备科科目；B 是 2026-10-01 我们跑 B5 排课导入时新建的**（`BTH-FOU01`，神学系代号）。两者**同名但不同代号、挂不同课程**。

## 2. 它们是怎么变成两个的（时间线，全部有据）

| 时刻 | 事件 | 依据 |
|---|---|---|
| 2026-08-22 12:41 | A 随 8/30 快照（含更早的种子/模块 data）进入本库 | §1 的 `create_date` |
| 2026-10-01 13:38 | 模块升级时，老表 14 条挂接被搬进 `edu_course_subject`（含 A→CRS-PRP） | `migrations/19.0.3.0.0`；link id 10 的 `create_date` |
| 2026-10-01 14:10 | **B5 排课导入**按 `timetable_import/sessions.csv` 建了 18 个科目，其中 `BTH-FOU01 基础信仰`（**名字与 A 相同**） | B5 运行日志「新建 op.subject … 18 个」；B 的 `create_date` |
| 2026-10-01 14:13 | **B6 课程导入**按 CSV 第 21 行 `基础信仰` 找**同名**科目 ⇒ 命中 B（不是 A），把 4 条学位挂接写在 B 身上 | `scripts/import_curriculum.py:71-74`（按名字 `smap.get(name)`）；link 83–86 的 `create_date` |

> ⇒ **这次重名不是「数据本来脏」，而是「排课导入的科目命名」与「预备科原有科目命名」撞车**，再由导入器「按名字判重」的规则放大成一次挂接错位。

## 3. 影响面（两条路，分别要动什么）

### 3.1 如果教务确认「**是同一门课**」⇒ 需要合并（建议 53 → 36，保留老 id）

合并 = 把 53 的所有引用改指到 36，然后停用/删除 53。全库**引用 `op_subject` 的外键共 23 条**（实测 `pg_constraint`），另有 20 张表含 `subject_id`/`op_subject_id` 列。按「当前有数据的」排序：

| 表 / 列 | 当前有没有数据 | 合并时要不要动 |
|---|---|---|
| `op_session.subject_id` | **B 有 4 节、A 有 0 节** | ✅ 必须改指（否则 4 节课挂在被停用的科目上） |
| `edu_course_subject.subject_id` | B 4 条、A 1 条 | ✅ 必须改指；⚠ 合并后同一科目会同时属于 **CRS-PRP + CRS-BED/BLA/BTH/MCS 共 5 个专业** —— **这本身要教务确认对不对**（预备科与学位课程共用一个科目，语义上可疑） |
| `op_course_op_subject_rel.op_subject_id` | A 1 条、B 0 条 | ✅ 老表也要改指（否则新旧表不一致） |
| `op_student_course_op_subject_rel` / `subject_compulsory_rel` / `op_subject_op_subject_registration_rel` | **都是 0** | 现在不用动（但合并脚本仍应覆盖，防未来） |
| `op_exam` / `op_held_exam` / `op_attendance_register` / `op_assignment_op_subject_rel` / `op_faculty_op_subject_rel` / `op_media_op_subject_rel` / `op_media_purchase.subject_ids` / `gen_time_table_line` / `grading_assignment` | **全 0** | 同上 |
| `edu_course_rep` / `edu_subject_prereq` / `edu_grade_history` / `edu_download_file` / `edu_leave` / `edu_lesson` | **全 0** | 同上 |

**风险与回滚**：合并**不可逆**（要删/停用一行）⇒ 必须先 `pg_dump`；回滚 = 用备份还原，或保留 53 为 `active=false` 而不删（更安全，代价是库里仍有一行停用重名）。**建议顺序**：先只做「改指」并把 53 停用，观察一个工作周期再决定是否物删。

### 3.2 如果教务确认「**不是同一门课**」⇒ 需要改名（**零行迁移，但有一个方向性陷阱**）

- **改名本身不动任何外键行**（名字不是主键），影响面只有「**按名字工作的地方**」：报课页的科目分组/展示、成绩簿与门户里对 `subject` 名的字符串匹配（本仓已有先例：`docs/research/gradebook-entry.md` 记过「换源后要改成按 `subject_id` 匹配 —— 同名科目会串」）、以及各类导出/报表。
- ⚠ **必须改对那一个（这是本次最容易做错的一步）**：导入器 `scripts/import_curriculum.py` **按名字判重**。
  - **改 A（`PRP-C02`，老科目）的名字** ⇒ 库里仍有 `基础信仰`（B）⇒ **下次重放 CSV 不会新建科目**，只挂接到 B。✅ 推荐方向。
  - **改 B（`BTH-FOU01`）的名字** ⇒ 库里**再没有任何叫 `基础信仰` 的科目** ⇒ **下次重放 CSV 会新建第三个「基础信仰」**，重名问题原样复活（甚至更乱）。❌ 不要这个方向。
- 顺带：改 B 的名字还会让 **`timetable_import/sessions.csv` / 课表导入的科目表**与库里对不上（下次重放课表可能再建一个）。

## 4. 请教务填这张表（一页、非技术人员可填）

> 请只看两行信息，回答一个问题，签个名即可。**不需要动系统**。

| 项目 | 内容 |
|---|---|
| 科目一 | **预备科** 的「基础信仰」（代号 **PRP-C02**，2026-08-22 建，挂在**预备科**课程下，**本学期没有排课**） |
| 科目二 | **神学系** 的「基础信仰」（代号 **BTH-FOU01**，2026-10-01 建，挂在**教育学士/文学学士/神学学士科/基督教研究硕士科**下，**本学期已排 4 节课**） |
| **问题** | **这两个「基础信仰」是同一门课吗？** |
| 请勾选 | ☐ **是同一门**（我们要合并成一条；请同时回答：合并后它属于哪几个专业？） ☐ **不是同一门**（我们要改名；**请给出两个正式名称**） |
| 备注 / 正式名称建议 | 科目一建议名称：________________ 科目二建议名称：________________ |
| 确认人 / 日期 | ______________________ |

> 附：若选「不是同一门」，请特别确认**哪一个是给预备科学生上的**（我们据此决定改哪一个——见 §3.2 的方向性陷阱）。

## 5. 我们不做什么（红线，再写一遍）

- 本清单**不改任何数据**：不合并、不改名、不停用、不动物删；
- **不改** `docs/curriculum/yongyue-curriculum.csv`（导入源，改了会污染下一次重放）；
- **不改** `timetable_import/sessions.csv`（课表导入源，同理）；
- 教务没签字之前，**任何**「顺手把重名修掉」的动作都不做。

## 6. 复跑命令（谁都能核）

```bash
# 1) 两个科目并排 + 建档人
ssh prod-host "docker exec -i edu19-prod-db-1 psql -U odoo -d edu19 -A -f -" <<'SQL'
select s.id, s.code, s.name, s.subject_type, s.active, s.create_date, u.login
  from op_subject s left join res_users u on u.id = s.create_uid
 where s.code in ('BTH-FOU01','PRP-C02') order by s.id;
select cs.id, c.code, cs.subject_id, cs.create_date from edu_course_subject cs
  join op_course c on c.id = cs.course_id
 where cs.subject_id in (36, 53) order by cs.id;
select subject_id, count(*) from op_session where subject_id in (36,53) group by 1;
select count(*) from op_student_course_op_subject_rel where op_subject_id in (36,53);
SQL

# 2) 引用 op_subject 的全部外键（合并时的影响面清单）
ssh prod-host "docker exec edu19-prod-db-1 psql -U odoo -d edu19 -A -c \"
  select conrelid::regclass as from_table, a.attname
    from pg_constraint c join pg_attribute a on a.attrelid=c.conrelid and a.attnum = any(c.conkey)
   where c.confrelid = 'op_subject'::regclass and c.contype='f' order by 1;\""

# 3) 全库还有没有别的重名对（当前应为「只有 基础信仰 这一对」）
ssh prod-host "docker exec edu19-prod-db-1 psql -U odoo -d edu19 -A -c \"
  select name, count(*), string_agg(code, ',' order by code) from op_subject group by name having count(*) > 1;\""
```

> **实测结果（2026-10-01）**：第 3 条返回 `基础信仰 | 2 | BTH-FOU01,PRP-C02`（**全库唯一的一对**）。
