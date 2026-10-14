# -*- coding: utf-8 -*-
"""公开报名表：元数据驱动（edu.apply.section / edu.apply.field），
表单渲染、必填校验、存储均按后台设置动态进行；口径预置见 data/form_meta_data.xml。"""
import json

from odoo import http
from odoo.http import request

# 实体列回写映射（选项值即中文标签，检索列需转回代码）
TRACK_CODES = {'3+1制本科班': 'b31', '家教学院': 'hsa', '3+2制本硕连读': 'm32'}
TRACK_LABELS = {v: k for k, v in TRACK_CODES.items()}
GENDER_CODES = {'男': 'male', '女': 'female'}
CN_NUMS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
ENTITY_CHARS = ('name', 'id_no', 'phone', 'email', 'church')


class EduApplyPublic(http.Controller):

    def _form_meta(self):
        """启用中的分区及字段，组装为模板友好结构。"""
        groups = []
        sections = request.env['edu.apply.section'].sudo().search(
            [('active', '=', True)], order='sequence, id')
        for sec in sections:
            flds = sec.field_ids.filtered('active')
            if not flds:
                continue
            idx = len(groups)
            groups.append({
                'anchor': 'sec-%s' % sec.id,
                'title': sec.name,
                'cn': CN_NUMS[idx] if idx < len(CN_NUMS) else str(idx + 1),
                'pos': idx + 1,
                'has_req': any(f.required for f in flds),
                'fields': flds,
            })
        return groups

    def _values(self, kw=None):
        kw = kw or {}
        meta = self._form_meta()
        req_names = [f.name for g in meta for f in g['fields'] if f.required]
        return {'meta': meta, 'v': kw, 'error': kw.get('error', ''),
                'miss_map': kw.get('miss_map') or {},
                'req_names_json': json.dumps(req_names),
                'req_count': len(req_names)}

    def _collect(self, meta, post):
        """按元数据收集提交值并做必填校验，返回 (values, missing)。"""
        values, missing = {}, []
        for g in meta:
            for f in g['fields']:
                raw = post.get(f.name)
                val = bool(raw) if f.type == 'checkbox' else (raw or '').strip()
                values[f.name] = val
                if f.required and not val:
                    missing.append({'key': f.name, 'label': f.label,
                                    'anchor': g['anchor']})
        # 安全审计 F5：原调试日志（DBG-COLLECT 前缀）会把申请人 PII（姓名/电话/教会）
        # 写进服务端 WARNING 日志，已彻底删除——此处不得再记录提交值。
        return values, missing

    @http.route('/apply', type='http', auth='public', website=True)
    def apply_form(self, **kw):
        return request.render('edu_apply.apply_form', self._values(kw))

    @http.route('/apply/submit', type='http', auth='public',
                methods=['POST'], website=True, csrf=True)
    def apply_submit(self, **post):
        if post.get('website_url'):  # 蜜罐：正常用户不可见必为空
            return request.redirect('/apply')
        meta = self._form_meta()
        values, missing = self._collect(meta, post)
        if missing:
            kw = dict(post)
            kw['error'] = '必填项未填：' + '、'.join(m['label'] for m in missing)
            # 缺失项映射：模板据此高亮对应字段并定位分区，便于补填
            kw['miss_map'] = {m['key']: m for m in missing}
            return request.render('edu_apply.apply_form', self._values(kw))

        vals = {'answer_json': json.dumps(values, ensure_ascii=False)}
        for key in ENTITY_CHARS:
            if values.get(key):
                vals[key] = values[key]
        _gl = (values.get('gender') or '').strip()
        _opts = [o.strip() for o in (request.env['edu.apply.field'].sudo().search([('name', '=', 'gender')], limit=1).options or '').splitlines() if o.strip()]
        vals['gender'] = 'male' if _gl in ('男',) else ('female' if _gl in ('女',) else (_opts[0] == '男' and 'male' or 'female'))
        vals['track'] = TRACK_CODES.get(values.get('track') or '', 'b31')
        app = request.env['edu.application'].sudo().create(vals)
        self._notify(app)
        return request.render('edu_apply.apply_thanks', {'app': app})

    def _notify(self, app):
        """新申请通知：发往招生邮箱（需已配置外发SMTP才会真实送达；失败不影响提交）。"""
        try:
            notify = request.env['ir.config_parameter'].sudo().get_param(
                'edu.apply_notify_email')
            if not notify:
                notify = request.env['res.company'].sudo().search([], limit=1).email
            if not notify:
                return
            body = (
                '<p>收到新的入学申请：</p>'
                '<ul>'
                '<li>姓名：%s</li><li>报考科别：%s</li>'
                '<li>电话：%s</li><li>教会：%s</li>'
                '<li>状态：%s</li>'
                '</ul><p>请登录后台「招生报名 → 入学申请」查看完整资料。</p>' % (
                    app.name or '', TRACK_LABELS.get(app.track, ''),
                    app.phone or '', app.church or '', app.state))
            request.env['mail.mail'].sudo().create({
                'subject': '【永约学坊】新入学申请：%s' % (app.name or ''),
                'body_html': body,
                'email_to': notify,
            }).send(raise_exception=False)
        except Exception:
            pass
