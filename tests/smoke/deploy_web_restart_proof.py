#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_myedu.sh「升级 → 重启必须配对」自证的**离线探针**（2026-09-29）。

为什么需要它：这条自证是"没有它已经出过两次生产事故"的判据（库升了、盘上文件是新的、
活体 web 进程还是旧的），而它在脚本里靠 ssh + docker + date 三个外部读数说话 ——
没有探针就只能靠"手工去生产上试一次"，下次改脚本谁都不会再试。

做法：**完全不碰生产**。用 PATH 上的三个 shim（ssh / docker / date）模拟远端，
把 payload 里的 /tmp/upg* 重写进沙箱，然后真跑 scripts/deploy_myedu.sh --verify。

双向判据（4 条，缺一不可）：
  ① 绿：rc=0 且 StartedAt **晚于**升级完成时刻        → exit 0 且印「自证成立」
  ② 红：rc=0 但 StartedAt **不晚于**升级完成时刻      → exit 10 且印那句处置话术
  ③ 拒判：读不到标记文件（无法自证）                  → exit 10，且**不得**印那句处置话术
     （不知道就不能断言 —— 把"读不到"说成"升级成功但没重启"是伪造结论）
  ④ 升级本身失败：rc≠0                                → exit 10 且印「升级本身没成功」

用法：python3 tests/smoke/deploy_web_restart_proof.py
退出码：0 = 4 条全对 ｜ 1 = 有判据不成立 ｜ 2 = 环境不满足（找不到脚本/沙箱起不来）
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "deploy_myedu.sh"
WANT_MSG = "升级成功但 web 未重启，活体注册表仍是旧的，请执行 docker compose restart web"

FAKE_SSH = r"""#!/bin/bash
# 假 ssh：忽略选项与 host，把远端命令与 stdin（heredoc payload）都在沙箱里跑。
# /tmp/upg* 一律重写进沙箱 —— 探针不许碰真实 /tmp，更不许碰生产。
cmd=""
for a in "$@"; do cmd="$a"; done
payload=$(cat)
rewrite() { sed -e "s#/tmp/upg#$SANDBOX/upg#g" -e "s#/opt/edu-app#$SANDBOX#g"; }
if [ -n "$payload" ]; then
  printf '%s' "$payload" | rewrite | bash -c "$(printf '%s' "$cmd" | rewrite)"
else
  bash -c "$(printf '%s' "$cmd" | rewrite)"
fi
"""

FAKE_DOCKER = r"""#!/bin/bash
# 假 docker：只答自证要问的两件事（web 容器 id / StartedAt），其余按成功静默。
if [ "$1" = "compose" ] && [ "$2" = "ps" ]; then echo "fakecid0000"; exit 0; fi
if [ "$1" = "compose" ] && [ "$2" = "restart" ]; then echo "fake restart ok"; exit 0; fi
if [ "$1" = "inspect" ]; then cat "$SANDBOX/started_at" 2>/dev/null; exit 0; fi
exit 0
"""

FAKE_DATE = r"""#!/bin/bash
# 假 date：只接管自证里那句 date -u -d <docker ISO> +%s%N（macOS 的 date 不支持 -d），
# 其余原样交给真 date。
for a in "$@"; do
  if [ "$a" = "-d" ]; then cat "$SANDBOX/started_ns" 2>/dev/null; exit 0; fi
done
exec /bin/date "$@"
"""


def build_sandbox() -> Path:
    sb = Path(tempfile.mkdtemp(prefix="deploy_proof_"))
    (sb / "bin").mkdir()
    for name, body in (("ssh", FAKE_SSH), ("docker", FAKE_DOCKER), ("date", FAKE_DATE)):
        p = sb / "bin" / name
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
    return sb


def set_state(sb: Path, rc="0", done_ns=None, done_iso=None, started_ns=None, started_iso=None):
    for f in ("upg.exit", "upg.done", "started_at", "started_ns"):
        try:
            (sb / f).unlink()
        except FileNotFoundError:
            pass
    if rc is not None:
        (sb / "upg.exit").write_text(rc + "\n", encoding="utf-8")
    if done_ns is not None:
        (sb / "upg.done").write_text("%s %s\n" % (done_ns, done_iso), encoding="utf-8")
    if started_iso is not None:
        (sb / "started_at").write_text(started_iso + "\n", encoding="utf-8")
    if started_ns is not None:
        (sb / "started_ns").write_text(str(started_ns) + "\n", encoding="utf-8")


def run_verify(sb: Path):
    env = dict(os.environ)
    env["PATH"] = "%s:%s" % (sb / "bin", env.get("PATH", ""))
    env["SANDBOX"] = str(sb)
    p = subprocess.run(["bash", str(SCRIPT), "--verify"], cwd=str(REPO), env=env,
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


def main():
    if not SCRIPT.exists():
        print("SKIP-ENV：找不到 %s" % SCRIPT)
        return 2
    cases = []
    sb = build_sandbox()
    try:
        # ① 绿：升级完成 13:26:47 → web 13:27:05 起（差 18s，与 2026-09-29 那次生产的真实读数同量级）
        set_state(sb, rc="0", done_ns=1790688407404991482, done_iso="2026-09-29T13:26:47Z",
                  started_ns=1790688425199090882, started_iso="2026-09-29T13:27:05.199090882Z")
        rc, out = run_verify(sb)
        cases.append(("① 正常路径必须绿（rc=0 且 StartedAt 更晚）", rc == 0 and "自证成立" in out,
                      "exit=%d 自证成立=%s" % (rc, "自证成立" in out), out))

        # ② 红：升级完成时刻**晚于** web 启动时刻（= 升级成功但没重启）
        set_state(sb, rc="0", done_ns=1790688758320195000, done_iso="2026-09-29T13:32:38Z",
                  started_ns=1790688425199090882, started_iso="2026-09-29T13:27:05.199090882Z")
        rc, out = run_verify(sb)
        cases.append(("② 升级成功但 web 未重启：必须判红 + 印处置话术",
                      rc == 10 and WANT_MSG in out, "exit=%d 话术=%s" % (rc, WANT_MSG in out), out))

        # ③ 拒判：没有标记文件 ⇒ 红，但**不许**断言「升级成功但 web 未重启」
        set_state(sb, rc=None)
        rc, out = run_verify(sb)
        cases.append(("③ 读不到标记：必须拒判（红）且不冒充结论",
                      rc == 10 and "无法自证" in out and WANT_MSG not in out,
                      "exit=%d 无法自证=%s 未冒充=%s" % (rc, "无法自证" in out, WANT_MSG not in out), out))

        # ④ 升级本身就没成功
        set_state(sb, rc="1", done_ns=1790688407404991482, done_iso="2026-09-29T13:26:47Z",
                  started_ns=1790688425199090882, started_iso="2026-09-29T13:27:05.199090882Z")
        rc, out = run_verify(sb)
        cases.append(("④ 升级容器 rc≠0：必须判红且说明是升级失败",
                      rc == 10 and "升级本身没成功" in out, "exit=%d 说明=%s" % (rc, "升级本身没成功" in out), out))
    finally:
        shutil.rmtree(sb, ignore_errors=True)

    bad = 0
    for item in cases:
        label, ok, detail = item[0], item[1], item[2]
        print("%s %s（%s）" % ("PASS" if ok else "FAIL", label, detail))
        if not ok and len(item) > 3:
            print("  --- 实际输出（前 12 行）---")
            for ln in item[3].splitlines()[:12]:
                print("  | " + ln)
        bad += 0 if ok else 1
    print("== 结论：%d/%d 条判据成立 ==" % (len(cases) - bad, len(cases)))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
