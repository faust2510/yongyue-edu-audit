# LMS 交付评审计划（auditor / t3 预备稿）

> 对象：t2 产出（models/lms.py、controllers/lms.py、views/lms.xml、ACL、manifest、scripts/seed_lms_demo.py）
> 对照：docs/plans/lms-design.md（scout t1）｜铁律：/Users/qwe/odoo-enterprise-ref/README.md
> 状态：等待 t2 完成通知

## 阶段一 · 代码评审检查点

### A. Odoo19 规范（已对照企业版核心源码核实）
- [ ] 视图用 `<list>` 不用 `<tree>`；列隐藏用 `column_invisible`，条件用 `invisible="expr"`
- [ ] search view 的 `<group>` 无 expand/string 属性
- [ ] 模板里 datetime 用 t-options 必须带 `'widget'` 键，否则 KeyError——推荐控制器预格式化（timetable 教训）
- [ ] 自建后台视图显式 `priority=1`（默认16会被上游 priority=8 压制）
- [ ] 用户组字段名：`user.group_ids`（19 改名）；menuitem 的 groups= 属性映射到 ir.ui.menu.group_ids
- [ ] 覆写既有路由靠继承顺序；编辑既有文件先重读小锚点改
- [ ] ACL 复用 base.group_portal / group_user / group_system，不建自定义组

### B. 设计符合性（对照 lms-design.md）
- [ ] edu.lesson：标题/类型(video|article|attachment)/video_url 或 html/文件/排序/subject_id/state
- [ ] edu.lesson.progress：student_id/lesson_id/state(draft→done)/completed_date + SQL unique(student_id, lesson_id)
- [ ] 三页路由：/my/courses 列表(进度条) → /my/courses/<id> 课次列表 → /my/courses/lesson/<id> 详情(视频 iframe 或文章+标记完成 POST)
- [ ] 后台中文 list/form + 「在线课程」菜单位置合理
- [ ] 种子：3 门预备科科目 × 2-3 课次(1视频+1文章)，幂等，演示内容标【演示】

### C. QWeb ↔ 控制器 values 一一对应
- [ ] 逐模板列出引用变量，与 render() values 字典比对（缺=KeyError/空渲染，多=死代码）

### D. 安全与越权面（重点）
- [ ] 学生只能读自己 progress；mark_done 只能给自己已选课程（服务端身份校验，不能信前端传 student_id）
- [ ] 家长视角数据域 = 孩子们班级的课程合集（参照 scheduling.py 四视角模式）
- [ ] 教师=全部可看+管理入口；裸门户账号/guest → 空列表不暴露全校数据
- [ ] ACL 最小权限参照 enterprise website_slides 模式：progress 模型对 portal 收紧（0 权或只读），写操作走控制器 sudo+身份校验
- [ ] save 路由 csrf=on；lesson 详情页 XSS 面：html 内容字段 sanitize 情况
- [ ] sudo() 使用处必须有先行的身份域收敛（沿用 timetable 评审标准）

### E. 合规红线（发现疑似照搬即 critical 并注明出处）
- [ ] 逐文件 diff 式比对 website_slides 企业版源码（30-资源/odoo源代码企业版/odoo/addons/website_slides/）：取新代码特征行反查该目录
- [ ] 比对 openeducat_erp 基座与本仓库既有代码（防自我重复/复制上游视图大段结构）
- [ ] reference/*.html 仅允许 DOM/class 风格借鉴（oe-mc-* oe-course-* 卡片风格），不允许 JS/模板整段照搬
- [ ] 概念允许：channel/slide/slide_partner 三层、completion=round(100*done/total) 除零保护——实现必须自研表述

## 阶段二 · 真机 QA（评审问题清零后）

1. 升级：docker exec edu19-clone-web-1 odoo -c /etc/odoo/odoo.conf -d edu19 --db_host=db -r odoo -w odoo -u edu_portal --stop-after-init
2. docker restart edu19-clone-web-1
3. 种子：seed_lms_demo.py 以 odoo shell --no-http 方式执行，跑两遍验幂等
4. 截图（playwright chrome headless 1440px，参考 shoot_timetable.py 登录模式）存 shots/local/lms_*.png：
   - lms_student_courses.png（学生课程卡+进度条）
   - lms_student_lessons.png（课次列表）
   - lms_student_lesson.png（详情页视频区+完成按钮）
   - lms_parent_courses.png（家长视角）
   - lms_admin_backend.png（后台在线课程菜单中文视图）
5. 每张 read_image 核验内容非空白/无报错页/进度条渲染正确
6. 运行时 bug 当场最小修复并在报告注明改动

## 环境事实（已核实）
- 容器 edu19-clone-web-1 up、db healthy；四账号 stu@local/faculty@local/parent@local/admin 均存在
- 本机 playwright 可用；截图基线脚本 scripts/shoot_timetable.py
