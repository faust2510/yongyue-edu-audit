/* v2-A7 / v4-t8：后台导航栏常驻「应用面板」入口。
   后台任意动作页点一下即回到 /apps 图标面板。

   本文件**只负责结构**（挂载 + 落点 + 可访问名），**不写任何色值/尺寸**：
   视觉全部交给 custom_addons/edu_brand/static/src/css/backend_b11.css 的
   .o_main_navbar > #yy-apps-chip（形与三态取自 Odoo 19 原厂导航栏条目惯例，
   见 docs/research/backend-navbar-entry.md）。
   历史：旧版在这里用 a.setAttribute('style', …) 写死 background:#714B67
   （Odoo 原厂主色）—— 内联样式任何选择器都盖不住，全站换色后它一个人留在紫底上，
   且 hover/active 一个状态都没有。色值搬出内联就是这条修复的核心。 */
(function () {
    'use strict';

    var ID = 'yy-apps-chip';
    // 落点 = 规范路径 /apps（controllers/main.py 的 EduAppsAlias.apps_menu）。
    // 旧路径 /openeducat/apps_menu 仍 302 兼容，但那是兼容层、不是入口，别再用它。
    var HREF = '/apps';

    // 启动竞态：脚本可能在 .o_main_navbar 挂出来之前执行。
    // 旧实现每 1.5s 轮询一次、**成功与否都永不停止**（一个长驻定时器）。
    // 现在：紧窗口内快速重试（有上限）→ 之后改由 DOM 变更事件驱动补挂。
    var BOOT_RETRY_MS = 250;
    var BOOT_MAX_TRIES = 40;   // ≈10s，足够覆盖 webclient 冷启动；到点停表，不再长驻

    function chip() {
        if (document.getElementById(ID)) return true;
        var bar = document.querySelector('.o_main_navbar');
        if (!bar) return false;
        var a = document.createElement('a');
        a.id = ID;
        a.className = 'yy-apps-chip';
        a.href = HREF;
        a.title = '应用面板';
        // 图标纯装饰 ⇒ aria-hidden；可访问名由可见文字「应用面板」提供（仓规 §10）。
        a.innerHTML = '<i class="fa fa-th-large" aria-hidden="true"></i><span>应用面板</span>';
        // 不装 click 监听：href 已设，交给浏览器原生处理 —— Cmd/Ctrl/中键点开新标签页
        // 都因此可用。旧实现无条件 ev.preventDefault() + window.location，把这三个
        // 用户预期直接掐掉了（真实可用性缺陷，非风格问题）。
        bar.appendChild(a);
        return true;
    }

    // SPA 内动作切换若重建了导航栏，补挂。用变更事件而不是定时器：
    // 收敛在一帧内，且不再有周期性唤醒；代价是每次 DOM 变更批次一次 getElementById。
    function watch() {
        if (typeof MutationObserver !== 'function') return;
        var mo = new MutationObserver(function () {
            if (!document.getElementById(ID)) chip();
        });
        mo.observe(document.body, { childList: true, subtree: true });
    }

    function boot() {
        if (chip()) { watch(); return; }
        var tries = 0;
        var t = setInterval(function () {
            tries += 1;
            if (chip() || tries >= BOOT_MAX_TRIES) {
                clearInterval(t);
                watch();   // 到点停表，但导航栏若在更晚才出现，仍由事件补挂
            }
        }, BOOT_RETRY_MS);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
