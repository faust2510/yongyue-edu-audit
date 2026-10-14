# -*- coding: utf-8 -*-
sec = env['edu.apply.section'].sudo().search([('name', '=', '基本信息')], limit=1)
f = env['edu.apply.field'].sudo().create({
    'section_id': sec.id, 'name': 'emergency_relation', 'label': '紧急联络人关系',
    'type': 'char', 'required': False, 'sequence': 15})
print('TEST_FIELD_ADDED', f.id)
env.cr.commit()
