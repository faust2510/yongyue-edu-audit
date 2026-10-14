#!/usr/bin/env bash
# 全新库安装演练（可复跑）—— 把「换新服务器/重建库」这条路上踩过的坑固化成检查。
#
# 为什么要单独立这一条（2026-10-04 第 68 轮立）：
#   第 65 轮第一次真去装一个全新库，发现**整条安装链是断的**：
#     · edu_brand 的 data 引用了 6 个模块的 xmlid，而 depends 只声明 3 个；
#     · 同一批 <function> 用 context={"lang":"zh_CN"} 写翻译字段，而 Odoo 19 只接受 **active 语言**；
#     · edu_schedule 用 calendar.event 却没依赖 calendar。
#   这三条**只在全新库上出现**，克隆库（生产早装过那些模块）永远看不出来 ——
#   而本项目**已经丢过一次生产库**，下一次重建是必然事件。
#   ⇒ 把「装得上 + 关键模块 installed + 关键数据在」做成一条可复跑的命令，
#     以后谁改动了 manifest / data file，跑一下就知道有没有把新库这条路弄断。
#
# 用法：bash scripts/check_fresh_install.sh [库名]      默认 edu19_rehearsal
# 退出码：0=装得上且关键项齐 ｜ 1=失败（含关键模块未装/关键数据缺失）｜ 2=ENV
#
# ⚠ 会 **drop 库名那个数据库**（默认 edu19_rehearsal，绝不碰 edu19）。
set -u
DB=${1:-edu19_rehearsal}
case "$DB" in
  edu19|postgres|template0|template1) echo "拒绝在 $DB 上跑（那是真库）"; exit 2 ;;
esac

DC="docker exec edu19-clone-db-1"
DW="docker exec -i edu19-clone-web-1"
# 与 deploy_myedu.sh:156 的默认清单一致 + 162 行注释指出的首次必须 -i 的那几个
MODULES="edu_life,edu_schedule,edu_apply,edu_portal,edu_brand,edu_tg_bind,edu_assess,edu_public,edu_zh"

# ⚠ 2026-10-03（第 108 轮）修两处（由独立验证方 root-cause 后报告）：
#   ① 原来的 `drop database if exists` **在库还有活动连接时会失败**（"is being accessed by other users"），
#      紧接着 create 就报 "already exists" ⇒ 脚本笼统报「建库失败」，把人往「权限/磁盘」方向带。
#      **真正卡住的是 DROP，不是 CREATE。** 加 `with (force)`（PG 13+ 会先掐掉连接；Odoo 19 的 PG 版本远高于此）。
#   ② 原来把 stderr 一起 `>/dev/null 2>&1` 吞掉了 ⇒ 诊断信息全丢。现在**留最后一行真实报错**。
if ! _drop_out=$($DC psql -U odoo -d postgres -c "drop database if exists $DB with (force);" 2>&1); then
  echo "ENV：删库失败（${DB}）—— 真实报错：$(echo "$_drop_out" | tail -1)"
  exit 2
fi
if ! _create_out=$($DC psql -U odoo -d postgres -c "create database $DB owner odoo;" 2>&1); then
  echo "ENV：建库失败（${DB}）—— 真实报错：$(echo "$_create_out" | tail -1)"
  exit 2
fi

echo "=== 安装 ${MODULES}（不带演示数据）==="
LOG=/tmp/fresh_install_$DB.log
$DW sh -c "cd /mnt && odoo -d $DB --db_host=db --db_user=odoo --db_password=odoo --no-http \
  --without-demo=all -i $MODULES --stop-after-init --log-level=warn" > "$LOG" 2>&1

bad=0
if grep -qE "CRITICAL|ParseError|AssertionError|Failed to initialize" "$LOG"; then
  echo "  ❌ 安装日志里有致命错误："; grep -E "CRITICAL|ParseError|AssertionError" "$LOG" | head -3
  bad=1
else
  echo "  ✅ 安装过程无致命错误（日志 ${LOG}）"
fi

echo "=== 关键模块是否 installed ==="
for m in edu_life edu_portal edu_brand edu_schedule edu_assess edu_public edu_zh; do
  st=$($DC psql -U odoo -d $DB -tAc "select state from ir_module_module where name='$m';" 2>/dev/null | tr -d " ")
  if [ "$st" = "installed" ]; then printf "  ✅ %-16s installed\n" "$m"; else printf "  ❌ %-16s %s\n" "$m" "${st:-缺失}"; bad=1; fi
done

echo "=== 关键数据（到堂打卡类型 —— 台账 P-01 关心的那条）==="
n=$($DC psql -U odoo -d $DB -tAc "select count(*) from edu_checkin_type where name like '%到堂%';" 2>/dev/null | tr -d " ")
if [ "${n:-0}" -ge 1 ]; then echo "  ✅ 到堂打卡类型在（$n 条）"; else echo "  ❌ 到堂打卡类型缺失"; bad=1; fi

echo "=== 清理 ==="
$DC psql -U odoo -d postgres -c "drop database if exists $DB with (force);" >/dev/null 2>&1 && echo "  已删除 $DB"

if [ $bad -eq 0 ]; then echo "结论：OK（全新库装得上，关键模块与关键数据齐）"; else echo "结论：FAIL（全新库这条路被弄断了）"; fi
exit $bad