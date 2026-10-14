#!/usr/bin/env python3
"""幻觉化守卫（v2-B2）。

--check  扫描 git 追踪文件，发现真实学院身份信息即退出码 1（接入推送前检查）。
--apply  将真实身份替换为幻觉占位（Sample Seminary / seminary.example）。

规则表维护在 LEAKS；新增敏感词请同步 config/server.local.md 的占位说明。
"""
import subprocess
import sys

LEAKS = [
    ("永约学坊", "示例神学院"),
    ("COVENANT REFORMED SEMINARY", "SAMPLE SEMINARY"),
    ("SCRTS", "SAMPLE"),
    ("edu.example.org", "seminary.example"),
    ("example.org", "example.org"),
    ("scrtsschool@gmail.com", "office@seminary.example"),
    ("203.0.113.10", "192.0.2.10"),
    ("203.0.113.9", "192.0.2.20"),
]


def tracked_files():
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    return [f for f in out.stdout.splitlines() if f]


def main():
    apply = "--apply" in sys.argv
    files = [f for f in tracked_files() if f.endswith(
        (".md", ".py", ".xml", ".csv", ".yml", ".json", ".html", ".txt",
         ".js", ".css", ".example"))]
    leaks = {}
    for f in files:
        try:
            s = open(f, encoding="utf-8").read()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        hits = [(real, ph) for real, ph in LEAKS if real in s]
        if hits:
            leaks[f] = hits
            if apply:
                for real, ph in hits:
                    s = s.replace(real, ph)
                open(f, "w", encoding="utf-8").write(s)

    if not apply:
        for f, hits in leaks.items():
            print(f"LEAK {f}: {[h[0] for h in hits]}")
        if leaks:
            print(f"\n{len(leaks)} 个文件存在真实身份泄露。"
                  "运行 `python3 scripts/hallucinate.py --apply` 修复。")
            sys.exit(1)
        print("✓ 无真实身份信息（幻觉化检查通过）。")
    else:
        print(f"✓ 已对 {len(leaks)} 个文件应用幻觉化替换。")


if __name__ == "__main__":
    main()
