# 邀请码分层（凭码注册即成为对应层级）调研

> **铁律 0 产物**（CLAUDE.md 铁律 0 / docs/dev-workflow.md 六步闸门第 2 步）。
> 任务：t6「调研+设计：邀请码分层（凭码注册即成为对应层级）」——本文件只做调研，不含实现。
> **取证时间**：2026-09-17（本机 docker 栈 + 上游源码固定 commit）。
> **行号漂移声明**：上游源码一律带 commit/分支；本机 Odoo 源码取自运行中的 `odoo:19` 镜像，行号以该镜像为准（见 §1.0）。

**一句话结论**：同类系统里**没有一家把「管理层级」写进邀请码**。最接近的范式是 Moodle 的 **group enrolment key**——「码 ⇒ 自动进组」，组就是归属；Canvas 的 join code 只给**单一固定角色**（student）；钉钉/企微/飞书/校管家的「邀请」只解决「进组织」，**层级/权限在加入后由管理员分配**；校管家的家长端则是「**先自助注册、再自助绑定学员**」，与本设计要面对的「层级码不绑人 ⇒ 档案缺口」同构。Odoo 19 核心**没有「邀请码」这个实体**：它的 token 是**绑人**的签名 URL，且不携带任何组/角色。

---

## 0. 结论速览

| 系统 | 机制（功能名） | 码/邀请是否自带层级 | 一手来源（路径:行 / URL） |
|---|---|---|---|
| Odoo 19 core | auth_signup 签名 token（`/web/login?token=…`） | ❌ 只绑 partner，不带组 | 本机镜像 `auth_signup/models/res_partner.py:171-201` |
| Odoo 19 core | Portal 向导「Grant Portal Access」 | ❌ 只写 `base.group_portal` | `portal/wizard/portal_wizard.py:32-34,133-165` |
| Odoo 19 core | 内部用户邀请（模板用户 copy） | ❌ 组由邀请人**先**设好 | `auth_signup/models/res_users.py:111-129` |
| Moodle | Self enrolment + **Enrolment key** + **Group enrolment key** | ⭕ **带归属**：组码 ⇒ 自动进该组；角色由实例 `roleid` 决定 | `moodle/moodle@e68a1418` `public/enrol/self/lib.php:174-205`、`public/lang/en/group.php:67-69` |
| Moodle（第三方） | `auth_enrolkey` 凭 key 一步注册+选课 | ⭕ 码 ⇒ 选课（角色仍是默认学生） | moodle.org 插件目录 + GitHub 元数据（§2.2） |
| Canvas | Course **Join Code / Secret URL**（可先注册后自助选课） | ❌ 角色恒为 student | `instructure/canvas-lms@1c9f0bb8` `app/controllers/self_enrollments_controller.rb:27,52`、`ui/features/new_login/services/register.ts:111` |
| 钉钉 | 添加组织成员 / 邀请链接 / 二维码邀请 / 开启成员邀请 / 角色管理 | ❌ 加入后由管理员分配部门与角色 | help.dingtalk.io 三篇（§3.1） |
| 企业微信 | 如何邀请成员加入企业 | ❌（**正文未取得**，见 §5） | open.work.weixin.qq.com `doc_id=14986` |
| 飞书 | 管理员邀请成员加入企业 / 企业成员邀请内部其他成员 | ❌ 邀请=进组织 | feishu.cn 两篇（§3.3） |
| 校管家 | 员工管理（权限组）；师生信家长端**手机号注册后自助绑定学员** | ❌ 权限组由管理员建、加员工时分配；家长端是**注册后自助绑档案** | wiki.xiaogj.com / helpcenter.xiaogj.com（§3.4） |

---

## 1. Odoo 19 核心：我们脚下的这块地

### 1.0 取证环境（先说清楚证据强度）

| 项 | 值 |
|---|---|
| 运行镜像 | `odoo:19`（容器 `edu19-clone-web-1`），源码在 `/usr/lib/python3/dist-packages/odoo/addons` |
| 版本 | `release.py` → `version_info = (19, 0, 0, FINAL, 0, '')` |
| 本机源码副本 | `/Users/qwe/Documents/文件大总管/30-资源/odoo源代码企业版/odoo/addons`（同版本；已逐文件 md5 对照，**除 `auth_signup/controllers/main.py` 少 9 行 `.well-known/change-password` 路由外全部一致**——引用该文件时以镜像为准） |
| 本机库 | `edu19`（docker `edu19-clone-db-1`，只读 SELECT） |

### 1.1 先纠正一条仓内注释：「auth_signup 未安装」在本机不成立

- 本机 DB 实测：`select name,state,latest_version,auto_install from ir_module_module where name='auth_signup';` → `auth_signup|installed|19.0.1.0|t`
- 原因：`auth_signup/__manifest__.py` 声明 `'auto_install': True`，依赖 `base_setup, mail, web`——装了 mail+website 的库会自动带上它。
- 影响：**`custom_addons/edu_portal/models/invite_code.py:4` 与 `custom_addons/edu_portal/controllers/register.py:6` 的注释（「替代 Odoo 原生开放注册（auth_signup 未安装）」「原生 /web/signup 保持不可用（auth_signup 未安装）」）已经不准确**。设计不能再以「核心没有注册模块」为前提；真正的开关在 §1.2。
- ⚠ **未验证**：生产库（马来西亚 prod-host）是否同样 `installed`。核实命令见 §5。

### 1.2 原生 `/web/signup` 到底为什么是 404

- 路由本体**存在**：`auth_signup/controllers/main.py:39-44`
  ```python
  @http.route('/web/signup', type='http', auth='public', website=True, sitemap=False, captcha='signup', …)
  def web_auth_signup(self, *args, **kw):
      qcontext = self.get_auth_signup_qcontext()
      if not qcontext.get('token') and not qcontext.get('signup_enabled'):
          raise werkzeug.exceptions.NotFound()
  ```
- `signup_enabled` 的取值链：`main.py:132` → `res.users._get_signup_invitation_scope() == 'b2c'`；而 **website 覆盖了它**：
  `website/models/res_users.py:66-68` → `return current_website.auth_signup_uninvited or super()._get_signup_invitation_scope()`（字段定义 `website/models/website.py:213`）。
- 本机实测（两张表对着看，这就是「为什么 404」的答案）：

  | 落点 | 本机值 | 是否生效 |
  |---|---|---|
  | `ir_config_parameter: auth_signup.invitation_scope` | `b2c` | ❌ **被 website 覆盖，不生效** |
  | `website.auth_signup_uninvited`（id=1 永约学坊） | `b2b` | ✅ 真实开关 |

- 实测 HTTP：`/web/signup → 404`（`<title>Page Not Found | 永约学坊</title>`），`/web/reset_password → 200`（同一模块的兄弟路由，说明模块确实在跑）。
- **设计含义（重要）**：今天挡公开注册的是**一个字段**，不是模块缺失——把 `website.auth_signup_uninvited` 改成 `b2c` 就立刻恢复「任何人自助注册门户账号」，**绕过邀请码**。分层邀请码上线必须把这个字段纳入巡检（生产同样要查）。

### 1.3 核心的三条「邀请」机制，为什么都不能直接当层级码用

**(a) 签名 token 邀请（绑人，不绑层）**
- 生成：`auth_signup/models/res_partner.py:171-191`：`payload = [self.id, self.user_ids.ids, self._get_login_date(), self.signup_type]` → `tools.hash_sign(…, expiration_hours=expiration)`
- 默认有效期来自系统参数：`auth_signup.signup.validity.hours = 144`（6 天）、`auth_signup.reset_password.validity.hours = 4`（第 186-188 行，**可用参数改**）
- **登录即失效**：docstring 180-181 明写「Since `last_login_date` is part of the payload, this token is invalidated as soon as the user logs in」
- 校验：`_get_partner_from_token`（193-201）比对 partner / user_ids / login_date / signup_type
- 语义：**一个 token 只对一个人**，没有可复制、可转发的「码」实体，也**没有任何层级字段**

**(b) Portal 向导「授予门户访问」（授的是固定组）**
- `portal/wizard/portal_wizard.py:133-165` `action_grant_access()`：建/复用 user 后**只写 `base.group_portal`**（第 147、159 行），随后 `user_sudo.partner_id.signup_prepare()`（161）并 `_send_email()`（163）
- 向导的字段只有 `partner_ids / user_ids / welcome_message`（`portal_wizard.py:32-34`）——**没有「选层级/选组」的地方**
- 生命周期零件齐全，值得抄：撤销 `action_revoke_access`（167-187：`active=False` + `signup_type=None`）、重发 `action_invite_again`（189-200）
- 建号方式：`_create_user`（207-217）→ `_create_user_from_template`（`auth_signup/models/res_users.py:111-129`，模板用户 `base.template_portal_user_id`，**本机 = 4**）

**(c) 内部用户邀请（组是邀请人先设的）**
- `auth_signup/models/res_users.py:38-85` `signup()`：带 token → 找 partner；partner 已有 user → 改密码；没有 → `_signup_create_user`（79）；不带 token → 外部注册，且 `_get_signup_invitation_scope() != 'b2c'` 时直接 `SignupError('Signup is not allowed for uninvited users')`（92-102）
- 新用户 = **模板用户的 copy**（111-129），组由创建者给——**邀请行为本身不携带层级**

**结论**：核心可复用的是「token 有有效期、可撤销、可重发」这套**生命周期思路**；「码 ⇒ 层级」在核心**没有对应物**，属于自研范围（本仓已有 `edu.invite.code`，见设计文档 §2）。这不是「重复造轮子」，是核心确实没有这个轮子。

### 1.4 一条必须绕开的硬约束

- `base/models/res_users.py:535-548` `_check_disjoint_groups`：**同一用户不能同时落在 portal 与 internal 两类组里**（"User %(user)s cannot be at the same time in exclusive groups %(groups)s"）
- 影响：教师层/教务层码**不能沿用现状「写 `base.group_portal`」的写法**；必须写 internal 组并清掉 portal。实施时必须实测（见设计 §4.2 与未决项）。

---

## 2. 同类开源

### 2.1 Moodle：self enrolment + enrolment key（含 **group enrolment key**）—— 最贴近的先例

> 取证 commit：`moodle/moodle@e68a1418bea512dd5992c29eb9e36570a3844e94`（branch `main`，2026-09-17）。Moodle 5.x 的代码在 `public/` 目录下。
> ⚠ `docs.moodle.org` 全站被 Cloudflare 挡（403 challenge，本机带 UA 重试同样 403）⇒ **改用仓库源码取证**，官方文档页面仅作为「有这份文档」的存在性证据。

**（1）课程自选课的两道闸：先密码，再角色**
- `public/enrol/self/lib.php:174-191` `enrol_self($instance, $data)`：
  - 第 178 行：`if ($instance->password && !isset($data->enrolpassword)) { … }` —— 设了 key 就必须给 key
  - 第 189 行：`$this->enrol_user($instance, $USER->id, $instance->roleid, $timestart, $timeend);` —— **角色来自 self-enrolment 实例的 `roleid`（第 91-96 行读取 role 记录），不是码里带的**
- `public/enrol/self/lib.php:193-205`：启用组码时（`$instance->password && $instance->customint1`），把**同一串密码**拿去和 `groups.enrolmentkey` 逐条比对，命中即**自动加组**（200-202）
- `public/enrol/self/locallib.php:31-50` `enrol_self_check_group_enrolment_key($courseid, $enrolpassword)`（表单校验用同一套匹配）

**（2）「码 ⇒ 层级」的官方措辞（本设计要引用的那句话）**
- `public/lang/en/group.php:67-69` `enrolmentkey_help`：
  > "An enrolment key enables access to the course to be restricted to only those who know the key. **If a group enrolment key is specified, then not only will entering that key let the user into the course, but it will also automatically make them a member of this group.**"

**（3）可直接抄的两个工程细节**
- **组码唯一性**：`public/group/group_form.php:208-211`——同课程内不允许两串相同 `enrolmentkey`，冲突时报 `enrolmentkeyalreadyinuse`（`public/lang/en/group.php:70`）
- **组码走密码策略**：`public/group/group_form.php:200-205`（`$passwordmanager->check_policy`）+ 站点开关 `public/admin/settings/security.php`（`groupenrolmentkeypolicy`，默认开）

**（4）其它可借用的措辞（我们做 UI 时可以直接用这套词）**
- `public/enrol/self/lang/en/enrol_self.php:85-86`：`password` = **Enrolment key**；`:77-79`：**Max enrolled users（0 = 不限）**；`:69-71`：**Use group enrolment keys**；`:94`：`passwordmatchesgroupkey`「这串 key 已被用作组码」；`:119-120`：**Use password policy**

**（5）边界**：Moodle 的组码作用域是**课程**（一码一组一课），**不是全局账号层级**；他也没有「一个码把账号提升到某个系统角色」的概念。

### 2.2 Moodle 第三方插件：auth_enrolkey（凭 key 一步注册 + 选课）

- 插件目录（官方 marketplace）：**「Enrolment key based self-registration」** https://moodle.org/plugins/auth_enrolkey/2020011400/21102 —— 描述为「Email-based self-registration 的功能克隆，另外依据收到的 token 把用户自动选进可用的课程」
- GitHub 元数据（`gh api repos/catalyst/moodle-auth_enrolkey`，2026-09-17）：`description="Much simpler 1-step registration and enrolment using course enrol keys"`、`default_branch=MOODLE_35_STABLE`、**`license=null`**、`stargazers=12`、`pushed=2026-09-01`
- **判定：只可借鉴交互，不可复用代码**——默认分支停在 Moodle 3.5、**未声明 license**（本仓合规口径要求版权干净，见 `docs/compliance-audit.md`）。

### 2.3 Canvas：join code / secret URL（可先注册，再自助选课）

> 取证 commit：`instructure/canvas-lms@1c9f0bb8013ed69c4f2efe11fd483025469b7e6c`（branch `master`）。

- `app/controllers/self_enrollments_controller.rb:27,52`：`def new` → `@course = @domain_root_account.self_enrollment_course_for(params[:self_enrollment_code])`
- `app/views/self_enrollments/_authenticate_or_register.html.erb`：未登录访问 join code 链接时，页面直接给「登录或**注册**」表单
- `ui/features/new_login/services/register.ts:96,111,120`：注册请求体里带 `joinCode` → `self_enrollment_code: payload.joinCode` + `self_enrollment: '1'`
- `app/helpers/self_enrollments_helper.rb`：提交到 `api_v1_course_enrollments_url(@course, enrollment: { self_enrollment_code: …, user_id: "self" })`
- 官方说明（Instructure 知识库，2026-09-17 抓到标题与摘要）：「How do I enable course self-enrollment with a join code or secret URL?」https://community.instructure.com/en/kb/articles/661134-how-do-i-enable-course-self-enrollment-with-a-join-code-or-secret-url ——「Self-enrollment allows a student to sign up for a course using a secret URL or code」
- 开发者文档（检索命中，见 §5 说明）：Enrollments 资源页提到「…the course allows self-enrollment, the user can self-enroll **as a student** in the default section by passing in a valid code」https://developerdocs.instructure.com/services/canvas/resources/enrollments
- **判定**：Canvas 的码只决定「进哪门课」，**角色恒为 student**，没有层级概念；但它证明了「**凭码注册 + 自动落位**」这条交互在主流 LMS 里是成立的。

### 2.4 小结（开源侧）

| 问题 | Moodle | Canvas | 对我们的含义 |
|---|---|---|---|
| 码能带「归属」吗 | ✅ 组码 ⇒ 进组 | ✅ join code ⇒ 进课 | 「码自带归属」有先例，可以放心做 |
| 码能带「系统角色/层级」吗 | ❌（角色来自实例设置） | ❌（恒 student） | 我们要做的**比同类更进取**——必须自己定义好边界与发放权限 |
| 码的唯一性 | ✅ 表单层查重 | —— | 我们得在**数据层**加唯一约束（现状没有，见设计 §7.1） |
| 码的强度 | ✅ 走站点密码策略 | —— | 允许自定义文本时必须补等价约束 |
| 一人一次 | ❌ 组码可多人复用 | ❌ 可多人用 | 我们现状「单次」比同类更严，保留但要做成可配置 |

---

## 3. 国内同类（功能名 + 官方 URL 级证据）

### 3.1 钉钉（Help Center：help.dingtalk.io，正文以 `.md` 端点取得）

| 功能名 | 官方 URL | 已取证的关键内容 |
|---|---|---|
| **添加组织成员** | https://help.dingtalk.io/zh/contacts/add-organization-members | 「管理员可以通过**手动添加、二维码邀请**等方式邀请员工加入团队，并**给团队员工分配部门**」；摘要句同时点名**邀请链接**与**批量导入** |
| **开启成员邀请** | https://help.dingtalk.io/zh/contacts/enable-member-invitations | 「若企业**主管理员/有通讯录权限的子管理员**开启了允许组织成员邀请他人加入组织功能，企业员工就可以邀请成员加入企业。**若关闭此功能，企业成员和管理员都无法邀请，只能管理员手动添加**」 |
| **管理角色** | https://help.dingtalk.io/zh/contacts/manage-roles | 默认角色（企业负责人=**主管理员权限** / 主管 / 主管理员）+ 自定义角色组；「**主管理员**为默认角色，需要**主管理员**进入【安全与权限 → 权限管理 → 主管理员】添加」 |

**判定**：邀请只解决「进组织」，**层级/角色在加入后由管理员分配**；但「谁能邀请」是**管理员开关**，而且**最高权限只能由最高权限者授予**——与本设计「教务层码仅超管可发」同构（§6 的设计依据之一）。

### 3.2 企业微信（WeCom）

| 功能名 | 官方 URL | 取证程度 |
|---|---|---|
| **如何邀请成员加入企业** | https://open.work.weixin.qq.com/help2/pc/cat?doc_id=14986 | 页面**标题已核实**（"Invite Members to Join a Company - Help Center"）；同页导航抓到 `Contacts Management → Member Management → Add Members / Manage Member Accounts`、`Company Information and Permissions → Permission Management`。**正文由 JS 渲染，未取得 ⇒ 细节未验证** |

**判定**：功能名 + 官方 URL 级证据成立；具体支持的能力（邀请链接/二维码/批量/角色）**标未验证**，见 §5。

### 3.3 飞书（Feishu）

| 功能名 | 官方 URL | 已取证的关键内容 |
|---|---|---|
| **管理员邀请成员加入企业** | https://www.feishu.cn/hc/zh-CN/articles/578016169187-管理员邀请成员加入企业 | 「管理员可在飞书管理后台中通过**直接添加成员、批量导入成员**的方式，邀请成员加入企业」；「管理员也可完善邀请成员功能的相关设置，**允许相关管理员或企业全员**在飞书客户端邀请其他成员加入企业」；注：「对于同时使用多个付费版本的企业，管理员**只能通过飞书管理后台邀请成员**」 |
| **企业成员邀请内部其他成员加入企业** | https://www.feishu.cn/hc/zh-CN/articles/360049067836 | 标题已核实（正文为 JSON 富文本，未逐句取证） |
| 使用企业二维码加入企业 | https://helpdesk.feishu.cn/hc/zh-CN/articles/360040932014 | **仅搜索结果标题级证据，正文未取 ⇒ 未验证** |

### 3.4 校管家（国内教务 SaaS，最贴我们的业务形态）

| 功能名 | 官方 URL | 已取证的关键内容 |
|---|---|---|
| **新手管理员入门手册** | https://wiki.xiaogj.com/docs/xin-shou-ru-men | 「**创建权限组** —— 可以按照**职位、角色**等方式创建权限组，用于在**添加员工时分配权限**」；「**新增员工** —— 除了填写员工信息外，还有以下重要信息需要完善：**创建登录系统的账号 / 分配权限组 / 分配可操作校区/部门**」（页面自注「最近修改: 2024-05-15」） |
| **员工管理** | https://wiki.xiaogj.com/docs/yuan-gong-guan-li | 「**所属权限组** —— 为员工分配对应的权限组，**1 个员工可以分配多个权限组**，分配多个权限组后该员工将拥有多个权限组的权限集合」；另有「**可登录产品**：设置账号需要登录使用的产品」 |
| **权限管理** | https://wiki.xiaogj.com/docs/quan-xian-guan-li | 「每一个操作入口都由权限控制，而众多的权限形成了权限组……」（权限组概念页） |
| **师生信家长端操作使用指南** ⭐ | https://helpcenter.xiaogj.com/help-list/detail-729.html | 「首次登录，需要用**手机号码进行注册**，注册完成后……**登录后需要绑定学员**（可以绑定多个学员），**输入手机号+验证码或账号密码添加即可**」 |

**判定（两条，对本设计直接有用）**：
1. 国内教务 SaaS 的账号体系是「**权限组 + 员工账号**」——**权限组在加员工时分配**，不是「邀请码带层级」。
2. **家长侧是「先自助注册账号、后自助绑定学员」**——这正是我们「层级码不绑人 ⇒ 档案缺口」的同类解法（设计文档 §5 的推荐方案依据）。

---

## 4. 可直接借用的结论（写进设计的那 7 条）

1. **「码 ⇒ 归属」成立**（Moodle 组码 / Canvas join code），所以「层级码」这个方向不是拍脑袋；但**同类都没有「码带系统角色」**，我们要自己把发放权限、有效期、次数收紧。
2. **码的唯一性必须在数据层强制**（Moodle 是表单层查重 + 明确报错），不能只靠人眼与口头沟通。
3. **自定义码文本要有等价于「码表强度」的约束**（Moodle 把组码纳入站点密码策略）；我们现状的 `EDU-XXXXXX` 用了去易混字符的 31 字符表，自定义文本会绕过它。
4. **「一人一次」是更严的选择**，同类都可多人复用；保留，但要做成**可配置**（Moodle 的 `maxenrolled` 就是这个旋钮，0 = 不限）。
5. **「谁能发码」是管理员开关**（钉钉「允许组织成员邀请他人加入组织」），**最高权限只能由最高权限者授予**（钉钉主管理员）——这是「教务码仅超管可发」的同类依据。
6. **码的生命周期要齐**：作废 + 重发（Odoo portal wizard 的 revoke / invite again 就是标准动作），别只做「用掉就没了」。
7. **「先有账号、后绑档案」是行业通行做法**（校管家家长端），因此层级码注册后**不是必须立刻有档案**——但必须给挂接闭环，否则就是新的「看得见点不开」（设计文档 §5）。

---

## 5. 未验证 / 待确认清单（不得当结论用）

| # | 事项 | 状态 | 建议的核实方式 |
|---|---|---|---|
| U1 | **生产库是否安装 `auth_signup`** | 未验证（本机 `installed`） | 生产 PG：`select name,state from ir_module_module where name='auth_signup';` |
| U2 | **生产 `website.auth_signup_uninvited` 取值** | 未验证（本机 `b2b`） | 生产 PG：`select id,name,auth_signup_uninvited from website;` |
| U3 | 生产 `/web/signup` 实际返回码 | 未验证（本机 404） | `curl -s -o /dev/null -w '%{http_code}' -c jar -b jar https://<生产域名>/web/signup` |
| U4 | 企业微信「邀请成员」支持的具体能力（链接/二维码/角色/批量） | 未验证（正文 JS 渲染，仅标题级证据） | 登录态访问帮助中心，或改用官方开放接口文档佐证 |
| U5 | 飞书「使用企业二维码加入企业」正文 | 未验证（仅搜索结果标题） | 打开 helpdesk.feishu.cn 对应页 |
| U6 | 飞书「企业成员邀请内部其他成员」正文细节 | 部分未验证（仅标题 + 相邻页交叉引用） | 同上 |
| U7 | Moodle 官方文档正文（`docs.moodle.org`） | 未验证（Cloudflare 403，带浏览器 UA 亦 403） | 换网络/登录态；或继续以 GitHub 源码为唯一证据源 |
| U8 | Canvas 开发者文档「self-enroll as a student … passing in a valid code」原句 | **摘要级**（来自检索结果，未逐字落盘） | 打开 developer docs Enrollments 页核对 |
| U9 | 教师层码注册后 `group_ids` 写入的实际结果（implied 传播 + portal/internal 互斥约束） | 未验证（**实施时必须实测**） | 本地库上跑一次真实注册，读 `res_groups_users_rel` |
| U10 | 生产「邀请码」后台菜单是否同样被停用（本机 `active=f`，见设计 §2.6） | 未验证 | 生产 PG：`select id,name->>'en_US',active from ir_ui_menu where id=542;` |

---

**参考文献（一手）**
- Odoo 19 源码：`/usr/lib/python3/dist-packages/odoo/addons/{auth_signup,portal,website,base}/`（运行镜像 `odoo:19`，version_info `(19,0,0,FINAL,0,'')`）
- 本仓源码：`custom_addons/edu_portal/{models/invite_code.py,controllers/register.py,controllers/contacts.py,views/invite_code_views.xml,security/ir.model.access.csv,views/group_tuning.xml,models/audit.py,controllers/roles.py}`
- Moodle：https://github.com/moodle/moodle/tree/e68a1418bea512dd5992c29eb9e36570a3844e94
- Canvas：https://github.com/instructure/canvas-lms/tree/1c9f0bb8013ed69c4f2efe11fd483025469b7e6c
- 钉钉帮助中心：https://help.dingtalk.io/zh/contacts/add-organization-members ｜ https://help.dingtalk.io/zh/contacts/enable-member-invitations ｜ https://help.dingtalk.io/zh/contacts/manage-roles
- 校管家帮助中心：https://wiki.xiaogj.com/docs/xin-shou-ru-men ｜ https://wiki.xiaogj.com/docs/yuan-gong-guan-li ｜ https://wiki.xiaogj.com/docs/quan-xian-guan-li ｜ https://helpcenter.xiaogj.com/help-list/detail-729.html
