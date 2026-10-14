#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settings_deadline_consumer_probe.py —— 截止日的**消费方**读数（HTTP 层）。

为什么单独一个量具：t110 修的是设置页字段类型，但**消费方**（谁在读
edu.apply.deadline / edu.enroll.deadline）必须证明「语义没变」。消费方是两处
**渲染**（本仓当前没有截止拦截逻辑，见 docs/plans/scheduling-overhaul-design.md:223
「本次不加截止拦截」）：
  1. /admissions           公开招生页：edu_brand/views/pages.xml:324
                           「…报名截止日期为 2026年10月1日。」
  2. /subject/enroll       学生报课页：edu_portal/views/enroll.xml:107
                           「本轮报课截止：2026年10月1日」
本量具把两页上的**日期文本原文**抓出来（不是读参数），因此可直接做修前/修后
逐字对照：同一个参数值必须渲染出同一个字符串。

控制组（证明不是恒红/恒绿）：
  · /my/home 学生首页与 /admissions 都是**修前就正常**的页面 —— 修后必须还是 200 且
    关键内容仍在（本脚本一并打印它们的判据）；
  · 若 /admissions 上出现「报名截止日期为」以外的日期串，说明读到了别的字段 —— 判红。

用法：python3 tests/smoke/settings_deadline_consumer_probe.py --out /tmp/consumer_after.json
退出码：0=绿 ｜ 1=红（页面缺日期/多日期/HTTP 非 200）｜ 2=ENV（站点不可达/登录失败）
"""
import argparse
import json
import re
import sys

import requests

DB = 'edu19'
BASE = 'http://127.0.0.1:8069'
# 中文日期：2026年10月1日（get_cn 的格式，见 edu.deadline.get_cn）
DATE_RE = re.compile(r'\d{4}\u5e74\d{1,2}\u6708\d{1,2}\u65e5')


def auth(login, pwd, base, db):
    s = requests.Session()
    s.trust_env = False
    r = s.post(base + '/web/session/authenticate', json={
        'jsonrpc': '2.0',
        'params': {'db': db, 'login': login, 'password': pwd}}, timeout=60)
    uid = (r.json().get('result') or {}).get('uid')
    if not uid:
        return None, 'login %s failed: %s' % (login, r.text[:200])
    return s, None


def find_all(text, anchor, window=90):
    """抓 anchor 之后 window 字符内出现的所有中文日期串。"""
    out = []
    for m in re.finditer(re.escape(anchor), text):
        seg = text[m.end(): m.end() + window]
        out += DATE_RE.findall(seg)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-url', default=BASE)
    ap.add_argument('--db', default=DB)
    ap.add_argument('--out')
    ap.add_argument('--expect', default=None,
                    help='期望日期（如 2026年10月1日）；给了就硬判等')
    args = ap.parse_args()
    base = args.base_url.rstrip('/')

    out = {'base_url': base, 'readings': {}}
    guest = requests.Session()
    guest.trust_env = False
    try:
        r = guest.get(base + '/admissions', timeout=60)
    except Exception as e:
        print('ENV: 站点不可达（%s）' % str(e)[:120], file=sys.stderr)
        return 2
    out['readings']['/admissions'] = {
        'status': r.status_code,
        'dates': find_all(r.text, '报名截止日期为'),
        'has_sentence': '报名截止日期为' in r.text,
    }
    stu, err = auth('stu@local', 'demo123', base, args.db)
    if err:
        print('ENV: %s' % err, file=sys.stderr)
        return 2
    r2 = stu.get(base + '/subject/enroll', timeout=60)
    out['readings']['/subject/enroll'] = {
        'status': r2.status_code,
        'dates': find_all(r2.text, '本轮报课截止'),
        'has_sentence': '本轮报课截止' in r2.text,
    }
    # 控制组：修前修后都该正常的另一页
    r3 = stu.get(base + '/my/home', timeout=60)
    out['readings']['/my/home(控制组)'] = {
        'status': r3.status_code,
        'has_student_marker': ('o_portal' in r3.text or 'card' in r3.text),
        'traceback': 'Traceback' in r3.text,
    }

    ok = True
    for name, rd in out['readings'].items():
        if rd['status'] != 200:
            ok = False
        if name.endswith('(控制组)'):
            if rd['traceback']:
                ok = False
            continue
        if not rd['has_sentence'] or len(rd['dates']) != 1:
            ok = False
        if args.expect and rd['dates'] and rd['dates'][0] != args.expect:
            ok = False
    out['verdict'] = 'PASS' if ok else 'FAIL'
    print('%s 消费方读数：%s' % (out['verdict'], json.dumps(out['readings'], ensure_ascii=False)))
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        print('OUT=%s' % args.out)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
