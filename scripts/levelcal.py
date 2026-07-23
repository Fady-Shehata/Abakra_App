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
                if syl:
                    lvls.append((yc,xc,''.join(syl)))
    return nums,ans,lvls

rows=[]
for pno in [34,35,36]:
    nums,ans,lvls=collect(pno)
    for (ay,ax,letter) in ans:
        cn=[(abs(ay-ny),nx-ax,nv) for (ny,nx,nv) in nums if abs(ay-ny)<8 and nx>ax]
        cn.sort()
        q=cn[0][2] if cn else None
        cl=[(abs(ay-ly),ax-lx,g) for (ly,lx,g) in lvls if abs(ay-ly)<8 and lx<ax]
        cl.sort()
        g=cl[0][2] if cl else None
        rows.append((q,letter,g))
rows=[r for r in rows if r[0]]
rows.sort()
# calibrate with known image levels for Q1-24
known={1:'متوسط',2:'سهل',3:'متوسط',4:'متوسط',5:'متوسط',6:'سهل',7:'صعب',8:'سهل',
9:'سهل',10:'صعب',11:'صعب',12:'متوسط',13:'صعب',14:'صعب',15:'متوسط',16:'متوسط',
17:'صعب',18:'متوسط',19:'سهل',20:'متوسط',21:'سهل',22:'صعب',23:'متوسط',24:'سهل'}
d_map={}
for q,l,g in rows:
    if q in known and g:
        d_map.setdefault(g,set()).add(known[q])
print("glyph -> known levels:")
for g,s in d_map.items():
    print(repr(g), s)
