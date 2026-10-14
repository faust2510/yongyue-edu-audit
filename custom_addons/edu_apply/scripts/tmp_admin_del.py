# -*- coding: utf-8 -*-
f = env['edu.apply.field'].sudo().search([('name', '=', 'emergency_relation')], limit=1)
f.unlink()
env.cr.commit()
print('CLEANED')
