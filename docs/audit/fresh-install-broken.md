# ✅ **全新库装不上 → 已修好**（2026-10-04 第 65 轮发现，第 66 轮修复并复验）

> **现状（2026-10-04 第 66 轮复验）**：同一条命令现在**装得完** ——
> `88 个模块 installed`、`607 张表`、零 ParseError，
> `edu_life / edu_brand / edu_portal / edu_schedule / calendar / digest` 全部 `installed`。
> 修了三处「用了别的模块的模型/字段却没声明」（`digest` / `calendar` / 那 38 条脆弱的 digest `<function>`）
> 与一处**语言时序**（zh_CN 未启用时不能写翻译字段）。详见下文的「已修」各节。

> 本项目**已经丢过一次生产库**（force majeure，`203.0.113.11` 那次）。
> 所以「在一台干净机器上能不能从零装起来」是**部署的硬前置**，而它**从来没被验过**。
> 本轮第一次验：**装不上。**

## 复现（三行，可原样重跑）

```
docker exec edu19-clone-db-1 psql -U odoo -d postgres -c "create database edu19_fresh owner odoo;"
docker exec -i edu19-clone-web-1 sh -c "cd /mnt && odoo -d edu19_fresh --db_host=db --db_user=odoo \
  --db_password=odoo --no-http --without-demo=all -i edu_life --stop-after-init --log-level=warn"
```

## 现象

```
ParseError: while parsing .../edu_brand/data_brand/brand_debrand_data.xml:65, somewhere inside
<function model="digest.digest" name="write" context="{'lang': 'zh_CN'}"
          eval="[[ref('digest.digest_digest_default')], {'name': '系统状态摘要'}]"/>
```

⇒ `edu_brand` 的 data 加载失败 ⇒ **整个安装中断**（`edu_life`/`edu_brand` 停在 `uninstalled`）。

## 两个成因（都在那份数据文件的 `<function>` 写法里）

### ① 引用横跨 **6 个模块**，而 `depends` 只声明了 3 个

该文件里的 `<function ... eval="[[ref(...)]]">` 逐条提取后，xmlid 来自：

```
digest · account · base_automation · hr · im_livechat · website      ← 6 个
edu_brand 的 depends 原文：['website', 'theme_web_openeducat', 'auth_totp_portal']   ← 3 个
```

⇒ 新库上**没装的模块**，它的 xmlid 解析不到 ⇒ `ref()` 抛异常 ⇒ 安装中断。
克隆库上看不出来，只因为生产早就装过那些模块。

**已修一部分**：`digest` 已补进 `depends`（本轮已提交）。**其余 4 个（account / base_automation / hr / im_livechat）尚未处理** ——
它们只被用来清空 digest 小贴士文案（`digest.tip`），属于**可有可无**的品牌清理，
不该为了它把 4 个业务模块拖成硬依赖。

### ② `context="{'lang': 'zh_CN'}"` 写翻译字段，只接受 **active 语言**

同文件上方**原有注释**已经为 `zh_TW` 记过这条（2026-10-01 重建生产事故）：
「Odoo 19 写翻译字段时 env.lang 只接受 active 语言」。**新库里 `zh_CN` 也可能尚未启用** ⇒ 同样抛异常。

## 建议的修法（已设计好，未落地 —— 本轮时间不够，**没有半成品留在仓里**）

把这 38 条 `<function>`（去重后 **19** 组「(xmlid, 模型, 字段, 目标值)」）收敛成**一个容错 ORM 方法**，
与 `edu_portal` 既有的 `edu_apply_menu_label_renames` / `_edu_apply_menu_retirements` 同一套纪律：

```python
rec = env.ref(xmlid, raise_if_not_found=False)      # 缺记录 ⇒ 跳过（记日志）
if not rec: skip += 1; continue
for code in env['res.lang'].search([]).mapped('code'):   # 只写**已启用**语言
    rec.with_context(lang=code).write({field: value})      # 任何一条失败都不影响安装
```

> 本轮我曾试着用脚本批量替换那份 XML，**改坏了两次**（行级切片留下孤儿标签、regex 转义出错）——
> 均已 `git checkout --` 还原，**仓里现在是干净的**（`git status` 只剩 `__manifest__.py` 与 `check_all.sh`）。
> 下一轮要动它，请**用编辑器的精确替换**逐条来，别再用行号切片。

## 为什么这条比一般缺陷要紧

· 它是**部署阻塞级**的：`deploy_myedu.sh` 在新服务器上会卡在 `edu_brand`；
· 它**只在全新库上出现**，本机克隆库永远看不出来 —— 这类问题最容易拖到「换机器那天」才爆；
· 而且本项目**已经丢过一次生产库** ⇒ 下一次重建是**必然事件**，不是假设。