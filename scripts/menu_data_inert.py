# -*- coding: utf-8 -*-
"""把 edu_nav 的菜单数据文件在「生效」与「惰性」之间切换（t2，宿主侧，纯文件操作）。

为什么需要它：
  组策略/档位在裁定过程中会反复调整，而**在裁定落地之前，任何一次全模块升级都不能改到菜单**。
  惰性 = 把全部业务 <record> 注释掉、只留文件头与说明 ⇒ 装载等于零变化；
  生效 = 恢复原生 <record>。切换是可逆的、幂等的，且**不改文件里的字段内容**。

判定方式不看"有没有注释符号"，而是看**有效记录数**（未注释的 record 行数），
所以重复运行不会把已经惰性的文件再注释一层。

用法：
    python3 scripts/menu_data_inert.py --status                  # 只报状态
    python3 scripts/menu_data_inert.py --inert                   # 切到惰性
    python3 scripts/menu_data_inert.py --live                    # 切到生效
    python3 scripts/menu_data_inert.py --check                   # 自测（切过去再切回来）
退出码：0 成功；1 校验失败。
"""
import io
import os
import re
import sys

PATH = 'custom_addons/edu_nav/data/menu_consolidation_data.xml'
LT, GT = chr(60), chr(62)
OPEN_C = LT + '!-- '
CLOSE_C = ' --' + GT
REC = LT + 'record'
REC_END = LT + chr(47) + 'record'
FLD = LT + 'field'

COMMENTED_LINE = re.compile(r'^\s*' + re.escape(OPEN_C) + r'.*' + re.escape(CLOSE_C) + r'\s*$')
MODE_INERT = '发射模式：INERT'
MODE_LIVE = '发射模式：生效'


def has_inert_marker(text):
    """容忍大小写：生成器写 '发射模式：inert'，本工具统一成 'INERT'。"""
    for line in text.split('\n'):
        if '发射模式' in line and 'inert' in line.lower():
            return True
    return False


def effective_records(lines):
    return [l for l in lines
            if l.strip().startswith(REC) and not l.strip().startswith(OPEN_C)]


def status(text):
    lines = text.split('\n')
    live = effective_records(lines)
    commented = [l for l in lines if COMMENTED_LINE.match(l)
                 and (REC in l or FLD in l)]
    return {'live_records': len(live), 'commented_lines': len(commented),
            'mode': 'live' if live else ('inert' if has_inert_marker(text) else 'inert(无标记)')}


def to_inert(text):
    if has_inert_marker(text):
        return text, 0
    out, n = [], 0
    for line in text.split('\n'):
        st = line.strip()
        if st.startswith(OPEN_C):
            out.append(line)
            continue
        if st.startswith(REC) or st.startswith(REC_END) or st.startswith(FLD):
            out.append('    ' + OPEN_C + st + CLOSE_C)
            n += 1
        else:
            out.append(line)
    return '\n'.join(out).replace(MODE_LIVE, MODE_INERT), n


def to_live(text):
    # 判定不只看头部标记，也接受"行形态"（整行被注释的 menu_state_* 记录行）——
    # 这样即便某次生成漏了标记行，工具仍能正确还原，而不是静默不动。
    marker = has_inert_marker(text)
    shaped = any(
        COMMENTED_LINE.match(l) and 'menu_state_' in l for l in text.split('\n'))
    if not marker and not shaped:
        return text, 0
    out, n = [], 0
    for line in text.split('\n'):
        st = line.strip()
        if COMMENTED_LINE.match(line) and (REC in st or FLD in st):
            inner = st[len(OPEN_C):-len(CLOSE_C)].strip()
            indent = ' ' * (len(line) - len(line.lstrip()))
            indent = ' ' * min(len(indent), 4) or '    '
            out.append(indent + inner)
            n += 1
        else:
            out.append(line)
    return '\n'.join(out).replace(MODE_INERT, MODE_LIVE), n


MODELS = 'custom_addons/edu_nav/models/menu_consolidation.py'


def _sync_count(n):
    """切换模式时同步模块里的期望条数常量 —— 常量与"数据里实际有几条"必须一致，
    否则装载期守卫会（正确地）报漂移，把"模式切换"误报成"数据旧了"。"""
    import re
    if not os.path.exists(MODELS):
        return
    src = io.open(MODELS, encoding='utf-8').read()
    new_src = re.sub(r'MENU_CONSOLIDATED_COUNT = \d+', 'MENU_CONSOLIDATED_COUNT = %d' % n, src)
    if new_src != src:
        io.open(MODELS, 'w', encoding='utf-8').write(new_src)


def main(argv):
    text = io.open(PATH, encoding='utf-8').read()
    st = status(text)
    if '--status' in argv or not argv:
        print('文件=%s 模式=%s 生效记录=%d 注释行=%d' % (
            PATH, st['mode'], st['live_records'], st['commented_lines']))
        return 0
    if '--check' in argv:
        # 先把文件归一到 live 再往返 —— 否则在惰性态下"惰性→惰性"是空操作，
        # 测不到真正的往返（这是本工具第一版的自测缺陷：它稳定地测了个空操作）。
        base, _ = to_live(text)
        base_st = status(base)
        inert, n1 = to_inert(base)
        s2 = status(inert)
        back, n2 = to_live(inert)
        s3 = status(back)
        ok = (base_st['live_records'] > 0 and s2['live_records'] == 0
              and n2 == n1 and s3['live_records'] == base_st['live_records']
              and back == base)
        print('%s | 自测：live=%d 条 → 惰性（注释 %d 行）→ 还原=%d 条，逐字节相同=%s' % (
            'PASS' if ok else 'FAIL', base_st['live_records'], n1,
            s3['live_records'], back == base))
        # 自测不改动文件：写回与原来一致的内容
        if base != text:
            print('（自测不改文件：文件当前仍是 %s 态）' % st['mode'])
        return 0 if ok else 1
    if '--inert' in argv:
        if st['mode'] == 'inert':
            print('已是惰性，未改动（幂等）')
            return 0
        new, n = to_inert(text)
        io.open(PATH, 'w', encoding='utf-8').write(new)
        _sync_count(0)
        print('已切到惰性：注释 %d 行，生效记录 %d → 0；模块常量已同步为 0' % (n, st['live_records']))
        return 0
    if '--live' in argv:
        if st['mode'] == 'live':
            print('已是生效，未改动（幂等）')
            return 0
        new, n = to_live(text)
        io.open(PATH, 'w', encoding='utf-8').write(new)
        live_n = status(new)['live_records']
        _sync_count(live_n)
        print('已切到生效：还原 %d 行，生效记录 → %d；模块常量已同步为 %d' % (n, live_n, live_n))
        return 0
    sys.stderr.write('未知参数 %s\n' % argv)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
