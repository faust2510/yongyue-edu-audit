
import json, os
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8069"
OUT = "/tmp/timetable-bulk-A"

def login(pg):
    pg.goto(BASE + "/web/login?db=edu19", wait_until="domcontentloaded")
    pg.fill("input[name=login]", "backoffice@local")
    pg.fill("input[name=password]", "demo123")
    try:
        pg.click("form.oe_login_form button[type='submit']", timeout=10000)
    except Exception:
        pg.press("input[name=password]", "Enter")
    pg.wait_for_load_state("domcontentloaded"); pg.wait_for_timeout(1200)

def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        login(pg)

        # ---------- T1: error path — does the form keep what I typed? ----------
        pg.goto(BASE + "/timetable/bulk", wait_until="load"); pg.wait_for_timeout(500)
        pg.select_option("select[name=course_id]", index=1)
        pg.select_option("select[name=faculty_id]", index=1)
        pg.fill("input[name=new_subject_name]", "我填了一半的科目")
        pg.check("#wd_0"); pg.check("#wd_2")
        pg.fill("input[name=week_ranges]", "1,3-5")
        pg.click("button:has-text('预览将生成的课节')")
        pg.wait_for_load_state("load"); pg.wait_for_timeout(800)
        state = pg.evaluate("""() => ({
          url: location.pathname,
          alertText: (document.querySelector('.alert')||{}).innerText || '',
          course: (document.querySelector('select[name=course_id]')||{}).value,
          faculty: (document.querySelector('select[name=faculty_id]')||{}).value,
          newSubject: (document.querySelector('input[name=new_subject_name]')||{}).value,
          wd0: (document.querySelector('#wd_0')||{}).checked,
          wd2: (document.querySelector('#wd_2')||{}).checked,
          weeks: (document.querySelector('input[name=week_ranges]')||{}).value,
          start: (document.querySelector('input[name=start_date]')||{}).value,
          end: (document.querySelector('input[name=end_date]')||{}).value,
        })""")
        print("T1_ERROR_RESET", json.dumps(state, ensure_ascii=False))
        pg.screenshot(path=OUT + "/t1-error-state.png", full_page=True)

        # ---------- T2: minimal happy path (single class) ----------
        pg.goto(BASE + "/timetable/bulk", wait_until="load"); pg.wait_for_timeout(400)
        pg.select_option("select[name=course_id]", index=1)
        pg.select_option("select[name=batch_id]", index=1)
        pg.select_option("select[name=subject_id]", index=1)
        pg.select_option("select[name=faculty_id]", index=1)
        pg.select_option("select[name=timing_id]", index=1)
        pg.check("#wd_0")
        pg.fill("input[name=start_date]", "2026-10-05")
        pg.fill("input[name=end_date]", "2026-12-20")
        pg.click("button:has-text('预览将生成的课节')")
        pg.wait_for_load_state("load"); pg.wait_for_timeout(900)
        prev = pg.evaluate("""() => {
          const q = s => document.querySelectorAll(s).length;
          const btn = Array.from(document.querySelectorAll('button')).map(x => x.innerText.replace(/\s+/g,' ').trim());
          const links = Array.from(document.querySelectorAll('a.btn')).map(x => x.innerText.replace(/\s+/g,' ').trim());
          const cards = Array.from(document.querySelectorAll('.card')).map(c => {
            const h = c.querySelector('.card-header');
            const r = c.getBoundingClientRect();
            return {header: h ? h.innerText.replace(/\s+/g,' ').trim().slice(0,60) : '(no header)',
                    y: Math.round(r.top + window.scrollY), h: Math.round(r.height)};
          });
          return {url: location.pathname, bodyH: document.body.scrollHeight, q: {card: q('.card'), details: q('details'), table: q('table')},
                  buttons: btn, links: links, cards: cards,
                  confirmY: (()=>{const el=document.querySelector("button.btn-success"); if(!el) return null; const r=el.getBoundingClientRect(); return Math.round(r.top+window.scrollY);})()};
        }""")
        print("T2_PREVIEW", json.dumps(prev, ensure_ascii=False))
        pg.screenshot(path=OUT + "/t2-preview-full.png", full_page=True)

        # ---------- T3: multi path — what does the user see? just read the form region ----------
        multi = pg.evaluate("""() => {
          const box = Array.from(document.querySelectorAll('div.border.rounded-3'))[0];
          if (!box) return null;
          const r = box.getBoundingClientRect();
          return {h: Math.round(r.height), y: Math.round(r.top + window.scrollY), text: box.innerText.replace(/\s+/g,' ').trim().slice(0,900)};
        }""")
        print("T3_MULTI_BLOCK", json.dumps(multi, ensure_ascii=False))

        # ---------- T4: mobile 375 ----------
        pgm = b.new_page(viewport={"width": 375, "height": 812})
        login(pgm)
        pgm.goto(BASE + "/timetable/bulk", wait_until="load"); pgm.wait_for_timeout(800)
        m = pgm.evaluate("""() => ({
          bodyH: document.body.scrollHeight,
          docW: document.documentElement.scrollWidth,
          winW: window.innerWidth,
          scrollX: document.documentElement.scrollWidth > window.innerWidth,
        })""")
        print("T4_MOBILE", json.dumps(m, ensure_ascii=False))
        pgm.screenshot(path=OUT + "/t4-mobile-full.png", full_page=True)

        # ---------- T5: counts of helper text volume ----------
        vol = pg.evaluate("""() => {
          let chars = 0, blocks = [];
          document.querySelectorAll('#wrap p, #wrap .form-text, #wrap .small.text-muted, #wrap .card-header, #wrap th').forEach(e => {
            const t = (e.innerText||'').replace(/\s+/g,' ').trim();
            if (!t) return;
            chars += t.length;
            blocks.push(t.length + ' :: ' + t.slice(0,70));
          });
          return {chars, blocks};
        }""")
        print("T5_TEXT_VOLUME", json.dumps(vol, ensure_ascii=False))
        b.close()

main()
