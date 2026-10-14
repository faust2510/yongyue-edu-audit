/* 登录页身份快捷标签（安全规格 2026-08-24）。
   点击 .demo-login-btn 仅填充用户名（data-username），并聚焦密码框；
   密码不写入页面、不自动提交。首次手动输入后由浏览器密码管理器记忆。
   原生 JS，无依赖。 */
(function () {
    'use strict';

    function initQuickLogin() {
        var buttons = document.querySelectorAll('.demo-login-btn');
        if (!buttons.length) {
            return;
        }
        buttons.forEach(function (btn) {
            btn.addEventListener('click', function (ev) {
                ev.preventDefault();
                var form = btn.closest('form.oe_login_form') ||
                           document.querySelector('form.oe_login_form');
                if (!form) {
                    return;
                }
                var loginInput = form.querySelector('input[name="login"]');
                var passInput = form.querySelector('input[name="password"]');
                if (loginInput) {
                    loginInput.value = btn.getAttribute('data-username') || '';
                }
                if (passInput) {
                    passInput.value = '';
                    passInput.focus();
                }
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initQuickLogin);
    } else {
        initQuickLogin();
    }
})();
