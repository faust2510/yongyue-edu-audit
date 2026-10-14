# 发现 F2：`/my/checkin/board` 500（t5 落库后引入的 NameError）

- 发现人：verifier（T7 独立验证）
- 日期：2026-09-17
- 严重度：**high / blocker**（教师与教务的看板页直接 500）
- 影响：队长裁定②明确要求「/my/checkin/board 仍须 200」；当前不满足

## 1. 实测（逐角色，只 GET）

| 账号 | /my/checkin/board | 备注 |
|---|---|---|
| faculty@local | **500** | 收口前为 200（见冻结基线） |
| backoffice@local | **500** | 教务同样不可用 |
| admin | **500** | 超管同样不可用 |
| stu@local | 303 → /my/checkins | 学生侧未报错（与收口前一致） |

复现命令：

```bash
python3 tests/audit/verify_consolidation.py --phase after
# 判据：rulings.checkin_board_200.ok 应为 true，当前 false
```

## 2. 服务端根因（docker compose logs web）

```
ERROR edu19 odoo.http: Exception during request handling.
Traceback (most recent call last):
  File "/mnt/custom-addons/edu_portal/controllers/welfare.py", line 100, in checkin_board
NameError: name 'datetime' is not defined. Did you forget to import 'datetime'
"GET /my/checkin/board HTTP/1.1" 500
```

即 `edu_portal/controllers/welfare.py` 的 `checkin_board` 用了 `datetime`
但模块顶部没有 `import datetime`。**属实现缺陷，不是环境问题**（同一进程其它路由正常）。

## 3. 与收口前对照（证明是新回归）

冻结基线 `tests/audit/out/before_result.json`（11:35 采集，收口前）中：
`faculty /my/checkin/board = 200`。
⇒ 收口后才变 500，方向与「收口不掉功能」相反。

## 4. 修复方向（交队长派 repair；verifier 不改实现）

- 最小修复：在 `edu_portal/controllers/welfare.py` 顶部补 `import datetime`
  （或把 `datetime.*` 用法改为已导入的等价对象），改动 1 行、可独立 commit 回滚。
- 修复后请跑：`python3 tests/audit/verify_consolidation.py --phase after`
  期望 `checkin_board_200.ok == true`，且 faculty/backoffice/admin 三账号均 200。

## 5. 备注

- 该文件正在被 t5 修改，故本条以「紧急」上报，避免与 t5 的后续改动撞车。
- 本发现只读取 GET 与容器日志，未改任何实现文件。
