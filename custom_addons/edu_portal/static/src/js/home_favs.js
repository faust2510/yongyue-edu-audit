/* W1/W2：常用应用置顶区编辑（渐进增强，零后端改动）。
 *
 * - 存储：localStorage 键 home_favs_<role>（role 来自 [data-home-role]）；
 *   未设置偏好时页面完全按服务端默认渲染（零丢失）。
 * - 加载：有本地偏好时按存储顺序重建常用区；
 *   存储为空数组 = 隐藏常用区（企微「无常用则不显示常用区」）。
 * - 交互：桌面 hover 卡片右上角「⋯」→ 固定/取消固定/上移/下移；
 *   编辑按钮进入编辑态后显示固定/取消固定/上移/下移按钮（移动端可用）。
 * - 仅重排 DOM 与 localStorage，不触碰任何业务逻辑与选择器。
 */
(function () {
    "use strict";

    var wrap = document.querySelector("[data-home-role]");
    if (!wrap) {
        return;
    }
    var role = (wrap.getAttribute("data-home-role") || "generic").replace(/[^a-z0-9_-]/gi, "");
    var STORE = "home_favs_" + role;
    var favGrid = wrap.querySelector("[data-fav-grid]");
    if (!favGrid) {
        return;
    }

    function read() {
        try {
            var raw = localStorage.getItem(STORE);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            return null;
        }
    }

    function save(list) {
        try {
            localStorage.setItem(STORE, JSON.stringify(list));
        } catch (e) { /* 隐私模式等：静默降级为仅本次页面生效 */ }
    }

    function esc(href) {
        if (window.CSS && CSS.escape) {
            return CSS.escape(href);
        }
        return href.replace(/["\\]/g, "\\$&");
    }

    function cardByHref(href) {
        if (!href) { return null; }
        var a = wrap.querySelector('a[data-app-href="' + esc(href) + '"]');
        return a ? a.closest(".o_portal_index_card") : null;
    }

    function favHrefs() {
        return Array.prototype.map.call(
            favGrid.querySelectorAll('a[data-app-href]'),
            function (a) { return a.getAttribute("data-app-href"); });
    }

    function isFav(href) {
        return !!favGrid.querySelector('a[data-app-href="' + esc(href) + '"]');
    }

    function favCategory() {
        return favGrid.closest(".ux-fav-category")        // v2 首页分组
            || favGrid.closest(".card");                   // 教师工作台卡片
    }

    /** 进入/退出编辑态：给常用区与非常用卡片挂排序/固定控件 */
    function setEditMode(on) {
        wrap.classList.toggle("ux-fav-editing", on);
        document.querySelectorAll(".ux-fav-edit-toggle").forEach(function (btn) {
            var icon = btn.querySelector(".fa");
            btn.classList.toggle("active", on);
            if (icon) {
                icon.className = "fa " + (on ? "fa-check" : "fa-pencil");
            }
            var label = btn.lastChild;
            if (label && label.nodeType === 3) {
                label.nodeValue = on ? "完成" : "编辑";
            }
        });
    }

    /** 常用区显示/隐藏（空 = 隐藏整个常用区标题与网格） */
    function showFav(visible) {
        var cat = favCategory();
        if (cat) {
            cat.style.display = visible ? "" : "none";
        }
    }

    function cleanClone(clone) {
        clone.removeAttribute("id");
        var menu = clone.querySelector(".ux-fav-menu");
        if (menu) { menu.remove(); }   // 由 decorateCard 按新位置重挂
        return clone;
    }

    /** 渲染常用区：按 hrefs 顺序重建（克隆自全站卡片，避免重复 id） */
    function renderFavs(hrefs) {
        while (favGrid.firstChild) {
            favGrid.removeChild(favGrid.firstChild);
        }
        hrefs.forEach(function (href) {
            var src = cardByHref(href);
            if (!src) { return; }
            favGrid.appendChild(cleanClone(src.cloneNode(true)));
        });
    }

    function currentOrder() {
        var order = [];
        // 常用区（有存储时按存储；无存储时按 DOM）
        favHrefs().forEach(function (h) { if (order.indexOf(h) < 0) { order.push(h); } });
        return order;
    }

    /** 3b 收藏服务端化：本地持久化的同时同步到服务端（fire-and-forget）。
     *  服务端失败不影响本页交互（localStorage 仍是兜底）。 */
    function syncServer(list) {
        var csrf = wrap.getAttribute("data-csrf");
        if (!csrf || !window.fetch) { return; }
        try {
            var body = new FormData();
            body.append("csrf_token", csrf);
            list.forEach(function (h) { body.append("hrefs", h); });
            fetch("/my/favorites/save", {
                method: "POST",
                body: body,
                keepalive: true,
            }).catch(function () { /* 网络失败静默：本地已保存 */ });
        } catch (e) { /* 同上 */ }
    }

    function persist() {
        var order = currentOrder();
        save(order);
        syncServer(order);
        showFav(order.length > 0);
    }

    /** 固定到常用：把卡片克隆进常用区（原卡保留，双侧可点） */
    function pin(href) {
        if (isFav(href)) { return; }
        var src = cardByHref(href);
        if (!src) { return; }
        favGrid.appendChild(cleanClone(src.cloneNode(true)));
        persist();
        syncBadges();
    }

    /** 取消固定：移除常用区中的克隆并持久化 */
    function unpin(href) {
        var el = favGrid.querySelector('a[data-app-href="' + esc(href) + '"]');
        if (el) {
            var card = el.closest(".o_portal_index_card");
            if (card) { card.remove(); }
        }
        persist();
        syncBadges();
    }

    /** 上移/下移（仅在同一分组内交换；常用区顺序持久化） */
    function move(href, dir) {
        var scope = isFav(href) ? favGrid : wrap;
        var cards = Array.prototype.filter.call(
            scope.querySelectorAll(".o_portal_index_card"),
            function (c) { return c.querySelector('a[data-app-href]'); });
        var idx = -1;
        cards.forEach(function (c, i) {
            var a = c.querySelector('a[data-app-href]');
            if (a && a.getAttribute("data-app-href") === href) { idx = i; }
        });
        if (idx < 0) { return; }
        var j = idx + dir;
        if (j < 0 || j >= cards.length) { return; }
        var target = cards[j];
        var card = cards[idx];
        if (dir < 0) {
            scope.insertBefore(card, target);
        } else {
            scope.insertBefore(card, target.nextSibling);
        }
        persist();
        syncBadges();
    }

    /** 编辑态徽标与「⋯」按钮同步（克隆卡片上的徽标保持原值） */
    function syncBadges() {
        // 常用区克隆卡片可能携带旧角标数据；从原卡取最新 data-msg-badge 同步
        favGrid.querySelectorAll("a[data-app-href]").forEach(function (a) {
            var href = a.getAttribute("data-app-href");
            var src = cardByHref(href);
            if (!src) { return; }
            var srcBadge = src.querySelector("[data-msg-badge]");
            var dstBadge = a.querySelector("[data-msg-badge]");
            if (srcBadge && dstBadge) {
                dstBadge.textContent = srcBadge.textContent;
            }
        });
    }

    // ---- 初始化 ----
    // 3b：SSR 已按服务端收藏直出时（data-fav-server="1"），localStorage 仅作
    // 兜底不再覆盖；服务端无收藏（"0"）时维持原有 localStorage 行为。
    var stored = read();
    var serverReady = wrap.getAttribute("data-fav-server") === "1";
    if (stored !== null && !serverReady) {
        if (stored.length) {
            renderFavs(stored);
            showFav(true);
        } else {
            showFav(false);
        }
    }

    // 编辑态开关（卡片头部的「编辑」按钮；教师工作台与 v2 首页共用类名）
    document.querySelectorAll(".ux-fav-edit-toggle").forEach(function (btn) {
        btn.addEventListener("click", function (ev) {
            ev.preventDefault();
            setEditMode(!wrap.classList.contains("ux-fav-editing"));
        });
    });

    // 卡片级操作（事件委托：hover「⋯」菜单 + 编辑态固定/取消固定/上移/下移）
    wrap.addEventListener("click", function (ev) {
        var btn = ev.target.closest("[data-fav-act]");
        if (!btn) { return; }
        ev.preventDefault();
        ev.stopPropagation();
        var href = btn.getAttribute("data-fav-href");
        var act = btn.getAttribute("data-fav-act");
        if (act === "pin") { pin(href); }
        else if (act === "unpin") { unpin(href); }
        else if (act === "up") { move(href, -1); }
        else if (act === "down") { move(href, 1); }
    });

    // 为每张带 data-app-href 的卡片注入编辑控件（编辑器按钮与移动箭头）
    function decorateCard(card) {
        if (card.querySelector("[data-fav-act]")) { return; }
        var a = card.querySelector("a[data-app-href]");
        if (!a) { return; }
        var href = a.getAttribute("data-app-href");
        var menu = document.createElement("span");
        menu.className = "ux-fav-menu";
        menu.setAttribute("aria-hidden", "true");
        var mk = function (act, icon, title) {
            var b = document.createElement("button");
            b.type = "button";
            b.className = "ux-fav-act btn btn-sm btn-light";
            b.setAttribute("data-fav-act", act);
            b.setAttribute("data-fav-href", href);
            b.setAttribute("title", title);
            b.setAttribute("aria-label", title);
            var i = document.createElement("i");
            i.className = "fa " + icon;
            b.appendChild(i);
            return b;
        };
        if (isFav(href)) {
            menu.appendChild(mk("unpin", "fa-star-o", "取消固定"));
        } else {
            menu.appendChild(mk("pin", "fa-star", "固定到常用"));
        }
        menu.appendChild(mk("up", "fa-chevron-up", "上移"));
        menu.appendChild(mk("down", "fa-chevron-down", "下移"));
        card.appendChild(menu);
    }

    // MutationObserver：克隆/移除后为新卡片补控件，保持行为一致
    var mo = new MutationObserver(function () {
        wrap.querySelectorAll(".o_portal_index_card").forEach(decorateCard);
    });
    mo.observe(wrap, { childList: true, subtree: true });
    wrap.querySelectorAll(".o_portal_index_card").forEach(decorateCard);
})();