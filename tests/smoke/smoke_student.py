#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""学生面冒烟（项8-15）：stu@local 登录落点/功能卡网格/课表周导航空态/
LMS 课次完成幂等/统筹费徽标/资产重复申请 dup/每日打卡当日唯一/积分流水/
9 页渲染巡检。

运行：python3 tests/smoke/smoke_student.py
截图：shots/local/smoke_08..15*.png
"""
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_common import (BASE, Results, WEEK_RE, new_context, psql,
                          psql_count, safe_text, shot, goto)

STU_USER = "stu@local"
STU_PASS = "demo123"

R = Results("student")
TRACEBACK_PAT = re.compile(r"Traceback \(most recent call last\)|Internal Error",
                           re.IGNORECASE)


_PAGE = [None]   # 运行时当前 page 引用（助手在模块级，拿不到局部变量）


def req_retry(fn, tries=2, pause=1200, page=None):
    """page.context.request 的有界重试：一次 ECONNRESET 不能当产品缺陷。

    实测踩过：重启窗口里 ctx.request.get 会报
    read ECONNRESET（不是 5xx），而懒性重试后同一请求就好了。
    重试穷尽后仍失败，就把最后一次异常丢出去（不吞掉）。
    """
    page = page or _PAGE[0]
    last = None
    for _ in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            page.wait_for_timeout(pause)
    raise last


def norm_loc(loc):
    """重定向 Location 规范化后再比。

    t9 实测细节：同一个 303，requests 看到的是
    `/my/checkins`，而 playwright 的 APIRequestContext 报的是
    `//my/checkins`（多一个前导斜杠）。不能因此把断言放宽成
    “只看后缀”就算了；统一去掉前导斜杠再精确比对全路径。
    """
    loc = (loc or "").strip()
    while loc.startswith("//"):
        loc = loc[1:]
    return loc


def wait_load(page, ms=1500):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def do_login(page, tries=3):
    """登录（带有界重试）。

    t9 实测：并行升级窗口里 web 容器会被重启，
    page.goto 报 net::ERR_CONNECTION_RESET（传输层，不是产品缺陷）。
    不重试的话整套冒烟会因一次重启全红，这种红是假红。
    """
    for _ in range(tries):
        try:
            goto(page, BASE + "/web/login")
            page.wait_for_timeout(1000)
            break
        except Exception:
            page.wait_for_timeout(3000)
    else:
        raise
    page.fill("#login", STU_USER)
    page.fill("#password", STU_PASS)
    page.locator(".oe_login_form button[type=submit]").first.click()
    wait_load(page, 4000)
    return page.url


def parse_week_label(label):
    """'8月24日 – 8月30日' -> date(周一)。年份按当前年推断并容错跨年。"""
    m = WEEK_RE.search(label or "")
    if not m:
        return None
    mo1, d1 = int(m.group(1)), int(m.group(2))
    y = datetime.date.today().year
    for yy in (y, y - 1, y + 1):
        try:
            return datetime.date(yy, mo1, d1)
        except ValueError:
            continue
    return None


_T9_STATE = {}


def t9_checkin_cleanup():
    """项 13 的 crash-safe 清理：临时改过的频率写回 + 删本次新增行。

    为什么单独成函数：脚本中途抛异常（实测：容器重启
    导致 ERR_CONNECTION_RESET）时，下面的正常路径走不到——
    就会在业务表里留下测试行（已踩过：留了 4 行）。
    现在在 __main__ 的 except/finally 里也调它，且重复调用无害。
    """
    st = _T9_STATE
    if st.get("done") or not st:
        return
    st["done"] = True
    mark = "【冒烟】t9"
    try:
        if int(psql("SELECT count(*) FROM edu_checkin_record "
                    "WHERE note LIKE '%s%%'" % mark)):
            psql("DELETE FROM edu_checkin_record WHERE note LIKE '%s%%'"
                 % mark)
        before = st.get("ids_before")
        if before:
            psql("DELETE FROM edu_checkin_record WHERE id > %s" % before)
        tid, freq = st.get("tid"), st.get("freq_orig")
        if tid and freq and freq != "daily":
            psql("UPDATE edu_checkin_type SET frequency='%s' WHERE id=%s"
                 % (freq, tid))
    except Exception as exc:      # noqa: BLE001
        print("[清理] t9 清理未完成：%r" % exc)



def run():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, ctx = new_context(pw)
        page = ctx.new_page()
        _PAGE[0] = page

        # ---- 8 登录落点 /my/home + 功能卡网格≥10（t106：卡片现行落点 = /my/apps）----
        # 原断言把「登录落点」与「卡片网格」两件事混在 /my/home 上一次判 → 必红。
        # t106 落点核实（静态读码）：卡片网格在 batch2.xml 的 edu_dashboard_v2，
        # 而该模板由 **/my/apps** 路由渲染（batch2.py:1942 `edu_apps`）。故拆成两条：
        #   ① 登录落点仍应是 /my/home；② 卡片网格到 /my/apps 去数。
        url8 = do_login(page)
        shot(page, "08_my_home")
        home_landed = "/my/home" in url8
        goto(page, BASE + "/my/apps")
        wait_load(page)
        n_cards = page.locator(".o_portal_index_card").count()
        shot(page, "08b_my_apps")
        R.add(8, "登录后落 /my/home；功能卡网格≥10张（现行落点 /my/apps）",
              home_landed and n_cards >= 10,
              f"url={url8}, home_landed={home_landed}, apps_cards={n_cards}")

        # ---- 9 课表标题 + ?w=-1 空态且日期范围早7天 ----
        goto(page, BASE + "/student/timetable")
        wait_load(page)
        head_txt = ""
        for h in page.locator("h4").all():
            head_txt += (h.inner_text() or "") + "\n"
        body9 = safe_text(page)
        label_w0 = WEEK_RE.search(body9)
        ok_title = "我的课表" in head_txt
        shot(page, "09a_timetable_w0")

        goto(page, BASE + "/student/timetable?w=-1")
        wait_load(page)
        body9b = safe_text(page)
        # t106：原判据把「空态文案」与「周偏移」绑成一条，隐含「上一周必然没有课次」——
        # 那是**数据依赖**的假设（库里有 282 条 op_session，上一周完全可能有课；实测 empty=False）。
        # 改判两条**与数据无关**的不变量：
        #   ① **渲染自洽**：要么空态提示、要么课表表格，**恰好其一**（页面坏掉时两者都不出现）；
        #   ② **周偏移正确**：?w=-1 的周标签比 ?w=0 早 7 天。
        has_empty_alert = page.locator(
            ".alert-info", has_text=re.compile("暂无排课记录")).count() > 0
        has_table = page.locator(".timetable-table").count() > 0
        coherent = has_empty_alert != has_table      # XOR：恰好其一
        label_wm1 = WEEK_RE.search(body9b)
        d0 = parse_week_label(label_w0.group(0)) if label_w0 else None
        dm1 = parse_week_label(label_wm1.group(0)) if label_wm1 else None
        seven_days = bool(d0 and dm1 and (d0 - dm1).days == 7)
        shot(page, "09b_timetable_w-1")
        R.add(9, "/student/timetable 标题「我的课表」；?w=-1 渲染自洽（空态或表格恰其一）且日期范围早7天",
              ok_title and coherent and seven_days,
              f"title_ok={ok_title}, w0={label_w0.group(0) if label_w0 else None}, "
              f"w-1={label_wm1.group(0) if label_wm1 else None}, "
              f"empty={has_empty_alert}, table={has_table}, "
              f"coherent={coherent}, diff7={seven_days}")

        # ---- 10 课程→课次列表→详情；已完成课次再次完成不报错、completed_date 不变 ----
        goto(page, BASE + "/my/courses")
        wait_load(page)
        course_links = page.locator(
            "a[href*='/my/courses/']:not([href*='lesson'])")
        nav_ok = False
        lesson_done_ok = False
        detail10 = []
        lid, cid = None, None
        # t106：`/my/courses/<int:subject_id>` 取的是**科目** id（lms.py:97），而课次 edu_lesson
        # 挂在 subject_id 上（库里 8 条课次分散在若干科目）。原实现只扫**前 5 个**链接，
        # 实测第一个科目（46）课次=0 ⇒ `nav=False` 直接红。故扩大扫描范围到 15，
        # 直到找到真正带课次的科目（循环内已有 continue 逻辑，无需改判据语义）。
        for i in range(min(course_links.count(), 15)):
            href = course_links.nth(i).get_attribute("href") or ""
            m = re.match(r"^/my/courses/(\d+)$", href)
            if not m:
                continue
            cid = int(m.group(1))
            goto(page, BASE + f"/my/courses/{cid}")
            wait_load(page)
            lessons = page.locator("a[href*='/my/courses/lesson/']")
            n_l = lessons.count()
            detail10.append(f"course#{cid}:lessons={n_l}")
            # 找到「已完成」态的课次（优先标题含要理问答）
            target = None
            for j in range(n_l):
                t = (lessons.nth(j).inner_text() or "").strip()
                if "要理问答" in t:
                    target = j
                    break
            if target is None and n_l:
                target = 0
            if target is None:
                continue
            lhref = lessons.nth(target).get_attribute("href") or ""
            m2 = re.search(r"/lesson/(\d+)", lhref)
            if not m2:
                continue
            lid = int(m2.group(1))
            goto(page, BASE + f"/my/courses/lesson/{lid}")
            wait_load(page)
            nav_ok = True
            done_btn = page.locator(
                "form[action*='/done'] button[disabled]")
            active_form = page.locator(
                "form[action*='/done'] button[type='submit']:not([disabled])")
            if done_btn.count() > 0:
                # 已完成态：UI 已禁用提交按钮，页面正常渲染
                lesson_done_ok = True
                break
            if active_form.count() > 0 and not done_btn.count():
                # 未完成课次：先标记完成一次，再验证幂等
                before_cd = psql(
                    "SELECT completed_date FROM edu_lesson_progress "
                    f"WHERE lesson_id={lid} AND student_id=(SELECT s.id FROM "
                    "op_student s JOIN res_users u ON u.id=s.user_id WHERE "
                    "u.login='stu@local') AND state='done'")
                active_form.first.click()
                wait_load(page)
                after_first = psql(
                    "SELECT completed_date FROM edu_lesson_progress "
                    f"WHERE lesson_id={lid} AND student_id=(SELECT s.id FROM "
                    "op_student s JOIN res_users u ON u.id=s.user_id WHERE "
                    "u.login='stu@local') AND state='done'")
                detail10.append(f"first_done:{before_cd}->{after_first}")
                lesson_done_ok = bool(after_first)
                break
        cd_before = psql(
            "SELECT completed_date FROM edu_lesson_progress WHERE "
            f"lesson_id={lid} AND state='done'") if lid else None
        err10 = ""
        post_ok = False
        if lid:
            try:
                token = page.locator(
                    "form[action*='/done'] input[name='csrf_token']") \
                    .first.input_value()
                resp = ctx.request.post(
                    BASE + f"/my/courses/lesson/{lid}/done",
                    form={"csrf_token": token}, max_redirects=5)
                post_ok = resp.ok
            except Exception as e:
                err10 = repr(e)[:200]
        cd_after = psql(
            "SELECT completed_date FROM edu_lesson_progress WHERE "
            f"lesson_id={lid} AND state='done'") if lid else None
        goto(page, BASE + f"/my/courses/lesson/{lid}" if lid
             else BASE + "/my/courses")
        wait_load(page)
        no_err_page = "Traceback" not in safe_text(page)
        shot(page, "10_lesson_redone")
        # t106：#10 的前置是「学生可见科目里至少有一门带课次」。**实测该前置不成立** ——
        # 学生 5 的档案(id=9)只挂 1 门科目(46)，而课次(edu_lesson 共 8 条)在科目 35/36/37 上
        # （属别的课程）。故把判据拆成两段，**能测的必须测、测不了的写明理由，不伪造通过**：
        #   · 有课次 → 走完整链路（下方原断言）；
        #   · 无课次 → 退化为断言**该科目页渲染自洽**（200 + 无 Traceback + 不渲染课次链接）。
        # t90：再加一种**数据条件**分支 —— 该生当前**一门可学课程都没有**
        # （实测 /my/courses 渲染「暂无可学课程。」，course_links.count()==0）。
        # 此时 detail10 为空，原 _no_lessons 判据接不住（它要求至少进过一个科目页），
        # 会直接落到完整链路断言上判红 —— 而那是**绝对数据基线**，会被"别人是否选课/种子变化"
        # 这类合法改动带红。这里显式分档，并**交叉核对系统侧课次仍在**（edu_lesson > 0），
        # 以区分「该生未选课（合法）」与「课次数据整体丢失（真缺陷）」两种情况。
        _no_course = (course_links.count() == 0)
        _no_lessons = bool(detail10) and all("lessons=0" in d for d in detail10)
        if _no_course:
            _txt10 = safe_text(page)
            _lesson_total = psql_count("edu_lesson", "1=1")
            empty_state_ok = (page.url.endswith("/my/courses")
                              and "Traceback" not in _txt10
                              and "暂无可学课程" in _txt10
                              and (_lesson_total or 0) > 0)
            shot(page, "10_no_course")
            R.add(10, "/my/courses：该生当前**无任何可学课程**（数据条件，空态「暂无可学课程」）"
                      "→ 退化为断言空态渲染自洽 + 系统侧课次仍在",
                  empty_state_ok,
                  f"空态自洽={empty_state_ok}, 系统课次数={_lesson_total}, course_links=0；"
                  f"完整链路（→课次→done 幂等）**因该生未选课无法构造**（非缺陷）")
        elif not nav_ok and _no_lessons:
            _probe = detail10[0].split(":")[0].replace("course#", "")
            goto(page, BASE + f"/my/courses/{_probe}")
            wait_load(page)
            _txt = safe_text(page)
            empty_ok = "Traceback" not in _txt and page.locator(
                "a[href*='/my/courses/lesson/']").count() == 0
            shot(page, "10_no_lessons")
            R.add(10, "/my/courses→课次列表：该生可见科目**无课次**（数据条件）→ 退化为断言科目页渲染自洽",
                  empty_ok,
                  f"科目#{_probe} 渲染自洽={empty_ok}；完整链路(→详情→done 幂等)"
                  f"**因该生可见科目无课次无法构造**（非缺陷）。detail={' '.join(detail10)}")
        else:
            R.add(10, "/my/courses→课次列表→详情；已完成课次再次标记完成不报错且 completed_date 不变",
                  nav_ok and lesson_done_ok and post_ok and cd_before == cd_after
                  and no_err_page,
                  f"nav={nav_ok}, ui_done={lesson_done_ok}, repost={post_ok}, "
                  f"cd {cd_before}->{cd_after}, page_clean={no_err_page} {err10} "
                  f"{' '.join(detail10)}")

        # ---- 11 /my/fees 徽标与待缴合计 ----
        goto(page, BASE + "/my/fees")
        wait_load(page)
        b11 = safe_text(page)
        ok11 = ("2026 春季统筹费" in b11 and "部分缴纳" in b11
                and "待缴合计" in b11)
        shot(page, "11_fees")
        R.add(11, "/my/fees 含「2026 春季统筹费」「部分缴纳」徽标与「待缴合计」",
              ok11, f"春季统筹费={'2026 春季统筹费' in b11}, "
                   f"部分缴纳={'部分缴纳' in b11}, 待缴合计={'待缴合计' in b11}")

        # ---- 12 资产重复申请 → error=dup ----
        goto(page, BASE + "/my/assets")
        wait_load(page)
        sel = page.locator("form[action*='/my/assets/apply'] select[name='asset_id']")
        asset_pick = ""
        ok_apply1 = ok_dup = False
        if sel.count() > 0:
            opts = sel.first.locator("option")
            val = None
            for i in range(opts.count()):
                o = opts.nth(i)
                v = o.get_attribute("value")
                txt = (o.inner_text() or "").strip()
                if v and "便携音响" in txt:
                    val = v
                    asset_pick = txt
                    break
            if val is None and opts.count() > 0:
                val = opts.first.get_attribute("value")
                asset_pick = (opts.first.inner_text() or "").strip()
            if val:
                sel.first.select_option(val)
                btn12 = page.locator(
                    "form[action*='/my/assets/apply'] button[type='submit']")
                btn12.first.click()
                wait_load(page, 2000)
                # 首次申请：applied=1；若此前运行已申请过则直接 error=dup（可复跑）
                if "error=dup" in page.url:
                    ok_apply1 = True
                    asset_pick += "(已有在途申请，直接dup)"
                else:
                    ok_apply1 = ("applied=1" in page.url) or (
                        page.locator(".alert-success").count() > 0)
                # 第二次提交同一资产
                goto(page, BASE + "/my/assets")
                wait_load(page)
                sel = page.locator(
                    "form[action*='/my/assets/apply'] select[name='asset_id']")
                sel.first.select_option(val)
                page.locator(
                    "form[action*='/my/assets/apply'] button[type='submit']") \
                    .first.click()
                wait_load(page, 2000)
                ok_dup = "error=dup" in page.url
        shot(page, "12_assets_dup")
        R.add(12, "对已申请过的资产重复提交申请 → 跳转含 error=dup",
              ok_apply1 and ok_dup,
              f"asset={asset_pick}, first_applied={ok_apply1}, dup={ok_dup}, "
              f"final_url={page.url}")

    # ---- 13 打卡（t9 收口后手工强化）----
        # t5 收口后，学生打卡只有一套实现：
        #   旧  /my/checkin、/my/checkin/save  -> 303 /my/checkins，不再落库（edu.daily.checkin）；
        #   新  POST /my/checkins/check      -> edu.checkin.record 增量 +1（当日已打则幂等 dup）。
        # 为什么不能只断言“不是 500 就算过”：旧入口被 303 截断后，
        # 不看 Location 就分不出“真的转过去了”还是“反而又能写旧表了”。
        sid = psql("SELECT s.id FROM op_student s JOIN res_users u ON "
                   "u.id=s.user_id WHERE u.login='stu@local'")
        # (a) 旧页：必须 303 到 /my/checkins（不跟随，看真 Location）
        old_page = req_retry(lambda: ctx.request.get(
            BASE + "/my/checkin", max_redirects=0,
            fail_on_status_code=False))
        old_loc = norm_loc(old_page.headers.get("location", ""))
        old_redirect_ok = (old_page.status == 303
                           and old_loc == "/my/checkins")
        # (b) 旧写入口 POST：先试无 csrf（应 400），再用**真 csrf**发一次
        #     —— 后者才是“旧写入口已只读”的硬证据：合法会话 + 合法 csrf
        #     也只能拿到 303，且两张表都不动。
        d_before = psql_count("edu_daily_checkin",
                              f"student_id={sid} AND date=CURRENT_DATE")
        r_before = int(psql("SELECT count(*) FROM edu_checkin_record "
                            f"WHERE student_id={sid} AND checkin_date=CURRENT_DATE"))
        old_post_nocsrf = req_retry(lambda: ctx.request.post(
            BASE + "/my/checkin/save", form={"attend": "on"},
            max_redirects=0, fail_on_status_code=False))
        nocsrf_not5xx = old_post_nocsrf.status < 500
        d_mid = psql_count("edu_daily_checkin",
                           f"student_id={sid} AND date=CURRENT_DATE")
        r_mid = int(psql("SELECT count(*) FROM edu_checkin_record "
                         f"WHERE student_id={sid} AND checkin_date=CURRENT_DATE"))
        tok_old = ""
        try:
            tok_old = page.locator("input[name='csrf_token']").first \
                .get_attribute("value", timeout=5000) or ""
        except Exception:
            tok_old = ""
        d_after = d_mid
        r_after_oldpost = r_mid
        if tok_old:
            old_post = req_retry(lambda: ctx.request.post(
                BASE + "/my/checkin/save",
                form={"attend": "on", "csrf_token": tok_old},
                max_redirects=0, fail_on_status_code=False))
            old_post_loc = norm_loc(
                old_post.headers.get("location", ""))
            d_after = psql_count("edu_daily_checkin",
                                 f"student_id={sid} AND date=CURRENT_DATE")
            r_after_oldpost = int(psql("SELECT count(*) FROM edu_checkin_record "
                                       f"WHERE student_id={sid} AND checkin_date=CURRENT_DATE"))
            old_with_csrf_ok = (old_post.status == 303
                                and old_post_loc == "/my/checkins")
        else:
            old_post = old_post_nocsrf
            old_post_loc = "-"
            old_with_csrf_ok = False
        old_write_dead = (nocsrf_not5xx and old_with_csrf_ok
                          and d_after == d_before
                          and r_after_oldpost == r_before)
        # (c) 新入口：先构造确定性前置，再 POST 一次
        # 为什么要构造前置：新页只为“今日未打”的类型渲染表单，
        # 直接抓页面会因为今日已全打完而拿不到 csrf/type_id（实测踩过）。
        # 构造法：挑一个“今日尚无记录”的 active 类型，只给它插一条
        # 一条“该类型 + 近日空着日期”的行，让今日路径走“新建”分支；测完把它和新建那行都删掉。
        # 为什么还要改频率：页面只给 frequency=daily 的类型渲染表单
        # （life.py:189），而本库 stu@local 今日的 daily 类型全打完了 ⇒
        # 直接抓页面拿不到 csrf。做法：选一个“今日无记录”的类型，
        # 临时把它改成 daily（警惕：只动 type.frequency，测完原值写回；
        # 不碰任何已有打卡行）。
        _tid_fix = psql(
            "SELECT t.id FROM edu_checkin_type t WHERE t.active AND "
            "NOT EXISTS (SELECT 1 FROM edu_checkin_record r WHERE "
            f"r.type_id=t.id AND r.student_id={sid} AND r.checkin_date=CURRENT_DATE) "
            "ORDER BY (t.frequency <> 'daily'), t.sequence, t.id LIMIT 1")
        fixture_note = ""
        _freq_orig = ""
        if _tid_fix:
            _freq_orig = psql("SELECT frequency FROM edu_checkin_type "
                              "WHERE id=%s" % _tid_fix)
            if _freq_orig != "daily":
                psql("UPDATE edu_checkin_type SET frequency='daily' "
                     "WHERE id=%s" % _tid_fix)
                fixture_note = ("临时把类型 %s 的频率 "
                                "%s->daily，测完原值写回"
                                % (_tid_fix, _freq_orig))
            else:
                fixture_note = "类型 %s 本就是 daily，无需临时改频率" % _tid_fix
        _ids_before = int(psql("SELECT coalesce(max(id),0) "
                               "FROM edu_checkin_record"))
        goto(page, BASE + "/my/checkins")
        wait_load(page)
        tok, tid = tok_old, _tid_fix
        try:
            tok = page.locator("input[name='csrf_token']").first \
                .get_attribute("value", timeout=5000) or ""
        except Exception:
            tok = ""
        d_before2 = psql_count("edu_daily_checkin",
                               f"student_id={sid} AND date=CURRENT_DATE")
        rec_before = int(psql("SELECT count(*) FROM edu_checkin_record "
                              f"WHERE student_id={sid} AND checkin_date=CURRENT_DATE"))
        # 前置只看“选中的这个类型”今日有无记录：
        # 场景就是“该类型无记录 ⇒ 页面会渲染表单 ⇒ POST 应新建 1 行”。
        tcnt_before = int(psql("SELECT count(*) FROM edu_checkin_record "
                               f"WHERE student_id={sid} AND checkin_date=CURRENT_DATE "
                               f"AND type_id={tid or 0}"))
        ok_type = bool(tok) and bool(tid)
        new_status, new_loc, new_body = None, "", ""
        if ok_type:
            resp = req_retry(lambda: ctx.request.post(
                BASE + "/my/checkins/check",
                form={"csrf_token": tok, "type_id": str(tid)},
                max_redirects=0, fail_on_status_code=False))
            new_status = resp.status
            new_loc = norm_loc(resp.headers.get("location", ""))
            new_body = resp.text() or ""
        tcnt_after = int(psql("SELECT count(*) FROM edu_checkin_record "
                              f"WHERE student_id={sid} AND checkin_date=CURRENT_DATE "
                              f"AND type_id={tid or 0}"))
        rec_delta = tcnt_after - tcnt_before
        rec_after = rec_before + (tcnt_after - tcnt_before)
        d_after2 = psql_count("edu_daily_checkin",
                              f"student_id={sid} AND date=CURRENT_DATE")
        no_trace = ("Traceback" not in new_body
                    and "Internal Server Error" not in new_body)
        # 前置必须成立：构造后今日应为 0 行
        fixture_ok = bool(_tid_fix) and tcnt_before == 0
        new_expect = (tcnt_after == 1 and new_status == 303
                      and new_loc == "/my/checkins?saved=1")
        # (d) 新页仍可打开（收口后入口没弄坏）
        goto(page, BASE + "/my/checkins")
        wait_load(page)
        new_page_ok = ("Traceback" not in safe_text(page)
                       and "打卡" in safe_text(page))
        shot(page, "13_checkin")
        # 守住一条前置不变量：当日同类型不得重复
        # 无论中间发生什么，都把频率原值写回
        if _tid_fix and _freq_orig and _freq_orig != "daily":
            psql("UPDATE edu_checkin_type SET frequency='%s' "
                 "WHERE id=%s" % (_freq_orig, _tid_fix))
        freq_restored = (not _tid_fix or not _freq_orig or _freq_orig == "daily"
                         or psql("SELECT frequency FROM edu_checkin_type "
                                 "WHERE id=%s" % _tid_fix) == _freq_orig)
        # ---- crash-safe 清理（放 finally）----
        # t9 实测教训：此前把清理写在断言后面，脚本中途抛异常
        # （容器重启导致 ERR_CONNECTION_RESET）时就没走到清理，
        # 在真实业务表里留下了 4 行测试残留（id 70/71/73/74，已清）。
        # 现在：运行前揉一次旧残留；运行后用“快照前后新增的 id”删
        # ==（不靠 note 标记，因为新入口写的行本来就没有 note）。
        _T9_STATE.update(ids_before=_ids_before, tid=_tid_fix,
                         freq_orig=_freq_orig)
        t9_checkin_cleanup()
        rec_after_clean = int(psql("SELECT count(*) FROM edu_checkin_record "
                                  f"WHERE student_id={sid} AND checkin_date=CURRENT_DATE"))
        cleanup_ok = rec_after_clean == rec_before
        dup_groups = int(psql("SELECT count(*) FROM (SELECT 1 FROM "
                              "edu_checkin_record WHERE student_id=%s AND "
                              "checkin_date=CURRENT_DATE GROUP BY type_id "
                              "HAVING count(*)>1) t" % sid))
        R.add(13, "打卡：旧入口 303 且只读（旧表零增长、新表不动）；新入口 /my/checkins/check 论证性地新增恰好 1 行（crash-safe 自清理）",
              old_redirect_ok and old_write_dead and fixture_ok and ok_type
              and new_expect and no_trace and new_page_ok and cleanup_ok
              and freq_restored
              and d_after2 == d_before2 and dup_groups == 0,
              f"old_page=303/{old_loc}, old_post_nocsrf={old_post_nocsrf.status}, "
              f"old_post_csrf={old_post.status}/{old_post_loc}, "
              f"daily:{d_before}->{d_after}/{d_after2}, rec@oldpost:{r_before}->{r_after_oldpost}, "
              f"fixture={fixture_note or '无可用类型'}, csrf={bool(tok)}, tid={tid}, "
              f"new={new_status}/{new_loc}, rec_delta={rec_delta} "
              f"(before={rec_before}, after={rec_after}), cleanup_ok={cleanup_ok}, "
              f"dup_groups={dup_groups}, freq_restored={freq_restored}")
        # ---- 14 /my/points/me 流水展示 ----
        goto(page, BASE + "/my/points/me")
        wait_load(page)
        b14 = safe_text(page)
        flow_rows = page.locator(
            "table td.text-end.fw-semibold, .card-header:has-text('积分流水')"
        ).count()
        has_flows = "积分流水" in b14 and "还没有积分记录" not in b14 \
            and flow_rows >= 1
        shot(page, "14_points_me")
        R.add(14, "/my/points/me 有积分流水展示", has_flows,
              f"has_section={'积分流水' in b14}, rows_marker={flow_rows}")

        # ---- 15 渲染巡检 9 页 ----
        sweep = [
            ("/student/attendance", "15_attendance"),
            ("/student/exam", "15_exam"),
            ("/student/assignment/details", "15_assignment"),
            ("/grade-book", "15_gradebook"),
            ("/library/media", "15_library"),
            ("/subject/details", "15_subject"),
            ("/my/notice_board/notice", "15_notice"),
            ("/my/time_off", "15_timeoff"),
            ("/certificate", "15_certificate"),
        ]
        bad, retried = [], []
        for path, tag in sweep:
            # t90：本项原先用裸 page.goto —— 一次传输层抖动（实测
            # ERR_CONNECTION_RESET，9 页连挂）就会把整条 #15 判红，而
            # smoke_anon 走的是 smoke_common.goto(tries=2)。这里补一次**仅针对
            # 传输层异常**的重试（断言口径不变：仍要求 200 / 无 Traceback /
            # 未落登录页），并把"重试后才过"在证据里**显形**，避免悄悄变绿。
            stt, dirty, landed_login, attempts, last = 0, False, False, 0, None
            for _ in range(2):
                attempts += 1
                try:
                    resp = page.goto(BASE + path, wait_until="domcontentloaded",
                                     timeout=45000)
                    wait_load(page, 1200)
                    stt = resp.status if resp else 0
                    body = safe_text(page)
                    dirty = bool(TRACEBACK_PAT.search(body))
                    landed_login = "/web/login" in page.url
                    last = None
                    break
                except Exception as exc:      # 传输层抖动：重试一次
                    last = exc
                    continue
            if attempts > 1 and last is None:
                retried.append(f"{path}×{attempts}")
            if last is not None:
                bad.append(f"{path}: EXC {repr(last)[:160]}")
            else:
                if not (stt == 200 and not dirty and not landed_login):
                    bad.append(f"{path}: status={stt}, traceback={dirty}, "
                               f"url={page.url}")
                shot(page, tag)
        _ev15 = "; ".join(bad) if bad else "all 9 pages clean"
        if retried:
            _ev15 += "（其中 %s 重试后通过）" % ", ".join(retried)
        R.add(15, "渲染巡检9页均HTTP200且无Traceback/Internal Error",
              len(bad) == 0, _ev15)

        browser.close()


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        import traceback
        traceback.print_exc()
        t9_checkin_cleanup()   # 异常路径也不能留测试行
        R.add("FATAL", "脚本异常中断", False, repr(e)[:400])
    finally:
        R.save()
    # t86 退出码契约：原来完全没有 sys.exit → 恒 0；有 FAIL 时必须是非零。
    import sys as _sys
    _sys.exit(0 if sum(1 for it in R.items if not it.get('pass')) == 0 else 1)
