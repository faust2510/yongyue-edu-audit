/** 评估矩阵录入的渐进增强（无 JS 也能提交 —— 网格输入本质是表单里的 input）。
 *
 * 五件事，前四件「不改变数据语义」，第五件只写一个 CSS 变量：
 *   1. 输入超满分时即时标红并在该格下方给出提示；
 *   2. 回车/方向键在同一列的上下行之间移动，方便整列录入；
 *   3. 保存前把超范围的值夹到 0~满分，避免整表被后端拒绝；
 *   4. **Excel 整块粘贴**（E7，docs/plans/eval-unified-design.md §6.7）：把剪贴板里的
 *      TSV 按行列铺进矩阵。只写**既有的** <input name="v_<roster>_<item>">，
 *      提交仍走原来的表单 POST ⇒ 服务端校验、幂等键、总分服务端算**全部不变**。
 *   5. **高度预算**（E6 的另一半，见下方 fitHeight）：按容器**实测顶边**算
 *      「视口高 − 顶边 − 底部留白」，写进 CSS 变量 --yy-assess-fit-h。
 *      纯 CSS 那条 max(18rem, calc(100vh - 24rem)) 保留为**无脚本兜底**。
 *
 * 冻结本身（position: sticky）**不在这里**：那是样式层的事，
 * 见 static/src/css/assess_grid.css。
 */
(function () {
    'use strict';

    function cells() {
        return Array.prototype.slice.call(
            document.querySelectorAll('.yy-assess-matrix input[type="number"]'));
    }

    function maxOf(input) {
        var v = parseFloat(input.getAttribute('max'));
        return isNaN(v) ? Infinity : v;
    }

    function paint(input) {
        var raw = input.value;
        if (raw === '') {
            input.classList.remove('is-invalid');
            return;
        }
        var value = parseFloat(raw);
        var bad = isNaN(value) || value < 0 || value > maxOf(input);
        input.classList.toggle('is-invalid', bad);
    }

    function clampAll() {
        cells().forEach(function (input) {
            var value = parseFloat(input.value);
            if (isNaN(value)) { return; }
            var top = maxOf(input);
            if (value < 0) { input.value = '0'; }
            if (value > top) { input.value = String(top); }
        });
    }

    function colIndex(input) {
        var td = input.closest('td');
        if (!td) { return -1; }
        return Array.prototype.indexOf.call(td.parentNode.children, td);
    }

    function rowIndex(input) {
        var tr = input.closest('tr');
        if (!tr || !tr.parentNode) { return -1; }
        return Array.prototype.indexOf.call(tr.parentNode.children, tr);
    }

    function move(input, dRow, dCol) {
        var list = cells();
        var r = rowIndex(input) + dRow;
        var c = colIndex(input) + dCol;
        for (var i = 0; i < list.length; i += 1) {
            if (rowIndex(list[i]) === r && colIndex(list[i]) === c) {
                list[i].focus();
                list[i].select();
                return;
            }
        }
    }

    // -----------------------------------------------------------------
    // E7 · Excel 整块粘贴（docs/plans/eval-unified-design.md §6.7）
    // -----------------------------------------------------------------

    //: 只接管「冻结容器里的矩阵数字格」的粘贴；矩阵之外一律放行（不劫持页面）。
    var PASTE_SCOPE = '.yy-assess-scroll .yy-assess-matrix input[type="number"]';
    //: 纯十进制数字（除正负号与小数点外不带任何符号；指数、全角、中文一律不算）
    var PLAIN_NUM = /^[+-]?(\d+(\.\d+)?|\.\d+)$/;
    //: 千分位分组形状（1,234 / 1,234,567.5）—— 只有这个形状才把逗号当分隔符去掉
    var GROUPED_NUM = /^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$/;

    /** 剪贴板文本 → 二维数组（行 × 列）。返回 [] 表示「没有可处理的块」。 */
    function parseTsv(text) {
        var norm = String(text === null || text === undefined ? '' : text)
            .replace(/\r\n/g, '\n').replace(/\r/g, '\n');
        var lines = norm.split('\n');
        // Excel 复制时结尾常带一个换行 ⇒ 末尾空行不是一行数据
        while (lines.length && lines[lines.length - 1] === '') {
            lines.pop();
        }
        if (!lines.length) { return []; }
        // 空单元格（连续两个 \t，或行首/行尾）保留成空串占位，不丢列
        return lines.map(function (line) { return line.split('\t'); });
    }

    /** 单元格文本 → {empty:true} / {ok:false} / {ok:true, text}。
     *
     * 口径照设计 §6.7「值处理」表：空 = 跳过（**不清库**）；非数字 = 不写入 + 标红 +
     * 计数；千分位/百分号/货币符号 = 去掉符号后按数字处理；超满分 / 负值 = 照写，
     * 由既有 paint() 标红、clampAll() 提交时夹取。
     *
     * ⚠ 两条刻意保守的判据（宁可拒绝，不猜语义 —— 猜错就是静默改分）：
     *   · 只有「1,234,567」这种**分组**形状才去掉逗号；「3,5」原样保留 ⇒ 落进
     *     非数字分支。欧式小数点与千分位在纯文本上无法区分。
     *   · 全角数字/全角符号不转换 ⇒ 非数字分支（设计把「全角符号」明确列为非数字）。
     */
    function parseValue(raw) {
        var s = String(raw === null || raw === undefined ? '' : raw).trim();
        if (s === '') { return {empty: true}; }
        var body = s.replace(/^[¥￥$€£]\s*/, '').replace(/\s*%$/, '');
        if (GROUPED_NUM.test(body)) { body = body.replace(/,/g, ''); }
        if (!PLAIN_NUM.test(body)) { return {ok: false}; }
        var num = parseFloat(body);
        if (isNaN(num)) { return {ok: false}; }
        return {ok: true, text: String(num)};
    }

    /** (行, 列) → input 的索引；坐标与 move() 同一套（td 在行里的物理序号）。 */
    function gridIndex() {
        var index = {};
        cells().forEach(function (input) {
            var r = rowIndex(input);
            var c = colIndex(input);
            if (r >= 0 && c >= 0) { index[r + ':' + c] = input; }
        });
        return index;
    }

    /** 矩阵的粘贴提示条（每张矩阵一条；惰性创建，缓存在容器上）。 */
    function statusNode(input) {
        var scope = input.closest ? input.closest('.yy-assess-scroll') : null;
        if (!scope || !scope.parentNode) { return null; }
        if (scope.yyStatus && scope.yyStatus.parentNode) {
            return scope.yyStatus;
        }
        var node = document.createElement('p');
        node.className = 'yy-assess-paste-status small text-muted mb-0';
        node.setAttribute('role', 'status');
        node.setAttribute('aria-live', 'polite');
        scope.parentNode.insertBefore(node, scope.nextSibling);
        scope.yyStatus = node;       // 空着时不占位（.yy-assess-paste-status 的样式）
        return node;
    }

    /** 以锚点格为左上角把二维块铺进矩阵；越界的格子舍弃并计数。 */
    function applyBlock(anchor, block) {
        var index = gridIndex();
        var r0 = rowIndex(anchor);
        var c0 = colIndex(anchor);
        var stat = {cells: 0, written: 0, empty: 0, invalid: 0, out: 0};
        block.forEach(function (row, dr) {
            row.forEach(function (raw, dc) {
                stat.cells += 1;
                var val = parseValue(raw);
                if (val.empty) { stat.empty += 1; return; }
                var target = index[(r0 + dr) + ':' + (c0 + dc)];
                if (!target) { stat.out += 1; return; }
                if (!val.ok) {
                    stat.invalid += 1;
                    target.classList.add('is-invalid');
                    return;
                }
                target.value = val.text;
                paint(target);
                stat.written += 1;
            });
        });
        return stat;
    }

    /** 计数 → 一句人话（越界/非数字都**不静默**）。 */
    function describe(stat) {
        if (!stat.written && !stat.invalid && !stat.out) {
            return '粘贴内容里没有可写入的数字：空单元格按「跳过」处理，不会清掉已有分数。';
        }
        var parts = ['粘贴 ' + stat.cells + ' 格：写入 ' + stat.written];
        if (stat.empty) { parts.push('空单元格跳过 ' + stat.empty); }
        if (stat.invalid) { parts.push('非数字忽略 ' + stat.invalid + '（已标红）'); }
        if (stat.out) { parts.push('超出矩阵范围舍弃 ' + stat.out); }
        return parts.join('，') + '。';
    }

    document.addEventListener('input', function (ev) {
        if (ev.target && ev.target.matches
                && ev.target.matches('.yy-assess-matrix input[type="number"]')) {
            paint(ev.target);
        }
    });

    document.addEventListener('keydown', function (ev) {
        var t = ev.target;
        if (!t || !t.matches
                || !t.matches('.yy-assess-matrix input[type="number"]')) {
            return;
        }
        if (ev.key === 'Enter') { move(t, 1, 0); ev.preventDefault(); }
        else if (ev.key === 'ArrowDown') { move(t, 1, 0); ev.preventDefault(); }
        else if (ev.key === 'ArrowUp') { move(t, -1, 0); ev.preventDefault(); }
        else if (ev.key === 'ArrowRight') { move(t, 0, 1); ev.preventDefault(); }
        else if (ev.key === 'ArrowLeft') { move(t, 0, -1); ev.preventDefault(); }
    });

    document.addEventListener('paste', function (ev) {
        var t = ev.target;
        if (!t || !t.matches || !t.matches(PASTE_SCOPE)) { return; }
        var data = ev.clipboardData;
        var text = data ? data.getData('text/plain') : '';
        if (!text) { return; }                  // 空剪贴板：不接管（本来也无事发生）
        var block = parseTsv(text);
        if (!block.length) { return; }
        // 全是空的块：同样不交给浏览器 —— 浏览器会把当前格清空，而口径是「空 = 跳过」
        ev.preventDefault();
        var hasValue = block.some(function (row) {
            return row.some(function (cell) {
                return String(cell).replace(/\s/g, '') !== '';
            });
        });
        if (!hasValue) { return; }
        var stat = applyBlock(t, block);
        var node = statusNode(t);
        if (node) { node.textContent = describe(stat); }
        // 提示条一变长，页面上方的东西就可能被顶下去 ⇒ 重算高度预算。
        scheduleFit();
    });

    document.addEventListener('submit', function (ev) {
        var form = ev.target;
        if (form && form.querySelector
                && form.querySelector('.yy-assess-matrix')) {
            clampAll();
        }
    });

    // -----------------------------------------------------------------
    // E6 · 高度预算：按**容器实际顶边**算，不用拍脑袋的固定预留
    // -----------------------------------------------------------------
    // 为什么（实测，不是推断）：纯 CSS 的 `max-height: max(18rem, calc(100vh - 24rem))`
    // 把 24rem 当成"页头占多高"的固定预留。页面上只要多出一条提示条，顶边就往下走，
    // 而预算不动 ⇒ 容器底边被推出视口。实测 /assess/fill（1440×900）：未提交时
    // 顶边 378.67、底边 894.67（刚好在首屏内）；**保存后**多出「已保存」提示条，
    // 顶边 468.05、底边 984.05 —— 超出视口 84px（读数见
    // tests/smoke/assess_grid_sticky_paste_results.json 的 G_saved_state）。
    //
    // 所以接管口径 = 视口高 − **实测**顶边 − 底部留白，写进 `--yy-assess-fit-h`；
    // 无脚本时 CSS 里那条兜底声明照旧生效（渐进增强，脚本不是提交路径的一部分）。

    //: 容器底边与视口底之间的留白（px）
    var FIT_MARGIN = 24;
    //: 矮视口下的下限（px，= 无脚本兜底里的 18rem）：再挤也要能录几行
    var FIT_FLOOR = 288;
    //: 写预算的 CSS 自定义属性（由 static/src/css/assess_grid.css 消费）
    var FIT_VAR = '--yy-assess-fit-h';

    /** 量一次实际顶边、重算每张矩阵的高度预算。返回读数（排查/测试可直接看）。 */
    function fitHeight() {
        var vh = window.innerHeight || document.documentElement.clientHeight || 0;
        var out = [];
        Array.prototype.forEach.call(
            document.querySelectorAll('.yy-assess-scroll'),
            function (scope) {
                var top = scope.getBoundingClientRect().top;
                if (top < 0) {
                    // 页面已经滚过容器顶边：这时"填满剩余视口"会越算越高
                    // （顶边为负 ⇒ 预算变大 ⇒ 文档更长 ⇒ 还能再滚）—— 自激循环，
                    // 所以此时**不动**，保留上一次的值。
                    out.push({top: top, skipped: true});
                    return;
                }
                // 顶边与视口高都没变就不重写（RO/MO 会成串地来；写同一个值也会把
                // "观察我自己的尺寸"变成来回抖动的通路）。
                // ⚠ 必须把 vh 一起进缓存键：窗口 resize 时**顶边可以一动不动**而
                //   预算必须跟着变（只盯 top 会把 resize 这条路整个跳过 —— 实测踩过）。
                if (scope.yyFitKey !== undefined
                        && Math.abs(scope.yyFitKey.top - top) < 0.5
                        && scope.yyFitKey.vh === vh) {
                    out.push({top: top, skipped: 'unchanged'});
                    return;
                }
                var avail = vh - top;
                // 先按"减掉底部留白"取，再拿下限兜底，最后**永不超过可用空间**
                // （底边 ≤ 视口底 是硬判据，下限不得破坏它）。
                var h = Math.min(avail, Math.max(FIT_FLOOR, avail - FIT_MARGIN));
                if (h < 0) { h = 0; }
                var px = h.toFixed(2) + 'px';
                if (scope.style.getPropertyValue(FIT_VAR) !== px) {
                    scope.style.setProperty(FIT_VAR, px);
                }
                scope.yyFitKey = {top: top, vh: vh};
                out.push({top: top, available: avail, height: h, vh: vh,
                          skipped: false});
            });
        return out;
    }

    var fitQueued = false;

    /** 同一帧内只算一次（resize / DOM 变化会成串地来）。 */
    function scheduleFit() {
        if (fitQueued) { return; }
        fitQueued = true;
        var run = function () { fitQueued = false; fitHeight(); };
        if (window.requestAnimationFrame) {
            window.requestAnimationFrame(run);
        } else {
            window.setTimeout(run, 16);
        }
    }

    /** 页面结构变了就重算（提示条、错误条、任何插到矩阵上方的东西都会顶边下移）。 */
    function watchLayout() {
        window.addEventListener('resize', scheduleFit);
        window.addEventListener('orientationchange', scheduleFit);
        // 图片/字体在 load 后才定稿：那一刻的顶边才是最终值
        window.addEventListener('load', scheduleFit);
        if (window.MutationObserver && document.body) {
            new window.MutationObserver(scheduleFit).observe(
                document.body, {childList: true, subtree: true});
        }
        if (window.ResizeObserver && document.body) {
            try {
                new window.ResizeObserver(scheduleFit).observe(document.body);
            } catch (err) { /* 老引擎没有：resize + MutationObserver 仍覆盖 */ }
        }
    }

    function init() {
        cells().forEach(paint);
        // 提示条先建好再等消息：role=status 的活区要在内容变化**之前**就存在，
        // 否则部分读屏不会播报（空元素不占位，见 .yy-assess-paste-status 的样式）。
        Array.prototype.forEach.call(
            document.querySelectorAll('.yy-assess-scroll'),
            function (scope) {
                var first = scope.querySelector(
                    '.yy-assess-matrix input[type="number"]');
                if (first) { statusNode(first); }
            });
        // 挂载时就量一次：服务端渲染的提示条（如 /assess/fill 的「已保存」）已经在
        // DOM 里，顶边就是最终值；随后由 watchLayout 跟着 resize / DOM 变化重算。
        fitHeight();
        watchLayout();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    //: 供将来「名单批量粘贴」（设计 §5.7）复用同一套 TSV / 数值口径，
    //: 避免长出第二套解析（同一个语义两处实现 = 本仓反复吃过的亏）。
    //: fitHeight 一并导出：验收探针要能**直接问**当前预算是多少（而不是反推样式）。
    window.YYAssessGrid = {parseTsv: parseTsv, parseValue: parseValue,
                           fitHeight: fitHeight};
})();
