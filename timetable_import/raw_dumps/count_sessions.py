import zipfile, re
from xml.etree import ElementTree as ET
path = "/Users/qwe/Documents/文件大总管/20-工作/公司事务/课程表/2+6排课表.xlsx"
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
z = zipfile.ZipFile(path)
sst=[]
root=ET.fromstring(z.read("xl/sharedStrings.xml"))
for si in root.findall(M+"si"):
    sst.append("".join(t.text or "" for t in si.iter(M+"t")))
def cv(c):
    v=c.find(M+"v")
    if v is None or v.text is None: return ""
    return sst[int(v.text)] if c.get("t")=="s" else v.text

def count(sheet,label):
    root=ET.fromstring(z.read(sheet))
    n=0; items={}
    for row in root.iter(M+"row"):
        for c in row.findall(M+"c"):
            v=cv(c).strip()
            if not v: continue
            # skip non-L cells like headers/星期
            for seg in v.split("\n"):
                seg=seg.strip()
                m=re.match(r"^(L\d+|师生互动|改革宗|救恩论|专文写作|福音|基础信仰|使徒行传C?)",seg)
                # 判定是课条目：包含 (数字点/数字点）或 班标注 或 师生互动/讲座/考试
                if re.search(r"点",seg) or re.search(r"A\d|B\d|考试|师生互动|讲座",seg):
                    if re.match(r"^L?\d",seg) or "互动" in seg or "讲座" in seg or seg.startswith("救恩论"):
                        items[seg.split("(")[0].strip()]=items.get(seg.split("(")[0].strip(),0)+1
                        n+=1
    print(f"{label}: 课次条目={n} 课程分布={ {k:v for k,v in sorted(items.items())} }")

count("xl/worksheets/sheet1.xml","sheet1-家教2")
count("xl/worksheets/sheet2.xml","sheet2-文26下")
count("xl/worksheets/sheet3.xml","sheet3-A神学部")
count("xl/worksheets/sheet4.xml","sheet4-B12")
