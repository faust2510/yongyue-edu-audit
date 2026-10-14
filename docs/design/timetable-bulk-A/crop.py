
import json
from playwright.sync_api import sync_playwright
BASE="http://127.0.0.1:8069"; OUT="/tmp/timetable-bulk-A"
def login(pg):
    pg.goto(BASE+"/web/login?db=edu19", wait_until="domcontentloaded")
    pg.fill("input[name=login]","backoffice@local"); pg.fill("input[name=password]","demo123")
    try: pg.click("form.oe_login_form button[type='submit']", timeout=10000)
    except Exception: pg.press("input[name=password]","Enter")
    pg.wait_for_load_state("domcontentloaded"); pg.wait_for_timeout(1200)
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1440,"height":900}, device_scale_factor=3)
    login(pg); pg.goto(BASE+"/timetable/bulk", wait_until="load"); pg.wait_for_timeout(700)
    lab = pg.query_selector("label[for=bk_course]")
    box = lab.bounding_box()
    print("LABEL_BOX", json.dumps(box))
    # clip a region including the label and its left margin
    pg.screenshot(path=OUT+"/crop-label.png", clip={"x":max(0,box["x"]-30),"y":max(0,box["y"]-10),"width":320,"height":40})
    row = pg.query_selector("div.d-flex.flex-wrap.gap-3")
    rb = row.bounding_box(); print("WD_ROW", json.dumps(rb))
    pg.screenshot(path=OUT+"/crop-weekdays.png", clip={"x":max(0,rb["x"]-30),"y":max(0,rb["y"]-8),"width":420,"height":36})
    b.close()
