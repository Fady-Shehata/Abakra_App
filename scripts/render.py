import fitz, os
d = fitz.open('data/church_councils_clean_header.pdf')
os.makedirs('pages', exist_ok=True)
for i in range(d.page_count):
    pix = d[i].get_pixmap(dpi=170)
    pix.save(f'pages/p{i+1:02d}.png')
print("rendered", d.page_count, "pages")
