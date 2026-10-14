# 登录页「使用密码 / Passkey」按钮的移除 —— 卸载 auth_passkey（2026-09-25）

> **结论（先看这条）**：按钮不是"隐藏"掉的，而是**把产生它的两个模块卸载掉**：
> `auth_passkey` + `auth_passkey_portal`。本地克隆实测**卸载会粘住**（4 次升级都不复活），
> 因此**本仓不需要、也不允许**再加一条隐藏它的视图 xpath —— 见 §4 的反例（会导致升级硬失败）。

## 1. 问题是什么

Odoo 19 核心 `auth_passkey`（`auto_install: True`）在登录表单下方注入一枚按钮：
`auth_passkey/views/auth_passkey_login_templates.xml:9-16` 把 `passkey_btn` 追加进
`web.login_oauth` 的 `auth_btns` 列表。图标 `fa-qrcode`，点击走
`auth_passkey/static/src/interactions/passkey_login.js` → `POST /auth/passkey/start-auth` → WebAuthn。

两处让它在本站是**纯摩擦**：

1. **zh_CN 错译**：Odoo 官方中文把 `Use a Passkey` 译成「**使用密码**」。中文读者会当成
   "用密码登录"，点下去却拿到 WebAuthn 报错；而它正上方本来就有一个能用的密码输入框。
2. **永远不可能成功**：生产 `auth_passkey_key` **零行**（无人注册过通行密钥），
   该按钮对本校任何人都只会失败。属 `batch3.xml:1264` 同类「看着能用、其实没用」的死控件。

## 2. 本地克隆实测：卸载粘得住

库 `edu19`（`edu19-clone-*` 容器），用 `ir.module.module.button_immediate_uninstall` 按
**先依赖方**顺序卸载 `auth_passkey_portal` → `auth_passkey`，然后反复跑标准升级入口：

| # | 升级命令 | 结果 | auth_passkey / auth_passkey_portal |
|---|---|---|---|
| 0 | 卸载前 | — | `installed` / `installed` |
| 1 | `bash scripts/safe_upgrade.sh edu_portal` | EXIT=0 | `uninstalled` / `uninstalled` |
| 2 | `bash scripts/safe_upgrade.sh web`（升它的依赖） | EXIT=0 | `uninstalled` / `uninstalled` |
| 3 | `bash scripts/safe_upgrade.sh edu_life,edu_eval,edu_schedule,edu_apply,edu_portal,edu_brand,edu_tg_bind,edu_assess`（= deploy_myedu.sh 的默认模块表） | EXIT=0 | `uninstalled` / `uninstalled` |
| 4 | `bash scripts/safe_upgrade.sh edu_portal`（最后一次，工作区干净） | EXIT=0 | `uninstalled` / `uninstalled` |

四次升级日志里 `Loading module auth_passkey` 出现 **0 次**；`information_schema`
里 `auth_passkey%` 表 **0 张**（`auth_passkey_key` 连同 0 行数据被正常删除）。
每次升级末尾 `safe_upgrade.sh` 都会 `docker compose restart web`，即"重启也不复活"。

**为什么粘得住（机制，别只信现象）**：Odoo 的自动安装展开在
`ir.module.module.button_install`，判据 `must_install()`（`ir_module.py:411-434`）：

```python
auto_domain = [('state','=','uninstalled'), ('auto_install','=',True)]
def must_install(module):
    states = {dep.state for dep in module.dependencies_id if dep.auto_install_required}
    return states <= install_states and 'to install' in states and (...)
```

即：**只有当它某个 `auto_install_required` 依赖正处于 `to install` 时**才会被拉回来。
`auth_passkey` 的这类依赖是 `base_setup` / `web`，二者早已 `installed`，
正常的 `-u` 上游模块不会把它们变成 `to install` ⇒ 不会复活。

## 3. 生产执行

**顺序不能反**（先依赖方）：

1. 后台 → 应用 → 搜索 `Passkeys` → 卸载 **Passkeys Portal**（`auth_passkey_portal`），
   再卸载 **Passkeys**（`auth_passkey`）。UI 会连带处理依赖，无需手工排序。
   无 UI 时等价的无头做法：对 `auth_passkey_portal`、`auth_passkey` 依次调
   `ir.module.module.button_immediate_uninstall`（XML-RPC / `odoo shell` 均可）。
2. `docker compose restart web`（清进程内缓存；`button_immediate_uninstall` 已重载注册表，重启是保险）。
3. 验收：
   ```bash
   docker exec edu19-clone-db-1 psql -U odoo -d edu19 -Atc \
     "select name||'='||state from ir_module_module where name like 'auth_passkey%';"
   # 期望两行都是 uninstalled
   ```
   并确认 `/login` 不再出现「使用密码」与 `- 或 -` 分隔行。

**本仓无需任何代码改动** —— 这就是本文件存在的全部理由：留档，防止后人"顺手把按钮加回来"。

## 4. 反例：为什么**不要**用视图 xpath 隐藏它（已实测炸升级）

第一版实现是"照本仓登录页惯例加一条 xpath"：
`inherit_id="web.login_oauth"` + `//t[@t-set='auth_btns'][@t-value='auth_btns + passkey_btn']` `position="replace"`。
在模块**已装**时它工作正常（按钮消失、无 JS 报错）；但一旦模块被卸载，这条 xpath 就**找不到父节点**：

| 场景 | 后果 |
|---|---|
| 卸载后访问 `/login` | `QWebError: 上级视图内找不到元素… (view: edu_portal.edu_login_no_passkey)` → **HTTP 500** |
| 卸载后跑 `bash scripts/safe_upgrade.sh edu_portal` | `odoo.tools.convert.ParseError` → **退出码 255，注册表拒绝加载** |

⇒ 这两种做法**互斥**。既然卸载是最终方案，那条 xpath 必须不存在。

## 5. 残余风险：什么情况下按钮会自己回来

- **建新库**（`-d <新库> -i base`）：`auto_install` 会重新装上 —— 本项目不涉及。
- **手工**在后台重新 Install `Passkeys` / 安装依赖它的模块（如 `auth_timeout`，目前 `uninstalled`）。
- **让 `base_setup`/`web` 进入 `to install` 的命令行**（如 `-i base_setup`）。
- 全局开关 `--skip-auto-install` 可关掉"自动安装"整条链路，但本站不需要（卸载已经粘住），
  且它会连累其他 `auto_install` 模块，**不建议用**。

## 6. 还原（要恢复按钮时）

```bash
bash scripts/safe_upgrade.sh -i auth_passkey,auth_passkey_portal   # 本地
# 生产：后台应用列表里重新 Install Passkeys（会自动带上 Passkeys Portal），再 restart web
```

## 7. 本地证据留存（gitignore 的 `shots/local/`）

- `login_probe_before.png/.json` —— 卸载前：按钮在，`passkey_login_link` 计数 1，无 JS 报错。
- `login_e2e_1_filled.png` / `login_e2e_2_after_login.png` —— 卸载后邮箱+密码端到端登录落 `/my/home`。
- `login_probe_uninstalled_final.png/.json` —— 卸载后：`passkey_login_link` 0、
  `fa-qrcode` 0、`o_login_auth` 0、HTML 里 `passkey`/`使用密码` 0 次；其余登录页控件一个不少。
- 升级日志 `/tmp/edu_upg_stick*.log`、`/tmp/edu_upg_final_clean.log`（临时目录，非权威）。
