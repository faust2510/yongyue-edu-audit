
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

        # ---------- T6: native required vs server error ----------
        pg.goto(BASE + "/timetable/bulk", wait_until="load"); pg.wait_for_timeout(400)
        pg.select_option("select[name=course_id]", index=1)
        pg.select_option("select[name=batch_id]", index=1)
        pg.select_option("select[name=subject_id]", index=1)
        pg.select_option("select[name=faculty_id]", index=1)
        pg.select_option("select[name=timing_id]", index=1)
        pg.check("#wd_0")
        # NO dates on purpose
        pg.click("button:has-text('预览将生成的课节')")
        pg.wait_for_timeout(1200)
        print("T6_NO_DATES", json.dumps(pg.evaluate("""() => ({
            path: location.pathname,
            invalid: Array.from(document.querySelectorAll(':invalid')).map(e => e.name || e.id),
            invalidMsg: Array.from(document.querySelectorAll(':invalid')).map(e => {
                try { return e.validationMessage; } catch(x) { return ''; } }),
            lang: document.documentElement.lang,
            errorAlert: Array.from(document.querySelectorAll('.alert-danger')).map(e=>e.innerText.trim()),
        })"""), ensure_ascii=False))

        # ---------- T7: all filled but no weekday -> server-side error; do values survive? ----------
        pg.fill("input[name=start_date]", "2026-10-05")
        pg.fill("input[name=end_date]", "2026-12-20")
        pg.select_option("select[name=classroom_id]", index=1)
        pg.fill("input[name=week_ranges]", "1,3-5")
        pg.click("button:has-text('预览将生成的课节')")
        pg.wait_for_load_state("load"); pg.wait_for_timeout(1000)
        print("T7_SERVER_ERROR", json.dumps(pg.evaluate("""() => ({
            path: location.pathname,
            danger: Array.from(document.querySelectorAll('.alert-danger')).map(e=>e.innerText.replace(/\\s+/g,' ').trim()),
            course: (document.querySelector('select[name=course_id]')||{}).value,
            batch: (document.querySelector('select[name=batch_id]')||{}).value,
            subject: (document.querySelector('select[name=subject_id]')||{}).value,
            faculty: (document.querySelector('select[name=faculty_id]')||{}).value,
            timing: (document.querySelector('select[name=timing_id]')||{}).value,
            room: (document.querySelector('select[name=classroom_id]')||{}).value,
            start: (document.querySelector('input[name=start_date]')||{}).value,
            end: (document.querySelector('input[name=end_date]')||{}).value,
            weeks: (document.querySelector('input[name=week_ranges]')||{}).value,
        })"""), ensure_ascii=False))
        pg.screenshot(path=OUT + "/t7-server-error.png", full_page=True)

        # ---------- T8: region geometry + prose volume on the FORM page ----------
        pg.goto(BASE + "/timetable/bulk", wait_until="load"); pg.wait_for_timeout(600)
        geom = pg.evaluate("""() => {
          const form = document.querySelector('form.card');
          const deact = Array.from(document.querySelectorAll('.card')).find(c => c.querySelector('.card-header'));
          const multiBox = document.querySelector('div.border.rounded-3');
          const hdr = document.querySelector('h4');
          const hint = document.querySelector('.alert');
          const mb = e => e ? {y: Math.round(e.getBoundingClientRect().top + window.scrollY), h: Math.round(e.getBoundingClientRect().height)} : null;
          const prose = [];
          document.querySelectorAll('#wrap .text-muted, #wrap .form-text, #wrap .alert, #wrap p').forEach(e => {
            const t = (e.innerText||'').replace(/\\s+/g,' ').trim();
            if (t) prose.push({len: t.length, y: mb(e).y, t: t.slice(0, 110)});
          });
          const sum = prose.reduce((a,x)=>a+x.len,0);
          // count '（推导，需人工确认'
          const body = document.body.innerText;
          return {
            viewportH: window.innerHeight, bodyH: document.body.scrollHeight,
            title: mb(hdr), hintAlert: mb(hint), form: mb(form), multiBox: mb(multiBox),
            deactivateCard: mb(deact),
            proseChars: sum, proseBlocks: prose.length, prose: prose,
            derivedCount: (body.match(/推导/g)||[]).length,
            innerCodeParens: (body.match(/（[A-Z]\\d/g)||[]).length,
            tableRows: document.querySelectorAll('table.edu-card-table tbody tr').length,
            stopButtons: document.querySelectorAll('a.btn-outline-danger').length,
            noLiveSpans: document.querySelectorAll('table.edu-card-table span.text-muted').length,
          };
        }""")
        print("T8_GEOM", json.dumps(geom, ensure_ascii=False))
        b.close()

main()
