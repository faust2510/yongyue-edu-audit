#!/usr/bin/env python3
'''永约门户图标生成器：统一「渐变圆角瓦片 + 白色线性图形」设计系统。
用法: python3 scripts/gen_icons.py   （在仓库根目录执行）
产物: custom_addons/{edu_portal,edu_apply,edu_life}/static/src/img/**/*.svg
'''
import math, os

ROOT = os.path.join(os.path.dirname(__file__), '..', 'custom_addons')

def tile(c1, c2, glyph):
    return '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient></defs>
<rect x="3" y="3" width="58" height="58" rx="14" fill="url(#g)"/>
<path d="M17 3h30a14 14 0 0 1 14 14v11H3V17A14 14 0 0 1 17 3Z" fill="#fff" opacity=".14"/>
<g transform="translate(32,33)" fill="none" stroke="#fff" stroke-width="3"
   stroke-linecap="round" stroke-linejoin="round">%s</g>
</svg>
''' % (c1, c2, glyph)

def star_pts(r_out=11, r_in=4.6):
    pts = []
    for i in range(10):
        r = r_out if i % 2 == 0 else r_in
        a = -math.pi / 2 + i * math.pi / 5
        pts.append('%.1f,%.1f' % (r*math.cos(a), r*math.sin(a)))
    return ' '.join(pts)

def G(name):
    return GLYPHS[name]

GLYPHS = {
 'calendar': '<rect x="-11" y="-9" width="22" height="19" rx="3"/>'
             '<path d="M-11 -2h22M-6 -13v5M6 -13v5"/>'
             '<circle cx="-5" cy="4" r="1.4" fill="#fff" stroke="none"/>'
             '<circle cx="1" cy="4" r="1.4" fill="#fff" stroke="none"/>',
 'calendar_check': '<rect x="-11" y="-9" width="22" height="19" rx="3"/>'
             '<path d="M-11 -2h22M-6 -13v5M6 -13v5"/><path d="M-5 3l3.5 3.5L5 0"/>',
 'calendar_plus': '<rect x="-11" y="-9" width="22" height="19" rx="3"/>'
             '<path d="M-11 -2h22M-6 -13v5M6 -13v5"/><path d="M0 1v6M-3 4h6"/>',
 'clock': '<circle r="11"/><path d="M0 -6V0l4.5 3"/>',
 'check_circle': '<circle r="11"/><path d="M-5.5 0l4 4L6 -4.5"/>',
 'doc': '<path d="M-8 -12h9l7 7v16h-16z"/><path d="M1 -12v7h7"/>'
        '<path d="M-4 2h8M-4 7h8"/>',
 'doc_edit': '<path d="M-8 -12h9l7 7v16h-16z"/><path d="M1 -12v7h7"/>'
        '<path d="M-6 8l1.2-4L3 -3.5l3 3L-2.5 7z"/>',
 'chart': '<path d="M-11 11H11"/><path d="M-7 11V2M0 11V-5M7 11V-1"/>',
 'trend': '<path d="M-11 11H11V-11"/><path d="M-9 6l6-7 4 3 7-8"/><path d="M4 -6h4v4"/>',
 'pie': '<path d="M0 -11a11 11 0 1 0 11 11H0z"/><path d="M4 -9.5A11 11 0 0 1 11 -2H4z"/>',
 'book': '<path d="M0 -8C-3 -11-8 -11-12 -9v18c4-2 9-2 12 1 3-3 8-3 12-1V-9C8 -11 3 -11 0 -8z"/>'
         '<path d="M0 -8v19"/>',
 'book_open': '<path d="M0 -7C-4 -10-9 -10-12 -8v16c3-2 8-2 12 1 4-3 9-3 12-1V-8C9 -10 4 -10 0 -7z"/>'
         '<path d="M0 -7v17"/>',
 'tablet': '<rect x="-8" y="-12" width="16" height="24" rx="2.5"/><path d="M-3 8h6"/>'
           '<path d="M-4 -5h8M-4 0h8"/>',
 'folder': '<path d="M-12 -8h7l3 3h12a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-20a2 2 0 0 1-2-2z"/>',
 'video': '<rect x="-12" y="-8" width="15" height="16" rx="3"/><path d="M3 -2l9-5v14l-9-5"/>',
 'megaphone': '<path d="M-12 -3L2 -9v18l-14-6z"/><path d="M2 -9v18"/>'
              '<path d="M-8 3v7h4v-5"/><path d="M7 -5a7 7 0 0 1 0 10"/>',
 'trophy': '<path d="M-6 -11h12v6a6 6 0 0 1-12 0z"/>'
           '<path d="M-6 -9h-4a4.5 4.5 0 0 0 5 5M6 -9h4a4.5 4.5 0 0 1-5 5"/>'
           '<path d="M0 1v5M-5 9h10M-3 6h6v3h-6z"/>',
 'plane': '<path d="M-12 3L12 -9 6 11 0 3z"/><path d="M0 3L12 -9"/>',
 'grad_cap': '<path d="M-13 -3L0 -9l13 6-13 6z"/><path d="M8 0v7"/>'
             '<path d="M-6 0.5V5c0 3 12 3 12 0V.5"/>',
 'award': '<circle cy="-2.5" r="7.5"/><path d="M-3.5 4L-6.5 12l3.5-2 2 3 2-6M3.5 4L6.5 12l-3.5-2"/>',
 'sign_in': '<path d="M-1 -11h10v22h-10"/><path d="M-12 0h11M-5 -5l5 5-5 5"/>',
 'exchange': '<path d="M-10 -4h15m-4 -4.5l4.5 4.5-4.5 4.5"/>'
             '<path d="M10 6h-15m4 -4.5L-5.5 6 4 10.5"/>',
 'list_ul': '<circle cx="-8.5" cy="-6" r="1.6" fill="#fff" stroke="none"/>'
            '<circle cx="-8.5" cy="0" r="1.6" fill="#fff" stroke="none"/>'
            '<circle cx="-8.5" cy="6" r="1.6" fill="#fff" stroke="none"/>'
            '<path d="M-3 -6h14M-3 0h14M-3 6h14"/>',
 'note': '<path d="M-10 -11h20v13l-8 8h-12z"/><path d="M2 10V2h8"/>',
 'user': '<circle cy="-5" r="5.5"/><path d="M-11 12c0-7 22-7 22 0"/>',
 'user_child': '<circle cx="-3" cy="-4" r="5"/><path d="M-12 11c0-6 18-6 18 0"/>'
            '<path d="M7 9c0-3 6-3 6 0 0-3 6-3 6 0 0 3-6 5-6 6 0-1-6-3-6-6z" stroke-width="2.4"/>',
 'lock': '<rect x="-9" y="-4" width="18" height="14" rx="3"/>'
         '<path d="M-5 -4v-3.5a5 5 0 0 1 10 0V-4"/>'
         '<circle cy="3" r="1.6" fill="#fff" stroke="none"/>',
 'marker': '<path d="M0 12C6 5 9 1 9 -3a9 9 0 1 0-18 0c0 4 3 8 9 15z"/><circle cy="-3" r="3"/>',
 'card': '<rect x="-12" y="-8" width="24" height="17" rx="3"/><path d="M-12 -2h24"/>'
         '<path d="M-7 4h5"/>',
 'star': None,
 'comment': '<path d="M-9 -10h18a4 4 0 0 1 4 4v9a4 4 0 0 1-4 4h-12l-8 6v-19a4 4 0 0 1 4-4z"/>'
            '<path d="M-4 -3h10M-4 2h6"/>',
 'comments': '<path d="M-12 2v-9a3.5 3.5 0 0 1 3.5-3.5H3"/>'
             '<path d="M-6 -4h13a4 4 0 0 1 4 4v7a4 4 0 0 1-4 4H-2l-6 5v-5"/>',
 'pencil': '<path d="M3 -11l8 8-13 13-9 2 2-9z"/><path d="M0 -8l8 8"/>',
 'files': '<rect x="-2" y="-12" width="13" height="16" rx="2.5"/>'
          '<rect x="-11" y="-5" width="13" height="16" rx="2.5"/>',
 'bag': '<path d="M-10 -6h20l-2 16h-16z"/><path d="M-5 -6v-2a5 5 0 0 1 10 0v2"/>',
 'bell': '<path d="M-9 5c1.5-2 2-4 2-8a7 7 0 0 1 14 0c0 4 .5 6 2 8z"/>'
         '<path d="M-2.5 8a2.5 2.5 0 0 0 5 0"/>',
 'clipboard': '<rect x="-10" y="-9" width="20" height="21" rx="3"/>'
         '<path d="M-4 -9v-3h8v3"/><path d="M-5 2l3.5 3.5L5 -1"/>',
 'shield': '<path d="M0 -12l10-4v12c0 6-4 9-10 12C-6 5-10 2-10 -4v-12z" '
           'transform="translate(0,2)"/><path d="M-4 0l3 3 6-6"/>',
 'home': '<path d="M-12 0L0 -11 12 0"/><path d="M-9 -2v13h18V-2"/><path d="M-2 11V4h4v7"/>',
 'inbox': '<path d="M-11 2h5l2 3h8l2-3h5"/><path d="M-11 2v6a2 2 0 0 0 2 2h18a2 2 0 0 0 2-2V2"/>'
          '<path d="M0 -11v8M-3.5 -6L0 -2.5 3.5 -6"/>',
 'camera': '<rect x="-11" y="-7" width="22" height="15" rx="3"/>'
           '<circle r="3.5"/><circle cx="8" cy="-3.5" r="1" fill="#fff" stroke="none"/>',
}
GLYPHS['star'] = '<polygon points="' + star_pts() + '" stroke-linejoin="round"/>'

P = 'edu_portal/static/src/img/icons/'
MENU = 'static/src/img/menu/'
SPEC = {
 P+'student/profile':            ('#F472B6', '#DB2777', G('user')),
 P+'my/fees':                    ('#FBBF24', '#B45309', G('card')),
 P+'my-library':                 ('#818CF8', '#4338CA', G('tablet')),
 P+'library/media':              ('#C084FC', '#7C3AED', G('book')),
 P+'meeting/information':        ('#22D3EE', '#0891B2', G('video')),
 P+'my/notice_board/notice':     ('#F87171', '#DC2626', G('megaphone')),
 P+'users/result-overview':      ('#FCD34D', '#D97706', G('trophy')),
 P+'my/time_off':                ('#94A3B8', '#475569', G('plane')),
 P+'student/progression':        ('#34D399', '#059669', G('trend')),
 P+'subject/details':            ('#FB923C', '#EA580C', G('folder')),
 P+'my/asset-request':           ('#67E8F9', '#0E7490', G('inbox')),
 P+'student/assignment/details': ('#60A5FA', '#2563EB', G('doc')),
 P+'student/exam':               ('#F87171', '#B91C1C', G('pencil')),
 P+'my/grievances':              ('#F472B6', '#BE185D', G('comments')),
 P+'my-courses':                 ('#A78BFA', '#6D28D9', G('grad_cap')),
 P+'certificate':                ('#FBBF24', '#CA8A04', G('award')),
 P+'student/attendance':         ('#34D399', '#0D9488', G('check_circle')),
 P+'student/newregistration/info':('#2DD4BF', '#0F766E', G('sign_in')),
 P+'student/timetable':          ('#60A5FA', '#1D4ED8', G('calendar')),
 P+'grade-book':                 ('#4ADE80', '#16A34A', G('chart')),
 P+'course/change/request':      ('#2DD4BF', '#0D9488', G('exchange')),
 P+'subject/registration':       ('#C084FC', '#9333EA', G('list_ul')),
 P+'my/academic-calendar':       ('#818CF8', '#4F46E5', G('calendar_plus')),
 P+'my/thesis':                  ('#FDA4AF', '#E11D48', G('note')),
 P+'online/meeting':             ('#38BDF8', '#0284C7', G('video')),
 P+'my/addresses':               ('#94A3B8', '#64748B', G('home')),
 P+'my/password':                ('#A8B4C4', '#334155', G('lock')),   # 原 my/security（改指逐字安全页）
 P+'my/checkins':                ('#4ADE80', '#059669', G('clipboard')),
 P+'my/journals':                ('#C084FC', '#7C3AED', G('book_open')),
 P+'eval/my':                    ('#FCD34D', '#D97706', G('star')),
 P+'eval/review':                ('#22D3EE', '#0E7490', G('comment')),
 P+'timetable/bulk':             ('#818CF8', '#4338CA', G('calendar_plus')),
 P+'timetable/copy':             ('#38BDF8', '#0369A1', G('files')),
 P+'journals/review':            ('#FBBF24', '#B45309', G('doc_edit')),
 P+'checkins/stats':             ('#34D399', '#047857', G('pie')),
 P+'extra/livechat':             ('#F472B6', '#DB2777', G('comment')),
 P+'extra/child':                ('#FDA4AF', '#E11D48', G('user_child')),
 P+'help':                       ('#A78BFA', '#6D28D9', G('book_open')),
 P+'downloads':                  ('#34D399', '#047857', G('doc')),
 'edu_apply/'+MENU+'apply.svg':      ('#818CF8', '#4338CA', G('doc_edit')),
 'edu_life/'+MENU+'life.svg':        ('#4ADE80', '#059669', G('clipboard')),
 'edu_schedule/'+MENU+'schedule.svg':('#818CF8', '#4338CA', G('calendar_plus')),
 'edu_portal/'+MENU+'approval.svg':  ('#4ADE80', '#059669', G('check_circle')),
 'edu_portal/'+MENU+'assets.svg':    ('#67E8F9', '#0E7490', G('inbox')),
 'edu_portal/'+MENU+'fees.svg':      ('#FBBF24', '#B45309', G('card')),
 'edu_portal/'+MENU+'invite.svg':    ('#F472B6', '#DB2777', G('sign_in')),
 'edu_portal/'+MENU+'jobs.svg':      ('#94A3B8', '#475569', G('folder')),
 'edu_portal/'+MENU+'lms.svg':       ('#A78BFA', '#6D28D9', G('grad_cap')),
 'edu_portal/'+MENU+'welfare.svg':   ('#FB923C', '#EA580C', G('bag')),
 'edu_portal/'+MENU+'downloads.svg': ('#34D399', '#047857', G('doc')),
}

def main():
    n = 0
    for rel, (c1, c2, glyph) in SPEC.items():
        if not rel.endswith('.svg'):
            rel += '.svg'
        path = os.path.join(ROOT, rel)
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, 'w') as fh:
            fh.write(tile(c1, c2, glyph))
        n += 1
    print('generated %d icons' % n)

if __name__ == '__main__':
    main()