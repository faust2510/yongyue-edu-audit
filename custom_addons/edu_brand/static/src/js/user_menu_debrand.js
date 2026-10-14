/** @odoo-module **/
// 去_odoo 化：用户菜单里的 "Help"（指向 odoo.com/buy）与
// "My Odoo.com account"（accounts.odoo.com）两项与本系统无关，直接移除。
import { registry } from "@web/core/registry";

const items = registry.category("user_menuitems");
items.remove("support");
items.remove("odoo_account");
