# 资料下载中心 — 设计说明
> **状态**：`归档` ｜ **主题**：`资料下载` ｜ **取代**：`downloads-v2-design.md` ｜ **核对**：`2026-10-06`
> ⚠️ 本文原写「已批准设计，等待实施」，实际已于 `f915056` 交付（2026-09-26 核对发现）。正文未改动。
> ⚠️ 本文已被 [`downloads-v2-design.md`](downloads-v2-design.md) 取代，请优先阅读后者。

日期：2026-08-25
状态：已批准设计，等待实施
模块：custom_addons/edu_portal

## 1. 目标(What/Why)

为永约学坊提供「行政通用资料下载中心」：管理员与教务人员上传通用表格模板
（请假表、阅读报告格式、常用表格等），学生登录后在统一页按分类下载。

背景：现有 openeducat 的 op.media 定位是图书/课程教材（关联科目课程、按
选课过滤、读权限只开放图书管理员与 library_user 读取），与本需求（全校通用
行政模板、教务上传）定位不同。不复用 op.media，另建轻量模型。

## 2. 角色与权限矩阵

| 动作 | 管理员 | 教务人员 | 教师 | 学生 | 匿名 |
|---|---|---|---|---|---|
| 上传/分类维护 | ✅ | ✅ | ❌ | ❌ | ❌ |
| 下载 | ✅ | ✅ | ✅ | ✅（核心） | ❌ |
| 管理菜单可见 | ✅ | ✅ | ❌ | ❌ | ❌ |

- 管理组：openeducat_core.group_op_back_office_admin（管理员天然在内）
- 下载：所有 auth='user' 的登录用户；anonymous 一律 303 回登录

## 3. 数据模型（新加于 edu_portal）

### edu.download.category（分类）
- name: Char required
- active: Boolean default True
- 排序：name；门户只展示「存在 active 文件」的分类

### edu.download.file（资料）
- name: Char required（标题）
- category_id: Many2one edu.download.category，required=True
- description: Text（可选说明）
- file: Binary required（附件；PDF/Word/Excel 等）
- file_name: Char readonly（附件原始文件名，展示与下载命名用）
- active: Boolean default True（停用隐藏，不真删）
- download_count: Integer default 0（登录下载 +1）
- 约束：name 唯一非必需；无 _sql_constraints（Odoo19 用 models.Constraint）

## 4. 权限（ir.model.access.csv）
- 两张表 × 两组：back_office_admin 1,1,1,1；group_user(base) 1,0,0,0
- 即学生/教师只读

## 5. 页面与路由

### 门户侧（学生视角）
- GET /downloads（auth='user', website=True）：下载中心首页
  - 按分类分组；每组列出：标题、说明、文件大小(human)、下载次数
  - 空状态提示「暂无资料」
- GET /downloads/file/<int:fid>（auth='user'）：
  - 记录不存在/未 active → 404/303
  - download_count += 1
  - 以附件原始文件名流式返回（Content-Disposition: attachment）

### 后台管理（教务视角）
- edu.download.category：list + form（name/active）
- edu.download.file：list（标题/分类/大小/次数/active）+ form（标题+分类+说明+附件）
- 菜单：顶级「资料下载」web_icon 瓦片，groups=back_office_admin，
  子项「上传资料」「分类管理」
- views：downloads_views.xml（后台）+ downloads_portal.xml（门户模板）

## 6. 入口接线

- 仪表盘卡片：batch2.py _YONGYUE_CARDS 追加
  ('downloads', '资料下载', 'fa-download', '请假表、报告格式等通用表格下载')
  + scripts/gen_icons.py 加 P+'downloads': (色, G('inbox' 或新图形))
  并重新生成 icons/downloads.svg
- 帮助中心：教师版/学生版各补一节「资料下载」

## 7. 安全细节

- 下载路由只接受记录 id（<int:fid>），无用户路径输入 → 无目录穿越面
- 附件经 ir.attachment（Odoo 二进制字段原生存储），不走自定义文件读写
- file 字段 add_attachment 由 ORM 管理；下载前 .sudo() 读取（学生无写权但读
  权有，通常不用 sudo；教师群 read-only 已够；保险起见 sudo 无风险）
- 下载计数：同请求内 write download_count +=1 后返回流；失败不计数

## 8. 验收标准（可观测）

1. 教务账号登录后台可见「资料下载」菜单，可新建分类、上传资料（含文件名回显）
2. 学生账号登录访问 /downloads 看到按分类分组列表与各文件大小/次数
3. 学生点击某文件 → 浏览器下载成功 + 列表下载次数 +1
4. 匿名访问 /downloads → 303 回登录页
5. 停用(active=False)的文件不出现在列表、直接访问 id 也不返回内容
6. 教师账号看不到后台管理菜单，也不能经 ORM 创建（ACL 0,0,0,0 组外）
7. 本地 -u edu_portal 升级 EXIT=0 无 Traceback；冒烟全过

## 9. 不做（Non-goals）

- 教师上传权限（用户明确不开）
- 家长端下载入口（后续可加）
- 搜索/分页/排序控件（分类 + 标题足够）
- 版本历史、到期自动下线、水印、格式转换
- 课程/班级关联的定向材料（与 op.media 定位区分，互不干扰）
