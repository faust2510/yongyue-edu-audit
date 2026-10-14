# 生产部署档案 —— 马来西亚服务器（seminary.example）

> 首次切换：2026-08-24 ｜ 方式：Docker Compose + Cloudflare(橙云) + nginx 反代
>
> ⚠ **2026-10-01：那台机器（203.0.113.10）欠费关机，当时记为「数据全丢」。**
> ✅ **2026-10-04 更正：数据并没有丢。** 校长续费后实测：容器自动拉起、`PGDATA` 197M 与 filestore 37M 完好，
> 学生 51 / 用户 39 / 附件 545 全部在（最后写入 2026-09-24）。已完整备份到校长 Mac 并**做过还原彩排**，
> 最新代码也已部署回该机（`REMOTE=prod-a bash scripts/deploy_myedu.sh`）。
> 全过程见 [old-server-187-recovery-2026-10-04.md](audit/old-server-187-recovery-2026-10-04.md)。
> **教训：「看不到」不等于「没有了」** —— 写「数据全丢」这种结论前必须有一次直接读数。
> ✅ **2026-10-05：当前生产是 203.0.113.10**（本文档原本记录的那台）。2026-10-04 已把
> `edu.example.org`（隧道 CNAME）与 `cn.edu.example.org`（灰云 A）双双指回该机；**203.0.113.11 已退货退款**。
> 切回过程见 [cutover-back-to-187-2026-10-04.md](audit/cutover-back-to-187-2026-10-04.md)，
> 退货前检查见 [decommission-201-2026-10-04.md](ops/decommission-201-2026-10-04.md)。
> 下面这段「换机过程」保留为历史记录（当时的新机 201 已不存在）：
> [docs/ops/migration/new-server-runbook.md](ops/migration/new-server-runbook.md)；
> 数据损失与重建见 [docs/audit/migration/data-loss-ledger.md](../audit/migration/data-loss-ledger.md) 与
> [docs/audit/migration/rebuild-plan.md](../audit/migration/rebuild-plan.md)。
> 保留下文是为了**留证**（它记录了旧机怎么搭起来的、踩过哪些坑），不要照着它的 IP 操作。

## 拓扑

```
访客 → Cloudflare(TLS) → 源站 nginx :80 (server_name seminary.example)
     → proxy_pass 127.0.0.1:8069 (Odoo19 web 容器)
     → /websocket → 127.0.0.1:8072
数据库：edu19-prod-db-1 (postgres:16, 数据落 /opt/edu-app/data/db)
```

## 服务器路径（host: prod-host = 192.0.2.10，Ubuntu 24.04）

| 路径 | 内容 |
|---|---|
| /opt/edu-app/docker-compose.yml | 生产编排（端口仅绑 127.0.0.1） |
| /opt/edu-app/config/odoo.conf | 运行配置（含 admin_passwd 强密钥，**不入 git**） |
| /opt/edu-app/custom_addons · openeducat_erp | 应用代码（与本地 rsync 字节一致） |
| /opt/edu-app/data/web/filestore | 附件/资产二进制（pg_dump 不含，需单独 rsync） |
| /root/backup-edu-system-*.tgz | 旧 Go 版教务系统完整备份 |

## 关键参数

- `web.base.url = https://seminary.example`（freeze=True）
- `proxy_mode = True`、`list_db = False`、workers=2
- 容器内运行用户 uid=100(odoo)/999(postgres)——**宿主机目录属主必须匹配**
  （教训：递归 chown 时切勿波及 data/db，PGDATA 必须 700 且归 postgres）

## 回滚（如需退回旧 Go 版）

```bash
ssh prod-host
cd /opt/edu-app && docker compose down
systemctl enable --now edu-system.service   # 旧服务回到 :8090
cp /root/edu-strcs.go8090.bak.* /etc/nginx/sites-enabled/edu-strcs && systemctl reload nginx
```

## 已知运维注意

0. **P0-CSRF 加固（2026-08-24）**：edu-strcs 站点全局 `add_header Cache-Control "no-store"`，
   仅 `/web/assets/` 正则块例外（immutable）。背景：管理员曾在陈旧标签页提交登录
   →「Session expired (invalid CSRF token)」。属会话过期正常防护，**刷新一次重登即可**；
   中间层禁缓存后不会再被放大。同日已移除登录页明文演示账密（demo_login 机制见
   `custom_addons/edu_portal/views/batch3.xml` 与 quick_login.js）。
1. `docker logs --since` 时间戳带 Z 后缀（宿主时区 UTC+8 解析坑）。
2. Odoo 后台页在 playwright 中禁用 networkidle（长轮询挂起），用固定等待。
3. 即时聊天：`website.channel_id`=校园服务频道；可用性=机器人规则(always)
   或操作员在线（教师/管理员登录后台「讨论」即上线接单）。

## 升级流程（后续版本发布）

本地提交并推 GitHub → 服务器 `git pull`？——本机采用 **rsync 直推**：
```bash
rsync -az --delete --exclude='__pycache__' custom_addons prod-host:/opt/edu-app/
ssh prod-host 'cd /opt/edu-app && docker compose restart web'
```
涉及模型变更时追加 `-u edu_portal,edu_public` 升级步骤。

## 迁移尝试记录（2026-08-31，中止）

- 用户曾计划迁移到 Hostinger 凤凰城 203.0.113.9（2C/7.8G/97G，root 密码已给）。
- 已完成：Docker/nginx/cloudflared 安装、代码+filestore+备份传输、digest 锁定、
  库恢复、栈拉起、nginx 链路冒烟全通（200/303 正常、登录页标题正确）。
- **发现关键事实：`edu.example.org` 的 DNS 不是 A 记录，而是 CNAME → Cloudflare Tunnel**
  （`9a830247-0646-450a-8f06-4a711b447656.cfargotunnel.com`），connector（systemd
  cloudflared）跑在马来西亚源站上。**正确迁移方式 = 把 connector 搬到新服务器**，
  DNS 记录本身无需任何改动，秒级切换秒级回滚。
- 用户随后决定**不迁移，留原马来西亚服务器**，新服务器已退款退货。
- 生产全程零影响：隧道未断、DNS 未动、外部 200 正常。
- 遗留待办（下次迁移时直接照抄此流程）：蓝绿步骤已验证可行——新服起栈+恢复
  dump+冒烟 → 停旧 connector → 终态 dump 补同步 → 启新 connector → 外部验证。
  隧道凭据备份在旧服 `/root/.cloudflared/`（tunnel run 只需 credentials json，
  不需 cert.pem）。Cloudflare API token 见本机 shell 历史（仅 Zone DNS/Cache 权限，
  无 Tunnel 权限，改隧道需面板或更强 token）。

## ⚠️ 退货服务器残留风险（2026-08-31 已消除）

203.0.113.9 退款前清理未完成，机器上曾残留隧道凭据副本 + 数据库 dump。
**同日已通过换隧道消除**（见下节「隧道轮换」）：旧隧道 `9a830247` 已删除，
其凭据即刻作废，退货机上的副本成为废纸。数据库 dump（全部用户/报名数据）
仍在退货机磁盘上，只能依赖商家磁盘擦除承诺；介意数据本身泄露的话唯一
彻底手段是换库内敏感字段（目前仅 2 条真实报名，风险可控）。

## Cloudflare 凭据与 DNS 管理（运维备忘）

- Zone: `example.org`（zone_id `6a25499461f86da2e3014b3787b59395`，account
  `345ab38903bce60bf208ac18e0820b8a`）
- API token 存于本机 zsh 历史（grep cloudflare 可见，仅 Zone DNS 读/Cache 清除
  权限，能列/改 DNS 记录，无 Tunnel/Account 权限）
- DNS 记录现状（2026-08-31）：
  - `A example.org → 203.0.113.9`（proxied）
  - `A www.example.org → 203.0.113.9`（proxied）
  - `CNAME edu.example.org → 9a830247-….cfargotunnel.com`（proxied，**生产站**）
- 改 DNS 用 token 直接 API 调用即可（列记录→改/建→验证 dig）。

## 隧道轮换记录（2026-08-31，消除退货机凭据风险）

背景：退货 Hostinger 机上残留 connector 凭据（旧隧道 `9a830247` edu-tunnel）。
方案：零停机换隧道——先建新隧道双 connector 并存 → API 切 DNS CNAME →
服务转正 → 删旧隧道（凭据即刻作废）。

执行结果：
1. `cloudflared tunnel create edu-tunnel-v2` → 新 ID `70802e77-8b92-4888-b0f8-62f8a2e0fddb`
2. `/etc/cloudflared/config-v2.yml`（ingress 同旧：edu.example.org → localhost:80）
3. 临时 connector 起来后，CF API PATCH DNS：
   `edu.example.org CNAME → 70802e77-….cfargotunnel.com`（记录 id 不变）
4. systemd 切 v2 配置重启（**教训：pkill -f 匹配串会误杀执行脚本的 bash 自身**
   ——命令行里含匹配串，导致约 1 分钟 530 中断后抢修；用 systemd restart 即可）
5. `cloudflared tunnel delete 9a830247-…` 旧隧道删除，退货机凭据作废
6. 终态：v2 四连接（kul01+sin14×2+sin18），外部 200 / 0.08s（服务器视角），
   health 心跳正常，凭据目录只余 v2 json

现役隧道：`edu-tunnel-v2 (70802e77-8b92-4888-b0f8-62f8a2e0fddb)`，
凭据 `/root/.cloudflared/70802e77-*.json`，配置 `/etc/cloudflared/config-v2.yml`，
systemd 单元仍叫 `cloudflared.service`（指向已改 v2）。

## 排课批量导入（2026-09-05，2+6 排课表 → 生产 edu19）

背景：把 `2+6排课表.xlsx` 四个 sheet（A神学部 / 文26下人文部 / 家教网课 / B12 弃用）全量排进
教务网课程表（op.session）。**文26下为 B 部唯一权威源，B12 全部弃用**（差异：英语整体晚 7 天
旧日历、圣灵论缺 9 节等）；A=神学部（A1-A3 年级，A123 合班）、B=人文部（B1-B4）；家教=网课
学员镜像（157 条与文26下同刻同课，并入同一实体不重复建）；L1-L18=课次编号非周次。

### 执行摘要（队长接管，deployer 通道故障后改派）
- 本地交付：契约 catalog.md + sessions.csv（226 实体）+ full_sources 433 逐源可回溯
- 本地验收全绿：t2 导入 216 节 + t3 独立验证 pass + t4 代码审查 pass（全 ORM/幂等/时区正确）
- 生产：rsync timetable_import/ → 容器内幂等导入 → 216 节全部创建（op.session ids 330-545）
  - 归档：18 op.subject（B 部前 BLA- / A 部前 BTH- / 跨部 GEN-）、16 op.batch（13 挂课 + 档案
    A2/A3/B2）、1 op.faculty「待定」占位（id=20）、10 op.timing，course 复用 6 个不新建
  - 裁决口径：B 部 B1-B4 全部归 **CRS-BED 教育学学士**（映射可配置 COURSE_OVERRIDES，可一键改回
    CRS-BLA）；跨部 A123* 合班归 CRS-BTH；师生互动 14 节不排（活动非课程，未建科目）；
    救恩论 A123 密集课按 12/28~12/31 + 1/4 展开 5 节（元旦 1/1 顺延）；考试 5+2 节照排（kind=考试）
  - 冒烟：HTTP / 与 /web/login 均 200；库内 op_session=216（占位教师名下 216）
  - 抽样：固定 seed 10 条逐字段比对 (date,start,end,course,batch,subject) 全部 MATCH（UTC naive
    存储正确，Asia/Shanghai 语义；psql 直显为 UTC 系二次转换错觉，odoo 渲染为北京本地钟）
- 已知现象（不阻断）：占位教师致 44 对跨班同刻同师在冲突配色视图标红（结构性，真实教师替换后
  消解，本地已验明本生产同构）；新「基础信仰」BTH-FOU01 与预备科 PRP-C02 同名（code 唯一，仅
  按名检索歧义，展示名建议微调区分）
- 回滚：导入失败=事务内 rollback 零写入；不满意=一条命令删占位教师名下全部 session 再删 faculty、
  按需清 subject/batch/timing；代码回退重传即回，无 schema 迁移
- 遗留：tests/smoke 既有脏项（F_roles_smoke.md 修改 + 2 prod_banner png）未并入本次提交；
  生产课表 UI 由用户浏览器登录后台目视验收

## 公开课程入口合并 + 科目挂靠修复（2026-09-06）

背景：用户反馈官网首页多个"课程"入口（/slides、/my-courses、/courses、我的课程 共 5 个 menu 项）点开无课程。
根因：①website_menu 残留 5 个重复课程入口（id30/57→/my-courses、id63/64→/slides、id56→/courses）；②18 个排课科目建了 op.subject 但从未挂靠 op.course.subject_ids → 公开 /courses 详情页"相关科目"全空。

修复（生产数据操作，已本地事务演练 + 生产备份 menu 行）：
- 菜单：停用(删除) id30/57/63，主菜单 id64 url /slides→/courses → 全站公开导航仅 1 个「课程→/courses」（重启 web 容器使缓存生效）
- 科目挂靠（op_course_op_subject_rel，幂等）：
  - B 部纯课 BLA-* 6 门 + 英语 BTH-GEN01 → CRS-BED（13 门）
  - A 部纯课 基础信仰/讲道法/摩西五经/改革宗讲座/法律导论 → CRS-BTH（5 门）
  - 跨部课 神论/圣灵论/救恩论/逻辑一/使徒行传/护教学 → 双挂 CRS-BED+CRS-BTH（12 条）
- 结果：CRS-BED=13 科目、CRS-BTH=11（含双挂）、CRS-PRP=14 原样；/courses?course=16 详情显示 13 科目
- 保留：门户顶栏登录后 /my-courses（在线课程中心，与公开站区分）、/slides 路由仍 200 但不再入导航（隐藏≠删除）

## 第二期·学生自主报课 + 教务审批 生产部署（2026-09-07，enroll-v2）

提交链：dd5cabc（feat）+ 3c6bef3（repair-round-2）→ 本批次 rsync 上生产。
本地验收：t3 独立验证 27/27 PASS、t7 复审 PASS（12/12 冒烟），用户经 /agent-teams 明确确认后放行。

### 同步与升级
- 备份：升级前 pg_dump 落 `/opt/edu-app/backup/edu19_before_enroll_v2.dump`（10.25 MB）。
- rsync `custom_addons/edu_portal`（新 enroll.py / registration.py / enroll.xml /
  approval_backend.xml / lms.py 联动 / edu_public /my-courses「进入学习」链）+ `chmod -R a+rX`。
- 升级：`docker compose stop web` → `docker compose run --rm web odoo -d edu19
  -u edu_portal,edu_public --stop-after-init`（/tmp/upg.log）→ 日志 `Modules loaded.`，
  **0 ERROR/0 CRITICAL/0 Traceback** → `docker compose start web`。
- 结构迁移核验：`op_subject_registration` 新增 6 列
  （doc_type / applicant_note / approved_at / approved_by / reject_reason / submitted_at）
  全部就位；生产该表 0 行（无存量单 → `_auto_init` doc_type 迁移空跑无副作用）；
  新后台菜单 `menu_edu_subject_registration_approval` 与 4 张门户视图
  （edu_enroll_catalog / edu_registrar_subject_approvals[_detail] / edu_student_subjects）注册成功。

### 生产冒烟（14/14 PASS，三阶段脚本：odoo shell 造数 → HTTP/RPC 主流程 → 全量清理）
用临时【冒烟】学生+教务账号（portal / back-office admin 组），档案镜像王佐 13 前置态
（course16 CRS-BED / batch13 B1 / term1 / running / 0 科目）：
1. 学生 GET /subject/enroll 200（报课选科/课程目录/科目选择）
2. POST /subject/enroll/save → 303，单 SR0013 submitted（必修自动带 13 门真实科目）
3. /subject/registration 我的申请 200
4. 教务 /registrar/subject/approvals 200 且含新单
5. 详情 200 → 通过 303 → **档案 subject_ids 注入 13/13 门 running**
   （t3 reviewer 备注的「生产 CRS-BED 科目注入」真实路径覆盖）
6. 学生 /my/courses（LMS 档案科目联动）、/my-courses（进入学习链）、/student/timetable 全 200
7. 驳回单 → 学生可见驳回原因
8. 权限负例：学生访问审批 303 → /my/home
9. doc_type 隔离：课程变更单（course_change）不进审批聚合
10. 空科目单通过防呆：UserError 拦截 + 状态保持 submitted
11. 审计 edu.audit.log（报课提交/选课审批）+ 站内通知【选课通知】学生可见
- 清理核验：临时账号/学生/档案/单据/审计/消息全 0 残留；
  王佐真实档案 op.student.course 13 未触碰（course16/batch13/term1/running/科目 0 维持原状）。
- 公网探活：https://edu.example.org / 与 /web/login 均 200。

## 全选修+登录修复+教务账号恢复（2026-09-07）

背景：用户反馈①报课"不是每门都必修"②两个教务账号无法登录③登录页英文翻译按钮消失。

处置（生产已生效）：
1. 全科目改选修：op_subject 30 门 compulsory→elective（此前 2 门已是 elective），现全库 32 门全
   elective；报课页必修/选修最终由教务后台逐门设定（数据可随时改回）。代码配套：
   enroll_save 加"至少勾选 1 门"校验（box=no_subject），无必修课程前端引导文案调整。
2. 教务账号恢复：backoffice@local(教务专员)/jiaowu@local(教务二号) active=f 系 8 月
   deploy-a8 runbook 清理时误停（@local 演示账号但实为真实教务在用）→ 恢复 active=t；
   jiaowu 密码非 demo123（用户自设），backoffice demo123 验证可登录。
3. 登录页语言切换修复：语言 select(简体/繁體/EN)原误置于 edu.dev_quick_login=1 的 demo
   快捷登录区块内（生产未设该参数→语言按钮消失）→ 移出为登录页无条件显示；demo 快捷
   登录按钮仍受参数控制。
4. 部署教训：rsync 整目录曾未覆盖部分文件（batch3.xml/enroll.py 旧版残留），且单文件
   rsync 后需 chmod a+rX 否则容器 PermissionError；本次逐文件核对+权限修复后 -u 升级
   exit=0 0 ERROR。生产验证：登录页语言 select 显示、backoffice 登录 uid=12、教务审批页
   200、报课页权限隔离 303。

## 全站语言切换 + 学生主页美化（2026-09-07 二轮）

- 官网全站语言悬浮器：继承 website.layout 加右下角悬浮胶囊（简体/繁體/EN），
  走 /my/lang 路由（referrer 回跳），edu_brand brand.css 品牌金样式；
  官网所有页面（首页/courses/programs 等）统一可见。
- 学生主页 hero 美化：多层渐变+光斑+网格纹理、问候语"👋 欢迎回来，{name}"+
  emoji 圆衬、两栏布局（左问候右搜索铃铛）、移动端自适应换行。
- 部署：逐文件 rsync + chmod + -u edu_brand,edu_portal（0 ERROR）；生产验证
  官网首页/courses 悬浮器存在、hero CSS/模板已更新。

## 第三期·财务总账 + 报销 生产部署（2026-09-10，ledger-p3）

提交链：本地分支 main-real（897cd73 设计文档）上未提交工作树（t1 实现 → t5 修复
→ t6 复审 pass）→ 本批次逐文件 rsync 上生产，部署后一次性 git 提交归档。
本地验收：t2 独立验证 PASS、t3 代码审查 needs_revision（6 findings）→ t5 修复
→ t6 复审 **verdict=pass**；p3 本地冒烟 26/26 全绿（含 R1/R1b/R2/R3/R6/R7/R7b）。
用户经 /agent-teams 明确确认后放行。

### 同步与升级
- 备份：升级前 pg_dump 落 `/opt/edu-app/backup/edu19_before_ledger.dump`（10.28 MB）。
- 逐文件 rsync（**11 个文件**，非任务卡所列 8 个——见下方「清单纠偏」）+
  远端 `chmod a+rX`，随后逐文件 md5 双向核对 **11/11 字节一致**。
- 升级：`docker compose stop web` → `docker compose run --rm --name deploy-upg web
  odoo -c /etc/odoo/odoo.conf -d edu19 -u edu_portal --db_host=db -r odoo -w odoo
  --stop-after-init --http-port=8099`（日志 /tmp/upg_ledger.log）→
  **UPGRADE_EXIT=0、ERROR/CRITICAL/Traceback 计数 0**，日志见
  `loading edu_portal/views/ledger.xml` → `Modules loaded.` → `docker compose start web`。
- 版本核验：ir_module_module.latest_version `edu_portal 19.0.1.10.0 → 19.0.1.11.0`
  （installed）。edu_schedule/edu_brand 本期无改动，未 -u（符合任务要求）。

### 清单纠偏（重要，供后续复用）
任务卡给的 8 文件清单**不完整，照抄会漏掉 3 个功能性必需文件**，实际待部署为 11 个：
1. `__manifest__.py` —— 注册 `views/ledger.xml` + 版本号 → **漏则台账视图不加载**
2. `controllers/__init__.py` —— `from . import ledger` → **漏则 /ledger* 全部 404**
3. `views/certificate_report.xml` —— 定义 `edu.reimburse.seq`（REB%06d 序列）
   → **漏则报销单号取不到**
其余 8 个与任务卡一致（models/fees.py、controllers/fees.py、controllers/ledger.py、
security/ir.model.access.csv、models/notify_pref.py、controllers/batch2.py、
views/fees.xml、views/ledger.xml）。
**教训：rsync 清单必须以 `git status` 实际改动集为准，不要采信转述的清单。**

### 生产冒烟（23/23 PASS；脚本 /tmp/p3_prod_ledger_smoke2.py，跑完自清）
镜像学生路径（同 enroll-v2 先例：临时账号 + 结束全量清理）：
- 基线快照 bill=0/pay=0/msg=0 → 建【冒烟】学生 op.student + portal 账号 →
  学生门户 GET `/my/fees` 200（空态正常）、`/my/reimburse/apply` 200（表单+csrf）→
  POST 带真实 PNG 收据 → 303 `box=reimburse_submitted` + `REB000006` 落库、
  附件 `public=false` → 学生页显示「申请中」
- 门禁：**非教务学生**（阻断重定向取原始码）/ledger、/ledger/new、/ledger/reimburse
  全 **303 → /my/home**；匿名 → 303 /web/login；模型层学生 RPC 调 approve →
  `Fault 2 '仅教务/管理员可执行此操作（报销审批、付款登记、记账）。'`
- 教务：/my/fees 200、/ledger 200（应收+应付双向）、/ledger/reimburse 200（含单号）、
  /ledger/export CSV 200（含「报销单号」表头）
- 全流程：打勾同意（改金额 88.50→80.00，approved|80.00）→ 付款登记
  （paid|paid + edu.fee.payment 80.00）→ 学生见「已付款」；驳回：缺原因
  `box=need_reason` 拦截、填原因 → refused+原因落库
- 通知 edu.message `reimburse_result`=3、审计 edu.audit.log=5（报销申请/审批/付款）
- 清理核验：bill=0(基线0)、pay=0、msg=0、aud=0、临时学生/账号 **0 残留**；
  生产仅 1 名真实学生（op.student id=11/user 19/batch 13 running）**未被触碰**

### 收据访问控制矩阵（10/10 PASS；脚本 /tmp/p3_prod_receipt_acl.py）
验证 t3 HIGH-2 修复在生产生效（4 类主体 × 2 条取数路径）：
- 本人 / 教务 → 受控路由 200 真实字节（授权，审批需要）
- **匿名 → 受控路由 303；匿名 /web/image → 仅 6078 字节占位图（非真实收据）**
- **第三方学生 → 受控路由 404；/web/image → 仅 6078 字节占位图**
- 结论：未授权方两条路径均拿不到真实收据字节，匿名公开泄漏已堵

### 已知现象（非阻断，供知悉）
- `views/enroll.xml` 存在**本次部署之前就有的既存漂移**：生产为旧版（缺
  `box=no_subject` 提示与「无必修科目」分支，27942 字节），本地为 2026-09-07
  修复版（28487 字节，已随该日承诺生效）。**本次未动它**（不在本期改动集），
  故修文案提示仍缺失；后端 `enroll.py` 的 no_subject 校验生产已在位，功能不受影响。
  如需对齐，另行安排一次 enroll.xml 单文件部署。
- 生产 37 个 `.svg` 图标仅存在于生产、本地无（历史遗留，无影响）。
- jiaowu@local 生产口令非 demo123（用户自设），本次冒烟用 backoffice@local 走通。

### 回滚
代码回退 = 重传旧版 11 文件 + `-u edu_portal`（无 schema 破坏性变更，新字段均带默认值）；
数据回退 = `/opt/edu-app/backup/edu19_before_ledger.dump`（pg_restore）。


## 静态资源缓存修复 + 校徽瘦身（2026-09-24，中国访问慢诊断）

### 背景：用户报「网速慢」的实测定性

从中国移动线路实测（2026-09-24 15:05 CST，本机）：

| 路径 | 结果 |
|---|---|
| 直连源站 203.0.113.10（绕过 CF） | ping **0% 丢包** / RTT 148–165ms；HTTPS 取首页 **0.5–0.8s** |
| 经 Cloudflare（edu.example.org） | 15 次请求 **6 次超时**，成功者 2.3–5.3s；ICMP **丢包 66.7%** |

- **服务器侧无责**：宿主 `load 0.14`、Odoo 容器内 TTFB **8ms**、首页 HTML 6.8KB(gzip)。
- **根因**：中国移动 → Cloudflare **洛杉矶**（响应头 `cf-ray: …-LAX`）跨太平洋段丢包；
  traceroute 走 CMI(223.120.x)，第 13 跳 263ms 后丢包。
- **对照**：从马来西亚服务器访问同一站点，CF 调度到 `-SIN` / `-HKG`（正常）；
  `www.cloudflare.com`(203.0.113.9) 0.85s 正常 ⇒ 是**特定 anycast 段的中国路由**问题，
  非 CF 整体故障，也非本站配置问题。
- **架构备注**：生产是 `edu.example.org CNAME → 70802e77-….cfargotunnel.com`（隧道 v2，
  connector 在 kul01/sin14×2/sin18）⇒ 源站不接 CF 入向连接，但 **:80 仍对公网开放**
  （直连实测可达，这是后续「中国直连入口」方案的可行性依据）。

### 本次改动（两处，已生效）

**① nginx 静态资源缓存**（`/etc/nginx/sites-available/edu-strcs`；
备份 `/root/edu-strcs.nginx.bak.2026-09-24-152420`；入库副本 `docs/ops/nginx-edu-strcs.conf`，md5 与生产一致）

全局 `add_header Cache-Control "no-store, must-revalidate"`（P0-CSRF 加固，2026-08-24）只给
`/web/assets/` 开了例外 ⇒ **模块静态资源被连带覆盖**：校徽 252KB + FontAwesome 77KB
每次开页重下，且 CF 侧 `cf-cache-status: BYPASS` 完全不缓存。

新增两个 location（覆盖 `/edu_*/static/`、`/openeducat_*/static/`、`/web/static/`）：用
`proxy_hide_header Cache-Control` 顶掉 Odoo 的原值（否则会出现两条互相打架的头 —— 这正是本 bug 的形态），
改为 `public, max-age=604800, stale-while-revalidate=86400` + `CDN-Cache-Control: public, max-age=604800`。
即**恢复 Odoo 自身的 STATIC_CACHE=7 天语义**（`odoo/http.py: Stream.from_path`：每次请求 `os.stat`
现取、ETag=`mtime-size-adler32(路径)`、静态文件**不经 ir_attachment**）⇒ **换静态文件无需重启/升级模块**。

验证：校徽 → 单条 `public, max-age=604800`，经 CF 首次 `MISS` → 之后 `HIT`（`age: 42`）；
`/web/assets/…` 仍 `immutable`（未动）；`/` 仍 `no-store`（CSRF 加固原样保留）；`/web/static/…woff2` → 7 天。

**② 校徽瘦身**：`logo-medallion.png` 410×410 / 252,373 B → **256×256 / 112,836 B（-55%）**
（Pillow LANCZOS 降采样，保留 RGBA）。页面里它最大只显示 52px(页脚)/38px(顶栏)/1em(登录徽标)，
256px 已有 5 倍冗余。原 410px 版本在 git 历史（`df8bc89` 及之前）。

⚠ **缓存已开 7 天** —— 以后替换**同名**图片要先改名，否则访客与 CF 边缘 7 天内看不到新图。

### ⚠ 测量坑（本轮踩过，供复用）

`curl -w '%{size_download}'` 量体积时，**中国链路中途断开会使 curl 非零退出但仍打印残缺字节数**。
本轮首测把 4.5MB 的 lazy 包量成 163KB（实为截断残包），差点得出「页面很轻」的错误结论。
⇒ 量体积必须看退出码/加 `--fail`，并以**源站或库内 `file_size` 为准**。

### 页面重量真账（gzip，源站直取）

| 资源 | 体积 | 缓存策略 |
|---|---|---|
| HTML | 6.8 KB | no-store（每次重新校验） |
| `web.assets_frontend.min.css`（原始 1.45MB） | 198 KB | immutable 1 年 |
| `web.assets_frontend_minimal.min.js` | 9.4 KB | immutable 1 年 |
| 校徽（本次改后） | 113 KB | **7 天（本次新增）** |
| FontAwesome woff2 | 77 KB | **7 天（本次新增）** |
| **首屏必需合计** | **≈ 404 KB** | 回访时仅剩 HTML 6.8KB |
| `web.assets_frontend_lazy.min.js` | **原始 4.5MB / gzip≈1MB** | immutable，`data-src` **按需**加载 |

⇒ 遗留待办（**未处理，另案评估**）：lazy 包 4.5MB（`ir_attachment.file_size=4513019` 已核）在弱网下
一旦触发交互即 1MB 下载，建议后续评估裁剪/拆分 bundle。

### 回滚

```bash
ssh prod-host 'cp /root/edu-strcs.nginx.bak.2026-09-24-152420 /etc/nginx/sites-available/edu-strcs \
  && nginx -t && systemctl reload nginx'
git checkout df8bc89 -- custom_addons/edu_brand/static/src/img/logo-medallion.png
rsync -az custom_addons/edu_brand/static/src/img/logo-medallion.png \
  prod-host:/opt/edu-app/custom_addons/edu_brand/static/src/img/
```

## 中国直连入口 cn.edu.example.org（2026-09-24 落地，方案 A）

### 是什么

给中国方向开了一条**不经 Cloudflare** 的快路；主站 edu.example.org（CF 隧道 + 橙云）保持不变。
两个入口是同一套 Odoo、同一个库、同一份会话逻辑，只是网络路径不同。

```
中国访客 → cn.edu.example.org  A → 203.0.113.10（灰云，不经 CF）
        → HAProxy :443（按 SNI cn.edu.example.org 分流；送 PROXY protocol v2）
        → 本机 nginx TLS 127.0.0.1:10443 → 127.0.0.1:8069 (Odoo)
        → 证书 Let's Encrypt（2026-12-23 到期；certbot 自动续期 + deploy 钩子重载 nginx）

其余地区 → edu.example.org → CF 隧道 v2（kul01/sin14×2/sin18）→ nginx :80 → Odoo（原样不变）
```

### 为什么

见上一节实测：中国移动 → CF 洛杉矶跨太平洋段丢包（15 次 6 次超时、ICMP 丢包 66.7%）。
**同口径背靠背对比**（均绑定物理网卡 en0，绕开本机代理 TUN，各 5 次）：

| 路径 | 成功 | 耗时 |
|---|---|---|
| 经 CF（edu.example.org） | **2/5** | 1.58s、11.86s，另 3 次 20s 超时 |
| 直连（cn.edu.example.org） | **5/5** | 0.65–0.69s |

### 改了什么（全部可回滚）

**DNS（Cloudflare zone example.org）**
- 新增 `A cn.edu.example.org → 203.0.113.10`，**proxied=false（灰云）**，TTL 300，
  记录 id `6f4dea926e49eb29d136d20f4c678469`。停用 = 删此记录。

**源站**
- nginx 新增 `sites-available/edu-cn`（:80，ACME 验证 + 301 跳 HTTPS）与
  `sites-available/edu-cn-tls`（`127.0.0.1:10443 ssl proxy_protocol http2`，站点本体）；
  `sites-enabled` 两个软链已建。入库副本见 `docs/ops/edu-cn.conf`、`docs/ops/edu-cn-tls.conf`。
- `conf.d/edu-cn-ratelimit.conf`：`edu_cn_all` 20r/s、`edu_cn_login` 2r/s、`edu_cn_conn` 40。
  直连绕过了 CF 的 WAF/DDoS，故用 nginx 兜底。**实测有效**：45 次猛打 `/web/login` → 34×302 + 11×503。
- HAProxy `haproxy.cfg`：加 `is_edu_cn` ACL + `edu_cn_backend`（`send-proxy-v2`）；
  备份 `/root/haproxy.cfg.bak.2026-09-24-154612`；默认后端（mtg/xray）与其它 SNI 未动。
- 证书：`certbot certonly --webroot -w /var/www/acme-challenge -d cn.edu.example.org`；
  新增 deploy 钩子 `renewal-hooks/deploy/reload-nginx.sh`（**续期后必须重载 nginx**，
  否则会一直端着旧证书）；`certbot renew --dry-run` 已通过。

### 已验证

- 证书链 `issuer=Let's Encrypt`，浏览器无告警；HTTP/2 生效（`ss` 见 127.0.0.1:10443 监听）
- **真实客户端 IP 透传正常**：nginx access.log 记录到真实公网 IP（非 127.0.0.1）⇒ 限流与
  Odoo 登录防爆破不会失真（这是用 `send-proxy-v2` + `real_ip_header proxy_protocol` 换来的）
- 页面：`/` 200 / 0.65s / 31KB；`/web/login` 302 / 0.53s；`/my/home` 303（未登录，符合预期）
- 缓存头与主站一致：校徽 7 天、`/web/assets/` immutable、HTML `no-store`
- 主站 edu.example.org 未受影响（200 + `no-store`）

### 注意 / 已知取舍

1. **绕过了 Cloudflare 的防护**（WAF / DDoS / 机器人管理），已用 nginx 限流兜底；
   源站 IP 因此公开 —— 实际早可通过同机 `yuding.618886.xyz` 查到，增量有限。
2. **两个入口 = 两套书签**。是否给中国 IP 做自动跳转（CF Redirect Rule 按国家）另议：
   在"连都连不上"的场景下跳转帮助有限，更实际的是通知中国用户改用新地址。
3. 若本机装了代理工具（fake-IP / TUN），新域名会被默认规则接管：测真实线路用
   `curl --interface en0 ...`；要让浏览器跑满速，在代理里给该域名加直连规则。

### 回滚（全部）

```bash
# 1) DNS：删除 A 记录 cn.edu.example.org
# 2) 源站：
ssh prod-host 'rm -f /etc/nginx/sites-enabled/edu-cn /etc/nginx/sites-enabled/edu-cn-tls \
  && nginx -t && systemctl reload nginx \
  && cp /root/haproxy.cfg.bak.2026-09-24-154612 /etc/haproxy/haproxy.cfg \
  && haproxy -c -f /etc/haproxy/haproxy.cfg && systemctl reload haproxy'
```

### 事故记录：edu.example.org 被置为灰云导致全网不可达（2026-09-24 15:42–16:25）

**现象**：主站（经 CF 的 edu.example.org）全网失败 —— 从中国与服务器侧访问均超时/瞬时失败；
`dig` 各公共解析器只返回 `70802e77-....cfargotunnel.com.` 这个 CNAME，**没有任何 A/AAAA 记录**
（cfargotunnel.com 公网不可解析 ⇒ 客户端无从连接）。

**根因**：Cloudflare 上 `edu.example.org`（CNAME → 隧道）的**代理状态被改成"仅 DNS"（灰云）**。
隧道型记录必须保持**橙云**：橙云时 CF 才合成边缘 anycast IP 并按隧道回源；一旦转灰，
CF 直接把隧道 CNAME 原样吐给客户端，而该名字在公网解析不了 ⇒ 站点立即全球不可达。

**时间线（CST，据 CF API `modified_on`）**
- `15:42:35` 该记录被修改（proxied=false）—— **早于本次会话对同一 zone 的首次写操作
  （15:47:04 创建 cn 记录）4 分 29 秒**，故不是本会话的创建动作所致；
  疑似控制台上对该行的误点，需向操作者确认。
- `16:25` 我在收尾复核时发现主站瞬时失败（0.001s，非超时）⇒ 定位到 DNS 只回 CNAME。
- `16:24:37`（UTC 08:24:37）用 API 把该记录的 `proxied` 置回 **true**。
- `16:26` 起 DNS 重新返回 CF IP；服务器侧 200×3（0.09–0.38s），中国侧 200。

**复盘要点**
1. **隧道 hostname 记录只能橙云**。若以后要"直连"，另开子域（如本次的 cn.），
   绝不动主域记录的代理开关。
2. **故障可被 5 分钟内发现**：`dig +short edu.example.org @1.1.1.1` 看有没有 A 记录 ——
   只回 CNAME 就是出事了。建议后续加一条定时探活（失败推 Telegram）。
3. **服务器本机 DNS 有缓存**：记录改回橙云后，服务器上 curl 仍失败（缓存里是 CNAME-only 的旧答案），
   `resolvectl flush-caches` 后恢复。排查时别被这一步误导。
4. 事故窗口约 **43 分钟**（15:42–16:25）。

## 站点探活与告警（2026-09-24 立）

起因：2026-09-24 15:42–16:25 主站断网 **43 分钟无人发现**（见上节事故）。

### 跑的是什么

宿主 `prod-host` 的 `edu-health-check.timer` **每 5 分钟**调用
`/opt/edu-app/scripts/health_check_alert.py`，四项检查：

| key | 检查 | 判据 |
|---|---|---|
| dns | `edu.example.org` 经 1.1.1.1 / 8.8.8.8 解析 | **必须出 A 记录**（只回 cfargotunnel CNAME = 灰云事故指纹）|
| main | `https://edu.example.org/` 经 Cloudflare | 200 |
| direct | `https://cn.edu.example.org/`（HAProxy SNI + nginx TLS + Odoo）| 200 |
| origin | `http://127.0.0.1/`（源站 nginx，Host: edu.example.org）| 200 |

### 告警怎么走

优先写 `edu_telegram_outbox`（由常在的 `telegram_relay` 投递，**不新增 token**），
收件人取自 `ir_config_parameter: edu_feedback.admin_chat_id`（= 管理群，学生意见同群）。
**数据库不可用时**回退直连 Bot API（token/chat 缓存在 `/etc/edu-health.env`，600）——
否则「DB 挂了」这种最该告警的场景反而发不出去。

去重：状态存 `/var/lib/edu-health/state.json`；OK→FAIL 立即告警，FAIL→OK 发恢复通知，
持续 FAIL 每 `HEALTH_REMIND_HOURS`（默认 6）小时重提醒一次。

### 实测（上线时已演练）

- `--test-alert` → outbox #169 投递成功
- `HEALTH_FORCE_FAIL=dns` → 告警 #170 投递成功（演练今天那次灰云故障）
- 恢复正常 → 恢复通知 #171 投递成功

### 常用操作

```bash
systemctl list-timers edu-health-check.timer                     # 下次执行时间
journalctl -u edu-health-check.service -n 20                     # 最近结果
python3 /opt/edu-app/scripts/health_check_alert.py                 # 手动跑一次
python3 /opt/edu-app/scripts/health_check_alert.py --test-alert    # 发测试消息
HEALTH_FORCE_FAIL=dns python3 /opt/edu-app/scripts/health_check_alert.py   # 演练 dns 项失败
```

改收件人：改 `edu_feedback.admin_chat_id` 即生效（脚本每轮读库并刷新缓存文件）。

### 已知盲点

1. **探针跑在源站上** ⇒ 整机宕机/网络全断时它自己也没法告警。这种场景建议再加一个
   外部探活（UptimeRobot / Healthchecks.io 免费版，指向 `https://edu.example.org/web/login`）。
2. 首次运行会把 token/chat 落到 `/etc/edu-health.env`（600）；若嫌落盘敏感，
   删掉该文件即退化为「仅 outbox 通道」。
3. `scripts/deploy_myedu.sh` 已把该脚本纳入 rsync（与 `check_live_registry.py` 同行）。

## 前端瘦身第一刀：lazy 包整族摘除（2026-09-24）

### 怎么发现的问题（可复用的测量法）

用 Playwright 实测**匿名访客首访**（`scripts/` 外的临时脚本，方法记在这里）：

| 资源 | 下载量 | 说明 |
|---|---|---|
| `web.assets_frontend_lazy.min.js` | **4.30 MB** | 首访必下，之后 immutable 缓存 1 年 |
| `web.assets_frontend.min.css` | 1.42 MB | gzip 后 198KB |
| `im_livechat/assets_embed.css` | 0.50 MB | 在线客服 |
| `website/translations?lang=zh_CN` | 0.38 MB | 前端翻译表 |
| hero 图 / 校徽 / 字体 等 | 0.36 MB | |
| **整页合计** | **7.08 MB** | |

**归因法（关键技巧）**：Odoo 生成的包体里**保留了每个源文件的路径注释** `/* /module/static/src/x.js */`，
所以按注释切段即可精确算出"每个文件/每个模块占多少"。这个包的真实构成：

| 模块 | 占用 | 占比 |
|---|---|---|
| web（框架/jQuery/owl/luxon） | 1308 KB | 29.7% |
| html_editor（网页编辑器） | 921 KB | 20.9% |
| **payment_stripe** | **616 KB** | **14.0%** |
| mail（讨论/私信） | 599 KB | 13.6% |
| website | 280 KB | 6.3% |
| website_sale / website_slides / account / im_livechat / sale / website_forum | 421 KB | 9.6% |

### 改了什么

`edu_brand` manifest 的 `web.assets_frontend_lazy` 加 **149 条 `('remove', ...)`**，
整族摘除 `payment* / website_sale* / delivery / sale / account / website_forum / website_slides`
（业务数据实测：支付单 0、销售单 0、会计凭证 0、发票行 0、论坛帖 1、课程 2、商品 2 占位）。
`portal` / `web_tour` 仍在用，未动。

**实测效果**：lazy 包 **4.30MB → 3.88MB（-446KB）**；整页 7.08MB → 6.66MB；
生产复核（真实浏览器打 `cn.edu.example.org`）15 个请求 0 失败、**0 JS 错误**；7 个页面冒烟 0 错误。

### 三个坑（都踩过，别再踩）

1. **只摘几个大文件会破坏 ES 依赖闭包**：摘掉 `@payment/interactions/payment_form` 后，
   浏览器报 `modules are needed by other modules but have not been defined …`
   （`website_payment` / `account_payment` / `delivery` / `website_sale_comparison|wishlist`
   还在依赖它们）⇒ **必须按依赖闭包整族摘**。
2. **同一清单不能加到 `web.assets_frontend`**：那些文件不在该包，Odoo 直接
   `ValueError('not found in bundle')`，**整页 500**（本地冒烟当场抓到，未上线）。
3. **门禁 `check_manifest_tracking.py` 会把 `('remove','外模块/文件')` 当本模块文件校验**，
   必然假红、卡死 `safe_upgrade.sh`。已修：按「路径首段 == 本模块名」判定自引用，
   并固化反例（t125）进自证。

### 遗留疑点（如实记录，未查明）

对 149 个被摘文件做**内容级审计**（逐文件取生产包内的唯一片段、再用它到新包里搜）：
**146 个内容确实已移除，合计 1041 KB**；但包体实际只降 **446 KB**。
即约 600KB 内容以某种形式（打包管线/依赖内联）又回到了产物里。
不影响本次交付的功能与体积结论（浏览器实测 -420KB 与包体 -446KB 相互印证），但成因未明，
后续若要做第二刀（卸载未使用模块 / 动 CSS）应先弄清这一条。

### 下一步更大的杠杆（未做）

- **卸载未使用的模块**（`website_sale*` / `website_slides` / `website_forum` / `payment_stripe` / `sale`…）：
  能从源头连 CSS 一起带走（CSS 包 1.42MB 里也有它们的份），但要先处理
  `edu_brand.depends` 里的 `website_sale`，属于较大改动，需单独设计。
- `im_livechat/assets_embed.css` 495KB、`website/translations` 377KB 是另外两块独立的大件。

### 回滚

删掉 `edu_brand/__manifest__.py` 里的 `'web.assets_frontend_lazy'` 整段 → `-u edu_brand` → `docker compose restart web`。

## 前端瘦身第二刀：整族卸载未使用模块（2026-09-24）

第一刀（见上节）只把电商族的 JS 从 lazy 包里摘了入口；第二刀从**源头**把它们卸掉。

### 为什么能卸（先做的调研）

| 障碍 | 结论 |
|---|---|
| `edu_brand.depends` 里有 `website_sale` ⇒ 卸载会级联到 edu_brand → edu_portal → 全部自研 | 该依赖**只有一个真用途**：停用 `website_sale.search` 视图 + 隐藏购物车/心愿单图标。3 处补丁已移除，依赖摘掉 |
| `account` 是否可卸 | **不能**：`openeducat_fees` / `openeducat_library`（教务在用）依赖它 ⇒ 保留（它 73KB 仍在包里） |
| `edu_nav` 引用了 14 条 `website_slides.*` / 4 条 `account_payment.*` 菜单 | 全部 `forcecreate="0"`（不存在即跳过）。先例：`hr_skills_slides` 从未安装，edu_nav 一直引用它的菜单而站点正常 ⇒ 机制已证 |
| 网站页面会不会被带走 | 5 个页面（/、/contactus、两个 thank-you）与电商无关 ✓ |
| 数据损失 | 商品 2、活动 4、论坛帖 1、课程 1；销售单 0、支付单 0、会计凭证 0 |

### 执行（生产）

1. **`pg_dump` 全量备份** → `/root/backup/edu19_before_slim.2026-09-24-174524.sql.gz`（5.7MB，`gzip -t` 通过）
2. 同步 3 个文件（manifest / brand_debrand_data.xml / odoo_debrand.xml，md5 与本地一致）
3. `-u edu_brand`（摘掉依赖与 3 处补丁）→ EXIT=0
4. 卸载 **18 个**（production 实际在装的）：`website_sale*`(4) `website_slides_forum` `website_slides` `website_forum` `website_event` `website_blog` `sale_edi_ubl` `sale_sms` `spreadsheet_dashboard_sale` `sale` `website_payment` `account_payment` `payment_custom` `payment_stripe` `payment`
   （另 3 个 `hr_skills_slides` / `spreadsheet_dashboard_website_sale` / `delivery` 本就没装）
5. 重启 web + 就绪轮询 + **活体注册表门禁 PASS**（90/90）

### 实测效果（浏览器打 cn.edu.example.org）

| 指标 | 最初 | 第一刀后 | **第二刀后** |
|---|---|---|---|
| 整页下载 | 7.08 MB | 6.66 MB | **6.23 MB（-12%）** |
| lazy JS 包 | 4.30 MB | 3.88 MB | **3.74 MB（-13%）** |
| CSS 包 | 1.45 MB | 1.45 MB | **1.15 MB（-21%）** |
| HTTP/JS 错误 | — | 0 | **0** |

模块数 138 → 117。

### 两个副产物（都已修）

1. **门禁边界常量**：`check_view_xpath.py` 的 `EXPECTED_SKIPPED_INHERIT` 25 → 23
   （卸载后少了 2 处跨模块继承），已按该文件的修订惯例升 r14 并写明来由。
2. **归因法的边界（重要认知）**：包体里的 `/* 路径 */` 标记**只覆盖部分文件**；被
   `odoo.define(...)` 包装的模块是**无标记内联**的，会被算到前一个带标记文件的头上。
   ⇒ 「按标记归因」得到的模块占比是**近似值**：早先"stripe_options.js 占 606KB"实为
   「该文件 + 其后一段无标记模块」的合计。体积结论以**包体字节/浏览器实测**为准。

### 回滚

模块卸载**不可逆**（重装模块不恢复数据）。唯一真正的回滚 = 恢复备份：
```bash
ssh prod-host
cd /opt/edu-app
docker compose exec -T db psql -U odoo -d edu19 -c 'drop schema public cascade; create schema public;'
gunzip -c /root/backup/edu19_before_slim.2026-09-24-174524.sql.gz | docker compose exec -T db psql -U odoo -d edu19
docker compose restart web
```
代码侧回滚：`git revert` 本次提交 + 重新安装被卸模块（数据不回来）。

### 剩余的杠杆（未做，需产品决策）

| 项 | 体积 | 代价 |
|---|---|---|
| `html_editor` + `html_builder` | ~1MB JS + 222KB CSS | 废掉后台「编辑网站」（含拖拽编辑器） |
| `mail` | 599 KB JS | 废掉讨论/私信/通知（在用） |
| `website/translations` | 377 KB | 前端翻译表 |
| `im_livechat` embed CSS | 495 KB | 在线客服（在用） |

## 前端瘦身第三刀：移除网站客服入口（2026-09-24）

### 为什么不是"卸载 im_livechat"

用户要求"客服不要了"。但先查了数据：**9 个访客会话 / 41 条消息，最近一次 09-19（5 天前）**——
卸载 `im_livechat` 会**连对话记录一起删掉**（不可逆）。而把客服气泡挂到网站上的其实只是
`website_livechat` 这个桥接模块（**反向依赖为空 ⇒ 卸载零级联**）。

⇒ 采用「只卸 `website_livechat`」：公开入口消失、资源不再下载，**对话记录留在后台**。
若日后确要连后台功能一起删（会丢那 41 条记录），再卸 `im_livechat`
（连带 `hr_livechat` / `spreadsheet_dashboard_im_livechat`）。

### 实测（本地先验，再生产）

| 指标 | 卸前 | 卸后 |
|---|---|---|
| 整页下载 | 6.23 MB | **5.74 MB（-490KB）** |
| 请求数 | 15 | 14（`im_livechat/assets_embed.css` 495KB 消失） |
| livechat/embed 请求 | 1 | **0** |
| JS 错误 | 0 | 0 |
| 数据 | 渠道 2 / 会话 9 / 消息 41 | **原样保留**（`im_livechat` 仍装） |

生产执行：卸载 → 重启 web → 就绪 302 → 数据核对通过。模块数 117 → 116。

### 顺带说明：`mail` 为什么不能卸（本次已核算，供以后挡需求）

`mail` 的反向依赖闭包 = **90 个已装模块**（占 117 个中的 90）。直接反依赖就含
`edu_apply` / `edu_life` / `edu_quiz` / `analytic` / `calendar` / `contacts` / `digest` /
`auth_signup` / `base_automation` …，并会级联到 `edu_portal`（整个门户）。
库内 `mail_message` **1433 条**（通知/私信/chatter 全在里面）。
⇒ **`mail` 是本站的承重墙，卸载等于拆楼**；若嫌它 599KB 重，只能做"按需加载"类改造，不能卸。

## 前端瘦身第四刀（**已探明不可行，回滚**）：把网站编辑器请出前端包

### 动机与归因（这半边结论仍然有效，值得留存）

懒包 3.73MB 里 `html_editor` 占 **921KB（24%）**，是最大单块。归因链（实证）：

```
web.assets_frontend_lazy → ('include', 'web.assets_frontend')
   → website_profile 声明了 ('include', 'html_editor.assets_editor')
   ⇒ 整个编辑器（editor.js / plugin.js / plugin_sets.js …）进了**每个访客**都要下的包
```

**踩到并用掉的机制（重要）**：Odoo 按**模块加载顺序**应用 assets 指令。
`edu_brand` 字母序在 `website_profile` 之前 ⇒ 我们的 `('remove', …)` 先执行、
随后又被人家的 `('include', …)` 加回来（实测：286 个文件原样还在）。
解法：让 edu_brand **依赖 website_profile** 把自己排到后面 ⇒ 摘除立即生效
（286 → 125 个文件、精简包体 3.73MB → **2.92MB，-857KB**）。

### 为什么最终不可行

摘除后实测（Playwright 登录 admin 点「编辑网站」）：

- 编辑器**能打开**（`o-website-builder` 出现）—— 因为编辑器本体确实由
  `website_builder_action.js:331` 的 `loadBundle("website.assets_inside_builder_iframe")` 按需加载；
- **但报 3 个 JS 错误**，点名缺失模块：
  `@html_editor/wysiwyg、@html_editor/plugin、@html_editor/plugin_sets、
   @html_editor/main/toolbar/toolbar_plugin …`
- 连带失败一大片：**`@mail/core/common/composer`、`@mail/core/common/thread`、
  `@mail/discuss/call/*`** ⇒ **`mail` 的前端组件（消息编辑器/聊天窗/讨论）直接 import
  `html_editor` 的核心模块**。

⇒ 那 921KB 不是「编辑网站」的开销，而是**私信/通知/讨论（mail）的前端底座**。
本站 `mail` 是承重墙（见上节：1433 条消息、闭包 90 个模块），**所以这一刀没有安全切法**。

### 结论（留给以后的自己）

- **前端包已无可摘的大件**：`web`(框架) / `mail`(+其 html_editor 底座) / `website` 都是在用功能。
- 若将来真要动，唯一方向是「让 composer 也按需加载」——那是改 Odoo 前端架构的活，
  不是配置级改动，需单独立项。
- 本次实验**已完整回滚**：manifest 复原、`-u edu_brand`、编辑器复测 0 错误、
  包体精确回到 3,915,062 字节。

### 顺带记录（本地开发环境）

为实测编辑器，本地库 `admin` 口令被设为 `demo123`（**仅本地**，生产未动）。
