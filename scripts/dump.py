import fitz
d = fitz.open('data/church_councils_clean_header.pdf')
out = []
for i in range(d.page_count):
    out.append(f"===== PAGE {i+1} =====")
    out.append(d[i].get_text())
open('data/raw_dump.txt','w',encoding='utf-8').write("\n".join(out))
print("done", d.page_count)
