/** @odoo-module **/
/* 对齐 OpenEduCat 企业版行为：进入后台但 URL 中没有任何动作时，
 * 不再默认打开第一个应用（本地排序最前的是“讨论”，导致一进去就是
 * 讨论收件箱），而是跳转到应用菜单网格页 /apps。
 *
 * 2026-10-13：本补丁已降为**兜底**。裸 /web、/odoo 现在由服务端直接 303 到 /apps
 * （见 controllers/main.py 的 EduHomeRedirect.web_client）—— 客户端补丁永远治不了
 * 「先渲染一整页后台外壳再跳」，真正的修法只能在服务端。仍会走到这里的情形：
 *   · 旧 /web?menu_id=… 深链（语义上就是「进后台」，服务端放行）；
 *   · JS 内部 selectMenu 到没有绑定动作的菜单。
 * 目标同时从 /openeducat/apps_menu 换成 /apps：后者是正门，旧路径只会 302 多绕一跳。
 */
import { WebClient } from "@web/webclient/webclient";
import { patch } from "@web/core/utils/patch";

patch(WebClient.prototype, {
    async _loadDefaultApp() {
        window.location.href = "/apps";
    },
});
