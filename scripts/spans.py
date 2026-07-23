import fitz
d = fitz.open('data/church_councils_clean_header.pdf')
page = d[0]
dd = page.get_text("dict")
spans=[]
for b in dd["blocks"]:
    for l in b.get("lines", []):
        for s in l.get("spans", []):
            spans.append(s)
# sort by reading position: top then right-to-left (x descending)
for s in spans[:60]:
    t=s["text"]
    ar=sum(1 for c in t if '\u0600'<=c<='\u06ff')
    sy=sum(1 for c in t if '\u1400'<=c<='\u167f')
    x0,y0=s["bbox"][0],s["bbox"][1]
    print(f"y={y0:6.1f} x={x0:6.1f} ar={ar:2d} sy={sy:2d} | {t!r}")
