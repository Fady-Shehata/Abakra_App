import fitz
d = fitz.open('data/church_councils_clean_header.pdf')
AMAP = {'Ց':'أ','Ֆ':'ب','՚':'ج','՝':'د'}

def collect(pno):
    page = d[pno]
    dd = page.get_text("dict")
    nums=[]; ans=[]; lvls=[]
    for b in dd["blocks"]:
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                t=s["text"].strip()
                xc=(s["bbox"][0]+s["bbox"][2])/2
                yc=(s["bbox"][1]+s["bbox"][3])/2
                if t and all(ch in '٠١٢٣٤٥٦٧٨٩' for ch in t):
                    val=int(''.join(str('٠١٢٣٤٥٦٧٨٩'.index(ch)) for ch in t))
                    nums.append((yc,xc,val))
                for ch in t:
                    if ch in AMAP:
                        ans.append((yc,xc,AMAP[ch])); break
                syl=[ch for ch in t if '\u1400'<=ch<='\u167f']
                if syl and len(t)<=8:
                    lvls.append((yc,xc,''.join(syl)))
    return nums,ans,lvls

# Gather all level glyph strings and their frequency to map
from collections import Counter
allrows=[]
for pno in [34,35,36]:
    nums,ans,lvls=collect(pno)
    for (ay,ax,letter) in ans:
        # nearest number to the right, same row
        cn=[(abs(ay-ny),nx-ax,nv) for (ny,nx,nv) in nums if abs(ay-ny)<8 and nx>ax]
        cn.sort()
        q=cn[0][2] if cn else None
        # nearest level glyph to the LEFT, same row
        cl=[(abs(ay-ly),ax-lx,g) for (ly,lx,g) in lvls if abs(ay-ly)<8 and lx<ax]
        cl.sort()
        g=cl[0][2] if cl else None
        allrows.append((q,letter,g))
cnt=Counter(g for (q,l,g) in allrows if g)
print("distinct level glyphs (top):")
for g,c in cnt.most_common(10):
    print(repr(g), c)
