# -*- coding: utf-8 -*-
sec = env['edu.apply.section'].sudo().search([('name', '=', '基本信息')], limit=1)
f = env['edu.apply.field'].sudo().search([('name', '=', 'name'), ('section_id', '=', sec.id)], limit=1)
if not f:
    f = env['edu.apply.field'].sudo().create({
        'section_id': sec.id, 'name': 'name', 'label': '姓名',
        'type': 'char', 'required': True, 'locked': True, 'sequence': 1})
    print('NAME_FIELD_CREATED', f.id)
else:
    f.write({'required': True, 'locked': True})
    print('NAME_FIELD_EXISTS', f.id)
env.cr.commit()
