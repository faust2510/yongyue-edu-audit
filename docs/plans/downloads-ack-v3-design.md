# 资料闭环补齐 v3 设计（t8）
> **状态**：`已上线` ｜ **主题**：`资料下载闭环` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`
> ⚠️ 本文原写「待 t6 交付后进入实现」，实际已于 `3b9f9c2` 交付（2026-09-26 核对发现）。正文未改动。

> 六步闸门第 4 步产出物。上游调研：[`docs/research/onestop-learning-and-repetitive-work.md`](../research/onestop-learning-and-repetitive-work.md)。
> 上游设计：[`docs/plans/study-hub-v3-design.md`](study-hub-v3-design.md)（t6，本文件依赖其 `subject_id` 字段）。
> 范围：需确认已读回执 / 过期自动下架 / 课程资料与行政表格分区。**依赖 t6 交付**（t8 deps=[t6]）。

最后更新：2026-09-12 ｜ 状态：待 t6 交付后进入实现

---

## 0. 既有事实核查（本次逐条核实，非引用）

### 0.1 cron 记录放哪 —— 核实结论：`views/downloads_views.xml` **已注册**，可直接用

`custom_addons/edu_portal/__manifest__.py` 第 57 行含 `'views/downloads_views.xml'`。
→ 可在其中直接加 `<record model="ir.cron">`，**无需改 manifest、无需借道 notice_admin.xml、无需惊动 flow-eng**。

> 附：`custom_addons/edu_portal/data/` 目前只有 `timetable_params.xml`，且 **edu_portal 全模块没有任何 ir.cron**（grep 确认）→ 本设计会产生 edu_portal 的第一个 cron。

### 0.2 cron XML 写法（抄 `edu_telegram/data/cron.xml`，Odoo 19 形态）

```xml
<record id="ir_cron_edu_expire_downloads" model="ir.cron">
    <field name="name">edu_portal: 资料过期自动下架（每小时）</field>
    <field name="model_id" ref="model_edu_download_file"/>
    <field name="state">code</field>
    <field name="code">model.cron_expire_downloads()</field>
    <field name="interval_number">1</field>
    <field name="interval_type">hours</field>
    <field name="active" eval="True"/>
</record>
```

Odoo 17+ 的 `ir.cron` 自带 `model_id/state/code`，**不再需要** `ir.actions.server` 中间层（旧写法会静默不执行）。

### 0.3 可见范围口径 —— 函数名已核实，全部复用

`controllers/downloads.py`：`_identity_fields()`（返回 `None`=教务处/管理员恒可见；否则命中组字段列表）→ `_visibility_domain()`（拼 OR domain）→ `_can_download(rec)`（逐条判定）→ `_visibility_label(f)`（中文标签）。
**t8 复用这四个函数，不另造可见性系统。**

### 0.4 已有回执先例 —— 照抄形状

`models/notice.py` 的 `EduNoticeRead`：`user_id` + `notice_id` + `read_date`，`UNIQUE(user_id, notice_id)`，`mark_read_for(user)` 幂等（先 search 后 create，savepoint 兜并发）。
t8 的确认表照此形状，只把父对象换成 `edu.download.file`。

### 0.5 导出 CSV 已有公共工具

`controllers/main.py:27 csv_download(filename, header, rows)`（utf-8-sig 防 Excel 乱码 + RFC5987 中文文件名）→ 未读名单导出**直接复用**，不新写导出。

---

## 1. 复用 vs 自研边界

| # | 能力 | 决策 | 载体 | 回引 |
|---|---|---|---|---|
| A1 | 资料存储/可见范围/审计 | **复用（零改动）** | `edu.download.file` / `EduDownloadLog` / `_visibility_domain()` | 仓内 downloads v2.1；调研 §3「Show course to」 |
| A2 | 回执表形状 | **抄形状，自成模型** | 新 `edu.download.ack`（仿 `EduNoticeRead`） | 调研 §4.4 钉钉「已读未读一目了然」/飞书「点击我已知悉」 |
| A3 | 未读名单导出 | **复用** | `csv_download()` | 仓内既有 |
| A4 | 催办（未读加推） | **复用** | `EduMessage` + 可选 Telegram outbox（运行时 env 查找，不新增 depends） | 调研 §4.4 飞书「未读加推」 |
| A5 | 过期下架 | **自研（调研指名做法）** | `ir.cron` 改发布状态 | 调研 §4.4 负面结论：「钉盘/企微微盘/飞书云文档均无分享有效期/过期自动下架 → 需自建（ir.cron 改发布状态）」 |
| A6 | 课程/行政分区 | **复用 + 1 字段** | 复用 t6 的 `subject_id` | 调研 §3 |

**明确不做**：不新建第二套资料系统；不新建第二套可见范围；不引入外部有效期/水印服务。

---

## 2. 数据模型

### 2.1 新增模型 `edu.download.ack`（需确认已读回执）

| 字段 | 类型 | 说明 |
|---|---|---|
| `file_id` | M2o `edu.download.file`（required, ondelete=cascade, index） | 被确认的资料 |
| `user_id` | M2o `res.users`（required, ondelete=cascade, index） | 确认人 |
| `ack_date` | Datetime（default=now） | 确认时间 |
| `ack_mode` | Char（related 展示用，可省） | 记录确认时的方式（click/interstitial） |

约束（Odoo 19 新 API，旧 `_sql_constraints` 会被静默忽略）：
```python
_ack_user_file_uniq = models.Constraint(
    'UNIQUE (user_id, file_id)', '同一用户对同一资料只能确认一次。')
```

ACL：`security/ir.model.access.csv` 加一条 portal 读 + 系统读写（**不建自定义组**，铁律 3）。

### 2.2 `edu.download.file` 新增字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `subject_id` | M2o `op.subject`（可空，index） | **t6 定义**，本设计复用为分区依据 |
| `ack_mode` | Selection `none/soft/hard`（default `none`） | `none`=无回执；`soft`=下载不受限但记录回执；`hard`=下载前必须点「我已知悉」 |
| `publish_from` | Datetime（可空） | 定时上架时间；**消费后清空**（见 §4.2） |
| `expire_at` | Datetime（可空） | 到期时间 |
| `expired_at` | Datetime（readonly） | 实际被自动下架的时间（审计留痕） |

> 复用现有 `active` 作为唯一上下架闸门（Odoo 约定，既有查询/ACL 都依赖它），**不新增状态字段**避免双真源。

---

## 3. 需确认已读（回执）

### 3.1 目标人群口径 `_target_users(rec)`

| 情形 | 人群 |
|---|---|
| `subject_id` 有值（课程资料） | 该科目的在读学生（`op.student.course.subject_ids` 含该科目）∪ 该科目的授课教师 |
| `subject_id` 为空（行政表格） | 按四勾选并集：`visible_student`→全部 `op.student.user_id`；`visible_parent`→全部 `op.parent.user_id`；`visible_teacher`→`group_op_faculty` 成员；`visible_registrar`→`group_op_back_office_admin` 成员 |

**口径决策**：教务处/管理员**不计入**应确认人群（他们是发布者，恒可见）。若计入，未读名单会永远挂着管理员。此决策无外部先例可抄（国内范式只讲「已读未读一目了然」，未定义发布者是否计入）→ **本仓自定，理由如上**。

### 3.2 未读名单

```
unacked(rec) = _target_users(rec) − {a.user_id for a in edu.download.ack[file_id=rec]}
```

### 3.3 导出

`csv_download('未读名单-<资料名>.csv', ['姓名','邮箱','身份','可见范围'], rows)`，复用 §0.5。

### 3.4 催办（未读加推，抄飞书）

`/downloads/remind/<id>/save`（POST+csrf）→ 对未读用户发 `EduMessage`；若已绑定 Telegram 则顺带入 outbox（运行时 env 查找 `edu.telegram.*`，**不新增 manifest depends**，对齐 code-map §4 的跨模块运行时查找约定）。

### 3.5 三档行为

| `ack_mode` | 下载页行为 | 后台 |
|---|---|---|
| `none`（默认） | 与现状完全一致 | 不显示回执列 |
| `soft` | 顶部显示「我已知悉」按钮，**不阻断下载** | 显示已读/未读计数 → 未读名单 |
| `hard` | 未确认时先渲染确认页，确认后跳回下载 | 同上 |

> 回引 §4.4：钉钉是「必达 + 已读未读一目了然 + 手写签字确认」（偏 `hard`），飞书是「点击我已知悉」（偏 `soft`）。两档都保留，由教务按资料性质选。

---

## 4. 过期自动下架

### 4.1 下架（`cron_expire_downloads`，每小时）

```python
now = fields.Datetime.now()
due = self.search([('expire_at', '!=', False), ('expire_at', '<=', now),
                   ('active', '=', True)])
due.write({'active': False, 'expired_at': now})
```
幂等：`active=False` 的行不再命中；`expired_at` 一旦写入不再变。

**已核实：下架即刻生效，无需改动下载路由** —— `controllers/downloads.py:396` 的守卫为
`if not rec.exists() or not rec.active or not rec.file: return request.not_found()`，
即 `active=False` 的资料自动 404。这是本设计与既有代码的一次天然对齐。

### 4.2 定时上架（同一 cron，一次性消费）

```python
ready = self.search([('publish_from', '!=', False), ('publish_from', '<=', now),
                     ('active', '=', False), ('expired_at', '=', False)])
ready.write({'active': True, 'publish_from': False})   # 消费即清空
```

**为什么清空 `publish_from`**：否则「手动停用过的、且当初设过定时发布」的文件会被 cron 反复复活。清空后该字段是**一次性触发器**，语义可预测；`expired_at=False` 条件保证不会复活已过期资料。
（此坑无外部先例可抄——调研只给了「ir.cron 改发布状态」一句，未涉及一次性语义 → **本仓自定**，理由如上。）

### 4.3 XML 落点

`views/downloads_views.xml`（**已注册**，见 §0.1），写法抄 §0.2。

---

### 4.4 `hard` 档拦截点（已核实源码 `controllers/downloads.py:393-425`）

`/downloads/file/<int:fid>` 实际有**两条取数分支**：

| 分支 | 行 | 行为 |
|---|---|---|
| 预览 `?inline=1`（pdf/图片白名单） | 405-417 | 直接 `make_response(data)` 吐出文件字节；**不计下载次数、不写审计** |
| 正常下载 | 418-425 | 先 `download_count + 1`、写 `edu.download.log`，再返回字节 |

**方案**：
- `soft`：两分支都不拦，只在门户加「我已知悉」按钮。
- `hard`：拦截**必须插在函数最前**（第 395-400 行守卫旁），且**必须同时覆盖 `inline=1`**——否则预览路径会原样吐出同一份字节，确认形同虚设。
  - 代价：`hard` 资料在确认前无法在线预览（可接受，确认是一次性动作）。
  - 提示：确认动作应与 `download_count` 自增、审计日志**在同一事务**内落库，避免「记了回执但下载失败」的错位。
- **反面**：只改门户模板按钮、不在路由层拦 → 直接敲 URL 即可绕过，**不达标**。

---

## 5. 课程资料 / 行政表格分区

- 判据：`subject_id` 非空 = **课程资料**；为空 = **行政表格**。
- `/my/study`（t6 新建）：科目内嵌该科目的课程资料，**复用 `_visibility_domain()`** 过滤。
- `/downloads`（既有）：默认展示行政表格，顶部提供「课程资料」页签跳 `/my/study`。
- 两侧互链，**不复制数据、不改可见范围口径**（回引 §3「Show course to / Course Attendees」）。

---

## 6. 路由清单

| 路由 | 方法 | 角色 | 说明 |
|---|---|---|---|
| `/downloads/ack/<int:file_id>/save` | POST | 登录用户 | 记录回执（csrf；兄弟路由 `/save` 约定） |
| `/downloads/ack/<int:file_id>` | GET | 登录用户 | `hard` 档的确认页（下载前置） |
| `/downloads/unacked/<int:file_id>` | GET | 教务/管理员 | 未读名单页（`privileged_staff()` 门禁） |
| `/downloads/unacked/<int:file_id>/export` | GET | 教务/管理员 | 未读名单 CSV（复用 `csv_download`） |
| `/downloads/remind/<int:file_id>/save` | POST | 教务/管理员 | 催办未读（`privileged_staff()`） |

写操作一律 POST + csrf + 兄弟路由 `/xxx/save`（`docs/dev-workflow.md`）；门禁用 `privileged_staff()`（铁律 3），**不建自定义组**。

---

## 7. 验收标准

| # | 验收项 | 判定手段 |
|---|---|---|
| B1 | `soft` 档：下载不受限，回执落库且幂等（两次确认仍 1 行） | 同一用户确认 2 次 → `edu.download.ack` 计数=1 |
| B2 | `hard` 档：未确认时**下载与预览都被拦截**（预览不得成为绕过通道） | 未确认用户分别直取 `/downloads/file/<id>` 与 `/downloads/file/<id>?inline=1` 复现（见 §4.4） |
| B3 | 未读名单 = 目标人群 − 已确认，且**不含**教务/管理员 | 手工构造 4 身份对比 |
| B4 | 未读名单 CSV 可导出且中文不乱码 | 下载后 Excel 打开 |
| B5 | 到期资料被 cron 下架：`active=False` 且 `expired_at` 有值；重跑不重复写 | 连跑 2 次 cron 比对 `expired_at` |
| B6 | 定时上架一次性：跑 1 次后 `publish_from` 清空；**手动停用的文件不被复活** | 建「手动停用 + 有 publish_from」样本，跑 cron 断言仍停用 |
| B7 | 分区正确：课程资料只在本科目出现，行政表格不在课程页出现 | 学生视角遍历 |
| B8 | 不泄露：分区后可见范围口径不变 | 学生/教师/家长/教务四身份矩阵 |
| B9 | 用户可见英文 = 0 | `python3 scripts/check_english.py`（新路由须登记其路由表） |
| B10 | 本地升级 EXIT=0 无 Traceback | `bash scripts/safe_upgrade.sh edu_portal` |

---

## 8. 未验证 / 风险

1. **回执的并发**：照抄 `EduNoticeRead.mark_read_for` 的 search→create + savepoint 兜底；本设计的 `UNIQUE(user_id, file_id)` 与之同构，但**未实测并发**。
2. ~~`hard` 档的下载拦截点未确认~~ → **已核实并定位（见 §4.4）**。核实中发现该路由有第二条取数分支（`inline=1` 预览），**只拦下载分支会被预览绕过**；处理方案已写入 §4.4。
3. **Telegram 催办**为运行时 env 查找，未验证 `edu_telegram` 未安装时是否完全静默（需 try/except 包住）。
4. **行政表格的目标人群规模**：本机仅 4 学生，未做规模验证；若生产放量需加索引（`ack(file_id)` 已有）。
5. 调研 §4.4 的国内范式来自钉钉页面描述与飞书帮助中心，**未取得 API 级字段证据**（原调研已声明）。

---

## 9. t8 授权范围（队长 2026-09-12 书面授权）

以下四个文件**全部归 study-eng，可改**（书面授权，不再需要逐次确认）：

| 文件 | 本设计中的用途 |
|---|---|
| `controllers/downloads.py` | ack 路由、未读名单页、催办、`hard` 档拦截点（§4.4） |
| `models/downloads.py` | `edu.download.ack` 模型、新增字段、`cron_expire_downloads()` |
| `views/downloads_views.xml` | ir.cron 记录（**已注册**，见 §0.1）、后台视图/菜单 |
| `views/downloads_portal.xml` | 门户侧 ack 按钮、未读名单页、分区页签 |

> **与 t6 的交界**：`subject_id` 字段由 **t6** 引入（`models/downloads.py` 同属两任务范围），t8 只**消费**、不重复定义；t8 deps=[t6]，实现时该字段必须已存在。
