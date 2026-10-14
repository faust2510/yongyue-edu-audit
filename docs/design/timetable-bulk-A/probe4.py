
import json
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

MOCK = """
<div class="container pt-3" id="mockroot" style="max-width:960px">
  <nav class="small text-muted mb-2">家 / 排课 / <span class="fw-semibold text-body">周期排课</span></nav>
  <div class="d-flex align-items-baseline justify-content-between mb-3">
    <div>
      <h4 class="mb-1">周期排课</h4>
      <div class="text-muted small">填 4 项 → 预览 → 生成。生成前不会写入任何课节。</div>
    </div>
    <div class="small text-muted">1 填表 · <b>2 预览</b> · 3 生成</div>
  </div>
  <div class="card shadow-sm border-0 rounded-3">
    <div class="card-body">
      <div class="row g-3">
        <div class="col-md-6">
          <label class="form-label fw-semibold">班级</label>
          <select class="form-select"><option>神学一年级</option></select>
          <details class="mt-1"><summary class="small text-primary">还要给别的班一起排（时间自动错开）</summary>
            <div class="border rounded-3 p-2 mt-2 small">
              <input class="form-control form-control-sm mb-2" placeholder="搜索班级或合班">
              <div class="d-flex flex-wrap gap-2">
                <span class="badge text-bg-light border">神学一年级</span>
                <span class="badge text-bg-light border">神学二年级</span>
                <span class="badge text-bg-light border">人文一年级</span>
                <span class="badge text-bg-light border">A1+A2+A3合班</span>
              </div>
              <div class="text-muted mt-2">勾选 ≥2 个班后，上面的「班级」不再生效。</div>
            </div>
          </details>
        </div>
        <div class="col-md-6">
          <label class="form-label fw-semibold">课程</label>
          <select class="form-select"><option>文学学士</option></select>
        </div>
        <div class="col-md-6">
          <label class="form-label fw-semibold">科目</label>
          <select class="form-select"><option>基础信仰</option></select>
        </div>
        <div class="col-md-6">
          <label class="form-label fw-semibold">教师</label>
          <select class="form-select"><option>【演示】李慧 老师</option></select>
        </div>
        <div class="col-md-6">
          <label class="form-label fw-semibold">星期几</label>
          <div class="d-flex flex-wrap gap-1">
            <span class="badge text-bg-primary">周一</span><span class="badge text-bg-light border">周二</span>
            <span class="badge text-bg-light border">周三</span><span class="badge text-bg-light border">周四</span>
            <span class="badge text-bg-light border">周五</span><span class="badge text-bg-light border">周六</span>
            <span class="badge text-bg-light border">周日</span>
          </div>
        </div>
        <div class="col-md-6">
          <label class="form-label fw-semibold">上课时间</label>
          <select class="form-select"><option>第3节 14:00</option></select>
          <details class="mt-1"><summary class="small text-primary">没有合适节次？自己填时间</summary>
            <div class="d-flex gap-2 mt-2"><input type="time" class="form-control form-control-sm"><input type="time" class="form-control form-control-sm"></div>
          </details>
        </div>
        <div class="col-md-6">
          <label class="form-label fw-semibold">起止日期</label>
          <div class="d-flex gap-2 align-items-center">
            <input type="date" class="form-control" value="2026-10-05">
            <span class="text-muted">~</span>
            <input type="date" class="form-control" value="2026-12-20">
          </div>
          <div class="small text-muted mt-1">已按第一学期预填（2026-06-23 ~ 2026-12-20）</div>
        </div>
        <div class="col-md-6">
          <label class="form-label fw-semibold">教室（可不填）</label>
          <select class="form-select"><option>— 不指定 —</option></select>
        </div>
        <div class="col-12">
          <details><summary class="small text-primary">高级：只排部分周 / 单双周</summary>
            <div class="row g-2 mt-2">
              <div class="col-md-6"><input class="form-control" placeholder="如 1,3-5,8-12，留空=整学期"></div>
              <div class="col-md-6"><select class="form-select"><option>每周</option><option>单周</option><option>双周</option></select></div>
            </div>
          </details>
        </div>
      </div>
      <hr class="my-3">
      <div class="d-flex flex-wrap align-items-center gap-3">
        <button class="btn btn-primary px-4">预览将生成的课节</button>
        <span class="small text-muted">有冲突的课节不会被创建，预览里会逐条说明</span>
      </div>
    </div>
  </div>
  <div class="small text-muted mt-3">其他工具：<a href="#">停用某班 / 某个合班的全部课时</a></div>
</div>
"""

def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        login(pg)

        # A. stale hint: /timetable/copy ?
        r = pg.goto(BASE + "/timetable/copy", wait_until="domcontentloaded")
        print("A_COPY_ROUTE", r.status, pg.url)

        # B. confirm page for a combined batch (id 10 = B1-B4全体)
        pg.goto(BASE + "/timetable/batch/10/deactivate", wait_until="load"); pg.wait_for_timeout(700)
        info = pg.evaluate("""() => {
          const body = document.body.innerText;
          return {
            h: document.body.scrollHeight,
            badgeCodes: (body.match(/[（(][A-Z]\\d[^）)]*[）)]/g)||[]).length,
            daitihao: (body.match(/代号/g)||[]).length,
            tuiDao: (body.match(/推导/g)||[]).length,
            inputs: document.querySelectorAll('input').length,
            buttons: Array.from(document.querySelectorAll('button')).map(x=>x.innerText.replace(/\\s+/g,' ').trim()),
            cards: Array.from(document.querySelectorAll('.card-header')).map(x=>x.innerText.replace(/\\s+/g,' ').trim()),
            firstText: body.slice(0, 700).replace(/\\s+/g,' '),
          };
        }""")
        print("B_CONFIRM_PAGE", json.dumps(info, ensure_ascii=False)[:2600])
        pg.screenshot(path=OUT + "/b-confirm-combined.png", full_page=True)

        # C. where do the tiny icons before labels come from?
        pg.goto(BASE + "/timetable/bulk", wait_until="load"); pg.wait_for_timeout(600)
        icons = pg.evaluate("""() => {
          const lab = document.querySelector('label[for=bk_course]');
          const cs = getComputedStyle(lab, '::before');
          const after = getComputedStyle(lab, '::after');
          return {beforeContent: cs.content, beforeFont: cs.fontFamily, afterContent: after.content,
                  html: lab.outerHTML.slice(0,200), parentHtml: lab.parentElement.outerHTML.slice(0, 400)};
        }""")
        print("C_LABEL_PSEUDO", json.dumps(icons, ensure_ascii=False))

        # D. mock layout measurement
        pg.evaluate("""(html) => {
          const wrap = document.querySelector('#wrap');
          wrap.innerHTML = html;
        }""", MOCK)
        pg.wait_for_timeout(300)
        m = pg.evaluate("""() => {
          const btn = document.querySelector('#mockroot button.btn-primary');
          const r = btn.getBoundingClientRect();
          const info = document.querySelector('#mockroot details[open]');
          return {bodyH: document.body.scrollHeight, btnY: Math.round(r.top + window.scrollY),
                  btnBottom: Math.round(r.bottom + window.scrollY),
                  formH: Math.round(document.querySelector('#mockroot .card').getBoundingClientRect().height),
                  inputs: document.querySelectorAll('#mockroot input, #mockroot select').length,
                  details: document.querySelectorAll('#mockroot details').length,
                  labelsVisible: document.querySelectorAll('#mockroot .form-label').length};
        }""")
        print("D_MOCK", json.dumps(m, ensure_ascii=False))
        pg.screenshot(path=OUT + "/d-mock-proposed.png", full_page=True)

        # E. mock with the multi-class details OPEN (worst case first paint)
        pg.evaluate("""() => document.querySelectorAll('#mockroot details').forEach(d => d.open = true)""")
        pg.wait_for_timeout(200)
        m2 = pg.evaluate("""() => {
          const btn = document.querySelector('#mockroot button.btn-primary');
          const r = btn.getBoundingClientRect();
          return {bodyH: document.body.scrollHeight, btnY: Math.round(r.top + window.scrollY)};
        }""")
        print("E_MOCK_OPEN", json.dumps(m2, ensure_ascii=False))
        pg.screenshot(path=OUT + "/e-mock-open.png", full_page=True)
        b.close()

main()
