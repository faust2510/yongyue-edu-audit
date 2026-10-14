/* 顶栏站内搜索：输入即出下拉建议（2026-09-29）。
 *
 * 用户定性：「不要等我回车才能搜索，输入之后下面就像浏览器一样有推荐」。
 *
 * 渐进增强（硬约束）：本脚本只是**增强层**。脚本不可用时，顶栏表单仍是
 * 原来的 GET /my/search（服务端渲染结果页），行为一个字没改。
 *
 * 无障碍（硬约束，本仓门禁基线 0、零余量）：下拉按 WAI-ARIA combobox 模式实现 ——
 *   input  : role=combobox / aria-expanded / aria-controls / aria-autocomplete /
 *            aria-haspopup / aria-activedescendant（仅在有高亮项时）
 *   弹层   : div[role=listbox]（稳定 id，aria-controls 的落点）
 *              div[role=group][aria-label=分组名]
 *                div[role=option][aria-selected]（可访问名来自内容）
 *   键盘   : ↑/↓ 移动（环绕）、回车打开高亮项、Esc 关闭（不冒泡，避免抢走
 *            search_focus.js 的「Esc 失焦」）、Tab 关闭
 *   鼠标   : mousedown 即跳转（preventDefault 保住焦点，避免 blur 先关面板）
 * 刻意**不默认高亮第一项**：回车仍是「提交表单看全部结果」——输入即出是增强，
 * 不改变用户已有的回车语义。
 */
(function () {
    "use strict";

    var ENDPOINT = "/my/search/suggest";
    var DEBOUNCE_MS = 200;
    var PANEL_ID = "yy-sg-panel";
    var LISTBOX_ID = "yy-sg-listbox";
    var OPT_ID = "yy-sg-opt-";

    function onReady(fn) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", fn);
        } else {
            fn();
        }
    }

    onReady(function () {
        var form = document.querySelector('form[action="/my/search"]');
        if (!form) {
            return;
        }
        var input = form.querySelector('input[name="q"]');
        if (!input || input.getAttribute("data-yy-suggest") === "1") {
            return;
        }
        input.setAttribute("data-yy-suggest", "1");

        // ---- DOM：定位容器 + 稳定的 listbox（aria-controls 必须指向**常驻**元素）----
        var wrap = document.createElement("div");
        wrap.className = "yy-sg-wrap";
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);

        var panel = document.createElement("div");
        panel.className = "yy-sg-panel";
        panel.id = PANEL_ID;
        panel.hidden = true;
        wrap.appendChild(panel);

        var listbox = document.createElement("div");
        listbox.className = "yy-sg-list";
        listbox.id = LISTBOX_ID;
        listbox.setAttribute("role", "listbox");
        listbox.setAttribute("aria-label", "搜索建议");
        panel.appendChild(listbox);

        // ---- combobox 语义 ----
        input.setAttribute("role", "combobox");
        input.setAttribute("aria-expanded", "false");
        input.setAttribute("aria-controls", LISTBOX_ID);
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-haspopup", "listbox");
        if (!input.getAttribute("aria-label")) {
            input.setAttribute("aria-label", "站内搜索");
        }
        // 别让浏览器自带的下拉与我们的叠加
        input.setAttribute("autocomplete", "off");

        var items = [];          // [{el, href}]
        var active = -1;
        var seq = 0;
        var timer = null;
        var lastQ = "";

        function setExpanded(on) {
            input.setAttribute("aria-expanded", on ? "true" : "false");
        }

        function highlight(next) {
            if (active >= 0 && items[active]) {
                items[active].el.setAttribute("aria-selected", "false");
            }
            active = next;
            if (active >= 0 && items[active]) {
                items[active].el.setAttribute("aria-selected", "true");
                input.setAttribute("aria-activedescendant", items[active].el.id);
                if (items[active].el.scrollIntoView) {
                    items[active].el.scrollIntoView({ block: "nearest" });
                }
            } else {
                input.removeAttribute("aria-activedescendant");
            }
        }

        function close() {
            panel.hidden = true;
            setExpanded(false);
            highlight(-1);
        }

        function open() {
            panel.hidden = false;
            setExpanded(true);
            clamp();
        }

        // 面板右/左越界时收回视口内（窄屏顶栏搜索框靠右，固定 left 会溢出）
        function clamp() {
            var rect = wrap.getBoundingClientRect();
            var width = Math.max(240, rect.width || 240);
            panel.style.minWidth = width + "px";
            var panelW = panel.offsetWidth || width;
            var left = rect.left;
            if (left + panelW > window.innerWidth - 8) {
                left = window.innerWidth - 8 - panelW;
            }
            if (left < 8) {
                left = 8;
            }
            panel.style.left = (left - rect.left) + "px";
        }

        function optionEl(it, kind) {
            var el = document.createElement("div");
            el.className = "yy-sg-item";
            el.id = OPT_ID + items.length;
            el.setAttribute("role", "option");
            el.setAttribute("aria-selected", "false");
            el.setAttribute("data-href", it.href || "");
            var ic = document.createElement("i");
            ic.className = "fa " + (kind === "entry" ? "fa-th-large" : "fa-search");
            ic.setAttribute("aria-hidden", "true");
            el.appendChild(ic);
            var txt = document.createElement("span");
            txt.className = "yy-sg-txt";
            var title = document.createElement("span");
            title.className = "yy-sg-title";
            title.textContent = it.title || "";
            txt.appendChild(title);
            if (it.desc) {
                var desc = document.createElement("span");
                desc.className = "yy-sg-desc";
                desc.textContent = it.desc;
                txt.appendChild(desc);
            }
            el.appendChild(txt);
            el.addEventListener("mousedown", function (ev) {
                ev.preventDefault();          // 保住焦点：blur 会先关掉面板
                go(-1, el.getAttribute("data-href"));
            });
            el.addEventListener("mousemove", function () {
                var idx = -1;
                for (var i = 0; i < items.length; i++) {
                    if (items[i].el === el) { idx = i; break; }
                }
                if (idx >= 0 && idx !== active) { highlight(idx); }
            });
            items.push({ el: el, href: el.getAttribute("data-href") });
            return el;
        }

        function render(data) {
            listbox.innerHTML = "";
            items = [];
            highlight(-1);
            var groups = (data && data.groups) || [];
            if (!groups.length) {
                // 空结果也给一句可读反馈（option 的上下文与可访问名都在）——
                // 回车仍是「看全部结果」，故该 option 不带 href。
                var empty = document.createElement("div");
                empty.setAttribute("role", "group");
                empty.setAttribute("aria-label", "无匹配");
                var tip = document.createElement("div");
                tip.className = "yy-sg-item yy-sg-item-empty";
                tip.setAttribute("role", "option");
                tip.setAttribute("aria-selected", "false");
                tip.setAttribute("aria-disabled", "true");
                tip.id = OPT_ID + "0";
                tip.textContent = "没有找到匹配项，按回车搜索全部结果";
                empty.appendChild(tip);
                listbox.appendChild(empty);
                items.push({ el: tip, href: "" });
                open();
                clamp();
                return;
            }
            groups.forEach(function (grp) {
                var box = document.createElement("div");
                box.setAttribute("role", "group");
                box.setAttribute("aria-label", grp.label || "建议");
                var head = document.createElement("div");
                head.className = "yy-sg-grp";
                head.setAttribute("aria-hidden", "true");
                head.textContent = grp.label || "";
                box.appendChild(head);
                var n = 0;
                (grp.items || []).forEach(function (it) {
                    box.appendChild(optionEl(it, grp.kind));
                    n += 1;
                });
                if (n) { listbox.appendChild(box); }
            });
            open();
            clamp();
        }

        function go(idx, href) {
            if (idx >= 0 && items[idx] && !items[idx].href) {
                form.submit();                 // 空态提示项：等价于直接回车
                return;
            }
            if (href) {
                window.location = href;
                return;
            }
            form.submit();
        }

        function fetchFor(q) {
            lastQ = q;
            var mine = ++seq;
            var url = ENDPOINT + "?q=" + encodeURIComponent(q);
            fetch(url, {
                credentials: "same-origin",
                headers: { "Accept": "application/json" }
            }).then(function (resp) {
                return resp.ok ? resp.json() : null;
            }).then(function (data) {
                // 迟到的响应丢弃：只认最后一次输入的结果
                if (!data || mine !== seq) { return; }
                if ((input.value || "").trim() !== q) { return; }
                if (data.throttled) { close(); return; }
                render(data);
            }).catch(function () {
                close();                       // 增强层失败就静默退回表单
            });
        }

        input.addEventListener("input", function () {
            var q = (input.value || "").trim();
            if (timer) { clearTimeout(timer); }
            if (!q) {
                seq += 1;
                close();
                return;
            }
            timer = setTimeout(function () { fetchFor(q); }, DEBOUNCE_MS);
        });

        input.addEventListener("focus", function () {
            var q = (input.value || "").trim();
            if (q && q === lastQ && items.length) { open(); }
        });

        input.addEventListener("blur", function () {
            window.setTimeout(close, 120);
        });

        input.addEventListener("keydown", function (ev) {
            var key = ev.key;
            if (key === "Escape") {
                if (!panel.hidden) {
                    ev.preventDefault();
                    ev.stopPropagation();      // 别让 search_focus.js 顺手把焦点撤了
                    close();
                }
                return;
            }
            if (key === "Tab") {
                close();
                return;
            }
            if (key === "ArrowDown" || key === "ArrowUp") {
                if (panel.hidden) {
                    var q = (input.value || "").trim();
                    if (!q) { return; }
                    ev.preventDefault();
                    if (q === lastQ && items.length) {
                        // 同一关键词的结果还在手上（最典型：刚按 Esc 关掉）——
                        // 同步重开并直接高亮，不给「↓ 之后马上回车」留异步窗口
                        open();
                        highlight(key === "ArrowDown" ? 0 : items.length - 1);
                    } else {
                        fetchFor(q);           // 首次开：不等防抖，立刻取
                    }
                    return;
                }
                if (!items.length) { return; }
                ev.preventDefault();
                var next;
                if (key === "ArrowDown") {
                    next = active + 1 >= items.length ? 0 : active + 1;
                } else {
                    next = active - 1 < 0 ? items.length - 1 : active - 1;
                }
                highlight(next);
                return;
            }
            if (key === "Enter" && !panel.hidden && active >= 0 && items[active]) {
                ev.preventDefault();
                items[active].el.setAttribute("aria-selected", "false");
                go(active, items[active].href);
            }
        });

        window.addEventListener("scroll", close, { passive: true });
        window.addEventListener("resize", close);
    });
})();
