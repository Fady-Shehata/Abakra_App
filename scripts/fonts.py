import fitz
d = fitz.open('data/church_councils_clean_header.pdf')
fonts = {}
for i in range(d.page_count):
    dd = d[i].get_text("dict")
    for b in dd["blocks"]:
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                f = s["font"]
                txt = s["text"]
                # classify chars
                arab = sum(1 for c in txt if '\u0600' <= c <= '\u06ff')
                syl = sum(1 for c in txt if '\u1400' <= c <= '\u167f')
                fonts.setdefault(f, [0,0,0])
                fonts[f][0]+=1
                fonts[f][1]+=arab
                fonts[f][2]+=syl
print("FONT | spans | arabicChars | syllabicChars")
for f,(n,a,s) in fonts.items():
    print(f, n, a, s)
