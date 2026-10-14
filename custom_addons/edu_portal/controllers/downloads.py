# -*- coding: utf-8 -*-
"""资料下载中心 v2：
- /downloads            下载端（搜索/文件夹筛选/排序/分页 + 上新与热门横带）
- /downloads/file/<id>  下载流（可见范围校验 + 审计 + 计数）
- /downloads/mine       我的下载记录
- /downloads/manage     管理台（教务处/管理员：文件夹 CRUD + 批量操作 + 行内编辑）
- /downloads/upload     批量上传（多文件 + 白名单/大小校验）
- /downloads/stats      下载统计
"""
import base64
import datetime
from urllib.parse import quote

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import content_disposition, request
from odoo.addons.portal.controllers.portal import pager

from .main import csv_download

PAGE_SIZE = 15
MANAGE_PAGE_SIZE = 20
DEFAULT_EXTS = 'pdf doc docx xls xlsx ppt pptx png jpg jpeg gif webp zip rar 7z mp4 mp3 txt csv'
# 扩展名 → (FA 图标, 徽章底色) ；其余走 OTHER
_EXT_STYLES = {
    'pdf': ('fa-file-pdf-o', 'text-bg-danger'),
    'doc': ('fa-file-word-o', 'text-bg-primary'),
    'docx': ('fa-file-word-o', 'text-bg-primary'),
    'xls': ('fa-file-excel-o', 'text-bg-success'),
    'xlsx': ('fa-file-excel-o', 'text-bg-success'),
    'csv': ('fa-file-excel-o', 'text-bg-success'),
    'ppt': ('fa-file-powerpoint-o', 'text-bg-warning'),
    'pptx': ('fa-file-powerpoint-o', 'text-bg-warning'),
    'png': ('fa-file-image-o', 'text-bg-info'),
    'jpg': ('fa-file-image-o', 'text-bg-info'),
    'jpeg': ('fa-file-image-o', 'text-bg-info'),
    'gif': ('fa-file-image-o', 'text-bg-info'),
    'webp': ('fa-file-image-o', 'text-bg-info'),
    'zip': ('fa-file-archive-o', 'text-bg-secondary'),
    'rar': ('fa-file-archive-o', 'text-bg-secondary'),
    '7z': ('fa-file-archive-o', 'text-bg-secondary'),
    'mp4': ('fa-file-video-o', 'text-bg-dark'),
    'mp3': ('fa-file-audio-o', 'text-bg-dark'),
    'txt': ('fa-file-text-o', 'text-bg-light'),
}
SORTS = {
    'newest': ('最新', 'write_date desc, id desc'),
    'hot': ('最热', 'download_count desc, name asc'),
    'name': ('名称', 'name asc'),
}
# 可浏览器内联预览的扩展名 → Content-Type（其余强制下载）
_INLINE_TYPES = {
    'pdf': 'application/pdf',
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'gif': 'image/gif',
    'webp': 'image/webp',
}


def _can_inline(file_name):
    return (_ext_of(file_name) or '').lower() in _INLINE_TYPES


def _human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return '%.0f%s' % (n, unit)
        n /= 1024.0
    return '%.1fGB' % n


def _fmt_dt(dt):
    return dt.strftime('%Y-%m-%d %H:%M') if dt else ''


def _ext_of(file_name):
    if not file_name or '.' not in file_name:
        return ''
    return file_name.rsplit('.', 1)[1].lower()


def _ext_style(file_name):
    ext = _ext_of(file_name)
    icon, cls = _EXT_STYLES.get(ext, ('fa-file-o', 'text-bg-secondary'))
    return {'ext': ext or '文件', 'icon': icon, 'cls': cls}


VIS_LABELS = [('registrar', '教务处'), ('teacher', '教师'),
              ('student', '学生'), ('parent', '家长')]


def _registrar():
    u = request.env.user
    return (u.has_group('openeducat_core.group_op_back_office_admin')
            or u.has_group('base.group_system'))


def _identity_fields():
    """当前登录者对应的可见组字段列表（grill 2026-08-29 共识口径）。

    返回 None = 教务处/管理员，恒可见；否则返回命中的组字段（OR 关系）：
    - 教师：openeducat_core.group_op_faculty
    - 家长：op.parent 绑定
    - 学生：门户非家长（含纯门户注册账号）
    - 其余内部用户按教师口径兜底
    """
    u = request.env.user
    if _registrar():
        return None
    out = []
    if u.has_group('openeducat_core.group_op_faculty'):
        out.append('visible_teacher')
    if u.has_group('base.group_portal'):
        # 门户身份：家长绑定 → 家长组；其余门户（学生/纯门户账号）→ 学生组。
        # 注意教师等内部用户不走学生口径（曾在冒烟中暴露：教师误见"仅学生"资料）
        if request.env['op.parent'].sudo().search_count(
                [('user_id', '=', request.env.uid)]):
            out.append('visible_parent')
        else:
            out.append('visible_student')
    if not out:
        out.append('visible_teacher')
    return out


def _visibility_domain():
    idents = _identity_fields()
    if idents is None:
        return []
    if len(idents) == 1:
        return [(idents[0], '=', True)]
    return ['|'] * (len(idents) - 1) + [(f, '=', True) for f in idents]


def _can_download(rec):
    idents = _identity_fields()
    if idents is None:
        return True
    return any(getattr(rec, f) for f in idents)


def _my_subject_ids():
    """当前登录者的在修科目 id；非学生/家长返回 None（表示不受科目限制）。"""
    env = request.env
    uid = env.uid
    stu = env['op.student'].sudo().search([('user_id', '=', uid)], limit=1)
    par = env['op.parent'].sudo().search([('user_id', '=', uid)], limit=1)
    if not stu and not par:
        return None
    Scs = env['op.student.course'].sudo()
    if stu:
        scs = Scs.search([('student_id', '=', stu.id)])
    else:
        scs = Scs.search([('student_id', 'in', par.student_ids.ids)])
    return scs.mapped('subject_ids').ids


def _src_domain(active_dom, my_subject_ids, src):
    """v3（t8）来源分区域。

    course = 课程资料（有 subject_id）；admin = 行政表格（无 subject_id）。
    学生/家长额外把课程资料限制在「我修的科目」内，行政表格沿用既有四组
    可见范围口径（不限制科目）。教务处/管理员 my_subject_ids=None，不受限。
    """
    dom = list(active_dom)
    if src == 'course':
        dom += [('subject_id', '!=', False)]
        if my_subject_ids is not None:
            dom += [('subject_id', 'in', my_subject_ids)]
    elif src == 'admin':
        dom += [('subject_id', '=', False)]
    elif my_subject_ids is not None:
        dom = ['|', ('subject_id', '=', False),
               '&', ('subject_id', '!=', False),
               ('subject_id', 'in', my_subject_ids)] + dom
    return dom


def _ack_gate_ok(rec):
    """hard 档确认门禁：教务处/管理员恒放行；其余人须已有回执。"""
    if _registrar():
        return True
    return bool(request.env['edu.download.ack'].sudo().search_count(
        [('file_id', '=', rec.id), ('user_id', '=', request.env.uid)]))


def _visibility_label(f):
    names = [n for k, n in VIS_LABELS if getattr(f, 'visible_' + k)]
    if len(names) == 4:
        return '公开'
    if len(names) == 1:
        return '仅' + names[0]
    return ' / '.join(names)


def _visibility_vals(post):
    """从 POST 勾选收集四组布尔；全不勾返回 None（由调用方回显错误）。"""
    vals = {('visible_' + k): bool(post.get('vis_' + k))
            for k, _n in VIS_LABELS}
    return vals if any(vals.values()) else None


# ---------------------------------------------------------------------------
# v3（t28）审计动作码 → 中文
# 背景：/edu/audit 的动作列直接渲染 edu.audit.log.action。批量资料操作原本用
# 「短码」传参并就地映射中文，字典漏键时 .get(action, action) 会**把原始英文
# 码原样写库并显示**（实测历史遗留 3 条 'activate'）。
# 因此这里改为集中表 + 显式兜底：**未登记的码一律不原样回显**。
# ---------------------------------------------------------------------------
_BULK_ACTION_LABELS = {
    'delete': '资料批量删除',
    'deactivate': '资料批量停用',
    'activate': '资料批量启用',
    'restore': '资料批量恢复',
    'move': '资料批量移动',
    'visibility': '资料批量改可见范围',
}


def _bulk_action_label(action):
    """动作码 → 中文标签；未知码不回落原码（防英文/技术码泄漏到审计页）。"""
    action = (action or '').strip()
    if not action:
        return '资料批量操作'
    label = _BULK_ACTION_LABELS.get(action)
    if label:
        return label
    # 调用方若直接传了中文标签，原样保留
    if any('\u4e00' <= ch <= '\u9fff' for ch in action):
        return action
    return '资料批量操作'


def _uploader_label(user):
    """上传人显示名：技术/机器人账号一律显示「系统」。

    基座把超级用户改名为 'OpenEducat Bot'（本机实测 res_users.id=1，
    login=__system__），而经 ORM/种子/导入创建的资料 create_uid 就是它，
    直接渲染会把基座品牌泄漏到学生可见的「上传人」列。

    口径与 controllers/roles.py 的 _audit_user_label **完全一致**
    （无值 / id=1 / 名字含 bot / 以 openeducat 开头 → 「系统」）。
    此处刻意**不 import 那个函数**：edu_portal 控制器有循环导入史
    （main → register → contacts → main，见 controllers/main.py 末尾注释），
    跨文件 import 的风险大于收益；关键是口径一致，而非复用形式。
    """
    if not user:
        return '系统'
    name = (user.name or '').strip()
    if not name or user.id == 1 or 'bot' in name.lower() \
            or name.lower().startswith('openeducat'):
        return '系统'
    return name


def _file_vals(f):
    """模板行数据（Python 侧预格式化，QWeb 内不做 % 格式化）。"""
    return {
        'id': f.id,
        'name': f.name,
        'description': f.description or '',
        'cat_name': f.category_id.name,
        'cat_id': f.category_id.id,
        'size_text': _human_size(f.file_size or 0),
        'download_count': f.download_count,
        'ext': _ext_style(f.file_name),
        'uploader': _uploader_label(f.create_uid),
        'updated': _fmt_dt(f.write_date),
        'active': f.active,
        'can_inline': _can_inline(f.file_name or f.name),
        'vis_label': _visibility_label(f),
        'vis': {k: bool(getattr(f, 'visible_' + k))
                for k, _n in VIS_LABELS},
        # v3（t8）：来源分区 + 需确认已读
        'subject': f.subject_id.name or '',
        'is_course': bool(f.subject_id),
        'ack_mode': f.ack_mode,
        'ack_n': f.ack_n,
        'acked': bool(request.env['edu.download.ack'].sudo().search_count(
            [('file_id', '=', f.id), ('user_id', '=', request.env.uid)])),
    }


def _flash_vals(**kw):
    """query 旗标 → 模板横幅（saved/err/done/skip/uploaded/failed）。

    query 串里全是字符串，数字先转 int，避免 '0' 误判为有值。"""
    def _int(key):
        try:
            return int(kw.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    vals = {}
    if kw.get('saved'):
        vals['flash_ok'] = '操作成功。'
    done, skip = _int('done'), _int('skip')
    if done or skip:
        vals['flash_ok'] = '批量操作完成：%d 条成功。' % done
        if skip:
            vals['flash_ok'] += '另有 %d 条跳过。' % skip
    uploaded, failed = _int('uploaded'), _int('failed')
    if uploaded or failed:
        vals['flash_ok'] = '上传完成：%d 份成功。' % uploaded
        if failed:
            vals['flash_ok'] += '另有 %d 份失败。' % failed
    err_map = {
        'folder_not_empty': '文件夹不为空，请先清空或移动其中的资料与子文件夹。',
        'folder_name': '请填写文件夹名称。',
        'nocat': '请选择或新建一个文件夹。',
        'nofile': '没有可上传的文件。',
        'toobig': '文件超过大小限制。',
        'badext': '文件类型不在白名单内。',
        'novis': '可见范围至少要勾选一个组。',
    }
    if kw.get('err') in err_map:
        vals['flash_err'] = err_map[kw['err']]
    if kw.get('last_error'):
        vals['flash_err'] = kw['last_error'][:120]
    return vals


class EduDownloads(http.Controller):

    # ------------------------------------------------------------------
    # 下载端（单页两态：普通态=纯净下载；教务 ?mode=manage 原地变管理台）
    # ------------------------------------------------------------------
    @http.route('/downloads', type='http', auth='user', website=True)
    def downloads_index(self, q='', cat=0, sort='newest', page=1,
                        status='all', mode='', **kw):
        File = request.env['edu.download.file'].sudo()
        Cat = request.env['edu.download.category'].sudo()
        q = (q or '').strip()
        sort = sort if sort in SORTS else 'newest'
        try:
            cat = int(cat or 0)
        except (TypeError, ValueError):
            cat = 0
        try:
            page = max(1, int(page or 1))
        except (TypeError, ValueError):
            page = 1
        is_registrar = _registrar()

        # ---------- 管理模式（同一页面的教务态） ----------
        if mode == 'manage' and is_registrar:
            status = status if status in ('all', 'active', 'inactive') \
                else 'all'
            _, cats, panel = self._manage_common()
            max_mb, exts_set = self._upload_limits()
            exts_text = ' '.join(sorted(exts_set))
            domain = []
            if q:
                domain += ['|', ('name', 'ilike', q),
                           ('description', 'ilike', q)]
            if cat:
                child_ids = [c.id for c in cats if c.parent_id.id == cat]
                domain += [('category_id', 'in', [cat] + child_ids)]
            if status == 'active':
                domain += [('active', '=', True)]
            elif status == 'inactive':
                domain += [('active', '=', False)]
            total = File.search_count(domain)
            pager_vals = pager('/downloads', total=total, page=page,
                               step=MANAGE_PAGE_SIZE,
                               url_args={'mode': 'manage', 'q': q,
                                         'cat': cat, 'status': status})
            recs = File.search(domain, order='category_id, name',
                               limit=MANAGE_PAGE_SIZE,
                               offset=(page - 1) * MANAGE_PAGE_SIZE)
            rows = [_file_vals(f) for f in recs]
            # 计划第 4 条：管理列表按文件夹分组展示（页内分组的节标题）
            manage_groups = []
            for r in rows:
                if not manage_groups or manage_groups[-1]['name'] != r['cat_name']:
                    manage_groups.append({'name': r['cat_name'], 'files': []})
                manage_groups[-1]['files'].append(r)
            # 上传逐文件结果（session 一次性取回）
            upload_results = request.session.pop(
                'edu.dl.upload_results', None) or []
            return request.render('edu_portal.edu_downloads_page', {
                'title': '资料下载',
                'page_name': 'downloads',
                'is_registrar': True,
                'manage_mode': True,
                'rows': rows,
                'manage_groups': manage_groups,
                'upload_results': upload_results,
                'panel': panel,
                'folder_options': self._folder_options(cats),
                'q': q,
                'q_enc': quote(q),
                'cat': cat,
                'status': status,
                'total': total,
                'pager': pager_vals,
                'max_mb': max_mb,
                'exts_text': exts_text,
                **_flash_vals(**kw),
            })

        # ---------- 普通下载态 ----------
        # v3（t8）来源分区：课程资料 / 行政表格（顶部两分区切换）
        active_dom = [('active', '=', True)] + _visibility_domain()
        src = kw.get('src') or 'all'
        if src not in ('all', 'course', 'admin'):
            src = 'all'
        my_subject_ids = _my_subject_ids()
        base_domain = _src_domain(active_dom, my_subject_ids, src)
        src_counts = {
            'course': File.search_count(
                _src_domain(active_dom, my_subject_ids, 'course')),
            'admin': File.search_count(
                _src_domain(active_dom, my_subject_ids, 'admin')),
        }
        new_count = File.search_count(base_domain + [
            ('create_date', '>=', fields.Datetime.now()
             - datetime.timedelta(days=30))])
        top_files = File.search(
            base_domain + [('download_count', '>', 0)],
            order='download_count desc', limit=5)

        # 文件夹 chips：聚合（父文件夹计数含子文件夹）
        cats = Cat.search([('active', '=', True)], order='sequence, id')
        cat_names = {c.id: c.name for c in cats}
        children = {}
        for c in cats:
            if c.parent_id:
                children.setdefault(c.parent_id.id, []).append(c.id)
        per_cat = {row[0].id: row[1] for row in File._read_group(
            base_domain, ['category_id'], ['__count'])}
        chip_counts = []
        for c in cats:
            if c.parent_id:
                continue
            n = per_cat.get(c.id, 0) + sum(
                per_cat.get(cid, 0) for cid in children.get(c.id, []))
            chip_counts.append({'id': c.id, 'name': c.name, 'count': n})
        total_count = sum(ch['count'] for ch in chip_counts)

        # 筛选态（q/cat）：平铺列表 + 分页；默认：按文件夹分组卡片
        flat = []
        pager_vals = None
        search_cat_ids = []
        if cat and cat in cat_names:
            search_cat_ids = [cat] + children.get(cat, [])
        elif cat:
            cat = 0
        if q or cat:
            domain = list(base_domain)
            if q:
                domain += ['|', ('name', 'ilike', q),
                           ('description', 'ilike', q)]
            if search_cat_ids:
                domain += [('category_id', 'in', search_cat_ids)]
            total = File.search_count(domain)
            pager_vals = pager('/downloads', total=total, page=page,
                               step=PAGE_SIZE,
                               url_args={'q': q, 'cat': cat, 'sort': sort})
            recs = File.search(domain, order=SORTS[sort][1],
                               limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
            flat = [_file_vals(f) for f in recs]
        else:
            recs = File.search(base_domain, order=SORTS[sort][1])
            groups = {}
            for f in recs:
                top = f.category_id.parent_id or f.category_id
                g = groups.setdefault(top.id, {
                    'id': top.id, 'name': top.name, 'files': [],
                    'subs': {}})
                row = _file_vals(f)
                if f.category_id.parent_id:
                    sid = f.category_id.id
                    g['subs'].setdefault(
                        sid, {'id': sid, 'name': f.category_id.name,
                              'files': []})['files'].append(row)
                else:
                    g['files'].append(row)
            groups = sorted(groups.values(), key=lambda g: (
                [c.id for c in cats].index(g['id'])
                if g['id'] in [c.id for c in cats] else 999))
            for g in groups:
                g['subs'] = sorted(g['subs'].values(), key=lambda s: s['name'])
        return request.render('edu_portal.edu_downloads_page', {
            'title': '资料下载',
            'page_name': 'downloads',
            'is_registrar': is_registrar,
            'manage_mode': False,
            'groups': groups if not (q or cat) else [],
            'flat': flat,
            'flat_mode': bool(q or cat),
            'q': q,
            'q_enc': quote(q),
            'cat': cat,
            'sort': sort,
            'sort_labels': SORTS,
            'chips': chip_counts,
            'total_count': total_count,
            'new_count': new_count,
            'src': src,
            'src_counts': src_counts,
            'top_files': [_file_vals(f) for f in top_files],
            'pager': pager_vals,
            'folder_options': (self._folder_options(cats)
                               if is_registrar else []),
            'max_mb': self._upload_limits()[0] if is_registrar else 20,
            'exts_text': (' '.join(sorted(self._upload_limits()[1]))
                          if is_registrar else ''),
        })

    @http.route('/downloads/file/<int:fid>', type='http', auth='user')
    def downloads_file(self, fid, **kw):
        rec = request.env['edu.download.file'].sudo().browse(fid)
        if not rec.exists() or not rec.active or not rec.file:
            return request.not_found()
        # 可见范围 v3：按登录身份勾选组判定（教务处/管理员恒可下）
        if not _can_download(rec):
            return request.not_found()
        # v3（t8）hard 档确认门禁：必须插在最前，并**同时覆盖 inline 预览分支**
        # —— 否则加 ?inline=1 即可拿到同一份字节，确认形同虚设（设计 §4.4）。
        if rec.ack_mode == 'hard' and not _ack_gate_ok(rec):
            # 本路由不带 website=True（它是纯文件流，不能套门户外壳），
            # 故跳到一个 website 路由去渲染确认页；确认后 next 指回本 URL。
            return request.redirect('/downloads/need-ack/%d' % rec.id)
        fname = rec.file_name or rec.name
        data = base64.b64decode(rec.file)
        # 在线预览：仅 pdf/图片白名单走 inline（浏览器原生渲染，零 JS）；
        # 预览不计下载次数、不写审计——「下载次数」只统计真正的下载。
        if kw.get('inline') == '1':
            ctype = _INLINE_TYPES.get((_ext_of(fname) or '').lower())
            if not ctype:
                return request.redirect('/downloads/file/%d' % fid)
            ascii_name = fname.encode('ascii', 'replace').decode() \
                .replace('"', '') or 'preview'
            return request.make_response(data, headers=[
                ('Content-Type', ctype),
                ('Content-Disposition',
                 "inline; filename=\"%s\"; filename*=UTF-8''%s"
                 % (ascii_name, quote(fname))),
                ('Content-Length', str(len(data))),
            ])
        rec.write({'download_count': rec.download_count + 1})
        request.env['edu.download.log'].sudo()._log_download(rec.id)
        headers = [
            ('Content-Type', 'application/octet-stream'),
            ('Content-Disposition', content_disposition(fname)),
            ('Content-Length', str(len(data))),
        ]
        return request.make_response(data, headers=headers)

    # ------------------- v3（t8）需确认已读 -------------------
    @http.route('/downloads/need-ack/<int:fid>', type='http', auth='user',
                website=True)
    def downloads_need_ack(self, fid, **kw):
        """hard 档确认页（独立 website 路由，便于套门户外壳）。"""
        rec = request.env['edu.download.file'].sudo().browse(fid)
        if not rec.exists() or rec.ack_mode != 'hard' or _ack_gate_ok(rec):
            return request.redirect('/downloads')
        return request.render('edu_portal.edu_downloads_ack_gate', {
            'title': '请先确认已读',
            'page_name': 'downloads',
            'file': rec,
            'next_url': '/downloads/file/%d' % rec.id,
        })

    @http.route('/downloads/ack/<int:fid>/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def downloads_ack_save(self, fid, **post):
        """记录「我已知悉」回执（幂等）。写操作走兄弟路由 /save + csrf。"""
        rec = request.env['edu.download.file'].sudo().browse(fid)
        if rec.exists() and rec.ack_mode != 'none' and _can_download(rec):
            rec.mark_ack(request.env.user)
        nxt = post.get('next') or ('/downloads/file/%d' % fid)
        if not str(nxt).startswith('/'):
            nxt = '/downloads'
        return request.redirect(nxt)

    @http.route('/downloads/unacked/<int:fid>', type='http', auth='user',
                website=True)
    def downloads_unacked(self, fid, **kw):
        """未读名单（教务处/管理员）：谁还没确认。"""
        if not _registrar():
            return request.redirect('/downloads')
        rec = request.env['edu.download.file'].sudo().browse(fid)
        if not rec.exists():
            return request.redirect('/downloads')
        unacked = rec.unacked_users()
        rows = [{'name': u.name or '', 'login': u.login or '',
                 'email': u.email or ''} for u in unacked]
        return request.render('edu_portal.edu_downloads_unacked', {
            'title': '未读名单',
            'page_name': 'downloads',
            'file': rec,
            'rows': rows,
            'unacked_n': len(rows),
            'acked_n': rec.ack_n,
            'target_n': len(rec.target_users()),
        })

    @http.route('/downloads/unacked/<int:fid>/export', type='http',
                auth='user')
    def downloads_unacked_export(self, fid, **kw):
        """未读名单 CSV（复用统一 csv_download：utf-8-sig 防乱码）。"""
        if not _registrar():
            return request.not_found()
        rec = request.env['edu.download.file'].sudo().browse(fid)
        if not rec.exists():
            return request.not_found()
        rows = [[u.name or '', u.login or '', u.email or '']
                for u in rec.unacked_users()]
        return csv_download(
            '未读名单-%s.csv' % (rec.name or ''),
            ['姓名', '账号', '邮箱'], rows)

    @http.route('/downloads/remind/<int:fid>/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def downloads_remind(self, fid, **post):
        """催办未读（范式参考：飞书广播号「未读加推」）。"""
        if not _registrar():
            return request.redirect('/downloads')
        rec = request.env['edu.download.file'].sudo().browse(fid)
        if rec.exists():
            body = ('【资料催办】《%s》需您确认已读，请到资料下载中心查看。'
                    % (rec.name or ''))
            sender = request.env.ref(
                'base.user_root', raise_if_not_found=False) \
                or request.env.user
            try:
                Msg = request.env['edu.message'].sudo()
                for usr in rec.unacked_users():
                    Msg.create({'sender_id': sender.id,
                                'recipient_id': usr.id, 'body': body})
            except Exception:
                pass
        return request.redirect('/downloads/unacked/%d' % fid)

    @http.route('/downloads/mine', type='http', auth='user', website=True)
    def downloads_mine(self, **kw):
        Log = request.env['edu.download.log'].sudo()
        logs = Log.search([('user_id', '=', request.env.uid)], limit=100)
        rows = [{
            'id': l.file_id.id,
            'name': l.file_id.name or '(已删除)',
            'href': '/downloads/file/%d' % l.file_id.id
                    if l.file_id.exists() and l.file_id.active else '',
            'date': _fmt_dt(l.create_date),
        } for l in logs]
        return request.render('edu_portal.edu_downloads_mine', {
            'title': '我的下载记录',
            'page_name': 'downloads',
            'rows': rows,
        })

    @http.route('/downloads/mine/export', type='http', auth='user')
    def downloads_mine_export(self, **kw):
        """本人下载记录 CSV 导出（近 500 条）。"""
        logs = request.env['edu.download.log'].sudo().search(
            [('user_id', '=', request.env.uid)], limit=500,
            order='create_date desc, id desc')
        rows = [[
            l.file_id.name if l.file_id.exists() else '(已删除)',
            l.file_id.category_id.name if l.file_id.exists()
            and l.file_id.category_id else '',
            _fmt_dt(l.create_date),
        ] for l in logs]
        return csv_download(
            '我的下载记录_%s.csv' % fields.Date.today().strftime('%Y%m%d'),
            ['文件', '文件夹', '下载时间'],
            rows)

    # ------------------------------------------------------------------
    # 管理台（教务处/管理员）
    # ------------------------------------------------------------------
    def _folders_tree(self):
        Cat = request.env['edu.download.category'].sudo()
        cats = Cat.search([], order='sequence, id')
        tops = [{'id': c.id, 'name': c.name, 'obj': c} for c in cats
                if not c.parent_id]
        child_map = {}
        for c in cats:
            if c.parent_id:
                child_map.setdefault(c.parent_id.id, []).append(c)
        return cats, tops, child_map

    def _folder_options(self, cats):
        """下拉选项：id/label（子文件夹缩进两格）。"""
        opts = []
        for c in cats:
            label = c.name if not c.parent_id else '　└ ' + c.name
            opts.append({'id': c.id, 'label': label})
        return opts

    def _manage_common(self):
        File = request.env['edu.download.file'].sudo()
        cats, tops, child_map = self._folders_tree()
        # 文件夹面板（含停用文件计数，供删除守卫提示）
        all_per_cat = {row[0].id: row[1] for row in File._read_group(
            [], ['category_id'], ['__count'])}
        panel = []
        for t in tops:
            entry = {
                'id': t['id'], 'name': t['name'],
                'description': t['obj'].description or '',
                'count': all_per_cat.get(t['id'], 0),
                'children': [],
            }
            for ch in child_map.get(t['id'], []):
                entry['children'].append({
                    'id': ch.id, 'name': ch.name,
                    'description': ch.description or '',
                    'count': all_per_cat.get(ch.id, 0),
                })
            panel.append(entry)
        return File, cats, panel

    @http.route('/downloads/manage', type='http', auth='user', website=True)
    def downloads_manage(self, q='', cat=0, status='all', page=1, **kw):
        """兼容旧入口：管理台已并入 /downloads?mode=manage。"""
        if not _registrar():
            return request.redirect('/downloads')
        url = '/downloads?mode=manage&status=%s' % (
            status if status in ('all', 'active', 'inactive') else 'all')
        if (q or '').strip():
            url += '&q=' + quote(q.strip())
        try:
            if int(cat or 0):
                url += '&cat=%d' % int(cat)
        except (TypeError, ValueError):
            pass
        return request.redirect(url)

    @http.route('/downloads/folder/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def downloads_folder_save(self, **post):
        if not _registrar():
            return request.redirect('/my/home')
        Cat = request.env['edu.download.category'].sudo()
        name = (post.get('name') or '').strip()
        if not name:
            return request.redirect('/downloads?mode=manage&err=folder_name')
        try:
            cid = int(post.get('cid') or 0)
        except (TypeError, ValueError):
            cid = 0
        try:
            parent = int(post.get('parent_id') or 0) or False
        except (TypeError, ValueError):
            parent = False
        vals = {
            'name': name,
            'description': (post.get('description') or '').strip(),
        }
        try:
            vals['sequence'] = int(post.get('sequence') or 10)
        except (TypeError, ValueError):
            vals['sequence'] = 10
        if cid:
            Cat.browse(cid).write(vals)
        else:
            vals['parent_id'] = parent
            Cat.create(vals)
        return request.redirect('/downloads?mode=manage&saved=1')

    @http.route('/downloads/folder/delete', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def downloads_folder_delete(self, **post):
        if not _registrar():
            return request.redirect('/my/home')
        try:
            cid = int(post.get('cid') or 0)
        except (TypeError, ValueError):
            cid = 0
        try:
            request.env['edu.download.category'].sudo().browse(cid).unlink()
        except UserError:
            return request.redirect(
                '/downloads?mode=manage&err=folder_not_empty')
        return request.redirect('/downloads?mode=manage&saved=1')

    # ------------------------------------------------------------------
    # 上传（批量；表单内联在 /downloads 页，本路由仅兼容跳转）
    # ------------------------------------------------------------------
    def _upload_limits(self):
        icp = request.env['ir.config_parameter'].sudo()
        max_mb = 20
        try:
            max_mb = int(icp.get_param('edu.downloads.max_file_mb', 20))
        except (TypeError, ValueError):
            pass
        exts = [e.strip().lower() for e in icp.get_param(
            'edu.downloads.allowed_ext', DEFAULT_EXTS).split() if e.strip()]
        return max_mb, set(exts)

    @http.route('/downloads/upload', type='http', auth='user', website=True)
    def downloads_upload(self, **kw):
        """兼容旧入口：上传面板已内联进 /downloads 管理模式。"""
        if not _registrar():
            return request.redirect('/downloads')
        return request.redirect('/downloads?mode=manage')

    @http.route('/downloads/upload/save', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def downloads_upload_save(self, **post):
        if not _registrar():
            return request.redirect('/my/home')
        File = request.env['edu.download.file'].sudo()
        Cat = request.env['edu.download.category'].sudo()
        try:
            cat_id = int(post.get('category_id') or 0)
        except (TypeError, ValueError):
            cat_id = 0
        new_cat = (post.get('new_category') or '').strip()
        if new_cat:
            cat = Cat.create({'name': new_cat})
            cat_id = cat.id
        if not cat_id or not Cat.browse(cat_id).exists():
            return request.redirect('/downloads?mode=manage&err=nocat')
        desc = (post.get('description') or '').strip()
        vis_vals = _visibility_vals(post)
        if vis_vals is None:
            return request.redirect('/downloads?mode=manage&err=novis')
        max_mb, exts = self._upload_limits()
        files = request.httprequest.files.getlist('files')
        if not files:
            return request.redirect('/downloads?mode=manage&err=nofile')
        ok, failed, last_error = 0, 0, ''
        results = []
        for fs in files:
            fname = fs.filename or ''
            reason = ''
            ext = _ext_of(fname)
            if not fname:
                continue
            if exts and ext not in exts:
                reason = '类型 .%s 不在白名单' % (ext or '?')
            data = fs.read()
            if not reason and len(data) > max_mb * 1024 * 1024:
                reason = '超过 %dMB 限制' % max_mb
            if reason:
                failed += 1
                last_error = '%s：%s' % (fname[:40], reason)
                results.append({'name': fname[:60], 'ok': False,
                                'reason': reason})
                continue
            File.create({
                'name': File._dedup_name(cat_id, fname),
                'category_id': cat_id,
                'description': desc,
                'file': base64.b64encode(data),
                'file_name': fname,
                **vis_vals,
            })
            ok += 1
            results.append({'name': fname[:60], 'ok': True, 'reason': ''})
        # 逐文件结果挂 session，管理模式页一次性取回展示（防 URL 过长）
        request.session['edu.dl.upload_results'] = results[:30]
        return request.redirect(
            '/downloads?mode=manage&uploaded=%d&failed=%d&last_error=%s'
            % (ok, failed, quote(last_error)))

    # ------------------------------------------------------------------
    # 批量操作 + 行内编辑
    # ------------------------------------------------------------------
    @http.route('/downloads/manage/bulk', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def downloads_manage_bulk(self, **post):
        if not _registrar():
            return request.redirect('/my/home')
        File = request.env['edu.download.file'].sudo()
        action = post.get('action') or ''
        raw_ids = request.httprequest.form.getlist('ids')
        ids = []
        for i in raw_ids:
            try:
                ids.append(int(i))
            except (TypeError, ValueError):
                continue
        recs = File.browse(ids).exists()
        done = skip = 0
        if action == 'delete':
            for r in recs:
                try:
                    r.unlink()
                    done += 1
                except Exception:
                    skip += 1
        elif action == 'deactivate':
            recs.write({'active': False})
            done = len(recs)
        elif action == 'activate':
            recs.write({'active': True})
            done = len(recs)
        elif action == 'visibility':
            vis_vals = _visibility_vals(post)
            if vis_vals is None:
                skip = len(recs)
            else:
                recs.write(vis_vals)
                done = len(recs)
        elif action == 'move':
            try:
                move_cat = int(post.get('move_cat') or 0)
            except (TypeError, ValueError):
                move_cat = 0
            if move_cat:
                recs.write({'category_id': move_cat})
                done = len(recs)
            else:
                skip = len(recs)
        else:
            skip = len(recs)
        # 4a 审计：资料批量操作
        request.env['edu.audit.log'].sudo()._log(
            _bulk_action_label(action),
            'edu.download.file', 0, '',
            '%d 条成功 / %d 条跳过' % (done, skip))
        return request.redirect(
            '/downloads?mode=manage&done=%d&skip=%d' % (done, skip))

    @http.route('/downloads/manage/file/update', type='http', auth='user',
                methods=['POST'], website=True, csrf=True)
    def downloads_manage_file_update(self, **post):
        if not _registrar():
            return request.redirect('/my/home')
        File = request.env['edu.download.file'].sudo()
        try:
            fid = int(post.get('fid') or 0)
        except (TypeError, ValueError):
            fid = 0
        rec = File.browse(fid)
        if not rec.exists():
            return request.redirect('/downloads?mode=manage&err=nofile')
        vals = {
            'name': (post.get('name') or rec.name).strip() or rec.name,
            'description': (post.get('description') or '').strip(),
            'active': bool(post.get('active')),
        }
        vis_vals = _visibility_vals(post)
        if vis_vals is None:
            return request.redirect('/downloads?mode=manage&err=novis')
        vals.update(vis_vals)
        try:
            cid = int(post.get('category_id') or 0)
            if cid:
                vals['category_id'] = cid
        except (TypeError, ValueError):
            pass
        fs = request.httprequest.files.get('replace_file')
        if fs and fs.filename:
            data = fs.read()
            max_mb, exts = self._upload_limits()
            ext = _ext_of(fs.filename)
            if (not exts or ext in exts) and len(data) <= max_mb * 1024 * 1024:
                vals['file'] = base64.b64encode(data)
                vals['file_name'] = fs.filename
        rec.write(vals)
        return request.redirect('/downloads?mode=manage&saved=1')

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------
    @http.route('/downloads/stats', type='http', auth='user', website=True)
    def downloads_stats(self, **kw):
        if not _registrar():
            return request.redirect('/my/home')
        File = request.env['edu.download.file'].sudo()
        Log = request.env['edu.download.log'].sudo()
        recs = File.search([], order='download_count desc, name', limit=50)
        events, last_dt, uniq = {}, {}, {}
        try:
            for f_rec, cnt in Log._read_group([], ['file_id'], ['__count']):
                events[f_rec.id] = cnt
            for f_rec, mx in Log._read_group([], ['file_id'], ['create_date:max']):
                last_dt[f_rec.id] = mx
            for f_rec, u_rec in Log._read_group([], ['file_id', 'user_id'], []):
                uniq.setdefault(f_rec.id, set()).add(u_rec.id)
        except Exception:
            pass
        rows = []
        max_count = max([f.download_count for f in recs] or [0]) or 1
        for f in recs:
            rows.append({
                'id': f.id,
                'name': f.name,
                'cat_name': f.category_id.name,
                'active': f.active,
                'count': f.download_count,
                'log_count': events.get(f.id, 0),
                'uniq': len(uniq.get(f.id, ())),
                'last': _fmt_dt(last_dt.get(f.id)),
                'size_text': _human_size(f.file_size or 0),
                'bar': int(round(f.download_count * 100.0 / max_count)),
            })
        total30 = 0
        try:
            total30 = Log.search_count([
                ('create_date', '>=', fields.Datetime.now()
                 - datetime.timedelta(days=30))])
        except Exception:
            pass
        return request.render('edu_portal.edu_downloads_stats', {
            'title': '资料下载统计',
            'page_name': 'downloads',
            'rows': rows,
            'total30': total30,
        })

    @http.route('/downloads/stats/export', type='http', auth='user')
    def downloads_stats_export(self, **kw):
        """下载统计 CSV 导出（教务处，全量文件）。"""
        if not _registrar():
            return request.redirect('/my/home')
        File = request.env['edu.download.file'].sudo()
        Log = request.env['edu.download.log'].sudo()
        recs = File.search([], order='download_count desc, name')
        events, last_dt, uniq = {}, {}, {}
        try:
            for f_rec, cnt in Log._read_group([], ['file_id'], ['__count']):
                events[f_rec.id] = cnt
            for f_rec, mx in Log._read_group([], ['file_id'],
                                             ['create_date:max']):
                last_dt[f_rec.id] = mx
            for f_rec, u_rec in Log._read_group([], ['file_id', 'user_id'], []):
                uniq.setdefault(f_rec.id, set()).add(u_rec.id)
        except Exception:
            pass
        rows = []
        for f in recs:
            rows.append([
                f.name or '',
                f.category_id.name or '',
                f.download_count or 0,
                events.get(f.id, 0),
                len(uniq.get(f.id, ())),
                _fmt_dt(last_dt.get(f.id)),
                '在架' if f.active else '已停用',
                _human_size(f.file_size or 0),
            ])
        return csv_download(
            '下载统计_%s.csv' % fields.Date.today().strftime('%Y%m%d'),
            ['文件', '文件夹', '下载次数', '去重前事件数', '独立人数',
             '最近下载', '状态', '大小'],
            rows)
