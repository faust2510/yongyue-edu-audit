# 实施代理 U · D1 导航接线报告（2026-08-23）

## 一、调查结论：导航为数据驱动（website.menu），非模板硬编码

证据：
1. `custom_addons/edu_brand`、`edu_public` 全部模板中**无任何 header/top_menu 覆盖**（仅页内阅读导航 `<nav class="yylc-reader-nav">`）；站点头部走 `website.layout` 标准渲染。
2. 历史脚本 `custom_addons/seed_menus.py`、`fix_menus.py` 正是通过创建/移动 `website.menu` 记录来控制导航的。

> ⚠ **存在性已变（2026-10-02）**：上面这两个脚本**已被删除**（不是改名）—— 它们的 sequence
> 约定已转录进 `scripts/seed_d1_nav.py`（后者注释自陈「沿用 fix_menus.py 的原站顺序约定」）。
> 本文是按**当时事实**写的取证记录，除本注记外不改原文（本仓铁律：历史取证块保留不动）。
3. 缺口根因已定位：`scripts/setup_brand_yongyue.py` 的 `MENU_REMOVE_NAMES` 在品牌化时**主动删除了原站的 14 个菜单**（商店/现在预订/活动/论坛/博客/入场/Course/Program/工作机会/工作/Alumni Jobs/校园工作/校友/展示位置），并把 `Courses` 改名 `课程` —— 与审计「本地仅剩 首页/图书馆/考试/联系我们/课程 5 项」吻合。

→ 按任务分支规定，采用**数据驱动方案**：新建幂等种子脚本 `scripts/seed_d1_nav.py`（ORM 创建/校准 website.menu，绝不删除任何条目）。顺序参照 `scrape/web__login.html` 头部实测层级与 `fix_menus.py` 的 sequence 约定。

## 二、导航核对表（入口 → 目标路由 → 状态）

| 入口 | 目标路由 | 归属 | 存在性证据 |
|---|---|---|---|
| 商店 | `/shop` | website_sale（已装） | P_public GET 200 |
| 现在预订 | `/booking` | edu_public `main.py:99` | GET 200（占位文案，原站亦然） |
| 图书馆（改指） | `/digital-library` | edu_public `main.py:80` | GET 200；原站导航即指此 |
| 考试（不动） | `/student/exam`（现状） | edu_portal | 维持现状，未列入本次改动 |
| 活动 | `/event` | website_event（已装） | GET 200（空态，C 包造数另议） |
| 论坛 | `/forum` | website_forum（已装） | GET 302→唯一论坛（标准行为） |
| 博客 | `/blog` | website_blog（已装） | GET 302→博客首页（标准行为） |
| 入场 ▾ | `#`（下拉父项，原站即 #） | — | 仅作分组容器 |
| ├ Course | `/courses-offered` | edu_public `main.py:124` | GET 200（静态卡空壳） |
| └ Program | `/program-offered` | edu_public `main.py:130` | GET 200（占位，原站亦然） |
| 工作机会 ▾ | `#`（下拉父项） | — | 仅作分组容器 |
| ├ Alumni Jobs | `/alumni/job/card` | edu_public `main.py:118` | GET 200（游客可见职位卡） |
| └ 校园工作 | `/campus/jobs` | edu_public `main.py:112` | GET 200 |
| 工作 | `/jobs` | 标准招聘路由 | P_public GET 200（空列表按约定不报死链） |
| 校友 | `/alumni` | edu_public `main.py:106` | GET 200 |
| 课程（改指） | `/courses` | edu_public `main.py:34` | GET 200；恢复原站 Courses=公开课目页语义 |
| 我的课程（新增） | `/my-courses` | edu_public `main.py:137` | auth='user'，游客 303→登录（正确行为） |
| ~~展示位置~~ | ~~`/website/activity/announcement`~~ | 企业版独有 | **按指令跳过，不创建** |

改指说明（均为更新 URL、非删除）：
- 图书馆 `/library/media` → `/digital-library`：对齐原站且游客可达；
- 课程（原 Courses）`/my-courses` → `/courses`：恢复原站语义；学生个人课表由新增的「我的课程」承接，`/my-courses` 不丢失。

顺序落位（sequence）：首页10 · 商店20 · 现在预订30 · 图书馆40 · 考试50 · 活动60 · 论坛70 · 博客80 · 入场90(Course91/Program92) · 工作机会100(Alumni Jobs101/校园工作102) · 工作110 · 联系我们120 · 校友130 · 课程140 · 我的课程145 —— 与原站一致，Placements 缺席为有意为之。

## 三、实施内容

| 文件 | 改动 |
|---|---|
| `scripts/seed_d1_nav.py`（新建） | 幂等 ORM 种子：缺失则建、已有则只校准 url/sequence/parent；打印 CREATE/UPDATE/OK(keep) 明细；结尾 commit；不删任何记录、不建 Placements |
| `edu_brand/views/brand_templates.xml` | `footer_yongyue` 内新增「联系我们」块：标题链接 `/contactus` + 邮箱 scrtsschool@gmail.com + 电话 +1 555-555-5556（原站页脚同款文案），位置在品牌名与版权行之间，社交图标未触碰 |
| `edu_brand/static/src/css/brand.css` | 新增 `.yylc-footer-contact/-head/-line/-phone` 规则；顺带修正页脚作用域内两处失效的 `var(--…)`（变量定义在 `.yylc-home` 上，页脚取不到值）改为对应色值 |

备注：
- 页脚联系方式含电话系按本任务指示复刻原站文案（+1 555-555-5556 为原站占位号）；`docs/yongyue-rebrand.md` 曾约定"公开资料未确认电话不得虚构"，两者冲突时以主代理拍板为准——若坚持仅邮箱，删掉模板里 `yylc-footer-phone` 一个 div 即可。
- `footer_yongyue` 是常规继承视图，**不受**首页 arch 移植警告影响，`-u edu_brand` 即生效。

## 四、需主代理执行的命令（U 未执行 docker）

```bash
# 1) 接线菜单（幂等，可重复跑）
docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 --no-http < scripts/seed_d1_nav.py

# 2) 更新品牌模块（页脚模板 + CSS 生效）
docker compose exec -T web odoo -c /etc/odoo/odoo.conf --db_host=db \
    -r odoo -w odoo -d edu19 -u edu_brand --stop-after-init

# 3) 回归抽查（应全部非 404；/my-courses 游客预期 303）
curl -sI localhost:8069/shop localhost:8069/booking localhost:8069/digital-library \
     localhost:8069/event localhost:8069/forum localhost:8069/blog \
     localhost:8069/courses-offered localhost:8069/program-offered \
     localhost:8069/alumni/job/card localhost:8069/campus/jobs \
     localhost:8069/jobs localhost:8069/alumni localhost:8069/courses \
     localhost:8069/my-courses -o /dev/null -w '%{url_effective} %{http_code}\n'
```

> ⚠️ **顺序铁律**：`scripts/setup_brand_yongyue.py` 的 `MENU_REMOVE_NAMES` 会再次删除本批菜单（名字完全同名）。凡重跑该脚本，**之后必须重跑 `scripts/seed_d1_nav.py`**。根治办法是从其 MENU_REMOVE_NAMES 移除这批名字或改为隐藏——该文件超出 U 的允许编辑范围，留主代理处理。

## 五、自查确认

- [x] 所有新入口 href 均指向确实存在的路由（见第二节证据列；本地控制器行号逐一核对）
- [x] 未执行任何 docker/odoo 命令；未触碰 edu_portal/edu_quiz/edu_telegram
- [x] 未删除任何现有导航项（含展示位置：既未加也未删）；考试/首页/联系我们保持原样
- [x] 种子脚本可重复执行（按名查找→校准/跳过，无副作用累积）

## 六、范围收紧合规说明（2026-08-23 追记）

调整后范围：edu_brand 目录、scripts/seed_d1_nav.py、edu_public 仅限页脚/导航布局模板段落；禁碰 controllers/*.py、course_detail.xml、__manifest__.py（归代理 W）。

- [x] 本代理全部产出天然落在收紧后范围内，**无需回滚**：
  `scripts/seed_d1_nav.py`（新建）、`edu_brand/views/brand_templates.xml`、
  `edu_brand/static/src/css/brand.css`、本报告。edu_public 目录零改动。
- [x] **页脚/导航不需要改控制器**：导航走 website.menu 数据（种子脚本解决），
  页脚是纯模板+CSS（edu_brand 内）。对 edu_public/controllers/main.py 仅做过只读
  核对（路由行号引用），无修改需求 → 无需主代理协调任何控制器变更。
- [x] 与 W 无文件交集；W 新增的 course_detail.xml / main.py 更改不影响本批导航入口
  （课程→/courses 为列表路由，详情参数属 B8/W 范畴）。
