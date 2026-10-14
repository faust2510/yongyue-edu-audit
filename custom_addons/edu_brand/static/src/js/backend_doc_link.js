/** @odoo-module **/
// 去 Odoo 化：后端所有「文档」图标（documentation_link.js:29 硬编码拼
// https://www.odoo.com/documentation/<版本><路径>）改为站内帮助中心。
// 上游位置（本机镜像实测）：addons/web/static/src/views/widgets/documentation_link/documentation_link.js:29
import { patch } from "@web/core/utils/patch";
import { DocumentationLink } from "@web/views/widgets/documentation_link/documentation_link";

patch(DocumentationLink.prototype, {
    get url() {
        return "/my/help";
    },
});
