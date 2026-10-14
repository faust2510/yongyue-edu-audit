/* 第 5 批 D：键盘快捷聚焦全局搜索。
 * Ctrl/Cmd+K 或 "/".focus 顶栏搜索框；Esc 关闭焦点。SSR 轻实现。 */
(function () {
    "use strict";
    var box = document.querySelector(".o_portal_search_panel input[name=\"search\"]")
        || document.querySelector(".o_portal_search_panel input[type=\"search\"]")
        || document.querySelector("input[name=\"q\"]");
    if (!box) { return; }
    document.addEventListener("keydown", function (ev) {
        var tag = (ev.target.tagName || "").toLowerCase();
        var typing = tag === "input" || tag === "textarea" || tag === "select"
            || ev.target.isContentEditable;
        if ((ev.ctrlKey || ev.metaKey) && (ev.key === "k" || ev.key === "K")) {
            ev.preventDefault();
            box.focus();
            box.select && box.select();
        } else if (ev.key === "/" && !typing) {
            ev.preventDefault();
            box.focus();
        } else if (ev.key === "Escape" && ev.target === box) {
            box.blur();
        }
    });
})();
