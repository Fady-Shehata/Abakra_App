import fitz
d = fitz.open('data/church_councils_clean_header.pdf')

AMAP = {'Ց':'أ','Ֆ':'ب','՚':'ج','՝':'د'}

def page_cells(pno):
    page = d[pno]
    dd = page.get_text("dict")
    nums = []   # (y, x, qnum)
    ans = []    # (y, x, letter)
    for b in dd["blocks"]:
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                t = s["text"].strip()
                x0,y0 = s["bbox"][0], s["bbox"][1]
                xc = (s["bbox"][0]+s["bbox"][2])/2
                yc = (s["bbox"][1]+s["bbox"][3])/2
                # pure digits (arabic-indic or ascii)
                digs = ''.join(ch for ch in t if ch.isdigit() or '\u0660'<=ch<='\u0669')
                if digs and all(ch.isdigit() or '\u0660'<=ch<='\u0669' or ch in '٠١٢٣٤٥٦٧٨٩' for ch in t):
                    # convert arabic-indic to ascii
                    val = int(''.join(str('٠١٢٣٤٥٦٧٨٩'.index(ch)) if ch in '٠١٢٣٤٥٦٧٨٩' else ch for ch in t))
                    nums.append((yc,xc,val))
                # answer letters: first char that is an armenian marker
                for ch in t:
                    if ch in AMAP:
                        ans.append((yc,xc,AMAP[ch]))
                        break
    return nums, ans

for pno in [34,35,36]:
    nums, ans = page_cells(pno)
    print(f"--- PAGE {pno+1}: {len(nums)} numbers, {len(ans)} answers ---")
    # For each answer, find the nearest number on the same row (yc within 8) to the RIGHT (higher x)
    result = []
    for (ay,ax,letter) in ans:
        cands = [(abs(ay-ny), nx-ax, nv) for (ny,nx,nv) in nums if abs(ay-ny)<8 and nx>ax]
        cands = [c for c in cands if c[1]>0]
        if cands:
            cands.sort(key=lambda c:(c[0], c[1]))
            result.append((cands[0][2], letter))
    result.sort()
    print(result)
