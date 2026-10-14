#!/usr/bin/env python3
"""双端截图 OCR 文本要素对照（验证关键文案成对出现）。"""
import subprocess
import sys
from pathlib import Path

SHOTS = Path(__file__).parent.parent / "shots"

KEYWORDS = {
    "my_home": ["Welcome", "Search anything", "Active courses",
                "Pending assignments", "Upcoming exams", "Attendance trend",
                "last 6 months", "Timetable", "Attendance", "GradeBook"],
    "timetable": ["时间表"],
    "attendance": ["出席率", "Present", "Absent"],
    "exam": ["考试", "Total Marks", "Percentage"],
}


def ocr(png):
    out = "/tmp/_ocr_tmp"
    subprocess.run(["tesseract", str(png), out, "-l", "eng+chi_sim",
                    "--psm", "3"], capture_output=True)
    try:
        return Path(out + ".txt").read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        return ""


def main(page=None):
    names = [page] if page else list(KEYWORDS)
    for name in names:
        kws = KEYWORDS.get(name, [])
        if not kws:
            continue
        row = {"target": SHOTS / "target" / f"{name}.png",
               "local": SHOTS / "local" / f"{name}.png"}
        texts = {side: ocr(p) for side, p in row.items()}
        print(f"== {name} ==")
        for kw in kws:
            t = kw.lower() in texts["target"].lower()
            l = kw.lower() in texts["local"].lower()
            mark = "✅" if (t and l) else ("🟡 仅原站" if t else "⚪ 两边都无")
            print(f"  {mark} {kw}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
