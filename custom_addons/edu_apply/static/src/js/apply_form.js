// edu_apply 公开报名表渐进增强：
// 1) 必填项完成进度条；2) 提交按钮防双击（提交中禁用）。
// 仅在存在报名表单的页面生效，其余页面为空操作。
(function () {
    'use strict';
    var form = document.querySelector('form[action="/apply/submit"]');
    if (!form) return;

    // 必填项清单由后台元数据动态下发（data-required-names 为 JSON 数组）
    var REQUIRED = (function () {
        try { return JSON.parse(form.getAttribute('data-required-names') || '[]'); }
        catch (e) { return []; }
    })();
    var bar = document.getElementById('yy-progress-bar');
    var txt = document.getElementById('yy-progress-txt');

    function filled(name) {
        var els = form.querySelectorAll('[name="' + name + '"]');
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            if (el.type === 'radio' || el.type === 'checkbox') {
                if (el.checked) return true;
            } else if ((el.value || '').trim() !== '') {
                return true;
            }
        }
        return false;
    }

    function updateProgress() {
        var done = 0;
        REQUIRED.forEach(function (n) { if (filled(n)) done++; });
        if (bar) bar.style.width = Math.round(done * 100 / REQUIRED.length) + '%';
        if (txt) txt.textContent = '必填已完成 ' + done + ' / ' + REQUIRED.length;
    }

    form.addEventListener('input', updateProgress);
    form.addEventListener('change', updateProgress);

    // 防双击：提交开始后禁用按钮并给出进行中提示。
    // 原生校验未通过时不会触发 submit，按钮保持可用。
    form.addEventListener('submit', function () {
        var btn = form.querySelector('button[type="submit"]');
        if (!btn || btn.disabled) return;
        btn.disabled = true;
        btn.innerHTML = '<i class="fa fa-spinner fa-spin me-1"></i>正在提交，请勿重复点击…';
    });

    updateProgress();
})();
