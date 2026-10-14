# 冒烟测试 P3：财务总账 + 报销（第三期 · ledger）

- 目标：http://localhost:8069（Odoo 19, docker edu19-clone, db edu19）
- 账号：stu@local / faculty@local / backoffice@local / parent@local
- 方法：HTTP 会话（requests）+ docker psql 校验 + 按标记清理
- 结果：**26 项全 PASS**（2026-09-10 本地真机；含 repair-round-2 六项修复回归
  与 R7 坏图健壮性回归）
- 造数：均带【冒烟测试可删】标记，跑毕自动清理（含通知/审计/附件残留，
  仅存留 2 条既有演示账单）

| 编号 | 项目 | 预期 | 实际 | 结果 |
|---|---|---|---|---|
| L13 | 旧统筹费账单兼容 | 既有应收账单在 /my/fees 原样展示 | 200，「2026 春季统筹费」可见 | PASS |
| L1 | /my/fees 同页 统筹费+我的报销 | 两段标题 | 200，统筹费账单/我的报销 均渲染 | PASS |
| L2a | /my/reimburse/apply 表单 | 分类/金额/收据上传 | 200 表单完整 | PASS |
| L2b | 学生提交报销 | 303 → reimburse_submitted&ref=REBxxxxxx | 303 REB000009 | PASS |
| L2c | 报销单号入库 | edu_fee_bill.reimburse_ref==REB%06d | 一致 | PASS |
| L3 | 防重 | 同人/同分类/同金额在途 → box=dup | box=dup 拦截 | PASS |
| L4 | 学生列表显示报销单 | 含单号且状态=申请中 | 是 | PASS |
| L5 | /ledger 总台账 | 应收/应付双向 + 统计 | 200 双向渲染 | PASS |
| L6 | /ledger 方向筛选 | direction=payable 过滤 | 200 | PASS |
| L7 | 报销审批台 | 200 + 受控收据预览链接 | /my/reimburse/receipt/* 链接在 | PASS |
| L8 | 审批同意（可改金额） | approved + approved_amount=80.00 | 库 approved\|80 | PASS |
| L9 | 付款登记平账 | payment+1 & state=paid/paid | Δpayment=1, paid\|paid | PASS |
| L10 | 驳回（填原因） | refused + reject_reason 学生可见 | refused\|发票抬头不符 | PASS |
| L11 | 驳回缺原因 | box=need_reason 拦截 | 是 | PASS |
| L12 | 权限负例 | 学生/教师/家长访问 /ledger* 全 303→/my/home | 9/9 拦截 | PASS |
| L14a | 通知 reimburse_result | 审批/付款/驳回均生成站内信 | 2+ 条 | PASS |
| L14b | 审计 edu.audit.log | 记账/报销申请/审批/付款四类埋点 | 单号相关 5 条 | PASS |
| R1 | 组守卫 | 学生/教师直连 RPC approve/refuse/pay/create应收 全 ERR | 8/8 拦截 | PASS |
| R1b | 教务可记账 | backoffice create 应收 OK | OK | PASS |
| R2 | 受控收据预览 | public=false；本人/教务200；其他人404；/web/image≠真实 | 教师/家长404，字节一致 | PASS |
| R7 | 坏图拦截（防 HTTP 500） | 损坏 PNG（非ASCII tEXt）→ 303 box=bad_image；不落库 | Δatt=0 Δbill=0 提示呈现 | PASS |
| R7b | 正常图片路径未受影响 | 合法 PNG 仍可提交 | 303 reimburse_submitted | PASS |
| R3 | 方向化统计 | 应付待付随 approved +300；学生待缴(应收)不变 | 0→300 / 12200→12200 | PASS |
| R6 | 非request不发号 | payable(无state) 无 reimburse_ref | NULL | PASS |
| Z1 | 清理冒烟数据 | 按标记 DELETE | DELETE 7 | PASS |
| Z2 | 清理残留通知/审计/附件 | 按已删单号清理 REB 残留 | 通知/审计/附件全清 | PASS |

补充实测（脚本之外）：
- 记总账 @学生/@班级/@老师 三种对象批量落库（box=saved&count=N）；
- 教师可发起报销，教务 @老师记应付（partner 落库）；
- /my/notify 通知偏好页已含「报销进展」事件开关；
- 通知金额按状态取 approved_amount（申请 200、同意 150 → 通知显示 150）；
- 序列并发 12 线程取号 12 唯一无重复（next_by_code 原子性）；
- 记录规则分角色实测：教师仅见本人相关单（他人单不可见）、教务/管理员全量、
  学生直读 edu.fee.bill = AccessError（deny-by-default）；门户页面经 sudo 正常；
- 后台财务菜单已限 教务/管理员（教师/学生可见财务菜单数 = 0）；
- ACL：base.group_user 仅读、group_op_back_office_admin 全权（记账/审批/付款）；
- 既有入口回归：/my/home、/my/fees、/my/reimburse/apply、/my/time_off、/my/notify、
  /subject/registration 四角色 24/24 全 200 无 Traceback；
- 坏图健壮性（R7）：损坏 PNG（合法签名 + 非 ASCII tEXt chunk）上传 → 303
  box=bad_image 中文提示「图片文件已损坏或格式不受支持，请重新选择」，不 500、
  不落库（Δ附件=0 Δ账单=0）；正常 PNG/截断 PNG/垃圾字节路径与修复前一致；
- check_english 中文扫描仅剩 /downloads 2 处既有 pdf 命中（非本期引入）。

口径备注（repair-round-2 复核所得，供后续维护者）：
- 规则域里「门户发起人」用 `created_by_partner.user_ids in [user.id]`；
  「教师档案/受理人」必须用 `faculty_id.partner_id.user_id = user.id`
  与 `partner_id.user_id = user.id`——`res.partner.user_id` 是可存化反向解析，
  教师档案的 partner.user_ids 恒为空，混用会静默不匹配（教师读到自己 0 条）。
