# AI 交接提示词（粘贴给任何 AI 助手即可接管）

> 用法：把下面整段发给新会话的 AI。配合仓库内的 `docs/code-map.md`（权威代码图谱）使用。

---

你好，你将接管「永约学坊神学院教务系统」的开发与运维。请先通读仓库根目录的 `docs/code-map.md`（一页代码图谱，含全部模块/路由/模型/铁律），再按本提示词行事。

## 1. 项目是什么

- 神学院教务系统，骨架为 **Odoo 19 + OpenEduCat（19.0 社区快照，只读不改）**，全部自研代码在 `custom_addons/edu_*`（10 个模块）。
- 服务对象：学生 / 家长 / 教师 / 教务处·管理员四类角色，中文界面，简繁英三语。
- 生产站：**https://edu.example.org**（马来西亚服务器，SSH 别名 `prod-host`，`/opt/edu-app`，容器 edu19-prod-*，库名 edu19）。
- 本地开发：仓库根 `docker compose up -d`，地址 http://localhost:8069（:8072 WebSocket 必须开），库名 edu19。
- 本地演示账号（密码均为 demo123）：教务 `backoffice@local`、教师 `faculty@local`、学生 `stu@local`；admin 是 Odoo 后台管理员。生产真实账号只有 admin 和一个教务邮箱账号（找我要）。

## 2. 当前状态（2026-08-30）

- 「辅助增强包」批次 1-5 已全部交付并部署生产：CSV 导出×9、PDF/图片在线预览、iCal 日历订阅（`/my/calendar/ics/<token>`）、状态提醒（站内信）、审批列表筛选分页、考勤防重复、全局搜索扩到 10 类、首页收藏服务端化、课表打印、测验历史页、家长摘要卡、操作审计（edu.audit.log）、公告有效期+附件、教师作业管理、通知偏好（edu.notify.pref）、QR 60 秒轮换自助签到、学生名单两段式导入。git log 155732d…b2676e1 可查。
- 生产测试/演示数据已清空（E2E 账号、演示师生、演示作业考试测验课表考勤、测试邀请码），保留了真实报名 2 条（王茜茜）、校友岗位 3 条、学年/学期/课程/科目/班级基础数据、用户自己的学生档案。
- **暂缓待做**：① Office(docx/pptx/xlsx) 转 PDF 预览——容器无 LibreOffice，装 soffice 后按懒转换+ir.attachment 缓存方案实现；② 生产开学前要用排课工作台重排真实课表（旧演示课表已清）。
- 数据库备份：服务器 `/opt/edu-app/backup/`（清理前后各一份）+ 用户 Mac `~/Documents/edu19-backups/`（生产 post-cleanup + 本地开发库）。恢复：`pg_restore -U odoo -d edu19 --clean --if-exists`。

## 3. 铁律（违反会返工）

0. **先调研，后设计（最优先）**：任何功能在进入设计前先查成熟实现（Odoo 19 核心源码 → OCA → Moodle/Canvas → 国内同类钉钉/企微/飞书/校管家），**能装不写、能抄不造**；结论落 `docs/research/<主题>.md` 并带一手来源 URL，未核实的标「未验证」。详见 `CLAUDE.md` 铁律 0 与 `docs/dev-workflow.md` 六步闸门第 2 步。
1. **Odoo 19 语法**：字段 `group_ids`（不是 groups_id）、视图 `<list>`（不是 tree）、SQL 约束用 `models.Constraint`；`sudo()` 只作用于 recordset。
2. **权限**：不建自定义组；控制器用 `current_student()/current_faculty()/privileged_staff()` 判定，写操作一律 POST+csrf+兄弟路由 `/xxx/save`；越权按"不存在"处理。
3. **品牌红线**：一切旧学院假资料必须清除；联系方式只允许永约学坊真实资料；演示数据必须带【演示】标记，测试数据带【冒烟】标记。
4. **QWeb 模板内禁止 `%` 格式化**（装载期 %% 折叠会崩），数字/日期在 Python 侧预格式化后传入。
5. **汉化门禁**：改动用户可见文案后必须 `python3 scripts/check_english.py`，可见英文串必须为 0。
6. **验证闭环**：改码 → **`bash scripts/safe_upgrade.sh <模块>`**（串行锁 + DB 参数 + `--no-http` + 挂载自检 + 失败特征硬失败；**默认 `-u`，仅首装新模块用 `-i`**）→ EXIT=0 无 Traceback → curl 各角色冒烟 → check_english → 路径范围 git commit。
   > ⚠ **`-i` 不能当验证手段**：实测 `-i` 对已装模块**不重载 data/view 文件**（新字段会建、新建视图不会进库），会给出「升级成功但页面没变」的假象；验证视图/模板必须用 `-u`。
   > **别再用** `docker compose exec web odoo ...`：exec **绕过 entrypoint**，缺 `--db_host` 会报 unix socket 连接失败；不传 `--no-http` 会撞主服务占用的 8069（`Address already in use`）；`-u` 对未装模块无效（要 `-i`）。也别把输出管进 `tail`——退出码会被吃掉。
7. **部署**：`bash scripts/deploy_myedu.sh [模块名列表]`（默认六模块）；**rsync/chmod 清单目前含 edu_quiz**（8/30 曾因权限 600 致 manifest 不可读、模块路由消失，勿再遗漏）；生产 SSH 可能超时，长升级用 nohup。
8. **数据结构变更**：init() 迁移必须 savepoint + information_schema 列检查（裸 except 会毒化升级事务）。
9. **多窗口协作**：小步路径范围提交；禁全树 stash/reset；同容器升级串行（用 `bash scripts/safe_upgrade.sh`）；`roles.py` 与 `main.py` 循环引用，roles 内需要 current_student 就地定义。
   > **挂载失步（静默灾难）**：Docker Desktop 偶尔让容器读到旧文件内容，症状是 `manifest not found` / `not installable, skipped` / `inconsistent states`，**但退出码仍是 0**，极易误判成升级成功。safe_upgrade.sh 已内置自检与硬失败；手工绕过时遇到就 `docker compose up -d --force-recreate web`。
10. **能并行就派子代理**（侦查/调研类），但同容器写操作与侦查链必须串行。

## 4. 常用工具位置

- 冒烟：`tests/smoke/`（aux1-4、p5_acd、p5b_selfcheck、p5f_import 等，requests 登录态脚本，跑前确保容器在跑）
- 汉化检查：`scripts/check_english.py`（requests 记得 trust_env=False，防系统代理 502）
- 部署/运维：`scripts/deploy_myedu.sh`；图标生成 `scripts/gen_icons.py`；本地起站+隧道 `scripts/dev_up.sh`
- 文档：`docs/plans/`（各功能设计）、`docs/research/`（调研档案：去品牌化+汉化、一站式学习+重复劳动，均为源码级取证）、`docs/audit/peer-research.md`（历史同类系统调研）、`docs/dev-workflow.md`

## 5. 工作方式

- 与用户（王佐）中文直接交流；他偏好自治推进：自己查代码和文档、别反复问；UI 只美化不丢功能；本地验收通过后才部署生产。
- 改动前先看 `docs/code-map.md` 对应小节，改完同步更新它。
