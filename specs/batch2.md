# 批次2 施工规格（成绩册 / 图书馆 / 学习材料 / 布告栏）

> 前置：批次1（考勤/档案/考试/作业）已完成，模式见 `controllers/batch1.py` + `views/batch1.xml`

## 页面清单

| 路由 | 标题 | 参考 DOM | 数据来源（社区版模型） |
|---|---|---|---|
| `/grade-book` | 成绩簿 | reference/grade-book.html（3.5K，简单） | op.marksheet.register / op.result.line（按学生过滤；无数据时空态） |
| `/library/media` | 图书馆 | reference/library__media.html（14K，7 卡） | op.media / op.media.unit / op.author / op.publisher |
| `/subject/details` | 学习材料 | reference/subject__details.html（13K） | op.subject（学生所在课程的科目列表） |
| `/my/notice_board/notice` | 布告栏 | reference/my__notice_board__notice.html（7.6K） | 社区版无此模型 → 新建轻量模型 `edu.notice`（title/content/date）+ 演示数据 |

## 通用要求

- 控制器新文件 `controllers/batch2.py`（import 进 `controllers/__init__.py`）
- 模板新文件 `views/batch2.xml`（加进 manifest data）
- 骨架 `<t t-call="edu_portal.edu_page">`，中文文案照抄参考页
- Odoo 19 注意：search() domain 必填；shell 脚本每条 create 包 savepoint、结尾 env.cr.commit()
- 种子脚本 `custom_addons/seed_batch2.py`，运行后 grep COMMITTED 确认

> ⚠ **路径已变（2026-10-02）**：该脚本已迁到 `scripts/seed_batch2.py`（**内容未改**）——
> 它本来就不是模块，不该待在 addons 路径下。见 [docs/audit/redundancy/inventory.md](../docs/audit/redundancy/inventory.md)。
- 升级部署：`-u edu_portal --stop-after-init` 后 restart web，curl 登录逐页验证

## 验证标记

- /grade-book → 标题「成绩簿」，空态或成绩行
- /library/media → 有图书卡片区，含书名/作者
- /subject/details → 科目列表含「高等数学」等种子科目
- /my/notice_board/notice → 至少 2 条布告标题渲染
