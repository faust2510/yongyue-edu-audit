/** @odoo-module **/
/* v2.1-B9 私信：30s 轮询小请求，刷新未读角标与新消息（/my/messages/poll）。
   仅在包含私信相关元素的页面启动，避免无关页面产生请求：
   - 我的主页：刷新「通知」组内「新私信」卡角标、铃铛数（只对私信做差量，
     不覆盖布告等其他类别的未读数；与 edu.alert.read 水位机制配合——
     点击「新私信」卡后由 alerts_read.js 上报 mark_read 提水位）；
   - /my/messages 列表：刷新各会话行未读徽标；
   - /my/messages/<uid> 对话：拉取新消息追加到时间线（服务端返回即标记已读）。
   轮询接口 auth=user 轻量 JSON GET，失败静默等待下一轮。 */
(function () {
    "use strict";

    var POLL_MS = 30000;

    function init() {
        var app = document.getElementById("msg-app");
        var hasBadgeZone = !!(document.querySelector(".portal_alert_category")
            || document.querySelector(".oe-notif-mirror"));
        if (!app && !hasBadgeZone) {
            return; // 该页面与私信角标/会话无关
        }
        var chatUid = app ? app.getAttribute("data-msg-chat") : "";

        // 差量基线：页面渲染时的铃铛总数与「新私信」未读数
        var bellEls = Array.prototype.slice.call(
            document.querySelectorAll(".oe-notif-mirror"));
        var bellStart = bellEls.length
            ? (parseInt(bellEls[0].textContent, 10) || 0) : null;
        var msgStart = initialMsgUnread();

        function initialMsgUnread() {
            var card = document.querySelector(
                '.oe-doc-alert[data-alert-key="my/messages"]');
            if (!card) {
                return 0;
            }
            var attr = card.getAttribute("data-msg-unread");
            if (attr) {
                return parseInt(attr, 10) || 0;
            }
            var badge = card.querySelector(".oe_count");
            return badge ? (parseInt(badge.textContent, 10) || 0) : 0;
        }

        function poll() {
            var url = "/my/messages/poll";
            var last = app ? app.getAttribute("data-msg-last") : "";
            if (chatUid) {
                url += "?with=" + chatUid;
                if (last) {
                    url += "&after=" + last;
                }
            }
            fetch(url, {
                method: "GET",
                credentials: "same-origin",
                headers: {Accept: "application/json"},
            })
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (chatUid) {
                        appendNew(data.new || []);
                    } else {
                        refreshBadges(data);
                    }
                })
                .catch(function () { /* 网络抖动静默，下一轮再试 */ });
        }

        // ---------------- 主页 / 列表页：角标刷新 ----------------

        function refreshBadges(data) {
            var unread = parseInt(data.unread, 10) || 0;

            // 1) 铃铛（差量：只把私信变化叠加到渲染时的总数上）
            if (bellEls.length && bellStart !== null) {
                var bellVal = bellStart - msgStart + unread;
                bellEls.forEach(function (el) {
                    el.textContent = bellVal;
                    el.style.display = bellVal > 0 ? "" : "none";
                });
            }

            // 2) 通知折叠头总数徽标（差量；无徽标元素则按需创建）
            var slot = document.getElementById("portal-alert-total-slot");
            if (slot) {
                var tb = slot.querySelector(".badge");
                var totalStart = tb ? (parseInt(tb.textContent, 10) || 0) : 0;
                var totalVal = totalStart - msgStart + unread;
                if (!tb && totalVal > 0) {
                    tb = document.createElement("span");
                    tb.className = "badge bg-danger";
                    slot.appendChild(tb);
                }
                if (tb) {
                    if (totalVal > 0) {
                        tb.textContent = totalVal;
                        tb.style.display = "";
                    } else {
                        tb.style.display = "none";
                    }
                }
                msgStart = unread; // 基线推进，下一轮差量继续正确
            }

            // 3) 「通知」组内「新私信」提醒卡角标（缺失时整卡注入）
            var card = document.querySelector(
                '.oe-doc-alert[data-alert-key="my/messages"]');
            if (card) {
                var b = card.querySelector(".oe_count");
                if (!b) {
                    b = document.createElement("span");
                    b.className = "oe_count badge rounded-pill text-bg-primary";
                    card.appendChild(b);
                }
                if (unread > 0) {
                    b.textContent = unread;
                    b.style.display = "";
                } else {
                    b.style.display = "none";
                }
            } else if (unread > 0) {
                injectMsgCard(unread);
                msgStart = unread; // 注入卡片后推进基线
            }

            // 4) 会话列表行未读徽标
            var convMap = {};
            (data.convs || []).forEach(function (c) {
                convMap[c.uid] = parseInt(c.unread, 10) || 0;
            });
            Array.prototype.forEach.call(
                document.querySelectorAll(".msg-conv"), function (row) {
                    var uid = row.getAttribute("data-conv-uid");
                    var badge = row.querySelector(".msg-conv-unread");
                    var n = convMap[uid] || 0;
                    if (n > 0) {
                        if (!badge) {
                            badge = document.createElement("span");
                            badge.className =
                                "msg-conv-unread badge rounded-pill text-bg-danger";
                            var link = row.querySelector("a");
                            if (link) {
                                link.appendChild(badge);
                            }
                        }
                        if (badge) {
                            badge.textContent = n;
                            badge.style.display = "";
                        }
                    } else if (badge) {
                        badge.style.display = "none";
                    }
                });

            // 5) 教师工作台「私信」卡角标（纯计数；打开会话即已读归零）
            var wbCard = document.querySelector('.card a[href="/my/messages"]');
            if (wbCard) {
                var wb = wbCard.querySelector("[data-msg-badge]");
                if (unread > 0) {
                    if (!wb) {
                        wb = document.createElement("span");
                        wb.className = "badge text-bg-danger rounded-pill";
                        wb.setAttribute("data-msg-badge", "");
                        wbCard.appendChild(wb);
                    }
                    wb.textContent = unread;
                    wb.style.display = "";
                } else if (wb) {
                    wb.style.display = "none";
                }
            }
        }

        // 「新私信」提醒卡从未渲染过（无任何历史消息）时：轮询发现未读→整卡注入
        function injectMsgCard(unread) {
            var list = document.getElementById("search-notification-list");
            if (!list) {
                return;
            }
            var li = document.createElement("li");
            li.className = "dropdown-item-text p-0";
            var wrap = document.createElement("div");
            wrap.className = "o_portal_index_card col-12";
            var a = document.createElement("a");
            a.href = "/my/messages";
            a.title = "新私信";
            a.setAttribute("data-alert-key", "my/messages");
            a.setAttribute("data-msg-unread", String(unread));
            a.className = "d-flex justify-content-start gap-2 gap-md-3 " +
                "align-items-center py-3 pe-2 px-md-3 h-100 rounded " +
                "text-decoration-none text-reset alert alert-primary " +
                "align-items-center position-relative oe-doc-alert";
            var box = document.createElement("div");
            box.className = "alert-link";
            var title = document.createElement("div");
            title.className = "mt-0 mb-1 fs-5 fw-normal lh-1 d-flex gap-2";
            var tspan = document.createElement("span");
            tspan.className = "fw-bold";
            tspan.textContent = "新私信";
            title.appendChild(tspan);
            box.appendChild(title);
            var empty = document.createElement("div");
            empty.className = "opacity-75";
            box.appendChild(empty);
            a.appendChild(box);
            var badge = document.createElement("span");
            badge.className = "oe_count badge rounded-pill text-bg-primary";
            badge.textContent = unread;
            a.appendChild(badge);
            wrap.appendChild(a);
            li.appendChild(wrap);
            list.appendChild(li);
        }

        // ---------------- 对话页：新消息追加 ----------------

        function appendNew(news) {
            if (!news || !news.length) {
                return;
            }
            var appEl = document.getElementById("msg-app");
            if (!appEl) {
                return;
            }
            var empty = appEl.querySelector(
                ".text-center.text-muted.small.py-4");
            if (empty) {
                empty.remove();
            }
            news.forEach(function (m) {
                var item = document.createElement("div");
                item.className = "msg-item d-flex " + (m.from_me
                    ? "justify-content-end" : "justify-content-start");
                var bubble = document.createElement("div");
                bubble.className = "msg-bubble rounded px-3 py-2 " + (m.from_me
                    ? "text-bg-primary" : "text-bg-light");
                bubble.style.maxWidth = "74%";
                bubble.style.whiteSpace = "pre-line";
                var body = document.createElement("div");
                body.textContent = m.body || "";
                var at = document.createElement("div");
                at.className = "small mt-1 " + (m.from_me
                    ? "opacity-75" : "text-muted");
                at.textContent = m.at || "";
                bubble.appendChild(body);
                bubble.appendChild(at);
                item.appendChild(bubble);
                appEl.appendChild(item);
            });
            appEl.scrollTop = appEl.scrollHeight;
            var lastMsg = news[news.length - 1];
            appEl.setAttribute("data-msg-last", String(lastMsg.id));
        }

        // 首轮立即拉取 + 每 30s 一次
        poll();
        setInterval(poll, POLL_MS);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();