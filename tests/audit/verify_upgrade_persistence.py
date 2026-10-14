#/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T7 升级重放驻留测试：收口值在「升级其它模块」后是否被重放。

背景（实测发现，2026-09-17）：
- edu_nav 用 <record id="<他模块>.<xmlid>"> 覆盖菜单；但被引用模块自己的
  <menuitem> 每次 -u 都会把 active/groups 写回声明值。
- 实测：-u edu_life 后不变；-u edu_portal 后 5 棵根菜单复活
  （542 邀请码 / 543 日常管理 / 576 在线课程 / 597 行政评估 / 606 老账号补挂身份）。

用法（真实执行模块升级，只在本机 edu19 上跑）：
  python3 tests/audit/verify_upgrade_persistence.py                       # 默认 batch
  python3 tests/audit/verify_upgrade_persistence.py --modules edu_life,edu_portal --restore

⚠ 安全纪律（2026-09-17 队长裁定，务必遵守）：
  · **必须用 `--batch`（一次性 `-u a,b,c`，容器只重启一次）**；
  · **禁止逐模块串行升级**：每次 `-u` 都会"升级 + 重启 web 容器"，实测 4–7 秒一个、
    容器 10–45 秒重启一次，会把同期冒烟/迁移测试搅黄（t9 冒烟跑不出有效样本）；
  · 只在**队长指定的空闲窗口**内跑，跑完把窗口时间写进报告；
  · `--serial` 仅供单模块调试，默认拒绝（需显式 `--i-know` 才执行）；
  · **默认即 `--batch`**（`--no-batch` 才能关掉），且 `--restore` 改为
    **"仅当快照比对发现 REPLAY 时才复原"** ⇒ 对不涉 edu_nav 覆盖项的模块
    （如 mail/account/contacts）连"复原"这一次重启也省掉。

判定：升级后各角色 B 根菜单集合与升级前一致 => PASS；否则 REPLAY 并列出复活根。

⚠ 判定口径（2026-09-28 修「假 PASS」）：**「升级是否真正发生」是一道独立的门**。
  safe_upgrade.sh 只有 **rc=0** 才算升级真正跑了（其契约：0 成功；3 等锁超时；
  4 挂载失步；5 退出码 0 但输出含失败特征「很可能没真正升级」；6 前置静态门禁拒绝；
  其它 = odoo 自身退出码）。
  旧实现只比快照、**不读 rc** —— 于是「没升级」时快照自然相同 ⇒ 结论行印
  「全部 PASS（收口值未被重放）」，是**假 PASS**（且上一行还写着 `[exit] 6`）。
  现在 rc≠0（或日志里有 Traceback）一律 **UNKNOWN＝拒判**，绝不判 PASS：
  没升级 ⇒ 既没证据说「重放」、也没证据说「不重放」，本轮读数**无效**。

退出码（本脚本）：0 = 全部 PASS ｜ 1 = 有 REPLAY（真判据命中）｜
                2 = 有 UNKNOWN（升级未真正发生 / 读数无效）｜ 3 = 参数被拒。
用法：
  python3 tests/audit/verify_upgrade_persistence.py --selftest    # 只证判定量具（离线，不连站点/不升级）
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import verify_consolidation as V
import audit_lib as A

REPO = HERE.parent.parent

# ---------------------------------------------------------------- 判定量具（纯函数，可离线自证）
VERDICT_PASS = "PASS"          # 升级确实发生 + 快照未变
VERDICT_REPLAY = "REPLAY"      # 升级确实发生 + 快照变了（真判据）
VERDICT_UNKNOWN = "UNKNOWN"    # 升级**没有真正发生**（rc≠0 / Traceback）⇒ 拒判

# safe_upgrade.sh 的退出码契约（scripts/safe_upgrade.sh 头部逐条对齐）
UPGRADE_RC_MEANING = {
    0: "成功（升级真正发生）",
    3: "等待升级锁超时 ⇒ 升级未发生",
    4: "挂载失步未修复 ⇒ 升级未发生",
    5: "退出码 0 但输出含失败特征（很可能没真正升级）⇒ 升级未发生",
    6: "前置静态门禁拒绝 ⇒ 升级未发生",
}
SELFTEST_CASES = 12           # 断言条数（selftest 实际计数比对；漂移即 FAIL）

def rc_meaning(rc):
    return UPGRADE_RC_MEANING.get(rc, "odoo/子进程退出码 %s（非 0 ⇒ 升级不可信）" % rc)


def verdict_for(rc, traceback_seen, roles_same):
    """升级有效性 × 快照比对 → 判定。**rc 先判**：没升级就不许看快照（那是「没重放」的假象）。"""
    if rc != 0 or traceback_seen:
        return VERDICT_UNKNOWN
    return VERDICT_PASS if roles_same else VERDICT_REPLAY


def exit_code_for(verdicts):
    """0 全 PASS ｜ 1 有 REPLAY（真判据命中，最该被处理）｜ 2 有 UNKNOWN（升级未发生 ⇒ 读数无效）。

    两个同时存在时给 1：REPLAY 是**已证实的**回归，UNKNOWN 只是「这一轮没量到」——
    都不能当 GREEN，但退出码要先报那个能立刻行动的证据。
    """
    if any(v == VERDICT_REPLAY for v in verdicts):
        return 1
    if any(v == VERDICT_UNKNOWN for v in verdicts):
        return 2
    return 0


def snapshot(tag):
    snap = V.menu_snapshot()
    A.save(str(HERE / "out" / ("persistence_" + tag + ".json")), snap)
    return snap


def upgrade(modules):
    cmd = ["bash", str(REPO / "scripts" / "safe_upgrade.sh"), "-u", modules]
    print("[run]", " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    log = HERE / "out" / ("upgrade_" + modules.replace(",", "_") + ".log")
    log.write_text(p.stdout + p.stderr, encoding="utf-8")
    tb = "Traceback" in (p.stdout + p.stderr)
    print("[exit] %s  traceback=%s  log=%s" % (p.returncode, tb, log.name))
    print("       ↑ 升级有效性：%s" % rc_meaning(p.returncode)
          + ("；日志含 Traceback（同样按未真正升级处理）" if tb else ""))
    return p.returncode, tb


def diff(pre, post):
    out = {"db": {}, "roles": {}}
    for k in ("A_root_menus_db", "A_total_menus_db", "A_active_menus_db"):
        out["db"][k] = {"before": pre[k], "after": post[k],
                        "same": pre[k] == post[k]}
    for role in pre["roles"]:
        a, b = pre["roles"][role], post["roles"][role]
        ra, rb = a.get("roots") or [], b.get("roots") or []
        names = dict(zip(b.get("roots") or [], b.get("root_names") or []))
        out["roles"][role] = {
            "before": a.get("B_root_count"), "after": b.get("B_root_count"),
            "same": ra == rb,
            "added": [[i, names.get(i)] for i in rb if i not in ra],
            "removed": [i for i in ra if i not in rb],
        }
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    # 2026-09-29：默认名单里的 edu_eval 已卸载删除（模块不存在，-u 会直接报错）
    # ⇒ 只留 F1 名单里仍然在册的两个。要复验"菜单收口是否被重放"，用这两个足够；
    # 需要时仍可显式传 --modules。
    ap.add_argument("--modules", default="edu_life,edu_portal")
    ap.add_argument("--batch", action="store_true", default=True,
                    help="默认：一次性 -u a,b,c（容器只重启一次）")
    ap.add_argument("--no-batch", dest="batch", action="store_false",
                    help="关闭批量（等价逐模块；须配 --serial --i-know）")
    ap.add_argument("--serial", action="store_true",
                    help="逐模块串行（默认拒绝；会把 web 容器反复重启）")
    ap.add_argument("--i-know", action="store_true",
                    help="确认知情：串行升级会反复重启容器")
    ap.add_argument("--restore", action="store_true",
                    help="仅当快照比对发现 REPLAY 时，才 -u edu_nav 复原"
                         "（对不涉 edu_nav 覆盖项的模块可省掉一次容器重启）")
    args = ap.parse_args()

    mods = [m.strip() for m in args.modules.split(",") if m.strip()]
    if args.serial and not args.i_know:
        print(
            "[拒绝] --serial 会逐模块重启 web 容器（实测 4–7 秒一个），\n"
            "        会搅黄同期冒烟/迁移测试。请改用 --batch，\n"
            "        或确知后果时加 --i-know。", file=sys.stderr)
        return 3      # 参数被拒（契约见文件头「退出码」）
    # 默认已是 batch；关掉批量即等于逐模块 ⇒ 同样必须显式知情（否则静默串行）
    if not args.batch and not args.i_know:
        print(
            "[拒绝] --no-batch 等价逐模块串行升级，会反复重启 web 容器。\n"
            "        默认用 --batch；确知后果时加 --i-know 放行。", file=sys.stderr)
        return 3      # 参数被拒（契约见文件头「退出码」）
    pre = snapshot("pre")
    print("升级前 B:", {k: v.get("B_root_count") for k, v in pre["roles"].items()})
    results = {}
    if args.batch:
        rc, tb = upgrade(",".join(mods))
        post = snapshot("post_batch")
        d = diff(pre, post)
        same = all(r["same"] for r in d["roles"].values())
        d["exit_code"], d["traceback"] = rc, tb
        d["modules"] = mods
        # ⚠ 先判「升级有没有真正发生」，再看快照：rc≠0 ⇒ 快照相同是「没升级」的必然结果，
        #   不是「没重放」的证据（旧实现漏了这一步，会印假 PASS）。
        d["upgrade_effective"] = (rc == 0 and not tb)
        d["verdict"] = verdict_for(rc, tb, same)
        if d["verdict"] == VERDICT_UNKNOWN:
            d["verdict_reason"] = rc_meaning(rc) + ("；日志含 Traceback" if tb else "")
        results["BATCH:" + ",".join(mods)] = d
        print("  -> BATCH %-40s %s  B=%s" % (",".join(mods), d["verdict"],
              {k: v["after"] for k, v in d["roles"].items()}))
        pre = post
        mod_iter = []
    else:
        mod_iter = mods
    for mod in mod_iter:
        rc, tb = upgrade(mod)
        post = snapshot("post_" + mod)
        d = diff(pre, post)
        same = all(r["same"] for r in d["roles"].values())
        d["exit_code"], d["traceback"] = rc, tb
        d["upgrade_effective"] = (rc == 0 and not tb)
        d["verdict"] = verdict_for(rc, tb, same)
        if d["verdict"] == VERDICT_UNKNOWN:
            d["verdict_reason"] = rc_meaning(rc) + ("；日志含 Traceback" if tb else "")
        results[mod] = d
        print("  -> %-12s %s  B=%s" % (mod, d["verdict"],
              {k: v["after"] for k, v in d["roles"].items()}))
        pre = post
    replay = [m for m, d in results.items() if d.get("verdict") == "REPLAY"]
    if args.restore:
        if not replay:
            # 队长裁定②：只为"发现被重放"才付一次容器重启的代价
            print("  无需复原：本次快照比对全部 PASS（未发现 REPLAY）")
            results["_restore_edu_nav"] = {"skipped": True,
                                           "why": "无 REPLAY，按需复原跳过"}
        else:
            print("  检测到 REPLAY（%s）⇒ 执行 -u edu_nav 复原" % ",".join(replay))
            rc, tb = upgrade("edu_nav")
            post = snapshot("post_restore")
            print("  复原后 B:", {k: v.get("B_root_count")
                                  for k, v in post["roles"].items()})
            results["_restore_edu_nav"] = {
                "exit_code": rc, "traceback": tb,
                "B": {k: v.get("B_root_count") for k, v in post["roles"].items()}}
    A.save(str(HERE / "out" / "upgrade_persistence_result.json"),
           {"modules": args.modules, "results": results})
    # 结论行**只读判定值**（旧实现不读 [exit] ⇒ 未升级也印 PASS）。
    verdicts = {m: d["verdict"] for m, d in results.items() if d.get("verdict")}
    bad = [m for m, v in verdicts.items() if v == VERDICT_REPLAY]
    unk = [m for m, v in verdicts.items() if v == VERDICT_UNKNOWN]
    if bad:
        print("== 结论: 以下模块升级后重放了收口值: " + ",".join(bad))
    if unk:
        print("== 结论: **拒判（UNKNOWN）** —— 下列升级未真正发生，本轮读数无效，"
              "既不判 PASS 也不判 REPLAY：")
        for m in unk:
            print("     %-42s %s" % (m, (results[m].get("verdict_reason") or "rc≠0")))
    if not bad and not unk:
        print("== 结论: 全部 PASS（升级确实发生，且收口值未被重放）")
    return exit_code_for(list(verdicts.values()))


def selftest():
    """只证判定量具：rc / Traceback / 快照三输入 → 判定 + 退出码（离线，不连站点、不升级）。"""
    ok, emitted = True, 0

    def case(label, got, want):
        nonlocal ok, emitted
        good = (got == want)
        ok = ok and good
        emitted += 1
        print("  %s %-46s 期望 %s 实际 %s" % ("PASS" if good else "FAIL", label, want, got))

    cases = [
        # rc=0（升级真正发生）+ 快照不变 ⇒ PASS
        ("rc0_same_is_PASS", verdict_for(0, False, True), VERDICT_PASS),
        # rc=0 + 快照变了 ⇒ REPLAY（真判据仍在）
        ("rc0_diff_is_REPLAY", verdict_for(0, False, False), VERDICT_REPLAY),
        # ⚠ 回归锁：本次要修的假 PASS 输入 —— rc=6（前置门禁拒绝，没升级）+ 快照相同
        ("rc6_same_NOT_PASS", verdict_for(6, False, True), VERDICT_UNKNOWN),
        ("rc6_diff_is_UNKNOWN", verdict_for(6, False, False), VERDICT_UNKNOWN),
        ("rc3_lock_timeout_is_UNKNOWN", verdict_for(3, False, True), VERDICT_UNKNOWN),
        ("rc4_mount_stale_is_UNKNOWN", verdict_for(4, False, True), VERDICT_UNKNOWN),
        ("rc5_failure_feature_is_UNKNOWN", verdict_for(5, False, True), VERDICT_UNKNOWN),
        ("rc1_odoo_exit_is_UNKNOWN", verdict_for(1, False, True), VERDICT_UNKNOWN),
        ("traceback_is_UNKNOWN", verdict_for(0, True, True), VERDICT_UNKNOWN),
        # 退出码：未升级必须非 0（门禁消费方据此判红）
        ("exit_UNKNOWN_is_2", exit_code_for([VERDICT_UNKNOWN]), 2),
        ("exit_REPLAY_is_1", exit_code_for([VERDICT_REPLAY]), 1),
        ("exit_all_PASS_is_0", exit_code_for([VERDICT_PASS, VERDICT_PASS]), 0),
    ]
    for label, got, want in cases:
        case(label, got, want)
    drift = (emitted != SELFTEST_CASES)
    ok = ok and not drift
    print("  %s %-46s 实际 %d / 声明 %d%s"
          % ("PASS" if not drift else "FAIL", "selftest_cases", emitted, SELFTEST_CASES,
             "" if not drift else "（漂移：请同步 SELFTEST_CASES）"))
    print("== 自证 %s ==" % ("通过" if ok else "不通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
