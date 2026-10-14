# 永约学坊品牌化改造 · 运维手册

> 2026-08-22 完成。范围：品牌替换 / 全站汉化 / 门户后端接线。与 telegram 相关工作面无交集。

## 品牌信息（唯一事实来源）

- 名称：永约学坊（COVENANT REFORMED SEMINARY / SCRTS），始创 2005 年，改革宗立场+四大信经
- 联系方式：**仅** scrtsschool@gmail.com（公开资料未确认电话/地址，不得虚构）
- 页脚：© 2026 永约学坊 / Soli Deo Gloria
- 设计令牌：旧项目 theo-edu-local/website-assets/css/covenant.css（covenant-gold #c8a870 金色系）
- 校徽：edu_brand/static/src/img/logo-medallion.png

## 模块与脚本

| 项 | 说明 |
|---|---|
| custom_addons/edu_brand | 中文落地页（覆盖 theme 首页）+ 品牌页脚 + 校徽 |
| scripts/setup_brand_yongyue.py | 公司名/邮箱/logo、默认语言、菜单清理、首页 arch 移植、存量数据汉化（幂等，可重跑） |
| scripts/i18n_xml_translate.py | XML 英文串抽取→Bing MT→回写（术语表 scripts/i18n_glossary.json，缓存 i18n_cache.json） |
| scripts/check_english.py | 登录态全路由英文残留扫描（验收工具） |
| scripts/test_submit_flows.py | 请假/申诉/换课提交 + 证书 PDF 下载端到端测试 |
| scripts/seed_certificate.py | 演示证书种子（幂等） |

## 关键实现决策

1. **首页**：theme_web_openeducat.homepage 被 COW 成站点专属视图后 xmlid 不存在，
   XML 里无法声明继承 → 模板在 XML 中存源，由 setup 脚本把 arch 移植进该视图（升级不覆盖）。
2. **汉化路径**：自研模板直接改源文件中文（Odoo 17+ 无 ir.translation，源级最稳）；
   官方模块 selection 标签在控制器里用「值→中文」映射（selection 原始标签不走翻译机制）。
3. **机翻工具链**：Google/GitHub raw 被墙，用 pip 的 translators 库走 Bing；术语表强制覆盖。
4. **提交表单 csrf**：本项目模板上下文用 t-att-value="request.csrf_token()"（csrf_token 变量在该上下文为空）。
5. **会议×2**：企业版无社区后端 → 导航隐藏、路由保留友好空态；后续如需自研再放开。

## 常用命令

    # 品牌数据重跑（幂等）
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db         -r odoo -w odoo -d edu19 --no-http < scripts/setup_brand_yongyue.py

    # 验收
    python3 scripts/check_english.py          # 英文残留（当前仅剩图书馆书籍元数据 5 条）
    python3 scripts/test_submit_flows.py      # 提交流程 OVERALL: PASS

## 已知边界

- 图书馆页的书籍作者/卷号（Thomas H. Cormen、Vol. 12）是数据非文案，保留英文。
- 演示数据（王小明/stu@local、考勤编号、SR/SLR/GRI 单号）保留作测试数据。
- edu.leave/edu.grievance 的教师端审批 UI 未做（学生提交→状态流转已可用），按需求"以后再说"。
- 证书越权防护：portal 组模型级读已配 ir.rule（仅本人可见，certificate_report.xml 内 edu_certificate_rule_portal）。

## 首页并入永约学坊官网（第二轮）

首页 = 新版骨架 + 旧 CovenantHome 内容合并：Hero 庭院插画底图（纯 CSS 缓缩放）、
专业设置区含校刊卡、公开信息 6 卡、教务入口、联系区（CTA 标语并入）。
新内页：`/about` 学院概况、`/admissions` 招生信息、`/journal` 校刊目录 + `/journal/page/N` 阅读。

⚠️ 注意：**首页 arch 由 setup 脚本移植进 DB 视图（2060），改 brand_templates.xml 后必须重跑
setup_brand_yongyue.py 才会生效**，单跑 -u edu_brand 只更新载体记录不更新站点视图。

## Zoom 会议链接配置

门户导航「线上会议」「Zoom 会议」两张卡 → /meeting/information、/online/meeting：
- 已配置系统参数 edu.zoom_url 时自动 303 跳转该链接；
- 未配置时显示"链接尚未发布"提示页。

设置方法：

    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db         -r odoo -w odoo -d edu19 --no-http <<'EOF'
    env['ir.config_parameter'].sudo().set_param('edu.zoom_url', 'https://zoom.us/j/你的会议号')
    env.cr.commit()
    print('OK')
    EOF

（换会议只改这个参数即可，无需重启；清空参数即恢复提示页。）


## 真实数据填充与审批后台（第三轮）

### 数据口径（拷问定案）

- ERP 只建**大学部体系 6 个专业**：基督教研究硕士科 / 神学学士科 / 文学学士 / 教育学士 / 家教学院 / 预备科。
  圣经高中是高中部，不进教务系统（公开官网 /programs 仍展示简章原文）。
- 科目只填预备科 14 门真课（PRP-C01..14）；其余专业留空待真实课表资料，宁缺毋编。
- 图书馆录入真实书单 29 本（阅读课 21 + 文史哲备考 8），作者只录可确证者，
  其余明确写「待补」；每本书配 1 册可借单元。

### 种子脚本 scripts/seed_yongyue_data.py（幂等，可反复重跑）

    # 建立/刷新骨架 + 最小【演示】运营数据（课节/考勤/作业/考试/成绩/图书）
    docker compose exec -T web odoo shell -c /etc/odoo/odoo.conf --db_host=db -r odoo -w odoo -d edu19 --no-http < scripts/seed_yongyue_data.py

    # 清场模式：撤除全部演示运营数据（保留专业骨架），开学前用
    SEED_PURGE=1 docker compose exec -T web odoo shell ... < scripts/seed_yongyue_data.py

要点：
- 幻觉数据（计算机科学与技术课程、假科目、李强/张红/刘国假教师、8 本 CS 假书、假账单）在 A 段自动清除；
- 所有临时运营记录强制带「【演示】」标记；课节名由模块按「教师:科目:时间」自动生成，
  因此清场按**批次范围**匹配而非名字；教师占位名为「预备科导师【演示】」（faculty@local 已升级为内部用户）。

### 门户卡片隐藏开关（隐藏≠删除）

系统参数 `edu.portal_hidden_cards`（逗号分隔 href）。未设置时默认隐藏：
费用账单 / 您的订单 / 支付方式 / 文档中心 / 询价 / 我们的订单 /
OMR 考试×2 / 入场注册 / 资产请求。设为空串即全部恢复。路由本身不受影响。

    docker compose exec -T web odoo shell ... <<'EOF'
    env['ir.config_parameter'].sudo().set_param('edu.portal_hidden_cards', '')
    env.cr.commit(); print('OK')
    EOF

### 教师/管理员审批后台

custom_addons/edu_portal/views/approval_backend.xml：顶级菜单「教务审批」→
请假审批 / 申诉处理 / 证书管理。按钮：请假 通过/驳回（驳回必填理由），
申诉 开始处理/解决/驳回/关闭，证书 确认签发。
同时补齐了 edu.leave/edu.grievance 此前缺失的 ACL（portal 只读、group_user 全权）。
教师验收链路：stu@local 提交 → faculty@local 后台批准 → 学生页状态更新，实测通过。

### 公开官网 /programs 专业设置页

五组结构：神学院 / 人文教育学院 / 家教学院 / 预备科·大学预备 / 高中部（收尾）。
内容全部取自 2026 总招生简章与预备科·圣经高中合订简章原文，含预备科 14 门课程列表
与圣经高中三年课程方案、GPA 附录摘要。首页「专业设置」卡改指 /programs
（改动 homepage 模板后记得重跑 setup_brand_yongyue.py）。

⚠️ 本机若开了系统代理（如 Clash），python requests 会把 localhost 打到代理上返回 502——
跑验收脚本请加 no_proxy="localhost,127.0.0.1"。

### 本轮验收记录

- 学生门户可见板块 18/18 内容级 PASS（学习材料为设计内空态）
- 隐藏板块导航不露出、路由仍可达
- test_submit_flows OVERALL: PASS（含证书 PDF 下载）
- check_english TOTAL visible-English hits: 0（书单中文化后清零）

### 录入权限模型（拷问定案：最小授权）

原版把全量权限集中在后台管理组（group_op_back_office_admin），普通内部用户对科目/图书只读。
已按 B 方案开放**录入权**而非整体提权：base.group_user 可建改 科目(op.subject)、
图书(op.media)、册单元、作者、出版社、媒体类型，**删除权仍只在管理员**
（ir.model.access.csv 尾部 access_op_*_user 六行，教师身份实测通过）。
若未来要切换为原版粗放模式（教师≈后台管理员），把教师加入该组即可，但误删风险自担。

日常教务数据（专业/班级/科目/课表/作业/考试/图书/审批）管理员与教师登录后台即可自助维护，
不再需要跑脚本；脚本仅用于演示数据重建（seed）与清场（SEED_PURGE=1）。

### 公开导航整备（第四轮）

scripts/setup_nav_yongyue.py（幂等）：
- 前排插入永约导航：学院概况/专业设置/招生信息/SCRTS校刊/登录（联系我们改指 /#contact）
- 原版功能入口**全部保留**（商店/活动/论坛/博客/图书馆/考试/入场/招聘等，空置可日后填充，
  拷问定案：入口不能消失）；根菜单更名「更多」，重复图书馆入口去重
- 清除：页眉占位句「请管理员填充」（视图2996停用）、社交默认假链接、
  假教师遗留联系人（张红/刘国）、event演示商品；拟真名中性化（李强→停用教师账号【演示】）
- 注意：utm「Job Campaign」是招聘模块功能数据，按同一原则保留；
  shell 进程提交后需重启 web 才能刷新视图/菜单缓存

⚠️ 网站菜单树：所有一级项都挂在根菜单 id=4 下，新建菜单必须 parent_id=4 才会渲染。

## 性能基线与调优记录（2026-08-24 实测）

| 页面 | 查询数 | 服务端耗时 |
|---|---|---|
| 公开首页 / 专业设置 / 报名表 | 5–10 | 12–24ms |
| 门户首页 /my/home | 85–87（卡片计数风暴，已知待优化项） | ~100ms |
| 课表 / 成绩簿 / 图书馆 | 22–40 | 20–83ms |

config/odoo.conf 已加（该文件含密钥被 .gitignore 排除，改动只存在于本地与部署机）：
workers=3, max_cron_threads=1, limit_memory_hard=2G/soft=1.5G,
limit_time_cpu=120, limit_time_real=240, db_maxconn=64。
多进程切换后全链路回归通过；worker 冷启动首请求偏慢属正常预热。

后续可选优化：①/my/home 计数批量合并或短缓存（当前无体感瓶颈，缓做）；
②部署时前置 nginx 做 gzip 与静态长缓存；③数据量上来后再调 Postgres。
GitHub 第三方性能模块经评估收益小、Odoo19 兼容风险大，不引入。

## 马来西亚部署记录（2026-08-24）

- **目标机更正**：旧文档中的测试服 scrts1（203.0.113.9）信息已过时并从 ~/.ssh/config 删除；
  正确目标为 **prod-host（203.0.113.10 吉隆坡，root，密钥 my_edu_ed25519）**
- 远端现状：Ubuntu 24.04 / 96G 盘 / 7.8G 内存，已有同构 Docker 栈 `/opt/edu-app`
  （compose 项目名 edu19-prod，web 绑定 127.0.0.1:8069 由 nginx 反代）
- 部署方式：rsync 六个模块目录（edu_life/edu_eval/edu_schedule/edu_apply + 更新的 edu_portal/edu_brand）
  → conf 追加 workers=3 → 停 web 容器跑 -i/-u 升级 → 起站
- ⚠️ 踩坑记录：rsync -a 保留本地属主导致容器内 odoo 用户无权写 data xml，
  升级报 PermissionError——同步后必须 chmod -R a+rX；py 变更需 restart 才生效（-u 不刷新内存代码）
- 线上冒烟：/ /programs /apply /contactus 公开页 200；
  stu@local 登录 /my/home /my/checkins /eval/my 全 200；四新模块 state=installed

报名邮件通知：钩子已上线（每份申请自动生成通知邮件至招生邮箱），
真实送达需在后台配置外发 SMTP（推荐 QQ邮箱授权码 smtp.qq.com:465 SSL/TLS）。

### 首页浏览器标题修复（夜间班补充）

现象：<title>Home | 永约学坊</title>。根因：COW 首页视图的 **en_US 名称副本**
仍为 Home，且布局层标题优先取该值。修复 = zh_CN 与 en_US 双写 name/meta_title
（scripts/fix_home_meta.py）+ 容器重启。公网已验证 <title>永约学坊</title>。

## 夜间 UX 全面优化（2026-08-25 交班）

基于 docs/ux-audit.md（eval-eng 三视角审计）与标杆实践，完成：

- **edu_life**：streak 连续天数横幅、今日进度徽章、周记三态提示条、
  历史状态筛选 chips、评语引号面板、统计大号完成率、窄屏打磨、实时字数统计
- **edu_eval / edu_apply**：报名表九区步骤感+必填进度条+错误定位+防双击+
  全字段保值；打分页分组卡片化+边界提示；结果页时间线化；匿名承诺置顶
- **机翻硬伤清零**：考试 经过→及格 等十余处批量修正；工具栏 没有任何→不分组
- **身份守卫**：成长组四卡仅学生可见；教师首页 quiz 卡中文化
- **性能**：多 worker 配置；首页计数 60s TTL 缓存（热访问 122ms→36ms）
- **SEO**：校徽 favicon、公开页中文标题/meta

部署：scripts/deploy_myedu.sh 一键同步 prod-host，公网 edu.example.org 全量验证通过。
已知遗留（P2/P3 见 ux-audit.md）：公开页 kicker 英文装饰词定位为品牌装饰保留；
contactus 公司字段已语境化待复核；RELAXNG 校验警告为旧语法提示不影响功能。

## 并发容量实测（2026-08-24 · scripts/loadtest.py）

| 场景 | 并发 | 结果 |
|---|---|---|
| 匿名登录页 | 40 | ✅ 全成功，29.8 req/s |
| 同时完整登录 | 25 | ✅ 全成功，最慢等待 ~7s |
| 同时完整登录 | 60 | ⚠️ 97% 成功，2 例连接重置 |
| 同时完整登录 | 100 | ❌ 约半数连接被重置 |
| 已登录浏览（6页连刷） | 12/40/60 | ✅ 全成功，吞吐 11–21 req/s |

结论：**日常浏览态百人规模无压力**；唯一硬点是"同一秒集体点登录"的洪峰
（约 40–60 并发起出现重置，与 workers 数无关，属瞬时连接排队机制）。
缓解：错峰登录引导即可覆盖百人规模；如需硬扛，前置 nginx 吸收握手排队。
config/odoo.conf 本地已调至 workers=6（内存峰值 945MB/7.75GB，余量充足）。
