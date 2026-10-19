import csv,re,os,html
import os; base=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '')
rows=list(csv.DictReader(open(base+'master.csv',encoding='utf8')))
def clean(s):
    s=html.unescape(re.sub('<[^>]+>',' ',s)); return re.sub(r'\s+',' ',s).replace('\t',' ').strip()
def dj(c):
    p=base+f'biz_raw/dj/{c}.html'
    if not os.path.exists(p): return ''
    t=open(p,'rb').read().decode('big5hkscs','replace')
    m=re.search(r'>營收比重</td>\s*<td[^>]*>(.*?)</td>',t,re.S)
    return clean(m.group(1)) if m else ''
def yh(c):
    p=base+f'biz_raw/y/{c}.html'
    if not os.path.exists(p): return ''
    t=open(p,encoding='utf8',errors='replace').read()
    i=t.find('主要經營業務')
    if i<0: return ''
    s=t[i+6:i+6000]; j=s.find('配股資訊'); s=s[:j] if j>0 else s[:2000]
    s=clean(s)
    return '' if s in ('-','') else s[:300]
nr=nb=nm=0
with open(base+'biz.tsv.tmp','w',encoding='utf8') as f:
    f.write('code\tname\trevenue_mix\tbusiness\tsource\n')
    for r in rows:
        c=r['code']; m=dj(c); b=yh(c)
        src=[]
        if m: src.append('moneydj_zca'); nr+=1
        if b: src.append('yahoo_profile'); nb+=1
        if not src: src=['missing']; nm+=1
        f.write(f"{c}\t{r['name']}\t{m}\t{b}\t{'+'.join(src)}\n")
os.replace(base+'biz.tsv.tmp',base+'biz.tsv')
print(len(rows),'mix',nr,'biz',nb,'missing',nm)
