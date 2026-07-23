import fitz
d = fitz.open('data/church_councils_clean_header.pdf')
AMAP = {'Ց':'أ','Ֆ':'ب','՚':'ج','՝':'د'}

def collect(pno):
    page = d[pno]
    dd = page.get_text("dict")
    nums=[]; ans=[]
    for b in dd["blocks"]:
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                t=s["text"].strip()
                xc=(s["bbox"][0]+s["bbox"][2])/2
                yc=(s["bbox"][1]+s["bbox"][3])/2
                if t and all(ch in '٠١٢٣٤٥٦٧٨٩' for ch in t):
                    val=int(''.join(str('٠١٢٣٤٥٦٧٨٩'.index(ch)) for ch in t))
                    nums.append((yc,xc,val))
                letter=None
                for ch in t:
                    if ch in AMAP:
                        letter=AMAP[ch]; break
                if letter:
                    syl=''.join(ch for ch in t if '\u1400'<=ch<='\u167f')
                    ans.append((yc,xc,letter,syl))
    return nums,ans

rows=[]
for pno in [34,35,36]:
    nums,ans=collect(pno)
    for (ay,ax,letter,syl) in ans:
        cn=[(abs(ay-ny),nx-ax,nv) for (ny,nx,nv) in nums if abs(ay-ny)<8 and nx>ax]
        cn.sort()
        q=cn[0][2] if cn else None
        rows.append((q,letter,syl))
rows=[r for r in rows if r[0]]
rows.sort()
known={1:'متوسط',2:'سهل',3:'متوسط',6:'سهل',7:'صعب',8:'سهل',10:'صعب',19:'سهل'}
from collections import defaultdict
m=defaultdict(set)
for q,l,g in rows:
    if q in known:
        m[g].add(known[q])
print("glyph -> level:")
for g,s in m.items():
    print(repr(g), s)
from collections import Counter
print("all glyph counts:", Counter(g for q,l,g in rows).most_common())
