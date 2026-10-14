
import json
from playwright.sync_api import sync_playwright
BASE="http://127.0.0.1:8069"
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1440,"height":900})
    pg.goto(BASE+"/web/login?db=edu19", wait_until="domcontentloaded")
    pg.fill("input[name=login]","backoffice@local"); pg.fill("input[name=password]","demo123")
    try: pg.click("form.oe_login_form button[type='submit']", timeout=10000)
    except Exception: pg.press("input[name=password]","Enter")
    pg.wait_for_load_state("domcontentloaded"); pg.wait_for_timeout(1000)
    pg.goto(BASE+"/timetable/bulk", wait_until="load"); pg.wait_for_timeout(700)
    out = pg.evaluate("""() => {
      const sels = [];
      for (const sh of document.styleSheets) {
        try { for (const rule of sh.cssRules) {
          if (rule.selectorText && rule.selectorText.includes('btn-check')) sels.push(rule.selectorText);
        } } catch(e){}
      }
      // real chip test: wrap a checkbox in the page's own form-check markup vs btn-check
      const host = document.createElement('div');
      host.style.cssText='position:absolute;left:-9999px;top:0';
      host.innerHTML = '<input type="checkbox" class="btn-check" id="pc1" checked><label class="btn btn-sm btn-outline-primary" for="pc1">周一</label>'
                     + '<input type="checkbox" class="btn-check" id="pc2" checked><label class="btn btn-sm btn-outline-secondary" for="pc2">周二</label>';
      document.body.appendChild(host);
      void host.offsetWidth;
      const l1 = host.querySelector('label[for=pc1]'), l2 = host.querySelector('label[for=pc2]');
      return {rules: sels, primaryBg: getComputedStyle(l1).backgroundColor, primaryColor: getComputedStyle(l1).color,
              secondaryBg: getComputedStyle(l2).backgroundColor, secondaryColor: getComputedStyle(l2).color,
              l2Border: getComputedStyle(l2).borderColor};
    }""")
    print("BTNCHECK_RULES", json.dumps(out, ensure_ascii=False))
    b.close()
