
import json
from playwright.sync_api import sync_playwright
BASE="http://127.0.0.1:8069"
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":375,"height":812})
    pg.goto(BASE+"/web/login?db=edu19", wait_until="domcontentloaded")
    pg.fill("input[name=login]","backoffice@local"); pg.fill("input[name=password]","demo123")
    try: pg.click("form.oe_login_form button[type='submit']", timeout=10000)
    except Exception: pg.press("input[name=password]","Enter")
    pg.wait_for_load_state("domcontentloaded"); pg.wait_for_timeout(1200)
    pg.goto(BASE+"/timetable/bulk", wait_until="load"); pg.wait_for_timeout(900)
    m = pg.evaluate("""() => {
      const mb = e => e ? {y: Math.round(e.getBoundingClientRect().top + window.scrollY), h: Math.round(e.getBoundingClientRect().height)} : null;
      const form = document.querySelector('form.card');
      const cards = Array.from(document.querySelectorAll('.card')).map(c => ({h: Math.round(c.getBoundingClientRect().height), y: Math.round(c.getBoundingClientRect().top + window.scrollY), head: (c.querySelector('.card-header')||{}).innerText || 'form'}));
      const btn = document.querySelector('form.card button.btn-primary');
      const multi = document.querySelector('div.border.rounded-3');
      return {bodyH: document.body.scrollHeight,
              submitY: mb(btn),
              formCard: mb(form),
              multiBox: mb(multi),
              cards: cards,
              rows: document.querySelectorAll('table.edu-card-table tbody tr').length,
              cbs: document.querySelectorAll('input[type=checkbox]').length,
              maxX: Math.max(...Array.from(document.querySelectorAll('#wrap *')).map(e => e.getBoundingClientRect().right))};
    }""")
    print("MOBILE_BULK", json.dumps(m, ensure_ascii=False))
    r = pg.goto(BASE+"/timetable/batch/10/deactivate", wait_until="load"); pg.wait_for_timeout(700)
    m2 = pg.evaluate("""() => ({bodyH: document.body.scrollHeight, status: 200})""")
    print("MOBILE_CONFIRM", json.dumps(m2, ensure_ascii=False))
    b.close()
