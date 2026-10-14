#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/color/chip_probe.py —— 后台「应用面板」入口的真机探针（v4-t8）。

为什么单独有一个探针（而不是并进取色量具）：
  · 取色量具量的是「页面级四属性色集」，它看不见两件关键事：
    ① 元素还在不在 / 可不可见（display:none 蒙过关会得到同样的「干净」读数）；
    ② 交互态（hover / active / focus）—— 量具根本不 hover，而「点上去毫无反馈」正是本次的用户抱怨。
  · 所以这里的判据是**元素级 + 交互级**的，与量具有意分开（探针 != 基线，见 tests/color/README.md）。

判据（全部必须成立，否则 exit 1）：
  1. 该页可见元素里，计算 background-color / color 为 rgb(113,75,103)（#714B67）的个数 = 0；
  2. 任何元素 inline style 里不得再出现 714b67 / 113,75,103（含 chip 自己）；
  3. #yy-apps-chip 在场、可见（有尺寸、非 display:none/visibility:hidden/opacity:0），
     且真的「有墨」（截图里有亮像素）；
  4. hover 有可见反馈（计算值变化 + 像素级差异）；
  5. focus-visible 有焦点环；
  6. 纯左键点击 -> 导航到 /apps；Cmd（Meta）+点击 -> 开新标签页（旧实现 preventDefault 掐掉的那条）。

用法：python3 tests/color/chip_probe.py [--base-url ...] [--db edu19] [--user faculty@local]
退出码：0=全绿 ｜ 1=判据不成立 ｜ 2=ENV（站点/浏览器不可用）
"""
import argparse
import io
import json
import os
import sys

PURPLE = 'rgb(113, 75, 103)'

JS_SCAN = r"""
() => {
  const PURPLE = "rgb(113, 75, 103)";
  const isVisible = (e) => {
    const cs = getComputedStyle(e);
    if (cs.display === "none" || cs.visibility === "hidden" || parseFloat(cs.opacity) === 0) return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const all = [...document.querySelectorAll("*")];
  const bgPurple = [], fgPurple = [], inlinePurple = [];
  for (const e of all) {
    const st = e.getAttribute("style") || "";
    if (/714b67|113\s*,\s*75\s*,\s*103/i.test(st))
      inlinePurple.push(e.tagName + "#" + (e.id || "") + " :: " + st.slice(0, 80));
    if (!isVisible(e)) continue;
    const cs = getComputedStyle(e);
    if (cs.backgroundColor === PURPLE) bgPurple.push(e.tagName + "." + String(e.className || "").slice(0, 40));
    if (cs.color === PURPLE) fgPurple.push(e.tagName + "." + String(e.className || "").slice(0, 40));
  }
  const c = document.querySelector("#yy-apps-chip");
  let chip = null;
  if (c) {
    const cs = getComputedStyle(c);
    const r = c.getBoundingClientRect();
    chip = {visible: isVisible(c), href: c.getAttribute("href"), text: (c.textContent || "").trim(),
            inline: c.getAttribute("style"), bg: cs.backgroundColor, color: cs.color,
            radius: cs.borderRadius, height: cs.height, fontSize: cs.fontSize,
            borderLeft: cs.borderLeftWidth + " " + cs.borderLeftColor,
            rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}};
  }
  return {url: location.href, title: document.title, elementCount: all.length,
          bgPurple, fgPurple, inlinePurple, chip};
}
"""

JS_STATE = r"""
() => { const c = document.querySelector("#yy-apps-chip"); if (!c) return null;
  const cs = getComputedStyle(c);
  return {bg: cs.backgroundColor, color: cs.color, outline: cs.outline}; }
"""


def ink_stats(png_bytes):
    """PNG 里亮像素数 —— 证明元素真的画出来了（不是被 hidden 蒙过关）。"""
    try:
        from PIL import Image
    except Exception:
        return None
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    bright = 0
    for px in im.getdata():
        if px[0] > 200 and px[1] > 200 and px[2] > 200:
            bright += 1
    return {"w": im.width, "h": im.height, "total": im.width * im.height, "brightPixels": bright}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-url', default='http://127.0.0.1:8069')
    ap.add_argument('--db', default='edu19')
    ap.add_argument('--user', default='faculty@local')
    ap.add_argument('--pass', dest='password', default='demo123')
    ap.add_argument('--pages', default='/odoo/contacts,/odoo/contacts/new')
    ap.add_argument('--out-dir', default='/tmp')
    args = ap.parse_args()
    base = args.base_url.rstrip('/')
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print('ENV: playwright 不可用（%s）' % str(e)[:120], file=sys.stderr)
        return 2

    fails, report = [], {}
    with sync_playwright() as p:
        br = p.chromium.launch()
        try:
            ctx = br.new_context(viewport={'width': 1440, 'height': 900})
            res = ctx.request.post(base + '/web/session/authenticate',
                                   data={'jsonrpc': '2.0', 'method': 'call',
                                         'params': {'db': args.db, 'login': args.user,
                                                    'password': args.password}})
            if '"uid"' not in res.text():
                print('ENV: 登录失败 -> %s' % res.text()[:160], file=sys.stderr)
                return 2
            page = ctx.new_page()
            for path in [x for x in args.pages.split(',') if x]:
                page.goto(base + path, wait_until='domcontentloaded', timeout=90000)
                page.wait_for_timeout(4000)
                sc = page.evaluate(JS_SCAN)
                rep = {'url': sc['url'], 'title': sc['title'], 'elementCount': sc['elementCount'],
                       'bgPurple': sc['bgPurple'], 'fgPurple': sc['fgPurple'],
                       'inlinePurple': sc['inlinePurple'], 'chip': sc['chip']}
                if sc['bgPurple'] or sc['fgPurple'] or sc['inlinePurple']:
                    fails.append('%s: 仍有 #714B67（bg=%s fg=%s inline=%s）'
                                 % (path, sc['bgPurple'][:3], sc['fgPurple'][:3], sc['inlinePurple'][:3]))
                chip = sc['chip']
                if not chip:
                    fails.append('%s: #yy-apps-chip 不在场' % path)
                    report[path] = rep
                    continue
                if not chip['visible']:
                    fails.append('%s: #yy-apps-chip 不可见（display:none 蒙过关不算）' % path)
                if chip['href'] != '/apps':
                    fails.append('%s: chip.href=%s（期望 /apps）' % (path, chip['href']))
                if chip['inline']:
                    fails.append('%s: chip 仍有 inline style（色值应全部搬进样式表）: %s'
                                 % (path, chip['inline'][:80]))
                box = chip['rect']
                clip = {'x': max(0, box['x'] - 2), 'y': max(0, box['y'] - 2),
                        'width': box['w'] + 4, 'height': box['h'] + 4}
                png_rest = page.screenshot(clip=clip)
                ink = ink_stats(png_rest)
                rep['chipInk'] = ink
                if ink and ink['brightPixels'] <= 0:
                    fails.append('%s: chip 区域截图 0 个亮像素（元素在，但没画出来）' % path)
                before = page.evaluate(JS_STATE)
                page.hover('#yy-apps-chip')
                page.wait_for_timeout(400)
                after = page.evaluate(JS_STATE)
                png_hover = page.screenshot(clip=clip)
                rep['hover'] = {'before': before, 'after': after,
                                'computedChanged': before != after,
                                'pixelsChanged': png_rest != png_hover}
                if before == after and png_rest == png_hover:
                    fails.append('%s: hover 无任何可见反馈（计算值未变、像素未变）' % path)
                # 按住不放时读一次 active 态；**先把指针移开再抬手** ——
                # 否则 mouseup 落在同一元素上会触发 click、直接导航到 /apps，
                # 后面所有读数就都跑到新页面去了（第一次跑就是这么翻车的）。
                page.mouse.move(box['x'] + box['w'] / 2.0, box['y'] + box['h'] / 2.0)
                page.mouse.down()
                page.wait_for_timeout(250)
                rep['active'] = page.evaluate(JS_STATE)
                page.mouse.move(5, 700)
                page.mouse.up()
                page.wait_for_timeout(300)
                # ⚠ :focus-visible 是**启发式**的：前面刚发生过鼠标交互时，程序化 focus() 不触发它
                #   （实测：同一份 CSS，无鼠标交互时 programmatic focus 会命中，有鼠标交互时不命中）。
                #   所以这里先敲一次键盘（切到键盘交互态），再程序化聚焦 —— 这样判据测的是我们的规则，
                #   而不是 Chrome 的启发式。
                page.keyboard.press('Tab')
                page.wait_for_timeout(100)
                page.evaluate("() => { const c = document.querySelector('#yy-apps-chip'); if (c) c.focus(); }")
                page.wait_for_timeout(200)
                foc = page.evaluate(JS_STATE)
                rep['focus'] = foc
                if not foc or 'none' in (foc.get('outline') or 'none'):
                    fails.append('%s: focus 无焦点环（outline=%s）' % (path, (foc or {}).get('outline')))
                report[path] = rep
            page.goto(base + '/odoo/contacts', wait_until='domcontentloaded', timeout=90000)
            page.wait_for_timeout(3500)
            page.click('#yy-apps-chip')
            page.wait_for_timeout(3000)
            report['click_plain'] = {'url': page.url}
            if '/apps' not in page.url:
                fails.append('纯左键点击后 URL=%s，期望落在 /apps' % page.url)
            page.goto(base + '/odoo/contacts', wait_until='domcontentloaded', timeout=90000)
            page.wait_for_timeout(3500)
            try:
                with ctx.expect_page(timeout=15000) as pinfo:
                    page.click('#yy-apps-chip', modifiers=['Meta'])
                newp = pinfo.value
                newp.wait_for_load_state('domcontentloaded', timeout=30000)
                # 新标签页可能先落在 about:blank 再导航 —— 有界轮询等它到底，别读瞬时值。
                for _ in range(20):
                    if newp.url and newp.url != 'about:blank':
                        break
                    newp.wait_for_timeout(500)
                report['click_meta'] = {'opened': True, 'newTabUrl': newp.url}
                if '/apps' not in newp.url:
                    fails.append('Cmd+点击的新标签页 URL=%s，期望 /apps' % newp.url)
                newp.close()
            except Exception as e:
                report['click_meta'] = {'opened': False, 'error': str(e)[:160]}
                fails.append('Cmd/Ctrl+点击没有开新标签页（旧实现 preventDefault 的真实缺陷）: %s'
                             % str(e)[:120])
        finally:
            br.close()

    out = os.path.join(args.out_dir, 'chip_probe.json')
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print()
    if fails:
        for f in fails:
            print('FAIL  %s' % f)
        print('VERDICT: FAIL（%d 项）｜ 明细 %s' % (len(fails), out))
        return 1
    print('VERDICT: PASS（六条判据全绿）｜ 明细 %s' % out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
