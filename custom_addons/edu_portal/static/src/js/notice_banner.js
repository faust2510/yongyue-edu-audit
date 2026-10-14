/** @odoo-module **/
/* notice-banner 门户顶部公告横幅：拉取 /my/notice_banner 轮播渲染。
   对标 tokenrouter 式蓝底横幅：左侧徽标胶囊 + 正文 + CTA 链接 +
   底部圆点轮播（自动 5s，悬停暂停），两端 🎉 装饰。
   管理员在「教务审批 → 布告栏管理」开关每条公告的横幅展示；
   用户点 × 关闭当前横幅（localStorage 记忆，仅隐藏不退订）。
   无数据 / 请求失败：静默移除挂载点，页面零变化。 */
(function () {
    "use strict";

    var ROTATE_MS = 5000;
    var STORE_KEY = "edu_banner_dismissed";

    function dismissedIds() {
        try {
            var raw = JSON.parse(localStorage.getItem(STORE_KEY) || "[]");
            return Array.isArray(raw) ? raw.map(Number) : [];
        } catch (e) {
            return [];
        }
    }

    function rememberDismissed(id) {
        try {
            var ids = dismissedIds().filter(function (v, i, a) {
                return a.indexOf(v) === i && !isNaN(v);
            });
            ids.push(id);
            while (ids.length > 50) { ids.shift(); }
            localStorage.setItem(STORE_KEY, JSON.stringify(ids));
        } catch (e) { /* 隐私模式等场景下忽略 */ }
    }

    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) { node.className = cls; }
        if (text !== undefined) { node.textContent = text; }
        return node;
    }

    function buildBar(zone, banners) {
        var bar = el("div", "edu-notice-bar");
        bar.setAttribute("role", "region");
        bar.setAttribute("aria-label", "公告横幅");

        bar.appendChild(el("span", "edu-notice-spark", "🎉"));

        var track = el("div", "edu-notice-track");
        var dots = el("div", "edu-notice-dots");
        var timer = null;
        var current = 0;

        var slides = banners.map(function (b) {
            var slide = el("div", "edu-notice-slide");
            if (b.badge) {
                slide.appendChild(el("span", "edu-notice-badge", b.badge));
            }
            slide.appendChild(el("span", "edu-notice-text", b.text));
            var cta = el("a", "edu-notice-cta", b.cta + " →");
            cta.href = b.url;
            slide.appendChild(cta);
            track.appendChild(slide);
            return slide;
        });

        var dotEls = banners.map(function (b, i) {
            var dot = el("button", "edu-notice-dot");
            dot.type = "button";
            dot.setAttribute("aria-label", "第 " + (i + 1) + " 条公告");
            dot.addEventListener("click", function () { show(i, true); });
            dots.appendChild(dot);
            return dot;
        });

        function show(i, manual) {
            current = (i + slides.length) % slides.length;
            slides.forEach(function (s, k) {
                s.classList.toggle("is-active", k === current);
            });
            dotEls.forEach(function (d, k) {
                d.classList.toggle("is-active", k === current);
            });
            if (manual) { restart(); }
        }

        function restart() {
            if (timer) { clearInterval(timer); }
            timer = setInterval(function () { show(current + 1); }, ROTATE_MS);
        }

        bar.appendChild(track);
        bar.appendChild(dots);

        var close = el("button", "edu-notice-close", "×");
        close.type = "button";
        close.setAttribute("aria-label", "关闭本条横幅");
        close.addEventListener("click", function () {
            rememberDismissed(banners[current].id);
            slides[current].remove();
            dotEls[current].remove();
            slides.splice(current, 1);
            dotEls.splice(current, 1);
            if (slides.length) {
                show(current % slides.length, true);
            } else {
                stop();
                bar.remove();
            }
        });
        bar.appendChild(close);

        bar.appendChild(el("span", "edu-notice-spark edu-notice-spark--right", "🎉"));

        bar.addEventListener("mouseenter", function () {
            if (timer) { clearInterval(timer); timer = null; }
        });
        bar.addEventListener("mouseleave", restart);

        zone.replaceChildren(bar);
        show(0);
        restart();
    }

    function init() {
        var zone = document.getElementById("edu-notice-banner");
        if (!zone) { return; }
        fetch(zone.getAttribute("data-fetch") || "/my/notice_banner", {
            headers: { "Accept": "application/json" },
            credentials: "same-origin",
        }).then(function (resp) {
            if (!resp.ok) { throw new Error("HTTP " + resp.status); }
            return resp.json();
        }).then(function (data) {
            var dismissed = dismissedIds();
            var banners = ((data || {}).banners || []).filter(function (b) {
                return dismissed.indexOf(b.id) === -1;
            });
            if (!banners.length) {
                zone.remove();
                return;
            }
            buildBar(zone, banners);
        }).catch(function () {
            zone.remove(); // 拉取失败静默收场，不影响页面
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
