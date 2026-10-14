# -*- coding: utf-8 -*-
"""恢复本地演示学生的「档案科目」（幂等种子；默认 DRY_RUN 只读）。

用法（宿主侧，经 stdin 送进 odoo shell）：
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf -d edu19 \
        --db_host=db -r odoo -w odoo --no-http < scripts/seed_wangxiaoming_subjects.py
    # 真写：在 -T 前加 -e APPLY=1（例：docker compose exec -T -e APPLY=1 web odoo shell …）

环境变量：
    APPLY=1        真写（**默认只读**，与 scripts/clean_local_group_drift.py 同风格）
    ALL_STUDENTS=1 一并恢复同课程下**其它**演示学生的空档案（默认只动王小明）
    COURSE_CODE    课程号，默认 CRS-PRP
    TARGET_LOGIN   目标账号，默认 stu@local

它做什么
--------
把「学生档案」那份 "op.student.course.subject_ids" 修回与**课程科目清单**一致。
学生档案的科目是**独立存储**的一份（不是课程表 —— 课程 CRS-PRP 自己那 14 门 PRP-C01..C14 一直在）。
只补/改科目，**不建档案、不动其它字段**；值相等时**不写**（幂等，可重复跑）。
若课程科目清单本身为空，则按种子脚本口径补出 PRP-C01..C14（名字/类型见下表 SUBJECTS）。

为什么会有这个脚本（2026-09-17 t7）
------------------------------------
本地演示档案在 09-17 被清成 0 门之后，"tests/smoke/p2_enroll_smoke.py" 的 #10
「空科目单通过防呆」失去前置 —— 防呆条件（registration.py:164-169）是
    if rec.doc_type == 'subject_registration' and not subject_ids and sc and sc.subject_ids:
**依赖 sc.subject_ids 非空**；档案为空时它根本不触发 ⇒ 该用例恒红、脚本"可重跑"名存实亡。
队长在 16:28 手工恢复过一次（0 → 14），但**手工不可复跑**；而且 p2 自己 #2 的审批会按
「注册单 = 最新意愿」**整体覆盖**档案科目（14 → 1 门）⇒ 每跑一次 p2 都会削弱该前置。
所以：**跑 p2 之前先跑本脚本**（或把它接进冒烟前置里），即可稳定复现。

09:12 那次清空的查证结论（可复算）
----------------------------------
表：edu_audit_log（模型 edu.audit.log）；create_date 存 **UTC**，本地 CST = create_date + interval '8 hours'。
查询：
    SELECT id, create_date, to_char(create_date + interval '8 hours','MM-DD HH24:MI') AS local_cst,
           user_id, res_id, detail
    FROM edu_audit_log
    WHERE model='op.subject.registration' AND detail LIKE '%档案 9%' ORDER BY id;
读数（56 行里的转折点）：
    id 1327  2026-09-12 16:46 UTC = 09-13 00:46 本地  仍报「通过：档案 9 …，科目 1 门」
    id 1449  2026-09-17 01:12 UTC = 09-17 09:12 本地  首次报「…科目 0 门」（user_id=11 / faculty@local）
    其后 01:23 / 01:32 / 01:38 / 01:45 UTC 各次均 0 门；07:26 / 07:44 UTC 亦 0 门
    id 1833  2026-09-17 07:58 UTC = 09-17 15:58 本地  又报「…科目 1 门」（被**并行改动**填回）
    id 1858  2026-09-17 08:02 UTC = 09-17 16:02 本地  同上
结论（**如实降级为推断**，不是"审计可查"）：
    清空落在 **(09-13 00:46, 09-17 09:15] 本地之间；具体动作与操作者「未验证」**。
    理由两条（正面理由，不是"删除不更新 write_date"那种间接推理）：
      ① 该表里**没有任何一行记录删除/清空** —— 那些行都是审批成功留痕，
         detail 记的是**审批后**的科目数；
      ② 由防呆逻辑反推：「空 payload 的审批能通过」意味着**审批前档案已经是空的**
         ⇒ 09:12 那几行只可能是「第一次看到它为 0」。
    u=11 是不是清空者**判不了**：取决于那 4 张单（311/313/315/317）的 doc_type，而这些行
    **已被删除**（SELECT … WHERE id IN (311,313,315,317) → 0 行），两分支无法区分：
      · doc_type='subject_registration' ⇒ 防呆适用 ⇒ 空 payload 通不过 ⇒ 清空更早；
      · doc_type 是别的值 ⇒ 防呆不适用 ⇒ **那次审批本身就是清空动作**。
    线索（留给后续查证）：那 4 张单在审计里**只有审批行、没有「报课提交」行** ⇒ 不是经门户
    /subject/enroll/save 建的，是**程序化创建**；09:10–09:15 同窗口还有脚本把「正对照矩阵」
    **直接打在真实对象上**（edu.leave 216/217 → approved/refused；edu.grievance 112/113 → resolve/reject）
    —— 本仓后来专门修过的「共享靶子」反模式。

其余 3 个演示学生要不要一并恢复？（t7 的判断）
---------------------------------------------
实测：课程 CRS-PRP 下有 4 个学生档案 —— sc9(王小明, 被 p2 覆盖成 1 门)、sc10/sc11/sc12(其余 3 人, 均 0 门)，
而课程自己那 14 门一直在。**建议一并恢复**，理由：
  · 它们是同一演示班的学生，档案空会让教师侧点名/成绩、课表等演示链路看起来"没人选课"；
  · 恢复的口径与王小明**完全同源**（镜像课程科目清单），不引入新假设。
但**默认不批量动数据**：需要显式 ALL_STUDENTS=1 —— 因为"该不该动非目标学生的数据"
属于演示数据口径问题，应由队长裁量（队长原话：「别默默动数据」）。
"""

import os

APPLY = os.environ.get('APPLY', '') == '1'
ALL_STUDENTS = os.environ.get('ALL_STUDENTS', '') == '1'
COURSE_CODE = os.environ.get('COURSE_CODE') or 'CRS-PRP'
TARGET_LOGIN = os.environ.get('TARGET_LOGIN') or 'stu@local'

# 课程科目清单为空时的兜底（口径同 scripts/seed_yongyue_data.py 的 SUBJECTS）
SUBJECTS = [
    ("小要理问答", "theory", "compulsory"), ("基础信仰", "theory", "compulsory"),
    ("圣经概论（新旧约概论）", "theory", "compulsory"), ("圣经救赎历史", "theory", "compulsory"),
    ("阅读课程", "other", "compulsory"), ("古汉语课程", "theory", "compulsory"),
    ("写作课程", "theory", "compulsory"), ("英语课程", "theory", "compulsory"),
    ("原文基础课程", "theory", "compulsory"), ("灵命塑造课程", "other", "compulsory"),
    ("文史哲综合备考课", "theory", "compulsory"), ("选修课程", "other", "elective"),
    ("意志和技能课程", "other", "compulsory"), ("游历课程", "other", "compulsory"),
]

Crs = env['op.course'].sudo()
Sub = env['op.subject'].sudo()
SC = env['op.student.course'].sudo()

course = Crs.search([('code', '=', COURSE_CODE)], limit=1)
assert course, '找不到课程 %s' % COURSE_CODE

print('== 恢复演示档案科目：课程 %s（id=%d）==' % (COURSE_CODE, course.id))
print('  APPLY = %s ｜ ALL_STUDENTS = %s ｜ TARGET_LOGIN = %s'
      % (APPLY, ALL_STUDENTS, TARGET_LOGIN))

# ---- 1) 课程科目清单：为空则按种子口径补 ----
if not course.subject_ids:
    print('  课程科目清单为空 → 按种子口径补 PRP-C01..C14')
    ids = []
    for i, (nm, typ, styp) in enumerate(SUBJECTS, 1):
        code = 'PRP-C%02d' % i
        s = Sub.search([('code', '=', code)], limit=1)
        if not s:
            s = Sub.create({'name': nm, 'code': code, 'type': typ, 'subject_type': styp})
            print('    新建科目', code, nm)
        ids.append(s.id)
    if APPLY:
        course.subject_ids = [(6, 0, ids)]
        env.cr.commit()
        print('    已写课程科目清单（%d 门）' % len(ids))
    else:
        print('    DRY RUN：未写课程科目清单')
    course = Crs.browse(course.id)

want = course.subject_ids
print('  课程科目清单：%d 门（%s）' % (len(want), ', '.join(want.mapped('code')) or '空'))

# ---- 2) 目标档案 ----
targets = []
su = env['res.users'].sudo().search([('login', '=', TARGET_LOGIN)], limit=1)
if su:
    stu = env['op.student'].sudo().search([('user_id', '=', su.id)], limit=1)
    if stu:
        sc = SC.search([('student_id', '=', stu.id), ('course_id', '=', course.id)], limit=1)
        if sc:
            targets.append(sc)
        else:
            print('  ! 王小明在该课程下没有档案 —— 本脚本只补科目、不建档案（请用 seed_yongyue_data.py）')
    else:
        print('  ! 账号 %s 未关联网学生记录' % TARGET_LOGIN)

all_scs = SC.search([('course_id', '=', course.id)]).sorted('id')
others = [x for x in all_scs if x not in targets]
print('  同课程档案共 %d 个；目标 %d 个；其它 %d 个'
      % (len(all_scs), len(targets), len(others)))
for sc in others:
    nm = (sc.student_id.first_name or '') + (sc.student_id.last_name or '')
    print('    · 其它档案 sc%d（学生 %s）当前科目 %d 门%s'
          % (sc.id, nm or '?', len(sc.subject_ids),
             ' ⇒ 用 ALL_STUDENTS=1 可一并恢复' if not sc.subject_ids else ''))
if ALL_STUDENTS:
    targets.extend(others)
    print('  ALL_STUDENTS=1 ⇒ 目标档案扩到 %d 个' % len(targets))

# ---- 3) 逐个补/改（值相等不写；幂等） ----
changed = 0
for sc in targets:
    cur = sc.subject_ids
    before = sorted(cur.mapped('code'))
    after = sorted(want.mapped('code'))
    if set(cur.ids) == set(want.ids):
        print('  sc%-3d 学生 %-10s 已经是目标态（%d 门）→ 不写'
              % (sc.id, sc.student_id.id, len(cur)))
        continue
    print('  sc%-3d 学生 %-10s %d 门 → %d 门  [%s] → [%s]'
          % (sc.id, sc.student_id.id, len(cur), len(want),
             ', '.join(before) or '空', ', '.join(after)))
    if APPLY:
        sc.write({'subject_ids': [(6, 0, want.ids)]})
        changed += 1
if APPLY and changed:
    env.cr.commit()
print('  → %s：应改 %d 个档案%s'
      % ('已提交' if APPLY else 'DRY RUN（未写入）',
         len([s for s in targets if set(s.subject_ids.ids) != set(want.ids)]) if not APPLY else changed,
         '' if APPLY else '；加 -e APPLY=1 真写'))
print('  回滚口径：把档案科目设回原值即可，例如 '
      'sc.write({'"'"'subject_ids'"'"': [(6, 0, [原 id 列表])]})')
print('完成')
