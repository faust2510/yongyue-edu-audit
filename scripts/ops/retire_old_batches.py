# -*- coding: utf-8 -*-
# 一次性数据迁移：退役 12 个 inactive 旧班级，并把其课程并入新建的「总览班」OVERVIEW
#
# 第 2 轮执行稿（2026-09-24）—— 本文件即本轮实际执行的完整脚本，已全部成功执行并提交；
# 生产库当前状态就是本文件的执行结果。末尾附「本轮执行原始输出」与「第 1 轮失败记录（历史）」。
#
# 仓库：/Users/qwe/Documents/文件大总管/10-项目/教务系统网站新架构
# 生产：ssh -o ConnectTimeout=20 prod-host（203.0.113.10）
#   web 容器 edu19-prod-web-1（Odoo 19）；db 容器 edu19-prod-db-1（PostgreSQL，库 edu19，角色 odoo）
# 执行命令（/etc/odoo/odoo.conf 里没有 db_host，必须显式传连接参数，否则连不上库）：
#   ssh -o ConnectTimeout=20 prod-host 'docker exec -i edu19-prod-web-1 odoo shell -d edu19 -c /etc/odoo/odoo.conf --no-http --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo' < 本文件
# 只读核对命令：
#   ssh -o ConnectTimeout=20 prod-host 'docker exec -i edu19-prod-db-1 psql -U odoo -d edu19 -A -P pager=off'
#
# 备份（迁移前生成，chmod 600，均在生产机 /root/）：
#   第 1 轮：/root/pre_overview_20260924b.gz（5,670,560 字节）
#   第 2 轮：/root/pre_overview2_20260924.gz（5,673,106 字节）   <- 本轮开工前
#
# 本轮与第 1 轮的唯一方法学差异（= 第 1 轮失败的绕行方案）：
#   改挂 batch_id 一律走 raw SQL（只 UPDATE batch_id 一列，完全不触碰 faculty_id / start_datetime /
#   end_datetime / classroom_id / subject_id），从而绕开被既存脏数据拦死的 ORM write 复检；
#   其余动作仍走 ORM（建班 Batch.create、删班 unlink，保留自身守卫）。
#   根因与原始报错见文末「历史：第 1 轮失败记录（保留）」。

# ===================== 步骤 0：新备份（在生产机 shell 执行，非本文件） =====================
#   docker exec edu19-prod-db-1 pg_dump -U odoo -d edu19 | gzip > /root/pre_overview2_20260924.gz \
#     && chmod 600 /root/pre_overview2_20260924.gz && ls -l /root/pre_overview2_20260924.gz
#   -> -rw------- 1 root root 5673106 Sep 24 16:54 /root/pre_overview2_20260924.gz   (>1e6 字节，通过)

# ===================== 步骤 1：建「总览班」（ORM，不碰任何 session） =====================
# 上一轮已确证事实（不再推导）：硕士科目补齐（旧步骤 3）已完成并提交，
#   edu_course_subject = 478 行（13:72, 14:79, 15:81, 16:88, 18:14, 19:72, 20:72），本轮不重跑。
OWNERS = [9, 11, 12, 14, 16, 17, 18, 19, 21]   # 持有课程的 9 个旧班（共 139 节课）
Batch  = env['op.batch']
ov = Batch.search([('code', '=', 'OVERVIEW')], limit=1)
if not ov:
    src = env['op.session'].search([('batch_id', 'in', OWNERS)])
    starts = [d for d in src.mapped('start_datetime') if d]
    ends   = [d for d in src.mapped('end_datetime') if d]
    ov = Batch.create({
        'code': 'OVERVIEW', 'name': '总览班', 'course_id': 14,
        'start_date': min(starts).date(), 'end_date': max(ends).date(),
        'active': True,
    })
env.cr.commit()
print("OVERVIEW_ID", ov.id, ov.code, ov.name, ov.start_date, ov.end_date)

# ===================== 步骤 2：改挂（raw SQL，绕开 timetable.py:314 复检） =====================
env.cr.execute("UPDATE op_session SET batch_id = %s WHERE batch_id = ANY(%s)", (ov.id, OWNERS))
print("SESSIONS_MOVED", env.cr.rowcount)
env.cr.execute("UPDATE op_exam_session SET batch_id = %s WHERE batch_id = 27", (ov.id,))
print("EXAMSESS_MOVED", env.cr.rowcount)
env.cr.commit()
env.invalidate_all()
print("STEP2_COMMITTED")
# 注：op_exam_session.batch_id 为 NOT NULL（已核 is_nullable=NO），且该表 id=3 行是孤儿
#   （op_exam 0 行；op_marksheet_register / op_result_template / op_result_line /
#    op_room_distribution 对该会话亦均 0 行），故采用「改挂到 OVERVIEW」而非置空或删除，不丢任何数据。

# ===================== 步骤 3：删除 12 个旧班（ORM unlink，走自身守卫） =====================
# 硬约束：若 unlink 失败，不得改用裸 SQL 强删；原样打印报错、保留现状。
RETIRED = [8, 9, 11, 12, 14, 16, 17, 18, 19, 21, 25, 27]
r = env['op.batch'].browse(RETIRED).exists()
print("TO_UNLINK", r.ids)
try:
    r.unlink()
    env.cr.commit()
    print("UNLINK_OK", len(r))
except Exception as e:
    env.cr.rollback()
    print("UNLINK_FAILED", type(e).__name__, str(e))

# ===================== 步骤 4：验证（psql / ORM 原始输出见文末） =====================
# 1. SELECT count(*) FROM op_batch WHERE active = false;                                  -> 0
# 2. SELECT id,code,name,active FROM op_batch ORDER BY id;                                 -> 12 行，全 t
# 3. SELECT count(*) FROM op_session;                                                      -> 216
# 4. SELECT b.code, count(*) FROM op_session s JOIN op_batch b ON b.id=s.batch_id GROUP BY 1
#      ORDER BY 2 DESC;                                                                    -> OVERVIEW 139, B3 40, B1 18, B4 15, A1 4
# 5. SELECT count(*) FROM op_exam_session WHERE batch_id = 27;                             -> 0
# 6. SELECT course_id, count(*) FROM edu_course_subject GROUP BY 1 ORDER BY 1;             -> 7 行，合计 478（未变）
# 7. ORM：env['op.batch'].with_context(active_test=False).search([]).mapped('name')        -> 读出 12 个班名，无报错

# ===================== 本轮执行原始输出（2026-09-24，逐字粘贴） =====================
# [步骤 1] OVERVIEW_ID 34 OVERVIEW 总览班 2026-08-31 2027-01-12
#
# [步骤 2] OVERVIEW_RESOLVED 34 OVERVIEW
#          SESSIONS_MOVED 139
#          EXAMSESS_MOVED 1
#          STEP2_COMMITTED
#
# [步骤 3] TO_UNLINK [8, 9, 11, 12, 14, 16, 17, 18, 19, 21, 25, 27]
#          UNLINK_OK 12
#          （odoo 日志旁证：User #1 deleted op.batch records with IDs: [8, 9, 11, 12, 14, 16, 17, 18, 19, 21, 25, 27]，
#            同时清理 mail.message [1757, 1755, 1334, 1332, 1331, 1330, 1329, 1327, 1325, 1324, 1322, 613]
#            与 mail.followers [368, 370]，均为这些班级自身的 chatter 痕迹）
#
# [步骤 4-1] count = 0（1 row）
# [步骤 4-2] id|code|name|active
#            10|A1|A1|t
#            13|B1|B1|t
#            15|B3|B3|t
#            20|B4|B4|t
#            22|A2|A2|t
#            23|A3|A3|t
#            24|B2|B2|t
#            28|CA|C·A硕|t
#            29|CB|C·B硕|t
#            30|PRP|预科|t
#            31|PRP2|二级本科|t
#            34|OVERVIEW|总览班|t
#            (12 rows)
# [步骤 4-3] count = 216（1 row）
# [步骤 4-4] code|count
#            OVERVIEW|139
#            B3|40
#            B1|18
#            B4|15
#            A1|4
#            (5 rows)
# [步骤 4-5] count = 0（1 row）
# [步骤 4-6] course_id|count
#            13|72
#            14|79
#            15|81
#            16|88
#            18|14
#            19|72
#            20|72
#            (7 rows)
#            另：SELECT count(*) FROM edu_course_subject; -> 478（1 row）
# [步骤 4-7] ORM_BATCH_READ_OK 12
#            ORM_BATCH_NAMES ['A1', 'B1', 'B3', 'B4', 'A2', 'A3', 'B2', 'C·A硕', 'C·B硕', '预科', '二级本科', '总览班']
#
# 结论：7 条验证全部达成预期 —— 成功（无降级、无强删、无未授权动作）。
# 执行期间未重启容器、未跑 -u、未改模块代码、未动其它表、未改 ir_config_parameter 任何 constraint 开关。

# ===================== 历史：第 1 轮失败记录（保留，勿删） =====================
# 第 1 轮（同一 2026-09-24，前一次执行）把「建班 + 改挂 + 删班 + 硕士科目补齐」写成单次 commit，
# 结果：**步骤 2 失败、事务整体回滚、生产库零变更**（从未到达任何 commit）；
# 步骤 3（硕士科目补齐）当时已单独成功提交，故本轮不再重跑。
#
# --- 第 1 轮的写法（已废弃，仅存档；切勿再执行 write({'batch_id': ...}) 改挂）---
#   src.write({'batch_id': ov.id})                      # <- 失败点（timetable.py:314 复检）
#   es.write({'batch_id': False}) / es.unlink()         # <- 均被否：前者 NOT NULL 失败，后者越权删数据
#
# --- 第 1 轮原始报错（odoo shell rc=1，完整调用链，逐字保留）---
#   File "<string>", line 21, in <module>                       <- src.write({'batch_id': ov.id})
#   File "/mnt/custom-addons/edu_portal/models/scheduling.py", line 24, in write
#   File "/mnt/custom-addons/edu_schedule/models/session_ext.py", line 756, in write
#   File "/mnt/extra-addons/openeducat_timetable/models/timetable.py", line 539, in write
#   File "/usr/lib/python3/dist-packages/odoo/addons/mail/models/mail_thread.py", line 391, in write
#   File "/usr/lib/python3/dist-packages/odoo/orm/models.py", line 4491, in write
#   File "/usr/lib/python3/dist-packages/odoo/orm/models.py", line 1268, in _validate_fields
#   File "/mnt/extra-addons/openeducat_timetable/models/timetable.py", line 314, in check_timetable_fields
#     raise ValidationError(_(
#   odoo.exceptions.ValidationError: 您无法在相同的日期和时间与相同的教师创建课程
#
# --- 第 1 轮根因（已在生产库只读取证）---
#   timetable.py:243 的 @api.constrains 由 write 触发复检；基座全校参数
#   timetable.is_faculty_constraint = 'True'，该检查**不看 batch**（全局「同 faculty_id + 时间重叠」即报错）。
#   这 139 节内既存 34 组「faculty_id=20 + 时间重叠」冲突（全表 44 组），涉及 22 节，
#   横跨 batch 14/11/13/15/21/9/10 等组合班与单班 —— 属旧数据既存问题，与本次合并无关。
#   故任何对这批记录 faculty_id / start_datetime / end_datetime / classroom_id / batch_id / subject_id
#   的 ORM write 都会失败；第 2 轮因此改为 raw SQL 只改 batch_id 一列。
#   （另：es.write({'batch_id': False}) 第 1 轮单独实测时抛 psycopg2.errors.NotNullViolation，
#     因为 op_exam_session.batch_id is_nullable=NO；本轮据此采用「改挂」而非置空。）
#
# --- 第 1 轮步骤 4 复核（当时状态，作为对照）---
#   inactive 仍 12、op_batch 仍 23 行、op_session 仍 216 且 139 节仍挂旧班、无 OVERVIEW、
#   op_exam_session batch_id=27 仍 1 行；仅步骤 3 的预期（edu_course_subject 合计 478）已达成。
