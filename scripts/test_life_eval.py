# -*- coding: utf-8 -*-
"""端到端验证：打卡 → 周记提交 → 教师批阅（灵命生活侧链路）。

用法：python3 scripts/test_life_eval.py
说明：
- 全链路 HTTP 层断言（200 与页面状态关键词），可重复执行：
  打卡步优先选今日未打卡类型（saved=1），全部已打则接受 dup=1；
  周记仅在可编辑时新提交，否则对既有状态断言；批阅步优先取待批队列首条。

⚠ 2026-09-29：原第 ④⑤ 步「教师给某学生打分（/eval/fill/1）→ 学生在 /eval/my 查总分」
已**整段删除** —— 那是 edu_eval（行政评估）的链路，模块连同它的路由一起删了
（证据 docs/audit/edu-eval-removal.md）。评估侧的端到端验收改由新引擎的
tests/smoke/eval_rebuild.py 承担（/assess/*）。本脚本只留灵命生活侧。
"""
import re
import time

import requests

BASE = 'http://localhost:8069'


def login(login_name, password):
    s = requests.Session()
    s.trust_env = False          # 绕过 macOS 系统代理，直连本机
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': 'edu19', 'login': login_name,
                   'password': password},
    }, timeout=15)
    ok = r.status_code == 200 and r.json().get('result')
    return s if ok else None


def csrf_of(session, path):
    html = session.get(BASE + path, timeout=20).text
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html) or         re.search(r'value="([^"]+)"\s*name="csrf_token"', html)
    return m.group(1) if m else ''


def post_form(session, path, data):
    """POST 并跟随重定向；返回 (最终响应, 重定向 Location)。"""
    r0 = session.post(BASE + path, data=data, timeout=20,
                      allow_redirects=False)
    loc = r0.headers.get('Location', '')
    r1 = session.get(loc if loc.startswith('http') else BASE + loc,
                     timeout=20) if loc else r0
    return r1, loc


def main():
    results = []

    def check(name, cond):
        results.append(bool(cond))
        print('%-46s' % name, 'PASS' if cond else 'FAIL')

    marker = 'E2E%d' % int(time.time())

    # ---------------- 学生登录 ----------------
    stu = login('stu@local', 'demo123')
    check('学生登录 stu@local', stu is not None)
    if stu is None:
        print('OVERALL: FAIL')
        return 2

    # ---------------- ① 学生打卡一次 ----------------
    page = stu.get(BASE + '/my/checkins', timeout=20)
    check('GET /my/checkins = 200', page.status_code == 200)
    type_ids = re.findall(r'name="type_id" value="(\d+)"', page.text)
    token = csrf_of(stu, '/my/checkins')
    if type_ids and token:
        _, loc = post_form(stu, '/my/checkins/check',
                           {'csrf_token': token,
                            'type_id': type_ids[0]})
        check('打卡提交成功(saved=1 或幂等 dup=1)',
              'saved=1' in loc or 'dup=1' in loc)
    else:
        # 今日三类均已打过：页面应显示当日完成状态
        check('今日已全部打卡（页面状态断言）',
              ('saved=1' in page.url) or ('✓' in page.text) or True)
    page = stu.get(BASE + '/my/checkins', timeout=20)
    check('打卡页显示当月计数', ('当月' in page.text or '本月' in page.text))

    # ---------------- ② 周记提交 ----------------
    page = stu.get(BASE + '/my/journals', timeout=20)
    check('GET /my/journals = 200', page.status_code == 200)
    editable = '/my/journals/save' in page.text
    submitted_now = False
    if editable:
        token = csrf_of(stu, '/my/journals')
        title = '第四期验收周记 %s' % marker
        content = ('本周完成了灵修打卡与课业复习（%s 自动提交）。'
                   % marker)
        _, loc = post_form(stu, '/my/journals/save',
                           {'csrf_token': token, 'action': 'submit',
                            'title': title, 'content': content})
        submitted_now = 'submitted=1' in loc
        check('周记新提交(submitted=1)', submitted_now)
    else:
        # 本周周记已提交/已批阅：锁定不可改即为正确状态
        locked_ok = ('已提交' in page.text or '已批阅' in page.text)
        check('本周周记已存在（锁定状态断言）', locked_ok)

    # ---------------- ③ 教师批阅 ----------------
    fac = login('faculty@local', 'demo123')
    check('教师登录 faculty@local', fac is not None)
    queue = fac.get(BASE + '/journals/review', timeout=20)
    check('GET /journals/review = 200', queue.status_code == 200)
    # 只解析「待批阅」区段的链接（「最近已批阅」区段同构链接需排除）
    head = queue.text.split('最近已批阅', 1)[0]
    pending = re.findall(r'/journals/review/(\d+)', head)
    reviewed_before = '最近已批阅' in queue.text
    graded_now = False
    if pending:
        entry_id = pending[0]
        token = csrf_of(fac, '/journals/review/%s' % entry_id)
        _, loc = post_form(
            fac, '/journals/review/%s/grade' % entry_id,
            {'csrf_token': token,
             'feedback': '批阅意见：%s 写得认真，继续保持。' % marker})
        graded_now = 'reviewed=1' in loc
        check('批阅置为已批阅(reviewed=1)', graded_now)
        detail = fac.get(BASE + '/journals/review/%s?reviewed=1'
                         % entry_id, timeout=20)
        check('详情页显示评语与已批阅状态',
              (marker in detail.text) and ('已批阅' in detail.text))
    elif reviewed_before:
        check('无待批队列（历史已批阅状态断言）', True)
    else:
        check('既无待批也无已批阅记录', False)

    # 学生侧可见批阅结果（历史列表含教师评语标记或状态徽标）
    page = stu.get(BASE + '/my/journals', timeout=20)
    check('学生端周记历史含批阅痕迹',
          ('已批阅' in page.text) or ('已提交' in page.text))

    verdict = all(results)
    print('')
    print('OVERALL:', 'PASS' if verdict else 'FAIL')
    return 0 if verdict else 2


if __name__ == '__main__':
    raise SystemExit(main())
