/** @odoo-module **/
/* 首页提醒分类「点击即记已读」（D3 分类已读语义）。
   监听 .portal_alert_category 区域内带 data-alert-key 的链接点击：
   以 keepalive fetch 异步 POST /alerts/mark_read（携带 csrf_token 与该类 key），
   不 await、不阻塞导航；上报失败静默忽略，导航照常进行。 */
(function () {
    "use strict";

    function csrfToken(scope) {
        // 首选页面 meta[name=csrf_token]，缺失时回退到提醒区隐藏域 /
        // 「全部标为已读」表单里的 csrf 输入框
        var meta = document.querySelector('meta[name="csrf_token"]');
        if (meta && meta.content) {
            return meta.content;
        }
        var input = scope.querySelector(".oe-alert-csrftoken");
        if (input && input.value) {
            return input.value;
        }
        var formInput = document.querySelector(
            'form[action="/alerts/mark_read"] input[name="csrf_token"]');
        return formInput ? formInput.value : "";
    }

    document.addEventListener("click", function (ev) {
        var zone = ev.target.closest(".portal_alert_category");
        if (!zone) {
            return;
        }
        var link = ev.target.closest("a[data-alert-key]");
        if (!link) {
            return; // 折叠头按钮等非链接点击不上报
        }
        var href = link.getAttribute("href") || "";
        if (!href || href.charAt(0) === "#") {
            return; // 锚点跳转不产生新未读，无需上报
        }
        try {
            var fd = new FormData();
            fd.append("csrf_token", csrfToken(zone));
            fd.append("key", link.getAttribute("data-alert-key"));
            void fetch("/alerts/mark_read", {
                method: "POST",
                body: fd,
                keepalive: true, // 页面即将跳转也尽量把请求发完
            }).catch(function () { /* 忽略网络错误 */ });
        } catch (_e) {
            /* 上报异常不影响本次导航 */
        }
    });
})();

/* =====================================================================
   B11 工作台（v2.1-P4）：移动端底部 Tab 与桌面左侧导航的激活态高亮。
   纯视觉层：按当前 pathname 前缀匹配 data-b11-tab，仅增删 .active 类，
   不改任何路由与业务逻辑；无匹配时不点亮任何 Tab（不误判）。
   ===================================================================== */
(function () {
    "use strict";
    function b11Highlight() {
        var path = window.location.pathname;
        var items = document.querySelectorAll("[data-b11-tab]");
        var hits = [];
        // 精确匹配优先；同一 key 可能同时出现在侧栏与底栏，全部点亮
        items.forEach(function (el) {
            var key = el.getAttribute("data-b11-tab");
            if (key && path === key) {
                hits.push(el);
            }
        });
        if (!hits.length) {
            items.forEach(function (el) {
                var key = el.getAttribute("data-b11-tab");
                if (key && key !== "/my/home" && path.indexOf(key) === 0) {
                    hits.push(el);
                }
            });
        }
        items.forEach(function (el) { el.classList.remove("active"); });
        hits.forEach(function (el) { el.classList.add("active"); });
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", b11Highlight);
    } else {
        // lazy 包通常在 DOMContentLoaded 之后执行，必须立即跑一次
        b11Highlight();
    }
})();
