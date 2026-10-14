# -*- coding: utf-8 -*-
"""学生端统一搜索（v2-A5）：作业 / 课程科目 / 布告 / 账单。

辅助增强包 3a 扩组：资料下载（按可见范围）/ 校历活动 / 在线测验 /
LMS 课次 / 本人请假与申诉。

v3 搜索可用性修复（2026-09-29，用户定性：「搜『资料下载』啥也没有」）：
  ① 原实现只搜**记录名**（作业 / 科目 / 文件名 …），**没有「应用 / 入口」这一层**。
     用户输入的是**应用的名字**（资料下载 / 校历 / 通讯录），而「资料」分组查的是
     edu.download.file.name（**文件名**）⇒ 搜「资料下载」必然 0 条。
     修法见下方 _panel_entries()：**不新建第二份应用清单** —— 入口集合直接取自
     门户宫格引擎 batch2._home_categories（/my/home 与 /my/apps 的同一数据源），
     于是「搜索里看得见」= 「宫格上看得见」，而宫格卡片本来就点得进去。
  ② 新增 JSON 建议端点 /my/search/suggest（输入即出、分组、入口优先）+ 顶栏下拉
     建议（static/src/js/search_suggest.js）。**渐进增强**：脚本不可用时下方表单
     仍是原来的 GET /my/search，行为一字未变。
"""
import time

from odoo import fields, http
from odoo.http import request

from .batch2 import _home_categories, _notice_audience_codes
from .main import assignment_scope_domain
from .downloads import _visibility_domain
from .lms import _subjects_for
from .main import current_student, student_course
from .roles import current_parent


# ---------------------------------------------------------------------------
# 应用入口索引（唯一来源 = 门户宫格引擎，不另造清单）
# ---------------------------------------------------------------------------
# 别名：用户嘴里的词 → 宫格卡片的 app_href。**只登记「导航标签与卡片名不同、
# 但落地页是同一个」的那几个**（左导航「课表」/「成绩册」/「消息」等）。
# 运行时护栏：别名目标**不在**当前用户可见入口集合里就完全不生效
# （见 _entry_hits），所以别名永远造不出用户看不到的入口。
_ENTRY_ALIASES = {
    '课表': 'my/calendar',        # 左导航「课表」→ /my/calendar；卡片名是「校历」
    '教学安排': 'my/calendar',     # 教师侧左导航同名不同词
    '成绩册': 'grade-book',        # 左导航「成绩册」；卡片名是「成绩簿」
    '消息': 'my/messages',         # 左导航「消息」；卡片名是「私信」
    '资料库': 'downloads',
}


# 入口索引短缓存（队长裁定 2026-09-29：**保留**，勿当 bug 删）。
#
# 为什么需要：宫格引擎一次构建要跑 ~40 个计数查询（宫格自己一次渲染只跑一遍），
# 而建议端点是**每键一请求** —— 不缓存就是「每敲一个键跑 40 个计数查询」。
#
# 为什么可以接受：缓存的是**宫格投影**（title/href/desc/app_href），不是第二份入口
# 清单 —— 过期即从宫格重建，两处不会漂移。陈旧窗口最长 30s，最坏情形是「刚被收回
# 权限的人仍看到那张入口卡」，而**点进去会被落地页自己的守门弹回**（搜索只负责
# 「看得见的入口点得进去」；可见性判据仍由各页守卫与宫格持有）——与宫格本身同口径。
#
# 什么情况下该去掉它：① 出现「入口卡可搜到、点进去也真能进去」的越权实例（那说明
# 落地页守卫本身漏了，先修守卫，别只删缓存）；② 有人要求入口可见性做到秒级一致
# （例如权限变更后必须立刻不可搜）。去掉的代价 = 每键一请求各跑约 40 个计数查询。
_ENTRY_CACHE_TTL = 30.0
_ENTRY_CACHE = {}


def _panel_entries():
    """当前登录用户**可见的应用入口** [{title, href, desc, app_href, icon}]。

    数据源是 batch2._home_categories(student) —— 门户宫格（/my/home 对
    学生/家长、/my/apps 对内部用户）的**唯一构建者**。这里只做投影，不复制
    任何身份/权限规则：改宫格就是改搜索，两处不会漂移。

    刻意剔除的三种「非入口」：
      · 提醒分组（portal_alert_category）—— 那是数据驱动的待办提醒，不是应用；
      · href 不以 '/' 开头（'#' 锚点）—— 不是页面；
      · 未登记卡片的**收藏占位卡**（title == app_href）：edu.favorite 里存着
        宫格认不出的 href 时，_build_favorites 会造一张 title=href 的占位卡；
        那种 href 不在任何角色可见清单内，放它进搜索就等于把「脏数据」当入口。
    """
    student = current_student()
    key = (request.env.uid, student.id if student else 0)
    now = time.time()
    hit = _ENTRY_CACHE.get(key)
    if hit and now - hit[0] < _ENTRY_CACHE_TTL:
        return hit[1]
    try:
        cats = _home_categories(student)
    except Exception:
        # 宫格引擎任何一步失败（缺模型 / 数据异常）都不该让搜索 500：
        # 退化到「没有入口组」，内容搜索照旧。
        return []
    out, seen = [], set()
    for cat in (cats or []):
        if cat.get('alert'):
            continue
        for card in (cat.get('cards') or []):
            href = (card.get('href') or '').strip()
            app_href = (card.get('app_href') or '').strip()
            title = (card.get('title') or '').strip()
            if not href.startswith('/') or not app_href or not title:
                continue
            if title == app_href or app_href in seen:
                continue
            seen.add(app_href)
            out.append({
                'title': title,
                'href': href,
                'desc': (card.get('desc') or '').strip(),
                'app_href': app_href,
                'icon': card.get('icon') or 'fa-th-large',
            })
    _ENTRY_CACHE[key] = (now, out)      # 只读共享：调用方不得原地修改
    if len(_ENTRY_CACHE) > 2048:
        cutoff = now - _ENTRY_CACHE_TTL
        for k in [k for k, v in _ENTRY_CACHE.items() if v[0] < cutoff]:
            _ENTRY_CACHE.pop(k, None)
    return out


def _entry_hits(q, limit=6):
    """入口命中（按相关度排序）。空 q / 无命中 → []。"""
    ql = (q or '').strip().lower()
    if not ql:
        return []
    entries = _panel_entries()
    if not entries:
        return []
    by_href = {e['app_href']: e for e in entries}
    aliased = {t for term, t in _ENTRY_ALIASES.items()
               if term in ql and t in by_href}
    scored = []
    for ent in entries:
        title = ent['title'].lower()
        if title == ql:
            score = 100
        elif title.startswith(ql):
            score = 85
        elif ql in title:
            score = 70
        elif ql in (ent['desc'] or '').lower():
            score = 45
        elif ql in ent['app_href'].lower():
            score = 30
        else:
            score = 0
        if ent['app_href'] in aliased:
            score = max(score, 60)
        if score:
            scored.append((score, ent))
    scored.sort(key=lambda t: (-t[0], len(t[1]['title']), t[1]['title']))
    return [ent for _s, ent in scored[:limit]]


def _entry_group(q, limit=6):
    """入口分组（与内容分组同形状：(标题, 更多链接, 条目列表)）。"""
    hits = _entry_hits(q, limit)
    if not hits:
        return []
    return [('应用入口', '', [{
        'id': 'entry:%s' % h['app_href'],
        'name': h['title'],
        'href': h['href'],
        'desc': h['desc'],
    } for h in hits])]


# ---------------------------------------------------------------------------
# 内容搜索（原 my_search 主体原样搬入，结果页与建议端点**共用同一实现**）
# ---------------------------------------------------------------------------
def _content_groups(q, limit=8):
    """11 组内容命中：(标题, 更多链接, [{id, name, href}])。q 为空 → []。"""
    env = request.env
    q = (q or '').strip()
    if not q:
        return []
    student = current_student()
    parent = current_parent()
    fac = env.user.has_group('base.group_user')
    dom_q = [('name', 'ilike', q)]
    lim = max(1, int(limit))
    groups = []

    # 作业（学生按班级，内部全部）
    a_dom = list(dom_q)
    if not fac and student:
        # 2026-10-03：原先只按 batch_id ⇒ 学生搜「作业」会把**别的课程**的作业也搜出来，
        # 点进去还会落到不显示该条的详情页。改用门户唯一口径（main.assignment_scope_domain）。
        a_dom += assignment_scope_domain(student)
    assignments = env['op.assignment'].sudo().search(a_dom, limit=lim)
    if assignments:
        groups.append(('作业', '/student/assignment/details', [
            {'id': a.id, 'name': a.display_name or a.grading_assignment_id.name,
             'href': '/student/assignment/details'}
            for a in assignments]))

    # 课程科目 → 课次列表
    # 2026-09-28 修（「搜索结果点不进去」定性）：本分组此前用裸 dom_q，
    # 非内部用户会搜到**自己没在册**的科目；而 /my/courses/<id> 自带守卫
    # （lms.py 的 /my/courses/<id> subject not in subjects → 303 /my/courses），
    # 实测学生与家长点任意一条「课程」命中都被弹回课程列表（等于没点）。
    # 改用 _subjects_for（与本文件「网课」分组同源口径），命中即本人可见科目。
    s_dom = list(dom_q)
    if not fac:
        vis_subjects, _srole = _subjects_for(student, fac, parent, env.user)
        s_dom.append(('id', 'in', vis_subjects.ids))
    subjects = env['op.subject'].sudo().search(s_dom, limit=lim)
    if subjects:
        groups.append(('课程', '/my/courses', [
            {'id': s.id, 'name': s.name,
             'href': '/my/courses/%d' % s.id} for s in subjects]))

    # 2026-10-04（第 86 轮）：**课程名 / 班级名也要能搜到**。
    #   首页那张上手卡片写的是「顶部搜索框可查应用入口与作业 / 课程 / 公告 / 账单」，
    #   而学生自己的页面把「预备科」显示为**课程**、把「预备科 · 2026级【演示】」显示为**班级**。
    #   实测：搜「选修课程」（科目名）→ 有命中；搜「预备科」「2026级」→
    #   「没有找到与「预备科」相关的内容」。
    #   这与本模块 v3 修过的那个问题**同一形状**（见文件头 docstring：
    #   用户输入的是自己嘴里的词，而分组查的是另一个字段 ⇒ 必然 0 条）。
    #   口径：只搜**本人档案**上的课程/班级（不泄露全目录），命中一律落到 /my/courses
    #   —— 那个页面本人打得开，不会重蹈「点了被弹回」（见上方 2026-09-28 那条）。
    if not fac and student:
        my_scs = env['op.student.course'].sudo().search(
            [('student_id', '=', student.id)])
        cb_hits = []
        for sc in my_scs:
            for rec in (sc.course_id, sc.batch_id):
                if rec and q.lower() in (rec.name or '').lower():
                    cb_hits.append({'id': 'sc:%s:%s' % (sc.id, rec.id),
                                    'name': rec.name, 'href': '/my/courses'})
        if cb_hits:
            groups.append(('课程 / 班级', '/my/courses', cb_hits))

    # 布告（t23：与布告栏/横幅/角标同一口径 —— 定向公告对非目标
    # 人群连标题与直链都不返回；教职工/管理员恒可见全部）
    n_dom = list(dom_q) + [
        ('active', '=', True),
        '|', ('date_until', '=', False),
        ('date_until', '>=', fields.Date.today())]
    codes = _notice_audience_codes()
    if codes is not None:
        n_dom += ['|', ('audience', '=', 'all'),
                  ('audience', 'in', codes)]
    notices = env['edu.notice'].sudo().search(n_dom, limit=lim)
    if notices:
        groups.append(('布告', '/my/notice_board/notice', [
            {'id': n.id, 'name': n.name,
             'href': '/my/notice/%d' % n.id} for n in notices]))

    # 账单（学生=本人；家长=子女；内部只读全库）
    # 2026-09-28 修：此前只有「student ? 本人 : 0」一条分支，家长侧
    # current_student() 恒为 None（identity.student_of_user 只反查学生档案）
    # ⇒ student_id=0 ⇒ 家长搜「教材」0 条，而同一张单在 /my/fees 的
    # 「孩子的账单」里明明可见（fees.py 走的正是 parent.student_ids）。
    # 家长分支口径与 fees.py 完全一致，不另造第二套。
    b_dom = list(dom_q)
    if not fac:
        if student:
            b_dom.append(('student_id', '=', student.id))
        elif parent:
            b_dom.append(('student_id', 'in', parent.student_ids.ids))
        else:
            b_dom.append(('student_id', '=', 0))
    bills = env['edu.fee.bill'].sudo().search(b_dom, limit=lim)
    if bills:
        groups.append(('账单', '/my/fees', [
            {'id': bb.id, 'name': bb.name, 'href': '/my/fees'}
            for bb in bills]))

    # —— 以下为辅助增强包 3a 扩组 ——

    # 资料下载（可见范围 v3：按登录身份过滤）
    try:
        d_dom = list(dom_q) + [('active', '=', True)] + _visibility_domain()
        files = env['edu.download.file'].sudo().search(d_dom, limit=lim)
    except Exception:
        files = env['edu.download.file'].sudo().browse(())
    if files:
        groups.append(('资料', '/downloads', [
            {'id': f.id, 'name': f.name,
             'href': '/downloads/file/%d' % f.id} for f in files]))

    # 校历活动（学生/家长限本班或全校活动）
    e_dom = list(dom_q) + [('active', '=', True)]
    if student:
        _, batch = student_course(student)
        e_dom = ['|', ('batch_id', '=', batch.id if batch else 0),
                 ('batch_id', '=', False)] + e_dom
    events = env['edu.event'].sudo().search(e_dom, limit=lim)
    if events:
        groups.append(('校历活动', '/my/calendar', [
            {'id': ev.id, 'name': ev.name, 'href': '/my/calendar'}
            for ev in events]))

    # 在线测验（t27：非内部用户按本角色**课程**收敛 —— 与作业/校历
    # 分组同源都走 student_course；此前裸 dom_q 会搜到未选课程的测验）
    q_dom = list(dom_q)
    if not fac:
        if student:
            course, _b = student_course(student)
            q_dom.append(('course_id', 'in', [course.id] if course else []))
        elif parent:
            scs = env['op.student.course'].sudo().search(
                [('student_id', 'in', parent.student_ids.ids)])
            q_dom.append(('course_id', 'in',
                          scs.mapped('course_id').ids))
        else:
            q_dom.append(('course_id', 'in', []))
    quizzes = env['edu.quiz'].sudo().search(q_dom, limit=lim)
    if quizzes:
        groups.append(('测验', '/quiz', [
            {'id': z.id, 'name': z.name, 'href': '/quiz'} for z in quizzes]))

    # LMS 课次（t27：复用 lms.py 的 _subjects_for —— 单一事实源，
    # 不另造范围规则；无档案/无科目者得到空列表而非全目录）
    l_dom = list(dom_q)
    if not fac:
        vis_subjects, _role = _subjects_for(student, fac, parent, env.user)
        l_dom.append(('subject_id', 'in', vis_subjects.ids))
    lessons = env['edu.lesson'].sudo().search(l_dom, limit=lim)
    if lessons:
        groups.append(('网课', '/my/courses', [
            {'id': le.id, 'name': le.name,
             'href': '/my/courses/lesson/%d' % le.id}
            for le in lessons]))

    # 本人请假单 / 申诉单（学生视角；内部走审批页搜索）
    if student:
        leaves = env['edu.leave'].sudo().search(
            ['|', ('name', 'ilike', q), ('reason', 'ilike', q),
             ('student_id', '=', student.id)], limit=lim)
        if leaves:
            groups.append(('请假单', '/my/time_off', [
                {'id': lv.id, 'name': lv.name or lv.reason or '',
                 'href': '/my/time_off'} for lv in leaves]))
        # 2026-09-28 修（本次搜索定性的主因）：原域的 ['|', '|', name,
        # subject, student_id=本人] 在 Odoo 波兰式域里等价于
        # OR(name, subject, student_id=本人) —— **归属限制被并进了 OR**：
        # ①任何关键词都返回本人全部申诉（实测 q=zzz_no_such_thing 仍出 8 条）；
        # ②「没有找到」分支对学生永远不渲染；
        # ③他人申诉只要主题/编号命中关键词就返回给学生（实测越权：学生 5
        #   在搜索页看到了学生 7 的申诉单）。
        # 正确形状 = 归属限制在最外层，关键词两条参与 OR（与上方「请假单」同形）。
        grievances = env['edu.grievance'].sudo().search(
            [('student_id', '=', student.id),
             '|', ('name', 'ilike', q), ('subject', 'ilike', q)],
            limit=lim)
        if grievances:
            groups.append(('申诉单', '/my/grievances', [
                {'id': g.id, 'name': g.subject or g.name,
                 'href': '/my/grievances'} for g in grievances]))

    # 邀请码（仅内部用户：管理员/教务按码或备注检索）
    if fac:
        codes = env['edu.invite.code'].sudo().search(
            ['|', ('code', 'ilike', q), ('note', 'ilike', q)],
            limit=lim)
        if codes:
            menu = env['ir.ui.menu'].sudo().search(
                [('name', '=', '邀请码')], limit=1)
            # v3 批次1（t4 代改，原无主文件）：原回退是
            # '/web#menu_id=%d'（对外可见的后台 URL），改指门户应用面板。
            # ⚠ 动作类型判定走 ir.ui.menu.edu_action_href（edu_brand，唯一口径）：
            # ir.actions.act_url 是「跳到某个 URL」，经 /odoo/action-<id> 会让用户
            # 先闪一遍后台外壳；这里与 /apps 卡片同规则（当前本库「邀请码」动作
            # 687 是 act_window，行为不变；换动作类型时不会回退成闪屏）。
            href = env['ir.ui.menu'].edu_action_href(
                '%s,%d' % (menu.action._name, menu.action.id)) \
                if menu and menu.action else '/apps'
            groups.append(('邀请码', href, [
                {'id': c.id,
                 'name': "%s · %s" % (c.code, c.note or '未填写备注')
                         + ("（已使用）" if c.state == 'used' else ""),
                 'href': href}
                for c in codes]))
    return groups


# ---------------------------------------------------------------------------
# 建议端点限流：令牌桶（每用户 · 进程内），防「每键一请求」把后端打爆
# ---------------------------------------------------------------------------
_SUGGEST_MAX_Q = 40          # 查询串上限：再长一律当无意义输入（省一次全表 ilike）
# 令牌桶口径：突发 15 次，之后每秒回填 6 个。
# 为什么是 6/s：前端防抖 200ms ⇒ 人手最快也就 5 请求/秒（连续猛敲），留一档余量；
# 爬虫/脚本连打则在 15 次后开始被拦（返回值仍是 200 + throttled:true，前端静默关闭）。
_SUGGEST_CAP = 15.0          # 桶容量（突发）
_SUGGEST_RATE = 6.0          # 回填速率（每秒）
_SUGGEST_BUCKET = {}


def _bucket_take(store, key, now):
    """令牌桶取一枚令牌（返回 True/False）。**纯函数**：store 与 now 都由调用方给，
    所以能在 odoo shell 里直接对着它自证（见 tests/smoke/search_suggest_evidence.py
    的 selftest 段），不必伪造 request。
    """
    st = store.get(key)
    if st is None:
        st = [_SUGGEST_CAP, now]
    else:
        st[0] = min(_SUGGEST_CAP, st[0] + (now - st[1]) * _SUGGEST_RATE)
        st[1] = now
    if st[0] < 1.0:
        store[key] = st
        return False
    st[0] -= 1.0
    store[key] = st
    if len(store) > 4096:                # 防键表无界增长
        cutoff = now - 600
        for k in [k for k, v in store.items() if v[1] < cutoff]:
            store.pop(k, None)
    return True


def _suggest_allowed():
    """本用户是否还有额度；超限返回 False（不报错，只是空结果）。

    键用 uid，不用 session.sid：sid 是「会话」粒度（同一人开三个标签页就三份额度），
    而且实测它在连发时不是稳定键（顺序 40 连发一枚都没拦到）。
    ⚠ 桶在**进程内存**里：本机 config/odoo.conf 是 workers=6 ⇒ 真实上限是
    「每进程一份」的软限流（单进程 15 突发 + 6/s；全站 ≈ 6 倍）。
    对「每键一请求」的滥用是有效刹车；要硬上限得换成共享存储（本任务不做，
    因为那要么新建模型、要么把限流塞进 config_parameter —— 都超出本任务口径）。
    """
    return _bucket_take(_SUGGEST_BUCKET, 'u%d' % (request.env.uid or 0),
                        time.time())


class EduSearchPortal(http.Controller):

    @http.route('/my/search', type='http', auth='user', website=True)
    def my_search(self, q='', **kw):
        q = (q or '').strip()
        groups = []
        if q:
            # ① 应用入口优先（用户输入的多半是应用名），② 再是内容记录
            groups += _entry_group(q)
            groups += _content_groups(q)
        return request.render('edu_portal.edu_search_results', {
            'title': f'搜索：{q}' if q else '搜索',
            'q': q,
            'groups': groups,
            'page_name': 'search',
        })

    @http.route('/my/search/suggest', type='http', auth='user',
                website=True, sitemap=False)
    def my_search_suggest(self, q='', **kw):
        """输入即出建议（JSON）。空 q → 空结果，**不吐全量**。

        形状：{q, groups:[{label, kind: entry|content, more, items:[{title,
        href, desc}]}], throttled}。入口组恒在内容组之前。
        """
        q = (q or '').strip()
        if not q or len(q) > _SUGGEST_MAX_Q:
            return request.make_json_response(
                {'q': q, 'groups': [], 'throttled': False})
        if not _suggest_allowed():
            return request.make_json_response(
                {'q': q, 'groups': [], 'throttled': True})
        entry_groups = _entry_group(q, limit=6)
        content_groups = _content_groups(q, limit=5)
        out = [{
            'label': g[0], 'kind': 'entry', 'more': g[1] or '',
            'items': [{'title': it['name'], 'href': it['href'],
                       'desc': it.get('desc') or ''} for it in g[2]],
        } for g in entry_groups]
        out += [{
            'label': g[0], 'kind': 'content', 'more': g[1] or '',
            'items': [{'title': it['name'], 'href': it['href'],
                       'desc': ''} for it in g[2]],
        } for g in content_groups]
        return request.make_json_response(
            {'q': q, 'groups': out, 'throttled': False})

    @http.route('/my/lang/<string:code>', type='http', auth='public',
                website=True)
    def set_lang(self, code, **kw):
        if code in ('zh_CN', 'zh_TW', 'en_US'):
            if not request.env.user._is_public():
                request.env.user.sudo().write({'lang': code})
            resp = request.redirect(
                request.httprequest.referrer or '/my/home')
            resp.set_cookie('frontend_lang', code, max_age=31536000)
            return resp
        return request.redirect('/my/home')

    @http.route('/my/help', type='http', auth='user', website=True)
    def help_center(self, **kw):
        return request.render('edu_portal.edu_help_center', {
            'title': '帮助中心',
            'page_name': 'help',
        })
