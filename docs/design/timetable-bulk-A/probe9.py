
import json
from playwright.sync_api import sync_playwright
BASE="http://127.0.0.1:8069"
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1440,"height":900})
    pg.goto(BASE+"/web/login?db=edu19", wait_until="domcontentloaded")
    pg.fill("input[name=login]","backoffice@local"); pg.fill("input[name=password]","demo123")
    try: pg.click("form.oe_login_form button[type='submit']", timeout=10000)
    except Exception: pg.press("input[name=password]","Enter")
    pg.wait_for_load_state("domcontentloaded"); pg.wait_for_timeout(1200)
    pg.goto(BASE+"/timetable/bulk", wait_until="load"); pg.wait_for_timeout(400)
    pg.select_option("select[name=course_id]", index=1)
    pg.select_option("select[name=batch_id]", index=1)
    pg.select_option("select[name=subject_id]", index=1)
    pg.select_option("select[name=faculty_id]", index=1)
    pg.select_option("select[name=timing_id]", index=1)
    pg.select_option("select[name=classroom_id]", index=1)
    pg.fill("input[name=start_date]", "2026-10-05")
    pg.fill("input[name=end_date]", "2026-12-20")
    pg.fill("input[name=week_ranges]", "1,3-5")
    pg.fill("input[name=new_subject_name]", "我填了一半的科目")
    # NOTE: no weekday checked on purpose
    pg.click("button:has-text('预览将生成的课节')")
    pg.wait_for_load_state("load"); pg.wait_for_timeout(900)
    out = pg.evaluate("""() => {
      const g = s => { const e = document.querySelector(s); return e ? e.value : null; };
      const c = s => { const e = document.querySelector(s); return e ? e.checked : null; };
      return {path: location.pathname,
              danger: Array.from(document.querySelectorAll('.alert-danger')).map(e => e.innerText.replace(/\s+/g,' ').trim()),
              dangerY: (()=>{const e=document.querySelector('.alert-danger'); return e? Math.round(e.getBoundingClientRect().top+window.scrollY):null;})(),
              formY: (()=>{const e=document.querySelector('form.card'); return e? Math.round(e.getBoundingClientRect().top+window.scrollY):null;})(),
              course: g('select[name=course_id]'), batch: g('select[name=batch_id]'),
              subject: g('select[name=subject_id]'), faculty: g('select[name=faculty_id]'),
              timing: g('select[name=timing_id]'), room: g('select[name=classroom_id]'),
              start: g('input[name=start_date]'), end: g('input[name=end_date]'),
              weeks: g('input[name=week_ranges]'), newSubject: g('input[name=new_subject_name]')};
    }""")
    print("ERROR_WIPE_TEST", json.dumps(out, ensure_ascii=False))
    b.close()
