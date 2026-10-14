g = env['edu.grievance'].search([('name','=','ZZPROBE1')], limit=1)
g.write({'date': '2026-12-31'})
env.cr.commit()
print('PROBE_ID=%d DATE=%s STUDENT=%s' % (g.id, g.date, g.student_id.id))
