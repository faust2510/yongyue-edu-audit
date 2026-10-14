
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
      const inp = document.createElement('input');
      inp.type = 'checkbox'; inp.className = 'btn-check';
      inp.id = 'probe_bc';
      const lab = document.createElement('label');
      lab.className = 'btn btn-sm btn-outline-secondary'; lab.setAttribute('for','probe_bc'); lab.textContent='周一';
      const host = document.createElement('div');
      host.style.cssText='position:absolute;left:-9999px';
      host.appendChild(inp); host.appendChild(lab); document.body.appendChild(host);
      const cs = getComputedStyle(inp);
      const cs2 = getComputedStyle(lab);
      const r = {btnCheck: {position: cs.position, clip: cs.clip, pointerEvents: cs.pointerEvents, display: cs.display},
                 btnWidth: Math.round(lab.getBoundingClientRect().width),
                 hasCheckedSelector: false};
      inp.checked = true;
      r.btnWidthChecked = Math.round(lab.getBoundingClientRect().width);
      r.labelBgWhenChecked = getComputedStyle(lab).backgroundColor;
      // does Bootstrap's rule .btn-check:checked+.btn exist?
      let rules = 0;
      for (const sh of document.styleSheets) {
        try { for (const rule of sh.cssRules) { if (rule.selectorText && rule.selectorText.includes('btn-check:checked')) rules++; } } catch(e){}
      }
      r.checkedRulesFound = rules;
      r.bootstrap = (window.bootstrap && bootstrap.Tooltip) ? 'loaded' : 'absent';
      r.hasDetails = (document.createElement('details') instanceof HTMLDetailsElement);
      return r;
    }""")
    print("PROBE", json.dumps(out, ensure_ascii=False))
    b.close()
