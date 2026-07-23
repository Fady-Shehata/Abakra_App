import fitz
d = fitz.open('data/church_councils_clean_header.pdf')
page=d[34]
dd=page.get_text("dict")
spans=[]
for b in dd["blocks"]:
    for l in b.get("lines", []):
        for s in l.get("spans", []):
            spans.append((round(s["bbox"][1],1), round(s["bbox"][0],1), round(s["bbox"][2],1), s["text"]))
spans.sort()
# print spans in the first few rows (y 460-560 approx where Q1-3 are)
for y0,x0,x1,t in spans:
    if 455 < y0 < 560:
        print(f"y={y0} x0={x0} x1={x1} | {t!r}")
