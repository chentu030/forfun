import sys, re, csv, html
from collections import Counter
rows=[]
for path, mkt in ((sys.argv[1],'上市'),(sys.argv[2],'上櫃')):
    t=open(path,'rb').read().decode('cp950',errors='replace')
    sec=None
    for tr in re.findall(r'<tr>(.*?)</tr>', t, re.S|re.I):
        tds=[html.unescape(re.sub(r'<[^>]+>','',x)).strip() for x in re.findall(r'<td[^>]*>(.*?)</td>',tr,re.S|re.I)]
        if len(tds)==1: sec=tds[0]; continue
        if len(tds)<5 or sec!='股票': continue
        parts=re.split(r'[　 ]+',tds[0],1)
        if len(parts)<2: continue
        code,name=parts
        if not re.fullmatch(r'\d{4}',code): continue
        if tds[3]!=mkt: print('mkt mismatch',tds,file=sys.stderr)
        rows.append((code,name.strip(),mkt,tds[4]))
out=sys.argv[3]
with open(out,'w',encoding='utf-8',newline='') as f:
    w=csv.writer(f); w.writerow(['code','name','market','industry']); w.writerows(sorted(rows,key=lambda r:(r[2]!='上市',r[0])))
print(Counter(r[2] for r in rows))
for k,v in sorted(Counter((r[2],r[3]) for r in rows).items()): print(k,v)
print('dups',[c for c,n in Counter(r[0] for r in rows).items() if n>1])
