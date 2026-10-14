# 生产部署预案 checklist（t5 准备阶段 · 未执行任何生产写操作）

> 状态：仅只读侦察完成，**零生产写入**。等待用户明确「可部署」批准后才进入执行阶段。
> 依据：git 证实 `custom_addons/` 零改动 → 本次不需要 `-u edu_schedule` 模块升级。
> 目标：prod-host（203.0.113.10）/opt/edu-app，compose 服务 web，库 edu19（当前 op_session=0、0 教师、已有 course 6 个 code 与 term 锚点）。

## A. 传输文件清单（rsync 源→目标）

| # | 源（仓库根） | 目标（生产） | 说明 |
|---|---|---|---|
| 1 | `timetable_import/`（整目录） | `prod-host:/opt/edu-app/timetable_import/` | 含 sessions.csv 契约主表、import_sessions.py、run_import_local.sh、catalog.md、全部分析 CSV。生产容器不挂载仓库根 → CSV 需经环境变量注入，与本地 run_import_local.sh 同机制 |
| 2 | `custom_addons/edu_schedule/` | `prod-host:/opt/edu-app/custom_addons/` | **校验用**：本地零改动时应与生产字节一致；rsync 传一遍可保证两端一致（无 -u 升级） |

> 无需上传：`openeducat_erp/`（禁止改）、`docs/`、`tests/`（冒烟脚本可留在本地远程驱动或按需临时 rsync 只读副本）。
> ⚠ 若用户裁决变更（如 B 部改归 CRS-BLA、师生互动是否建、救恩论密集日期调整）→ 只改 `import_sessions.py` 常量区后重传本目录即可，幂等安全。

## B. 预计生产要执行的命令（获得批准后）

### B0. 部署前基线（只读）
```bash
ssh prod-host 'cd /opt/edu-app && docker compose exec -T db psql -U odoo -d edu19 -tAc "select count(*) from op_session"'
ssh prod-host 'cd /opt/edu-app && docker compose exec -T db psql -U odoo -d edu19 -tAc "select count(*) from op_faculty"'
ssh prod-host 'cd /opt/edu-app && docker compose exec -T db psql -U odoo -d edu19 -tAc "select code from op_course order by code"'
```
期望：`0` / `0` / 6 个 course code（CRS-BTH/CRS-BLA/CRS-BED/CRS-HSA/CRS-PRP/CRS-MCS）。

### B1. rsync 上传（无 -u 升级）
```bash
rsync -az --exclude='__pycache__' -e "ssh -o BatchMode=yes" \
  timetable_import/ prod-host:/opt/edu-app/timetable_import/
# 校验用（本地零改动，两端应一致）：
rsync -az --exclude='__pycache__' -e "ssh -o BatchMode=yes" \
  custom_addons/edu_schedule/ prod-host:/opt/edu-app/custom_addons/edu_schedule/
ssh prod-host 'chmod -R a+rX /opt/edu-app/timetable_import /opt/edu-app/custom_addons/edu_schedule'
```

### B2. 生产库导入（容器内 odoo shell，幂等）
```bash
# 在生产 web 容器内执行 import_sessions.py（env 注入 CSV，同本地机制）
ssh prod-host 'cd /opt/edu-app && SESSIONS_CSV="$(cat timetable_import/sessions.csv)" \
  docker compose exec -T -e SESSIONS_CSV="$SESSIONS_CSV" web \
    odoo shell -c /etc/odoo/odoo.conf --db_host=db -r odoo -w odoo -d edu19 --no-http \
    < /opt/edu-app/timetable_import/import_sessions.py'
```
> ⚠ 生产 web 容器需能读取 `/opt/edu-app/timetable_import/import_sessions.py`（`<` 重定向在**宿主 shell** 读文件喂容器 stdin，无需容器内挂载）——本地同款 `run_import_local.sh` 即此形态。若生产 compose 文件与本地命名不同，以 `docker compose ps` 实测为准。
> 预期输出：裁决2 剔除 14 / 展开后 / 计划去重 = 216；同 batch 冲突 0；新建 216 · 幂等跳过 0 · 库内总 216（空库起算）；审计 edu.audit.log 写入。
> 幂等：重跑 → created=0/skipped=216。

### B3. 生产冒烟（两层）
1. **HTTP 冒烟（公共面 + 登录页）**：
   ```bash
   ssh prod-host 'for u in / /web/login; do echo "$u $(curl -sS -o /dev/null -w "%{http_code}" --max-time 15 http://127.0.0.1:8069$u)"; done'
   ```
   → 期望 `/` 与 `/web/login` 均 200（curl 无法走登录后 /student/timetable，因其 auth=user；后台课表 200 需登录态，本地 UI 已由 t3/t4 与本地验收覆盖，生产以登录页 200 + 库计数 + 抽样为准）。
2. **库内计数与抽样比对（验收证据）**：
   ```bash
   ssh prod-host 'docker compose exec -T db psql -U odoo -d edu19 -c "select count(*) from op_session"'
   # 期望 216 == 契约总数
   # 抽样：随机/固定 seed 10 条 → 与契约 (batch,subject,date,start,end,course) 逐字段比对
   ```
   抽样键 = (batch_code, subject_code, 本地日期, start HH:MM) + course 归属；跨两学期、含跨部合班 A123B234/A123B34、考试 07:45 档、密集课 09:00-17:00、基础信仰 A1。

### B4. 部署档案更新 + git 提交
- `docs/deploy-malaysia.md` 增补「2026-09-0X 排课批量导入（2+6）」小节：生产 op.session 216、course/batch/subject/faculty 建档数、抽样 10 条比对证据、冒烟 curl 结果、回滚说明。
- 同时 git 提交 `timetable_import/`（新目录）与档案更新（t5 完成态）；本地未提交的 `tests/smoke/` 图片/F_roles_smoke.md 属 t5 范围外的既有脏项，**不并入本次提交**，如需一并提交需用户点头。

## C. 影响范围（获批执行时）

| 对象 | 影响 |
|---|---|
| 生产库 edu19 | 新建：18 op.subject、16 op.batch（13 挂课 + 档案 A2/A3/B2）、1 op.faculty「待定」占位、10 op.timing、216 op.session（state=draft）；course 复用现有 6 个不新建；term 已存在不新建 |
| 生产文件 | 新增 /opt/edu-app/timetable_import/；custom_addons/edu_schedule 字节同步（无代码差异） |
| 代码/模块 | 无 -u 升级（edu_schedule 零改动）；不触碰 openeducat_erp/ |
| 既有数据 | 生产 op_session 现为 0 → 无演示数据可冲突；不删不改任何既有行 |

## D. 回滚预案

| 情形 | 处置 |
|---|---|
| 导入报错/中断 | odoo shell 脚本内已 try/rollback：批量 create 失败自动回滚本事务；commit 前失败=零写入。任何一步失败**不 commit**，直接停止，生产保持空库 |
| 导入成功但用户不满意 | 216 节全部挂在占位「待定」教师(id?) 下，一条命令删除：`op.session.search([('faculty_id', fac)])` 全删（state=draft 无考勤/成绩依赖）；再删该占位 faculty；subjects/batches/timings 按需清理（或保留供重导） |
| rsync 后想退回 | 生产代码与本地字节一致，重传旧版即回退；数据库无 -u 结构变更，无 schema 迁移风险 |
| 需要彻底清场重来 | 顺序：删 216 session → 删占位 faculty → 删新建 batch/subject/timing → 恢复 course 原状（未新建无需恢复）|

## E. 铁律复核（执行前 gate）

- [ ] 用户已看到本地验收结果（t3 全绿 + t4 pass + 本地课程表/周历/冲突分色 UI）并**明确说出「可部署」** → 才可进入 B 节
- [ ] t3 + t4 均为 pass（当前已满足）
- [ ] 本地与生产数据差异已向用户说明：生产空库将从 0 直接到 216；本地 263（=216+47 演示）仅为本地克隆库现象，生产不会出现 47 演示
- [ ] 若用户对裁决（B 部归 CRS-BED vs CRS-BLA、师生互动、密集日期等）有调整 → 先在本地重导重验，再走本流程
