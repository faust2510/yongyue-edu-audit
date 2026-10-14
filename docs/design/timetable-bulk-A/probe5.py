
import json
from playwright.sync_api import sync_playwright
BASE="http://127.0.0.1:8069"; OUT="/tmp/timetable-bulk-A"
def login(pg):
    pg.goto(BASE+"/web/login?db=edu19", wait_until="domcontentloaded")
    pg.fill("input[name=login]","backoffice@local"); pg.fill("input[name=password]","demo123")
    try: pg.click("form.oe_login_form button[type='submit']", timeout=10000)
    except Exception: pg.press("input[name=password]","Enter")
    pg.wait_for_load_state("domcontentloaded"); pg.wait_for_timeout(1200)

WIZARD = """
<div class="container pt-3" id="mockroot" style="max-width:960px">
  <div class="small text-muted mb-2">家 / 排课 / <span class="fw-semibold text-body">周期排课</span></div>
  <div class="d-flex align-items-baseline justify-content-between mb-2">
    <div><h4 class="mb-1">周期排课</h4>
    <div class="text-muted small">填完下面的项目 → 预览 → 生成。生成前不会写入任何课节。</div></div>
    <div class="small text-muted">1 填表 · 2 预览 · 3 生成</div>
  </div>
  <div class="alert alert-light border py-1 px-2 small mb-2"><i class="fa fa-flag me-1"></i>本学期已登记 1 个停课日，生成时自动跳过（<a href="#">查看</a>）</div>
  <div class="card shadow-sm border-0 rounded-3">
    <div class="card-body">
      <div class="row g-3">
        <div class="col-md-6"><label class="form-label fw-semibold">班级</label>
          <select class="form-select"><option>神学一年级</option></select>
          <details class="mt-1"><summary class="small text-primary">还要给别的班一起排（时间自动错开）</summary>
            <div class="border rounded-3 p-2 mt-2 small"><div class="d-flex flex-wrap gap-2">
              <span class="badge text-bg-light border">神学一年级</span><span class="badge text-bg-light border">神学二年级</span>
              <span class="badge text-bg-light border">人文一年级</span><span class="badge text-bg-light border">A1+A2+A3合班</span></div>
              <div class="mt-2"><label class="form-label small mb-1">每班顺延（分钟）</label>
              <input class="form-control form-control-sm" placeholder="留空 = 一个课时长"></div></div></details></div>
        <div class="col-md-6"><label class="form-label fw-semibold">课程</label>
          <select class="form-select"><option>文学学士</option></select>
          <input class="form-control form-control-sm mt-1" placeholder="或直接输入新课程名"></div>
        <div class="col-md-6"><label class="form-label fw-semibold">科目</label>
          <select class="form-select"><option>基础信仰</option></select>
          <input class="form-control form-control-sm mt-1" placeholder="或直接输入新科目名"></div>
        <div class="col-md-6"><label class="form-label fw-semibold">教师</label>
          <select class="form-select"><option>【演示】李慧 老师</option></select></div>
        <div class="col-md-6"><label class="form-label fw-semibold">星期几</label>
          <div class="d-flex flex-wrap gap-1"><span class="badge text-bg-primary">周一</span><span class="badge text-bg-light border">周二</span>
          <span class="badge text-bg-light border">周三</span><span class="badge text-bg-light border">周四</span>
          <span class="badge text-bg-light border">周五</span><span class="badge text-bg-light border">周六</span>
          <span class="badge text-bg-light border">周日</span></div></div>
        <div class="col-md-6"><label class="form-label fw-semibold">上课时间</label>
          <select class="form-select"><option>第3节 14:00</option></select>
          <details class="mt-1"><summary class="small text-primary">没有合适节次？自己填时间</summary>
            <div class="d-flex gap-2 mt-2"><input type="time" class="form-control form-control-sm"><input type="time" class="form-control form-control-sm"></div></details></div>
        <div class="col-md-6"><label class="form-label fw-semibold">起止日期</label>
          <div class="d-flex gap-2 align-items-center"><input type="date" class="form-control" value="2026-10-04">
          <span class="text-muted">~</span><input type="date" class="form-control" value="2026-12-20"></div>
          <div class="small text-muted mt-1">已按第一学期预填</div></div>
        <div class="col-md-6"><label class="form-label fw-semibold">教室（可不填）</label>
          <select class="form-select"><option>— 不指定 —</option></select></div>
        <div class="col-12"><details><summary class="small text-primary">高级：只排部分周 / 单双周</summary>
          <div class="row g-2 mt-2"><div class="col-md-6"><input class="form-control" placeholder="如 1,3-5,8-12；留空 = 整学期"></div>
          <div class="col-md-6"><select class="form-select"><option>每周</option><option>单周</option><option>双周</option></select></div></div></details></div>
      </div>
      <hr class="my-3">
      <div class="d-flex flex-wrap align-items-center gap-3">
        <button class="btn btn-primary px-4">预览将生成的课节</button>
        <span class="small text-muted">有冲突的课节不会被创建，预览里逐条说明</span></div>
    </div></div>
  <div class="small text-muted mt-3 d-flex gap-3 flex-wrap">
    <span>其他工具：<a href="#">批量停用某班的全部课时</a></span>
    <span>只想改一节？去<a href="#">后台时间表</a>直接改删</span></div>
</div>
"""

STOP = """
<div class="container pt-3" id="mockroot" style="max-width:960px">
  <div class="small text-muted mb-2">家 / 排课 / <span class="fw-semibold text-body">批量停用课时</span></div>
  <h4 class="mb-1">批量停用课时</h4>
  <div class="text-muted small mb-3">停用 = 状态改成「停课」，记录不删、随时可改回；学生和老师的课表马上不再显示。</div>
  <div class="card shadow-sm border-0 rounded-3">
    <div class="card-header bg-white fw-semibold">有在用课时的班级（14）</div>
    <div class="card-body p-0 table-responsive"><table class="table table-sm align-middle mb-0 edu-card-table">
      <thead class="table-light"><tr><th>班级</th><th class="text-end">在用</th><th class="text-end">已停用</th><th></th></tr></thead>
      <tbody>
        <tr><td>A1+A2+A3合班 <span class="badge text-bg-light border">合班</span></td><td class="text-end">23</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>预备科 · 2026级【演示】</td><td class="text-end">72</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>人文三年级</td><td class="text-end">40</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>人文一年级</td><td class="text-end">18</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>B1-B4全体 <span class="badge text-bg-light border">合班</span></td><td class="text-end">18</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>人文四年级</td><td class="text-end">15</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>A123+B1合班 <span class="badge text-bg-light border">合班</span></td><td class="text-end">15</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>B2+B3+B4合班 <span class="badge text-bg-light border">合班</span></td><td class="text-end">15</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>A123+B234合班 <span class="badge text-bg-light border">合班</span></td><td class="text-end">12</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>A23+B34合班 <span class="badge text-bg-light border">合班</span></td><td class="text-end">12</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>A123+B34合班 <span class="badge text-bg-light border">合班</span></td><td class="text-end">11</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>A2+A3合班 <span class="badge text-bg-light border">合班</span></td><td class="text-end">6</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>神学一年级</td><td class="text-end">4</td><td class="text-end text-muted">0</td><td class="text-end"><a class="btn btn-sm btn-outline-danger">停用…</a></td></tr>
        <tr><td>人文二年级</td><td class="text-end">0</td><td class="text-end text-muted">0</td><td class="text-end"></td></tr>
      </tbody></table></div></div>
  <details class="mt-2"><summary class="small text-primary">没有在用课时的班级（3）</summary>
    <div class="small text-muted mt-1">神学二年级 · 神学三年级 · 人文二年级 —— 这些班当前没有课时，无需停用。</div></details>
</div>
"""

def measure(pg, label):
    m = pg.evaluate("""() => {
      const btn = document.querySelector('#mockroot button.btn-primary');
      const r = btn ? btn.getBoundingClientRect() : null;
      return {bodyH: document.body.scrollHeight,
              btnY: r ? Math.round(r.top + window.scrollY) : null,
              cardH: Math.round(document.querySelector('#mockroot .card').getBoundingClientRect().height),
              controls: document.querySelectorAll('#mockroot input, #mockroot select').length,
              details: document.querySelectorAll('#mockroot details').length,
              mutedLines: Array.from(document.querySelectorAll('#mockroot .small, #mockroot .text-muted')).filter(e=>e.innerText.trim()).length,
              rows: document.querySelectorAll('#mockroot tbody tr').length,
              stopBtns: document.querySelectorAll('#mockroot a.btn-outline-danger').length};
    }""")
    print(label, json.dumps(m, ensure_ascii=False))

with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1440,"height":900})
    login(pg); pg.goto(BASE+"/timetable/bulk", wait_until="load"); pg.wait_for_timeout(500)
    pg.evaluate("(h)=>{document.querySelector('#wrap').innerHTML=h}", WIZARD); pg.wait_for_timeout(300)
    measure(pg, "A_WIZARD_DEFAULT")
    pg.screenshot(path=OUT+"/a2-wizard.png", full_page=True)
    pg.evaluate("()=>document.querySelectorAll('#mockroot details').forEach(d=>d.open=true)"); pg.wait_for_timeout(200)
    measure(pg, "A_WIZARD_ALLOPEN")
    pg.evaluate("(h)=>{document.querySelector('#wrap').innerHTML=h}", STOP); pg.wait_for_timeout(300)
    measure(pg, "B_STOP_LIST")
    pg.screenshot(path=OUT+"/b2-stop.png", full_page=True)
    b.close()
