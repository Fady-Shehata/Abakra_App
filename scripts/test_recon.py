import fitz, unicodedata
d = fitz.open('data/church_councils_clean_header.pdf')

def clean(txt):
    out=[]
    for c in txt:
        o=ord(c)
        if 0x1400<=o<=0x167f:      # Canadian syllabics (garbage)
            continue
        if 0x0530<=o<=0x058f:      # Armenian (used as bullets) -> keep marker
            out.append(c)
            continue
        out.append(c)
    return ''.join(out)

# Test on page 1: process line by line, reverse arabic runs
page = d[0]
for line in page.get_text().split('\n'):
    c = clean(line)
    # reverse the whole line to get logical order
    print(repr(c[::-1]))
