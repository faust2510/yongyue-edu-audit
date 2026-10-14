# 登录页美化（superdesign，2026-10-06）

> 校长：「登录页面的UI能不能也优化一下？」沿用首页那套打法：**看现状 → 出稿 → 翻译进真站 → 真渲染验证 → 部署**。

## 一、现状（改前实测）

| 问题 | 读数 |
|---|---|
| 表单挤在上半屏、下方大片纯白空 | 容器 600px 高，页面 1000px |
| 提交按钮是 A 套工作台蓝 | `class="btn btn-primary"`，`bg=rgb(12,109,215)` |
| 重置密码等链接也是蓝 | `btn-link` + 两个裸 `<a>` |
| 表单区无品牌元素 | 校徽只出现在页脚 |

## 二、安全核对（顺手做的一件事）

本地登录页上有一排「选择你的身份」按钮（学生/教师/家长/教务/管理员），类名 `demo-login-btn` —— **看着像生产泄露**。
读源码后确认**是安全的**：

- 渲染条件是系统参数 `edu.dev_quick_login == '1'`（`edu_portal/views/batch3.xml:1288`）；
- 实测**生产库该参数 `<未设置>`**、本地克隆为 `1`（对照组）；
- 按钮**只填用户名**（`data-username`），注释写明「密码永不写入页面、永不自动提交」（2026-08-24 安全规格）。

生产站复验：`hasDemoButtons: false` ✓。

## 三、设计稿

| 项 | 值 |
|---|---|
| draftId | `958b491a-edc1-4913-9cce-1e37539e9f22`（永约学坊学生门户登录） |
| 预览 | https://p.superdesign.dev/draft/958b491a-edc1-4913-9cce-1e37539e9f22 |
| 模型 | `gemini-3.1-pro`（免费档）｜20.5 credits |

## 四、落地（只改两个文件，不碰 Odoo 基座）

**`views/login.xml`** —— 新增 `yy_login_brand_head`，inherit `web.login`，在 `csrf_token` 前插入校徽 + 校名 + 「学生与教务门户」。
校徽复用页脚那枚 `logo-medallion.png`；「学生与教务门户」取自本模块既有页脚文案，**非新造**；**不动任何既有表单控件**（输入框 name 逐字不变）。

**`static/src/css/brand.css`** —— 新增登录页样式段，**作用域 `.oe_website_login_container`**（登录页专属容器，实测是 form 的父级）⇒ 不会外溢。

| 项 | 改前 | 改后 |
|---|---|---|
| 页面底 | 纯白 | 暖纸渐变 `linear-gradient(165deg,#f7f2eb,#fdfaf6,#f3ece1)` |
| 表单 | 300px 裸表单、无卡片 | 420px 卡片、底 `rgba(255,255,255,.8)`、圆角 16px、淡金描边 |
| 容器高 | 600px（下方空白） | 930px（撑满视口，页脚自然落底） |
| 提交按钮 | `#0C6DD7` 蓝 | 金色渐变胶囊 + 金色柔光 |
| 链接 | 蓝 | `#836a42` 金（纸底对比度 ≥4.5 的一档） |

## 五、验证（生产站真渲染复量）

```
https://edu.example.org/login
  hasCrest true ✓  hasName true ✓  hasDemoButtons **false** ✓
  formBg rgba(255,255,255,0.8) ✓  formRadius 16px ✓
  btnGradient linear-gradient(135deg, rgb(231,215,184), …) ✓  btnRadius 999px ✓
  contGradient linear-gradient(165deg, rgb(247,242,235), …) ✓
```

**模板改动确实到了生产**（校徽与校名在线上显示 ✓）—— 说明 `web.login` 的 inherit **不受**首页那套 COW 机制影响。

## 六、遗留

- 设计稿用了 Tailwind / iconify / Google Fonts 三个外部 CDN（简报里禁止）⇒ 与首页那次一样，**只当设计参考**，落地时全部换成站内已有的 Bootstrap + 系统字体栈；
- 稿子里的校徽位置是占位「YY」，落地时换成了**真校徽**。