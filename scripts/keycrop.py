import fitz
d = fitz.open('data/church_councils_clean_header.pdf')
for i in [34,35,36]:  # pages 35,36,37
    page = d[i]
    r = page.rect
    pix = page.get_pixmap(dpi=300)
    pix.save(f'pages/key{i+1}_full.png')
# also split each into left/right halves via clip
for i in [34,35,36]:
    page = d[i]
    r = page.rect
    mid = (r.x0+r.x1)/2
    left = fitz.Rect(r.x0, r.y0, mid+20, r.y1)
    right = fitz.Rect(mid-20, r.y0, r.x1, r.y1)
    page.get_pixmap(dpi=300, clip=right).save(f'pages/key{i+1}_R.png')
    page.get_pixmap(dpi=300, clip=left).save(f'pages/key{i+1}_L.png')
print("done")
