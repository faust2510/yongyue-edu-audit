# A8 生产升级 Runbook（探活门禁版）

> 🆕 **全新服务器首次安装？** 本文件讲的是**已有生产上的升级**。
> 新机器从零建库要显式 `-i` 一批模块（默认的 `-u` 清单**只升级、不安装**，且不含 `edu_public`/`edu_zh`）——
> 实测清单、命令与踩到的坑见 **`docs/audit/fresh-install-rehearsal.md`**（2026-10-04 第 67 轮整装演练）。
> 一句话版：`-i edu_life,edu_schedule,edu_apply,edu_portal,edu_brand,edu_tg_bind,edu_assess,edu_public,edu_zh`，
> 再单独 `-i edu_nav`（若确实需要它 —— 生产当前未装，且它在全新库上会因写死数字 id 而崩，见该文）。

> 对应 v2.1 清单 A8（生产「陈年视图」修复）与每批上线流程。
> 基线：docs/deploy-malaysia.md + scripts/deploy_myedu.sh（rsync 直推模式）。

## 0. 升级前（本地）

1. 本地验收通过：
   - `python3 -m compileall -q custom_addons`
   - XML 解析：`python3 -c "import glob,xml.etree.ElementTree as ET; [ET.parse(f) for f in glob.glob('custom_addons/**/*.xml',recursive=True)]; print('OK')"`
   - 本地 docker 栈升级：`docker compose exec web /entrypoint.sh odoo -d edu19 -u <模块> --stop-after-init --no-http`
2. 需要升级的模块（**以 `scripts/deploy_myedu.sh:156` 的默认清单为准**）：
   `edu_life,edu_schedule,edu_apply,edu_portal,edu_brand,edu_tg_bind,edu_assess`
   （`edu_nav` **单独跑一趟**，不能与别的模块同一个 `-u` 列表 —— 见 `deploy_myedu.sh` 第 3 步的说明）

   > ⚠ **2026-10-04 更正**：本行原先写的是 `edu_portal,edu_eval,edu_life,edu_schedule,edu_apply` ——
   > 其中 **`edu_eval` 已于 2026-09-29 按用户授权整体删除**（见 `docs/audit/edu-eval-removal.md`），
   > 照旧清单部署会因「模块不存在」直接失败。本轮实测核对后改为上面的真实清单。

## 1. 同步代码（rsync + chmod）

```bash
# 在仓库根目录，REMOTE=prod-host（203.0.113.10），DIR=/opt/edu-app
cd custom_addons
rsync -az --exclude='__pycache__' -e "ssh -o BatchMode=yes" \
  edu_portal edu_brand edu_life edu_schedule edu_apply edu_tg_bind edu_assess \
  "$REMOTE:$DIR/custom_addons/"
# 一并同步 openeducat_erp（若本批动了社区模块）：
cd ../openeducat_erp
rsync -az --exclude='__pycache__' -e "ssh -o BatchMode=yes" \
  . "$REMOTE:$DIR/openeducat_erp/"

# 权限修复（容器内 odoo 用户 uid=100 需可读；切勿递归 chown data/db，PGDATA 必须 700）
ssh -o BatchMode=yes "$REMOTE" \
  "cd $DIR/custom_addons && chmod -R a+rX edu_portal edu_brand edu_life edu_schedule edu_apply edu_tg_bind edu_assess"
```

## 2. 模块升级（-u，停 web 或端口错开）

```bash
ssh -o BatchMode=yes "$REMOTE" "cd $DIR && docker compose stop web >/dev/null 2>&1"
ssh -o BatchMode=yes "$REMOTE" "cd $DIR && docker compose run --rm --name deploy-upg \
  web odoo -c /etc/odoo/odoo.conf -d edu19 \
  -u edu_life,edu_schedule,edu_apply,edu_portal,edu_brand,edu_tg_bind,edu_assess \
  --db_host=db -r odoo -w odoo --stop-after-init --http-port=8099 \
  > /tmp/upg.log 2>&1 || true"
## 升级日志判读：必须出现 "Modules loaded"，不得有 ERROR/CRITICAL/Traceback
ssh -o BatchMode=yes "$REMOTE" \
  "grep -E 'ERROR|CRITICAL|Traceback|Modules loaded' /tmp/upg.log | tail -5"
```

> 说明：A8 根因即「代码已改、库中动作/视图未升级」→ 每个动作型变更批次都必须跑本步。
> 涉及 `edu.media` 等附加模块时按需追加模块名。

## 3. 起站

```bash
ssh -o BatchMode=yes "$REMOTE" "cd $DIR && docker compose start web >/dev/null 2>&1"
sleep 8
curl -s -o /dev/null -w '%{http_code}\n' https://edu.example.org/web/login   # 期望 200
```

## 4. 探活审计（A8 门禁，必跑）

把审计脚本传入生产机并针对生产库执行（`prod-host:/opt/edu-app/custom_addons` 之外的 /tmp）：

```bash
scp scripts/check_prod_menus.py "$REMOTE:/tmp/"   # 或 docker compose cp
ssh -o BatchMode=yes "$REMOTE" "cd $DIR && docker compose exec -T web python3 \
  /tmp/check_prod_menus.py --db-host db --db-name edu19 \
  --db-user odoo --db-password '$(grep -m1 db_password $DIR/config/odoo.conf | awk -F= "{print \$2}")'"
```

判读：
- 全部 `ok  ` → 通过，可继续对外流量；
- 出现 `FAIL` → 对应模块未升级/未安装：回到第 2 步补 `-u` 对应模块；若为已卸载模块的
  遗留菜单，在后台「用户界面 → 菜单」停用该菜单（或代码级删除后重新发布）。

可选补充探活（每批截图回报用）：
```bash
for u in / /programs /apply /contactus /my/home /web/login; do
  echo -n "$u "; curl -s -o /dev/null -w '%{http_code}\n' "https://edu.example.org$u"
done
```

## 5. 样品清理门禁（A10，正式使用前必跑）

```bash
scp scripts/cleanup_demo_data.py "$REMOTE:/tmp/"
ssh -o BatchMode=yes "$REMOTE" "cd $DIR && docker compose exec -T web python3 \
  /tmp/cleanup_demo_data.py --db-host db --db-name edu19 \
  --db-user odoo --db-password '$(grep -m1 db_password $DIR/config/odoo.conf | awk -F= "{print \$2}")' \
  --dry-run --include-linked-data --include-seed-codes"
# ↑ 先预览：样品账号邮箱清单 + 各演示模型命中明细（含演示人档案与关联数据）
# 人工确认清单无误后再正式执行（停用账号 + 删演示数据 + 删演示人档案）：
ssh -o BatchMode=yes "$REMOTE" "cd $DIR && docker compose exec -T web python3 \
  /tmp/cleanup_demo_data.py --db-host db --db-name edu19 \
  --db-user odoo --db-password '$(grep -m1 db_password $DIR/config/odoo.conf | awk -F= "{print \$2}")' \
  --execute --deactivate --include-linked-data --include-seed-codes --delete-demo-persons"
```

安全约束（评审 F3 强制约定，已内置到脚本）：
- 默认 `--dry-run`，`--execute` 才真正改动；账号默认**停用**（--deactivate）
  而非删除；`--delete-users` 危险——op.student.user_id 外键为
  **ON DELETE CASCADE**，直接删账号会级联删掉整个学生档案！（本库实测：
  op_student.user_id=CASCADE；op_parent.user_id / res_partner.user_id=SET NULL；
  res_users.partner_id=RESTRICT；op_faculty 无 user_id 列，经 res_partner 委托。）
  因此脚本内置「① 解绑 → ② 账号 → ③ 人档案 → ④ 数据」执行顺序：
  **解绑阶段先把样品账号与待删人档案的 user_id 全部置空**（op_student.user_id/
  op_parent.user_id/res_partner.user_id），再执行账号停用/删除与档案删除。
  已实测验证：删账号/停用后学生档案完整保留且 user_id 置空，零级联误删。
- `--delete-users` 在逐账号 savepoint 中执行，被 hr.employee 等 FK 引用的账号
  自动跳过并报告（退出码 3 = 有跳过项需人工复核），不会中途整体回滚。
- `--delete-demo-persons` 删除演示人档案（先解绑再删）；被选课/测验等 FK
  引用的档案跳过并报告。
- CRS-*/PRP-2026 等已转为真实骨架的种子数据**不在**自动删除范围（脚本已排除）；
  名称带「【演示】」残留的真实记录（如被真实选课引用的班级）会因 FK 自动跳过，
  人工复核后按需改名/保留。

### 5.1 业务数据清理纪律（评审 F2 强制约定，B9/B10 起适用）

清理 `edu.message`（私信）等业务测试数据时：

```bash
# 一律 DELETE（或 TRUNCATE），禁止 DROP TABLE：
docker compose exec -T db psql -U odoo -d edu19 -c \
  "DELETE FROM edu_message WHERE body LIKE '%【冒烟测试可删】%';"
```

- **禁止 `DROP TABLE edu_message`**——代码已随批次落地时模型已注册，表被
  DROP 后 `/my/home` 全角色 500（本地实测复现：事务级 UndefinedTable 会
  复炸渲染）。真清空用 `TRUNCATE edu_message;`。
- **若确需 DROP**（如重建表结构）：必须**立即**执行第 2 步 `-u edu_portal`
  重建，并验证 `curl /my/home`（各角色）返回 200 后方可继续。
- 冒烟脚本自带清库（tests/smoke/G_messages_smoke.py 末尾按标记 DELETE），
  不依赖手工清理。

## 6. 验证与回报

- [ ] `-u` 日志无 ERROR/CRITICAL，`Modules loaded` 出现
- [ ] `check_prod_menus.py` 全部 `ok`（或人工确认的降级清单）
- [ ] 关键公开页与门户页 200
- [ ] 截图回报（对照 B11 铁律：每页改造后功能可达）
- [ ] 通知用户：样品账号已停用 + 清单已归档

## 7. 回滚

A8 升级本身不改数据结构（只刷新动作/视图），失败少见；如出现异常按
docs/deploy-malaysia.md 回滚流程：`docker compose down` →
`systemctl enable --now edu-system.service`（旧服务 :8090）→ nginx 切回。