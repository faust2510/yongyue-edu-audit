
import json, os, sys, re
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8069"
OUT = "/tmp/timetable-bulk-A"
os.makedirs(OUT, exist_ok=True)

def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(BASE + "/web/login?db=edu19", wait_until="domcontentloaded")
        pg.fill("input[name=login]", "backoffice@local")
        pg.fill("input[name=password]", "demo123")
        try:
            pg.click("form.oe_login_form button[type='submit']", timeout=10000)
        except Exception as e:
            print("click fallback:", e)
            pg.press("input[name=password]", "Enter")
        pg.wait_for_load_state("domcontentloaded")
        pg.wait_for_timeout(1500)
        print("after login url:", pg.url)

        pg.goto(BASE + "/timetable/bulk?db=edu19", wait_until="load")
        pg.wait_for_timeout(1200)
        print("bulk url:", pg.url, "title:", pg.title())

        metrics = pg.evaluate("""() => {
          const q = s => document.querySelectorAll(s).length;
          const el = document.querySelector('#wrap') || document.body;
          return {
            input: q('input'), select: q('select'), label: q('label'),
            button: q('button'), a_btn: q('a.btn'), form: q('form'),
            card: q('.card'), small_muted: q('.form-text'),
            details: q('details'), textarea: q('textarea'),
            bodyH: document.body.scrollHeight,
            wrapH: el.scrollHeight,
            viewportH: window.innerHeight,
            docW: document.documentElement.scrollWidth,
          };
        }""")
        print("METRICS", json.dumps(metrics, ensure_ascii=False))

        outline = pg.evaluate("""() => {
          const out = [];
          const walk = (node, depth) => {
            if (depth > 7) return;
            for (const ch of node.children) {
              const cls = (ch.className && typeof ch.className === 'string') ? ch.className : '';
              const tag = ch.tagName.toLowerCase();
              const txt = (ch.innerText || '').replace(/\s+/g,' ').trim().slice(0,90);
              const r = ch.getBoundingClientRect();
              out.push({d: depth, tag, cls: cls.slice(0,70), id: ch.id||'', y: Math.round(r.top + window.scrollY), h: Math.round(r.height), txt});
              walk(ch, depth+1);
            }
          };
          walk(document.querySelector('#wrap') || document.body, 0);
          return out;
        }""")
        with open(OUT + "/outline.json", "w") as f:
            json.dump(outline, f, ensure_ascii=False, indent=1)

        # full page screenshot
        pg.screenshot(path=OUT + "/bulk-full.png", full_page=True)
        pg.screenshot(path=OUT + "/bulk-viewport.png")

        # capture the text of all helper texts and labels in order
        texts = pg.evaluate("""() => {
          const res = {labels: [], formtext: [], options: {}, alerts: [], buttons: []};
          document.querySelectorAll('label').forEach(l => res.labels.push((l.innerText||'').replace(/\s+/g,' ').trim()));
          document.querySelectorAll('.form-text').forEach(l => res.formtext.push((l.innerText||'').replace(/\s+/g,' ').trim()));
          document.querySelectorAll('.alert').forEach(l => res.alerts.push((l.innerText||'').replace(/\s+/g,' ').trim()));
          document.querySelectorAll('button, a.btn').forEach(l => res.buttons.push((l.innerText||'').replace(/\s+/g,' ').trim()));
          document.querySelectorAll('select').forEach(s => {
            const nm = s.name || s.id;
            res.options[nm] = Array.from(s.options).map(o => o.text.trim()).slice(0, 30);
          });
          const cbs = [];
          document.querySelectorAll('input[type=checkbox]').forEach(c => {
            const lab = c.id ? document.querySelector('label[for="'+c.id+'"]') : null;
            cbs.push({name: c.name, value: c.value, checked: c.checked, label: lab ? lab.innerText.replace(/\s+/g,' ').trim() : ''});
          });
          res.checkboxes = cbs;
          return res;
        }""")
        with open(OUT + "/texts.json", "w") as f:
            json.dump(texts, f, ensure_ascii=False, indent=1)
        print("LABELS", json.dumps(texts["labels"], ensure_ascii=False))
        print("FORMTEXT", json.dumps(texts["formtext"], ensure_ascii=False))
        print("ALERTS", json.dumps(texts["alerts"], ensure_ascii=False)[:1500])
        print("BUTTONS", json.dumps(texts["buttons"], ensure_ascii=False))
        print("CB_COUNT", len(texts["checkboxes"]))
        print("CB", json.dumps(texts["checkboxes"], ensure_ascii=False))
        print("SELECTS", json.dumps(texts["options"], ensure_ascii=False)[:2500])

        # first-paint fold: what is visible within 900px
        fold = pg.evaluate("""() => {
          const vis = [];
          document.querySelectorAll('#wrap label, #wrap button, #wrap h4, #wrap .card-header, #wrap .form-text').forEach(e => {
            const r = e.getBoundingClientRect();
            if (r.top + window.scrollY < 900) vis.push({y: Math.round(r.top + window.scrollY), t: (e.innerText||'').replace(/\s+/g,' ').trim().slice(0,60)});
          });
          return vis;
        }""")
        print("FOLD", json.dumps(fold, ensure_ascii=False))
        b.close()

main()
