// tests/color/capture_page.js — Tabbit/Playwright 取色程序（单页）
//
// 由 tests/color/color_audit.py 做占位符替换后经 stdin 提交给 tabbit-cli：
//   __URL__   -> 目标页绝对 URL
//   __LABEL__ -> 页面 key（用于错误归因）
//
// 口径（与 docs/audit/ui-color-audit-2026-09-15.md §7.3 对齐）：
//   · 四属性：text=computed color / bg=computed background-color /
//             border=真实边框色 / anchor=<a> 的 computed color
//   · 逐元素 computed 值去重计数；只统计「可见」元素
//   · 原始值原样保留（含 rgba(0,0,0,0) 与 color(srgb …)）；归一与剔除由 color_audit.py 做
//   · anchor 值按归档 schema 追加 " | -"（来源变量未知，与生产归档一致）
//
// 可见性判据：display!=none 且 visibility!=hidden 且 computed opacity!=0
//   且 getBoundingClientRect 宽高不全为 0。（生产 §1 的「可见元素」数可比：
//   本地 / 实测 262，生产归档 241。）
//
// 除四属性外另抓两组「回归锚点」数据（captain 2026-09-15 要求）：
//   tokens   —— documentElement 与 body 上若干令牌的计算值（含 --body-color / --text-3 / --brand-action）
//   contrast —— 每个「自己直接含文本」的元素的实际 (前景色, 有效背景色) 对
//               （有效背景 = 自身或最近祖先的非透明 backgroundColor）
//
// ⚠ 每次取色都新开 page 并在 finally 关闭：
//   实测某页 goto 超时后会把复用中的 page 卡死，之后的请求会「瞬时失败」而非超时；
//   换新 page 可让失败只影响当次。

const target = "__URL__";
const label = "__LABEL__";

// 需要留档计算值的令牌（回归锚点 + 报告用）
const TOKEN_NAMES = [
  "--body-color", "--text-1", "--text-2", "--text-3",
  "--bg", "--surface-card", "--border",
  "--brand-500", "--brand-action", "--brand-action-hover",
  "--success", "--danger", "--warning", "--warning-ink",
  "--info", "--info-soft", "--success-soft", "--danger-soft", "--warning-soft",
  "--focus-ring",
  "--bs-body-color", "--o-cc1-text",
];

const tab = await context.newPage();
try {
  // 实测：DB 序列化争用下带会话的首屏可达 ~100s（Odoo werkzeug 日志 101.022s），故给 120s。
  await tab.goto(target, { waitUntil: "domcontentloaded", timeout: 120000 });
  // ⚠ Odoo 19 的 bus 长连接让 networkidle 基本永不触发 —— 只给它 5s 兜底，不靠它判「渲染完」。
  await tab.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});
  // SPA（/odoo/*、/apps）挂载后才有内容；等一个通用容器。
  await tab.waitForSelector(".o_web_client, .o_action_manager, main, #wrap", { timeout: 8000 }).catch(() => {});
  // ⚠ 固定 sleep 不可靠：高负载下门户页的元素数会从 ~150 缓慢长到 ~350，
  //   取早了读数直接偏小（实测同一页两次相差一倍以上）。改为「元素数连续 5 次采样不变」才取。
  let lastN = -1;
  let stable = 0;
  for (let i = 0; i < 40; i++) {
    const n = await tab.evaluate(() => document.querySelectorAll("body *").length);
    if (n === lastN) {
      stable += 1;
      if (stable >= 5) break;
    } else {
      stable = 0;
      lastN = n;
    }
    await tab.waitForTimeout(600);
  }
  await tab.waitForTimeout(800);

  const data = await tab.evaluate((names) => {
    const bump = (m, k) => m.set(k, (m.get(k) || 0) + 1);
    const text = new Map(), bg = new Map(), border = new Map(), anchor = new Map();
    const contrast = new Map();
    let scanned = 0, visible = 0, textEls = 0;

    const parseColor = (s) => {
      const m = /rgba?\(([^)]+)\)/.exec(s || "");
      if (!m) return null;
      const p = m[1].split(",").map((x) => parseFloat(x));
      if (p.length < 3 || p.some((v) => Number.isNaN(v))) return null;
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    };

    // 有效背景：自身或最近祖先上第一个「不透明到足以遮住背景」的 backgroundColor
    const effectiveBg = (el) => {
      let node = el;
      while (node && node.nodeType === 1) {
        const c = parseColor(getComputedStyle(node).backgroundColor);
        if (c && c.a > 0.05) return getComputedStyle(node).backgroundColor;
        node = node.parentElement;
      }
      return "rgb(255, 255, 255)";
    };

    // 只算「自己直接含文本」的元素，避免把纯容器算进来
    const hasOwnText = (el) => {
      for (const n of el.childNodes) {
        if (n.nodeType === 3 && n.textContent && n.textContent.trim()) return true;
      }
      return false;
    };

    for (const el of document.querySelectorAll("body *")) {
      scanned += 1;
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      if (parseFloat(cs.opacity) === 0) continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 && r.height <= 0) continue;
      visible += 1;
      bump(text, cs.color);
      bump(bg, cs.backgroundColor);
      // ⚠ 只记「真的画出来的」边框：元素无边框宽度时 border-*-color 仍会返回
      //   currentColor（= 文字色），会把边框列污染成文字列的副本（实测本地 / 得到 33 色、
      //   其中大半与 text 逐项相同）。生产归档的边框列明显不是这个形态 ⇒ 必须按宽度过滤。
      if (parseFloat(cs.borderTopWidth) > 0) bump(border, cs.borderTopColor);
      if (parseFloat(cs.borderRightWidth) > 0) bump(border, cs.borderRightColor);
      if (parseFloat(cs.borderBottomWidth) > 0) bump(border, cs.borderBottomColor);
      if (parseFloat(cs.borderLeftWidth) > 0) bump(border, cs.borderLeftColor);
      if (el.tagName === "A") bump(anchor, cs.color);

      if (hasOwnText(el)) {
        textEls += 1;
        bump(contrast, cs.color + " @@ " + effectiveBg(el));
      }
    }

    // 焦点环：WCAG 1.4.11「非文本对比度」—— 环色（按 alpha 合成到参照背景上）vs 参照背景，需 >= 3:1。
    // **两种形态都要覆盖**：
    //   (a) outline 形态 —— outline-width>0 且 outline-style!=none；
    //   (b) box-shadow 形态 —— 这是 Bootstrap 5 / Odoo 以及 backend_b11.css:58
    //       （box-shadow: 0 0 0 .2rem rgba(14,123,242,.35)）用的形态。
    // ⚠ 只覆盖 (a) 会得到「没抓到」的假绿 —— 我们要修的那圈环恰恰是 (b)。
    const focus = new Map();
    let focusSampled = 0;
    let focusShadowSampled = 0;

    // 从一条 box-shadow 里判「这是不是一圈环」：非 inset、且 offsetX==0 && offsetY==0。
    const alphaOf = (c) => {
      if (/^transparent$/i.test(c)) return 0;
      const m = c.match(/rgba?\(([^)]+)\)/);
      if (!m) return 1;                       // #hex / color(...) 视为不透明
      const p = m[1].split(",").map((x) => x.trim());
      return p.length > 3 ? parseFloat(p[3]) : 1;
    };

    const ringFromShadow = (s) => {
      if (!s || /inset/.test(s)) return null;
      const cm = s.match(/(rgba?\([^)]+\)|color\([^)]+\)|#[0-9a-fA-F]{3,8})/);
      if (!cm) return null;
      const color = cm[1];
      const lens = (s.replace(color, "").match(/-?[\d.]+px/g) || []).map(parseFloat);
      if (lens.length < 2) return null;
      const ox = lens[0], oy = lens[1];
      const blur = lens.length > 2 ? lens[2] : 0;
      const spread = lens.length > 3 ? lens[3] : 0;
      if (ox !== 0 || oy !== 0) return null;        // 有偏移 ⇒ 是投影，不是环
      // ⚠ 必须是**画得出来**的环：全透明（Chrome 会输出 rgba(0,0,0,0)）且无扩散/模糊时不算环。
      //   不排掉会得到一批 1.00 的假违规。
      if (alphaOf(color) <= 0.01) return null;
      if (!(blur > 0 || spread > 0)) return null;
      return color;
    };

    // Chrome 的 computed boxShadow 可能有多条，逗号分隔；rgba() 内的逗号不能当分隔符。
    const splitShadows = (raw) => {
      const out = [];
      let depth = 0, cur = "";
      for (const ch of raw) {
        if (ch === "(") depth += 1;
        if (ch === ")") depth -= 1;
        if (ch === "," && depth === 0) { out.push(cur); cur = ""; } else { cur += ch; }
      }
      if (cur.trim()) out.push(cur);
      return out.map((x) => x.trim()).filter(Boolean);
    };

    const cands = [...document.querySelectorAll("a[href], button, .btn, input, select, textarea")].slice(0, 12);
    for (const el of cands) {
      const cs0 = getComputedStyle(el);
      if (cs0.display === "none" || cs0.visibility === "hidden") continue;
      const rc0 = el.getBoundingClientRect();
      if (rc0.width <= 0 && rc0.height <= 0) continue;
      try { el.focus({ preventScroll: true }); } catch (e) { continue; }
      const csF = getComputedStyle(el);
      const refBg = effectiveBg(el);

      // (a) outline 形态
      const ow = parseFloat(csF.outlineWidth) || 0;
      if (ow > 0 && csF.outlineStyle && csF.outlineStyle !== "none") {
        focusSampled += 1;
        bump(focus, csF.outlineColor + " @@ " + refBg + " @@ outline");
      }
      // (b) box-shadow 形态
      const bs = csF.boxShadow;
      if (bs && bs !== "none") {
        for (const sh of splitShadows(bs)) {
          const ringColor = ringFromShadow(sh);
          if (ringColor) {
            focusShadowSampled += 1;
            bump(focus, ringColor + " @@ " + refBg + " @@ box-shadow");
          }
        }
      }
      try { el.blur(); } catch (e) {}
    }

    const rootCS = getComputedStyle(document.documentElement);
    const bodyCS = getComputedStyle(document.body);
    const tokens = {};
    for (const n of names) {
      tokens[n] = (rootCS.getPropertyValue(n) || "").trim();
      tokens[n + "@body"] = (bodyCS.getPropertyValue(n) || "").trim();
    }

    const dump = (m) =>
      [...m.entries()]
        .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
        .map(([c, n]) => [c, n]);

    return {
      title: document.title,
      url: location.href,
      scanned,
      visible,
      textEls,
      // outcome 级锚点（captain 2026-09-15 修正读取位置）：
      // 修复后的声明可能落在 **body 元素**而非 :root ⇒ 只读 documentElement 的 --body-color 会误判。
      // body 的 used color 是最终渲染结果，与声明落点无关，才是可信锚点。
      bodyColor: getComputedStyle(document.body).color,
      htmlColor: getComputedStyle(document.documentElement).color,
      // 校名/链接色锚点（eng-web 2026-09-15 建议）：
      // ⚠ 判据必须是「== --brand-action 的 rgb」，**不能**写成「!= #0F34C3」——
      //   因为 auto-contrast 会派生另一个蓝 #0955A7（实测过），后者仍令牌外却会蒙混过关。
      brand: (() => {
        const el = document.querySelector("a.navbar-brand, .navbar-brand");
        if (!el) return { found: false };
        const cs = getComputedStyle(el);
        return { found: true, tag: el.tagName, cls: String(el.className || "").slice(0, 40), color: cs.color };
      })(),
      text: dump(text),
      bg: dump(bg),
      border: dump(border),
      anchor: dump(anchor).map(([c, n]) => [c + " | -", n]),
      focusSampled,
      focusShadowSampled,
      focus: [...focus.entries()]
        .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
        .map(([k, n]) => {
          const parts = k.split(" @@ ");
          return [parts[0], parts[1], n, parts[2] || "?"];
        }),
      contrast: [...contrast.entries()]
        .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
        .map(([k, n]) => {
          const parts = k.split(" @@ ");
          return [parts[0], parts[1], n];
        }),
      tokens,
    };
  }, TOKEN_NAMES);

  return { label, value: data };
} finally {
  await tab.close().catch(() => {});
}
