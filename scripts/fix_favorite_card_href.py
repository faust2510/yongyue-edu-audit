#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t122：edu.favorite 中 card_href 为空/空白的记录 —— 一次性订正（可容器内跑，幂等、可回滚）。

背景
    /my/apps 曾出现 href="/" 且无标题的**空卡片**。根因是控制器把空 href 当"隐藏开关"
    （custom_addons/edu_portal/controllers/batch2.py: livechat_href = ''），而未知 href 会回退成
    ('', 'fa-file-o', '') ⇒ 渲染成 <a href="/" title="">。控制器侧已加固（空 href 不再成卡）；
    本脚本处理**数据侧同类隐患**：card_href 为空的收藏行解析不出任何卡片，属脏数据，清理。

行为
    1) 先**全量打印受影响行原值**（含可直接回滚的 INSERT 语句）——订正前留痕；
    2) 删除这些行；
    3) 提交（env.cr.commit()）；
    4) **幂等**：第二次运行受影响 0 行、不做任何写操作。

用法（容器内，推荐）
    docker exec -i edu19-clone-web-1 odoo shell -d edu19 --no-http < scripts/fix_favorite_card_href.py
用法（本机 python3，仅做语法/说明自检，不连库）
    python3 scripts/fix_favorite_card_href.py

⚠ 生产执行不在本任务范围（需用户确认后另立任务）。
"""
import sys


def _q(v):
    """SQL 字面量转义：空串要打成 ''，否则回滚语句不可执行（实测踩过）。"""
    if v is None:
        return 'NULL'
    return "'" + str(v).replace("'", "''") + "'"


def _rollback_sql(rows):
    out = []
    for r in rows:
        out.append(
            "INSERT INTO edu_favorite (id, user_id, card_href, sequence, create_date) "
            "VALUES (%s, %s, %s, %s, %s);" % (
                r.id, r.user_id.id, _q(r.card_href), r.sequence,
                _q(r.create_date)))
    return out


def run(env):
    Fav = env['edu.favorite'].sudo()
    dom = ['|', ('card_href', '=', False), ('card_href', '=', '')]
    rows = Fav.search(dom, order='id')
    print('=' * 60)
    print('edu.favorite 中 card_href 为空/空白的记录：%d 行' % len(rows))
    if not rows:
        print('受影响 0 行 ⇒ 无变更（本脚本幂等；第二次运行即此结果）')
        return 0
    print('-' * 60)
    print('订正前原值（可回滚；下列 INSERT 复制即回滚）：')
    for r in rows:
        print('  id=%s user=%s(%s) card_href=%r sequence=%s create_date=%s'
              % (r.id, r.user_id.display_name, r.user_id.id,
                 r.card_href, r.sequence, r.create_date))
    for sql in _rollback_sql(rows):
        print('  ' + sql)
    print('-' * 60)
    ids = rows.ids
    rows.unlink()
    env.cr.commit()
    print('已删除 %d 行并 commit：%s' % (len(ids), ids))
    print('=' * 60)
    return len(ids)


if 'env' in globals():          # odoo shell 注入
    _n = run(env)               # noqa: F821
    print('DONE changes=%d' % _n)
else:                           # 本机 python3：只做可用性说明
    print('本脚本需在 Odoo shell 内运行（需要 env）：')
    print('  docker exec -i edu19-clone-web-1 odoo shell -d edu19 --no-http '
          '< scripts/fix_favorite_card_href.py')
    sys.exit(0)
