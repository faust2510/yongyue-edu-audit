#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨角色访问「只该某角色看」的页面 —— **报告型越权探针**。

## 为什么立它（2026-10-03）

前 37 轮的验收轴覆盖了渲染、错误路径、翻译、可访问性，但**没验过「不该看见的能不能看见」**。
门户有 50+ 条带对象 id 的 GET 路由，这是标准的**越权（IDOR）**表面 —— 值得做成可复跑的探针，
而不是靠「默认它是对的」。

## 判据（看的是**结果**，不是路由有没有守卫）

| 档 | 判据 |
|---|---|
| ✅ 正确拒绝 | 非授权角色访问 ⇒ 落到 `/my/home`、403、或 404（**且不是 200**） |
| ✅ 正确放行 | 授权角色访问 ⇒ 200 且内容类型符合预期 |
| ⛔ 越权 | 非授权角色拿到 **200 且停在原 URL**（= 看到了不该看的） |

退出码：0=无越权 ｜ 1=有越权 ｜ 2=ENV（登录失败）—— **2 不是通过**。

## 本机实测（2026-10-03，edu19 克隆库）

· 13 条「教务/教师专属详情页」用**学生**身份打 ⇒ **全部落 `/my/home`**，0 条 200；
· `/my/child/<id>` 用**学生**身份打 ⇒ 落 `/my/child`（学生不是家长）；
· 证书下载 `/my/certificate/download/3`（证书本人 = 学生 5）：
  本人 ✅ 200 PDF ／ 教务 ✅ 200 PDF ／ 教师 ✅ 200 PDF（守卫放行「本人 or 内部用户」）／
  家长 ⛔ 404 —— 但是**家长页面上根本没有指向它的链接**（`/certificate` 对家长显示「暂未获得结业证…」空态），
  所以**不构成断链**；守卫注释本身就写明「仅本人或内部用户」，属**有意**的授权范围。

## 第 84 轮补充：加了 3 条**对象级文件/下载**路由

第 69 轮补教师侧附件时意识到：**带对象 id 的文件口最容易漏归属校验** ——
拿到别人的附件就是 IDOR，比看到别人的姓名严重得多。实测：

```
/my/assignment/sub/3/file   [faculty   ] 303  ✅ 已挡（守卫按 current_student() 判归属）
/my/assignment/sub/3/file   [backoffice] 303  ✅ 已挡
/my/child/5/leave           [faculty   ] 303  ✅ 已挡
```

**量具自证**（照本仓规矩：修完的检查要能红）：往 SHOULD_NOT_SEE 里塞一条
「学生本来就能看」的页面（`/my/home`）⇒ 探针立刻报
`⛔ 越权（200 且有内容）｜ RESULT=FOUND（1 处）` ⇒ 绿灯是有意义的。
"""
import sys

BASE = "http://127.0.0.1:8069"
LOGINS = {"student": ("stu@local", "demo123"),
          "faculty": ("faculty@local", "demo123"),
          "backoffice": ("backoffice@local", "demo123"),
          "parent": ("parent@local", "demo123")}

# (路径, 用什么身份打, 该身份【不该】拿到 200)

SHOULD_NOT_SEE = [
    ("/leave/approvals/241", "student"),
    ("/grievances/approvals/1", "student"),
    ("/assignment/edit/1", "student"),
    ("/assignment/submissions/1", "student"),
    ("/registrar/subject/approvals/1", "student"),
    ("/assess/tasks/1", "student"),
    ("/assess/templates/1", "student"),
    ("/assess/tasks/1/roster", "student"),
    ("/journals/review/1", "student"),
    ("/grading/entry", "student"),
    ("/assess/student/5/history", "student"),
    ("/my/child/5", "student"),
    # 2026-10-04（第 84 轮）加：**带对象 id 的文件/下载路由** —— 第 69 轮补教师侧附件时
    #   意识到这类口子最容易漏归属校验：拿到别人的附件就是 IDOR（比看到别人姓名严重得多）。
    #   `/my/assignment/sub/3/file` 是**学生自己**的附件口（sid=3 属学生 5），
    #   守卫是 `sub.student_id.id != current_student().id` ⇒ 非学生身份不该拿到 200。
    ("/my/assignment/sub/3/file", "faculty"),
    ("/my/assignment/sub/3/file", "backoffice"),
    ("/my/child/5/leave", "faculty"),
    # 2026-10-04（第 93 轮）：**跨学生**越权（此前探针只测跨角色，没测过「另一个学生」）。
    #   库里除王小明（学生 5 / stu@local）外还有 3 个有账号的学生：452(dsh_a) / 453(dsh_b) /
    #   576(empty@local)，其 user_id 分别是 624 / 625 / 820 —— 用学生 5 的身份去够它们。
    #   实测全部被挡（私信回 /my/messages?denied=1，其余弹回 /my/child 或 /my/home），
    #   且响应里**不含**他人姓名。这里固化成回归项。
    ("/my/messages/624", "student"),        # 学生452 的私信
    ("/my/messages/625", "student"),        # 学生453 的私信
    ("/my/messages/820", "student"),        # 空态学生的私信
    ("/my/child/452", "student"),           # 把学生452 当自己孩子
    ("/my/child/452/leave", "student"),     # 替学生452 请假
    ("/assess/student/452/history", "student"),   # 学生452 的评估史
    ("/assess/child/452/history", "student"),     # 学生452 的评估史（家长口）
    # 2026-10-04（第 94 轮）：继续补第 93 轮量出来的那 36 条未覆盖项。
    #   这些都是「不该这个角色看」的页面，id 取自库里真实存在的对象：
    #   考试 11 / 课次 293 / 注册单 10 / 测验 1 / 作答 10 / 批次 8。
    ("/timetable/batch/8/deactivate", "student"),     # 批量停用课时（只读确认页，教务专属）
    ("/timetable/session/293/impact", "student"),     # 课次影响面（教务工具）
    ("/student/exam/data/11", "parent"),              # 考试数据（家长不该看学生端数据）
    ("/quiz/1/result/10", "parent"),                  # 别人的测验作答结果
    ("/quiz/1/take", "parent"),                       # 家长去参加测验
    ("/my/rollcall/293", "parent"),                   # 点名（教师侧）
    ("/my/marks/11", "parent"),                       # 录分（教师侧）
    ("/subject/registration/data/10", "parent"),      # 注册单数据
    ("/assess/task/1/results", "student"),            # 整任务的评估结果（学生只看自己的）
    ("/assess/grade/1", "student"),                   # 整班打分（教师专属）
    ("/assess/fill/1", "parent"),                     # 家长去填学生评教
]

# 2026-10-04（第 94 轮）：**200 不等于泄露** —— 本仓有多处守卫用的是「200 + 一句拒绝文案」
#   （edu_telegram 的 ops_message 就是这种：`/my/rollcall` 回「无此课或不是你的课。」、
#     `/my/marks` 回「无此考试或不是负责人。」—— 状态码 200，正文里**没有任何真实数据**）。
#   第 94 轮我先按「200 且有内容」把这两条判成越权，人工复核后确认是**假阳性**。
#   ⚠ 这类假阳性必须查清后落进判据，否则探针会永远红着 —— **永远红的检查等于死的检查**。
_REFUSAL_MARKERS = ("无此", "不是你的", "不是负责人", "无权", "仅面向",
                    "请返回门户首页使用与您身份对应的功能", "Access Denied")


# (路径, 身份, 期望出现在响应里的特征) —— 授权角色应当能拿到
SHOULD_SEE = [
    ("/my/certificate/download/3", "student", "%PDF"),
]


def main():
    import sys as _sys
    selftest = "--selftest" in _sys.argv
    if selftest:
        # 2026-10-04（第 101 轮）加：此前红证是拿临时副本做的（改一条 SHOULD_NOT_SEE 再跑），
        #   那样**下一个人复现不了**。这里固化成开关：塞一条「学生本来就能看、
        #   且不含任何拒绝文案」的页面（/my/home）⇒ 必须被判越权。
        SHOULD_NOT_SEE[:] = [("/my/home", "student")]
    from playwright.sync_api import sync_playwright
    bad = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        cache = {}

        def sess(role):
            if role in cache:
                return cache[role]
            ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            pg = ctx.new_page()
            pg.goto(BASE + "/web/login", timeout=45000)
            pg.wait_for_selector("form.oe_login_form", timeout=30000)
            u, pw = LOGINS[role]
            pg.fill("form.oe_login_form input[name=login]", u)
            pg.fill("form.oe_login_form input[name=password]", pw)
            pg.click("form.oe_login_form button[type=submit]", timeout=30000)
            pg.wait_for_load_state("load", timeout=45000)
            if "/web/login" in pg.url:
                return None
            cache[role] = ctx
            return ctx

        print("=== 不该看见的（非授权角色）===")
        for path, role in SHOULD_NOT_SEE:
            ctx = sess(role)
            if ctx is None:
                print("SKIP-ENV：%s 登录失败 —— 这不是通过" % role)
                return 2
            # ⚠ 必须 `max_redirects=0`：本仓的越权守卫大多是 `redirect('/my/home')`，
            #   而 **APIRequestContext 默认跟随重定向** ⇒ 落到 /my/home 也是 200 且有内容，
            #   于是「200 且无登录表单」会把**被正确挡下**的也算成越权。
            #   （本工具第一版就是这个错，一跑就报 12 条越权，与先前 fetch 实测「全部落 /my/home」直接矛盾 ——
            #    矛盾的读数就是 bug 的信号，别当成「发现了 12 个漏洞」。）
            r = ctx.request.get(BASE + path, max_redirects=0)
            body = r.body()
            refused_text = any(m.encode() in body for m in _REFUSAL_MARKERS)
            leaked = (r.status == 200 and b"oe_login_form" not in body
                      and not refused_text)
            if r.status in (301, 302, 303, 307, 308):
                mark = "✅ 已挡（%d 重定向）" % r.status
            elif leaked:
                mark = "⛔ 越权（200 且有内容）"
            else:
                mark = "✅ 已挡（%d）" % r.status
            if leaked:
                bad.append((path, role, r.status))
            print("  %-34s [%-10s] %-4s %s" % (path, role, r.status, mark))

        print("=== 该看见的（授权角色）===")
        for path, role, needle in SHOULD_SEE:
            ctx = sess(role)
            if ctx is None:
                print("SKIP-ENV：%s 登录失败 —— 这不是通过" % role)
                return 2
            r = ctx.request.get(BASE + path, max_redirects=0)
            body = r.body()
            ok = r.status == 200 and needle.encode() in body[:16]
            mark = "✅ 放行" if ok else "⛔ 被误挡"
            if not ok:
                bad.append((path, role, r.status))
            print("  %-34s [%-10s] %-4s %s（%d 字节）" % (path, role, r.status, mark, len(body)))

        for ctx in cache.values():
            ctx.close()
        b.close()
    if selftest:
        caught = any(p == "/my/home" for p, _r, _s in bad)
        print("  自证：拿学生本来就能看的页面冒充越权，%s"
              % ("被抓到（对）" if caught else "**没抓到 —— 量具坏了**"))
        return 0 if caught else 1
    if bad:
        print("RESULT=FOUND（%d 处）" % len(bad))
        return 1
    print("RESULT=OK（越权 0 条；该放行的也放行了）")
    return 0


if __name__ == "__main__":
    sys.exit(main())