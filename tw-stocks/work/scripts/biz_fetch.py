import csv,subprocess,os,time,random,sys,concurrent.futures as cf
import os; base=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '')
rows=list(csv.DictReader(open(base+'master.csv',encoding='utf8')))
DJ=['https://fubon-ebrokerdj.fbs.com.tw','https://concords.moneydj.com']
def curl(url,p,minsize):
    for a in range(3):
        r=subprocess.run(['curl','-sS','-m','40','-A','Mozilla/5.0 (Windows NT 10.0; Win64; x64)','-o',p,'-w','%{http_code}',url],capture_output=True,text=True)
        if r.stdout=='200' and os.path.exists(p) and os.path.getsize(p)>=minsize: return True
        time.sleep(2+3*a)
    return False
def get(r):
    c=r['code']; ok1=ok2=True
    p=base+f'biz_raw/dj/{c}.html'
    if not (os.path.exists(p) and os.path.getsize(p)>5000):
        ok1=False
        for h in ([DJ[0],DJ[1]] if random.random()<.5 else [DJ[1],DJ[0]]):
            if curl(f'{h}/z/zc/zca/zca_{c}.djhtm',p,5000): ok1=True;break
        time.sleep(0.3)
    sfx='TW' if r['market']=='上市' else 'TWO'
    p=base+f'biz_raw/y/{c}.html'
    if not (os.path.exists(p) and os.path.getsize(p)>10000):
        ok2=curl(f'https://tw.stock.yahoo.com/quote/{c}.{sfx}/profile',p,10000)
        time.sleep(0.3)
    return c,ok1,ok2
n=0
with cf.ThreadPoolExecutor(5) as ex:
    for c,a,b in ex.map(get,rows):
        n+=1
        if not(a and b): print('FAIL',c,a,b,flush=True)
        if n%200==0: print(n,flush=True)
