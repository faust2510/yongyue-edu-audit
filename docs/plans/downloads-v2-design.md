# 资料下载中心 v2 — 管理端优先扩展（设计说明）
> **状态**：`已上线` ｜ **主题**：`资料下载 v2 管理台` ｜ **取代**：`—` ｜ **核对**：`2026-09-26`

日期：2026-08-29
状态：已交付（本文档作存档）
模块：custom_addons/edu_portal
前序：downloads-design.md（v1，2026-08-25，按分类浏览 + 下载计数）

## 1. 背景与目标(What/Why)

v1 只有「按分类浏览 + 下载计数」，管理动作全靠后台表单。v2 把管理权完整
交给教务/管理员：

- 管理端：自建两级文件夹、批量上传、批量删除/停用/恢复/移动、行内编辑
  与替换文件、下载审计与统计、首页「上新」提醒
- 下载端：补搜索(q)/筛选(cat)/排序(sort)/分页(page)、我的下载记录、
  按身份的可见范围（audience）

## 2. 数据模型变更（models/downloads.py）

| 模型 | 变更 | 说明 |
|---|---|---|
| edu.download.category | +parent_id | 两级文件夹；@api.constrains `_check_parent_depth` 限深（父不能再有父） |
| edu.download.category | +sequence, +description | `_order = 'sequence, id'`，管理台可拖排序 |
| edu.download.category | unlink 守卫 | 非空拒绝（UserError 提示资料数与子文件夹数） |
| edu.download.file | +audience | Selection(all/staff/student)，默认 all |
| edu.download.file | file_size 改真实字节数 | b64decode 后 len；init() 对存量数据 add_to_compute 重算 |
| edu.download.file | `_dedup_name` | 同文件夹内防撞名（重名自动加后缀） |
| edu.download.log（新） | file_id(ondelete=cascade) + user_id + create_date | `_log_download`：同人同文件同日去重，审计与统计共用 |

## 3. 路由清单（controllers/downloads.py）

| 路由 | 要点 |
|---|---|
| GET /downloads | q/cat/sort/page；筛选态平铺列表 + pager；默认分组卡片；chips 聚合含子文件夹计数；近30天上新横带 + Top5 热门 |
| GET /downloads/file/<int:fid> | audience 校验不过 → 404；审计落 log；content_disposition（Odoo 原生，RFC5987 中文文件名） |
| GET /downloads/mine | 当前用户下载记录（按时间倒序） |
| GET /downloads/manage | q/cat/status/page + 左侧文件夹面板 + 批量操作条 + 行内编辑（collapse 折叠） |
| POST /downloads/folder/save | 新建/重命名/改父级/排序 |
| POST /downloads/folder/delete | 空文件夹才可删（与 unlink 守卫一致） |
| GET /downloads/upload | 上传页（拖拽区 + 20MB/扩展名提示） |
| POST /downloads/upload/save | getlist 多文件；20MB 上限与扩展名白名单经 ir.config_parameter `edu.downloads.max_file_mb` / `edu.downloads.allowed_ext` 可调 |
| POST /downloads/manage/bulk | action=delete/deactivate/activate/move |
| POST /downloads/manage/file/update | 行内编辑提交，含 replace_file 替换附件 |
| GET /downloads/stats | 累计次数/独立人数/最近下载/近30天总量 + 条形图（纯 CSS 百分比宽度） |

## 4. 权限矩阵

- 管理台全部路由（/downloads/manage、/downloads/folder/*、/downloads/upload/*、
  /downloads/manage/bulk、/downloads/manage/file/update、/downloads/stats）：
  has_group(group_op_back_office_admin) or has_group(group_system)，
  否则 redirect /my/home
- 下载端：auth='user' + audience 过滤——internal(base.group_user) 看全部，
  portal 看 all + student
- ACL 追加：edu.download.log 教务组 1,1,1,1；group_user 1,0,0,0（只读）
- 写路径全程 sudo + 仅 POST + csrf_token

## 5. 前端要点（views/downloads_portal.xml）

- QWeb 模板内不做 `%` 格式化（QWeb 不支持），控制器预格式化后传入：
  `_file_vals`（大小/时间/次数等人读字段）、`_flash_vals`（提示条）
- 管理台避免 form 嵌套（HTML 禁止）：行复选框与批量操作条用 HTML5
  form 属性挂到独立 `dl_bulk_form`，不包在筛选 form 里
- 拖拽上传为 IIFE（无全局污染）；全选反选与删除 confirm 为内联小 JS

## 6. 首页接线（controllers/batch2.py）

- `_ALERT_CARDS` 追加 `('downloads', '资料库上新')`：有新资料时首页横带提示
- `_count_for_card` 加 downloads 分支：近30天新资料数，卡片角标与铃铛共用
  同一口径
- 教师工作台（registrar 专属）追加「资料管理台」卡 → /downloads/manage

## 7. 验收标准（可观测）

1. 本地 `-u edu_portal` 升级 EXIT=0 无 Traceback
2. 三身份 curl 矩阵：学生 200/303（管理路由 303 回 /my/home）、
   教师（internal）下载端 200、backoffice 全部路由 200 + 批量操作成功
3. audience=staff 的文件学生对 /downloads/file/<id> 得 404
4. 批量停用后下载端不显示、直接访问 id 404；恢复后重新可见
5. 非空文件夹删除被拒并提示资料数/子文件夹数
6. 同人同文件同日重复下载只记 1 条 log；download_count 每次下载仍 +1
7. check_english.py 含 5 条新路由全绿（门户无英文漏翻）

## 8. 并行协作注记

本次实施期间，同分支另一窗口并行施工发生过 stash 往返覆盖；事后逐文件
核实确认零丢失。后续约定：同一分支同一时间只允许一个会话改动，或改动
前先 commit——避免未提交工作区被 stash/pop 覆盖。

## 9. 不做（Non-goals）

- 三级及以上文件夹层级（两级足够，constrains 硬限）
- 文件版本历史、回收站、到期自动下线
- 下载量报表导出（stats 页面展示即止）
- 家长端 audience（目前仅 all/staff/student）
- 匿名下载（v1 起维持 auth='user'）
