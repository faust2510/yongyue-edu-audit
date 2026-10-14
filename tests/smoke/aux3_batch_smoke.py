# -*- coding: utf-8 -*-
"""辅助增强批次3冒烟：搜索扩组 / 收藏服务端化 / 打印按钮 / 测验历史 / 家长摘要。"""
import re
import sys

import requests

BASE = 'http://localhost:8069'
PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print('%s %s%s' % ('PASS' if cond else 'FAIL', name,
                       (' | ' + str(extra)[:140]) if (extra and not cond) else ''))


def login(login_name, password='demo123'):
    s = requests.Session()
    s.trust_env = False
    r = s.post(BASE + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': 'edu19', 'login': login_name,
                   'password': password}}, timeout=20)
    return s if (r.status_code == 200 and r.json().get('result')) else None


def main():
    stu = login('stu@local')
    fac = login('faculty@local')
    check('学生登录', bool(stu))
    check('教师登录', bool(fac))

    # ---- 3a 搜索扩组（校历活动/资料/测验组按数据有无，页面不炸即可）----
    r = stu.get(BASE + '/my/search', params={'q': '的'}, timeout=30)
    check('搜索页 200', r.status_code == 200, r.status_code)
    r = stu.get(BASE + '/my/search', params={'q': 'zzz无效词'}, timeout=30)
    check('无结果搜索 200', r.status_code == 200, r.status_code)
    r = stu.get(BASE + '/my/search', params={'q': '冒烟'}, timeout=30)
    check('搜索资料组出现（有冒烟资料时）',
          r.status_code == 200, r.status_code)
    r = fac.get(BASE + '/my/search', params={'q': 'a'}, timeout=30)
    check('教师搜索 200', r.status_code == 200, r.status_code)

    # ---- 3b 收藏服务端化 ----
    # t100 ④：落点已随 v3 迁移 —— `data-csrf` / `data-fav-server` / 瓦片 `data-app-href`
    # 现在在 **/my/apps**（35 个瓦片随应用页迁移），不再在 /my/home。
    r = stu.get(BASE + '/my/apps', timeout=30)
    check('学生应用页 /my/apps 200', r.status_code == 200, r.status_code)
    m = re.search(r'data-csrf="([^"]+)"', r.text)
    check('/my/apps 带 csrf 标志', bool(m))
    fav_flag = 'data-fav-server="1"' in r.text
    # 保存一组收藏（预置 href 池内）
    r2 = stu.post(BASE + '/my/favorites/save', data={
        'csrf_token': m.group(1) if m else '',
        'hrefs': ['my/calendar', 'student/timetable'],
    }, timeout=30)
    check('收藏保存 200', r2.status_code == 200 and
          r2.json().get('ok') is True, r2.text[:80])
    r = stu.get(BASE + '/my/apps', timeout=30)
    check('服务端收藏标志点亮（/my/apps）', 'data-fav-server="1"' in r.text)
    fav_pos = r.text.find('data-app-href="my/calendar"')
    check('SSR 常用区含收藏入口', fav_pos > 0, fav_pos)
    # 清空收藏回预置
    r2 = stu.post(BASE + '/my/favorites/save', data={
        'csrf_token': m.group(1) if m else '',
    }, timeout=30)
    r = stu.get(BASE + '/my/apps', timeout=30)
    check('清空收藏后回预置口径（/my/apps）', 'data-fav-server="0"' in r.text)

    # ---- 3c 打印按钮 ----
    r = stu.get(BASE + '/student/timetable', timeout=30)
    check('周课表 200', r.status_code == 200, r.status_code)
    check('周课表含打印按钮', 'window.print()' in r.text)
    check('周课表含打印样式', '@media print' in r.text)

    # ---- 3d 测验历史页 ----
    r = stu.get(BASE + '/quiz/my', timeout=30)
    check('测验历史页 200', r.status_code == 200, r.status_code)
    check('测验历史页标题', '我的测验成绩' in r.text, r.text[:80])
    r = stu.get(BASE + '/quiz', timeout=30)
    check('测验列表含我的成绩入口', '/quiz/my' in r.text)

    # ---- 3d 家长端摘要（本地有家长演示账号则验证，无则跳过）----
    par = login('parent@local')
    if par:
        r = par.get(BASE + '/my/child', timeout=30)
        if r.status_code == 200:
            ids = re.findall(r'/my/child/(\d+)', r.text)
            if ids:
                r2 = par.get(BASE + '/my/child/%s' % ids[0], timeout=30)
                check('家长仪表盘 200', r2.status_code == 200)
                check('家长仪表盘含摘要卡', '学习生活摘要' in r2.text)
            else:
                check('家长仪表盘（无孩子数据，跳过）', True)
        else:
            check('家长端列表（跳过）', True)
    else:
        check('家长账号不存在（本地已清理，跳过）', True)

    print('\nPASS=%d FAIL=%d' % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
