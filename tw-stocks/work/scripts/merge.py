import csv, re, sys, collections, os, ast

S = sys.argv[1]  # scratchpad dir
OUT = sys.argv[2]  # output dir

master = {r['code']: r for r in csv.DictReader(open(f'{S}/master.csv', encoding='utf-8'))}
biz = {r['code']: r for r in csv.DictReader(open(f'{S}/biz.tsv', encoding='utf-8'), delimiter='\t')}

# ---------- categories ----------
CAT_RENAME = {
    '網通/光通訊元件': '光通訊/光通訊元件與CPO',
    '半導體/矽光子與CPO': '光通訊/光通訊元件與CPO',
}

def norm_cat(c):
    c = re.sub(r'（[^）]*）', '', c).strip()
    return CAT_RENAME.get(c, c)

# per-stock research (revenue-mix based): primary category, business, themes
per = {}
for f in sorted(os.listdir(f'{S}/biz_out')):
    for r in csv.DictReader(open(f'{S}/biz_out/{f}', encoding='utf-8')):
        code = r['code'].strip()
        assert code in master and code not in per, (f, code)
        per[code] = r
assert set(per) == set(master), set(master) ^ set(per)

# earlier slice classification (web-researched): alternate category
alt = {}
for f in sorted(os.listdir(f'{S}/out')):
    for r in csv.DictReader(open(f'{S}/out/{f}', encoding='utf-8')):
        alt[r['code'].strip()] = norm_cat(r['category'])

prim = {c: norm_cat(per[c]['primary_category']) for c in master}
second = {c: alt[c] for c in master if c in alt and alt[c] != prim[c]}

# ---------- themes ----------
THEME_ALIAS = {
    'HBM/記憶體漲價': '記憶體/HBM',
    '記憶體': '記憶體/HBM',
    'ABF載板/玻纖布': 'ABF載板/高階PCB/玻纖布',
    'ABF載板/高階PCB': 'ABF載板/高階PCB/玻纖布',
    '銀髮長照': '長照/高齡化',
    '核能/重電': None,  # covered by 重電/電網強韌 + 電線電纜
    'AI ASIC/IP矽智財': 'AI ASIC/IP',
    '2奈米/台積電先進製程供應鏈': '2奈米/先進製程供應鏈',
    '台積電海外設廠受惠股': '台積電海外設廠',
    '輝達AI伺服器': '輝達AI伺服器(GB300/Rubin)',
    '光通訊': '光通訊模組(800G/1.6T)',
}
THEME_DROP = {('人形機器人', '4562')}  # 穎漢: bending machines, QA found no robot link
THEME_GROUP = ast.literal_eval(re.search(r'^THEME_GROUP = (\[.*?\n\])\n', open(f'{S}/scripts/theme_group.py', encoding='utf-8').read(), re.S | re.M).group(1))
ROLE_RANK = {'龍頭': 0, '母公司': 0, '核心': 1, '子公司': 1, '相關': 2, '轉投資': 2, '': 3}
grouped = [t for _, ts in THEME_GROUP for t in ts]

# theme -> code -> {'role','note','list','biz','mkt'}
themes = collections.OrderedDict((t, {}) for t in grouped)
groups = collections.OrderedDict()

def entry(d, code):
    return d.setdefault(code, {'role': '', 'note': '', 'list': False, 'biz': False, 'mkt': False})

for f in sorted(os.listdir(f'{S}/themes')):
    if not re.match(r'T\d\.csv$', f):
        continue
    for r in csv.DictReader(open(f'{S}/themes/{f}', encoding='utf-8')):
        t = THEME_ALIAS.get(r['theme'].strip(), r['theme'].strip())
        code = r['code'].strip()
        if t is None or (t, code) in THEME_DROP:
            continue
        assert code in master, (f, code)
        if t.startswith('集團/'):
            d = groups.setdefault(t.split('/', 1)[1], {})
        else:
            assert t in themes, t
            d = themes[t]
        e = entry(d, code)
        e['list'] = True
        role, note = r['role'].strip(), r['note'].strip()
        if ROLE_RANK.get(role, 3) < ROLE_RANK.get(e['role'], 3):
            e['role'] = role
        if len(note) > len(e['note']):
            e['note'] = note

for code, r in per.items():
    for raw in r['themes'].split(';'):
        raw = raw.strip()
        if not raw:
            continue
        m = re.match(r'^(.*?)【(業務|市場)】$', raw)
        assert m, (code, raw)
        t = THEME_ALIAS.get(m.group(1), m.group(1))
        if t is None or (t, code) in THEME_DROP:
            continue
        assert t in themes, (code, t)
        e = entry(themes[t], code)
        e['biz' if m.group(2) == '業務' else 'mkt'] = True

def evidence(e):
    parts = []
    if e['list']:
        parts.append('網路名單')
    if e['biz']:
        parts.append('有營收')
    elif e['mkt'] and not e['list']:
        parts.append('市場題材')
    return '+'.join(parts)

def strength(e):  # lower = stronger; used for sorting
    if e['list'] and e['biz']:
        return 0
    if e['list']:
        return 1
    if e['biz']:
        return 2
    return 3

stock_themes = collections.defaultdict(list)
for t, d in themes.items():
    for code in d:
        stock_themes[code].append(t)
stock_groups = collections.defaultdict(list)
for g, d in groups.items():
    for code in d:
        stock_groups[code].append(g)

# ---------- outputs ----------
os.makedirs(OUT, exist_ok=True)

def mix(code):
    return re.sub(r'\s+', ' ', biz.get(code, {}).get('revenue_mix', '')).strip()

with open(f'{OUT}/台股分類總表.csv', 'w', encoding='utf-8-sig', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['代號', '名稱', '市場', '官方產業別', '大類', '細類', '次要分類', '題材', '其他標籤', '集團',
                '主要業務', '營收比重(MoneyDJ)', '信心度'])
    for code in sorted(master, key=lambda c: (prim[c], c)):
        m, p = master[code], per[code]
        big, _, small = prim[code].partition('/')
        w.writerow([code, m['name'], m['market'], m['industry'], big, small, second.get(code, ''),
                    '、'.join(stock_themes.get(code, [])), p['extra_tags'].replace(';', '、'),
                    '、'.join(stock_groups.get(code, [])), p['main_business'], mix(code), p['confidence']])

order = lambda d: sorted(d, key=lambda c: (strength(d[c]), ROLE_RANK.get(d[c]['role'], 3), c))
with open(f'{OUT}/題材成分股.csv', 'w', encoding='utf-8-sig', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['題材大類', '題材', '代號', '名稱', '市場', '依據', '角色', '說明'])
    for g, ts in THEME_GROUP:
        for t in ts:
            d = themes[t]
            for code in order(d):
                e = d[code]
                w.writerow([g, t, code, master[code]['name'], master[code]['market'], evidence(e), e['role'],
                            e['note'] or per[code]['main_business']])
    for g, d in groups.items():
        for code in order(d):
            e = d[code]
            w.writerow(['集團股', g, code, master[code]['name'], master[code]['market'], '網路名單', e['role'], e['note']])

# markdown
cats = collections.defaultdict(list)
for code, c in prim.items():
    cats[c].append(code)
bigs = collections.OrderedDict()
for c in sorted(cats):
    bigs.setdefault(c.split('/')[0], []).append(c)
n_tse = sum(m['market'] == '上市' for m in master.values())
mark = {0: '★', 1: '●', 2: '○', 3: '△'}
L = ['# 台股上市櫃細分類與題材股', '',
     f'資料日期：2026-10-19　｜　上市櫃普通股共 {len(master)} 檔（上市 {n_tse}、上櫃 {len(master) - n_tse}）', '',
     '- **第一部分：產業細類**：每檔一個主分類，依營收比重與網路上最常一起討論的族群歸類（不照官方產業別）。'
     '若先前另一輪研究給了不同分類，列在總表的「次要分類」。',
     '- **第二部分：題材概念股**：一檔可同時屬於多個題材。',
     '- **第三部分：集團股**。', '',
     '完整欄位（主要業務、營收比重、信心度）見 `台股分類總表.csv`；題材成員與依據見 `題材成分股.csv`。', '',
     '> 名單由 AI agent 依 MoneyDJ 營收比重、財經新聞與概念股文章整理，難免有誤或過時，'
     '投資前請自行確認。標為低信心的股票列在文末。', '',
     '## 目錄', '']
for b, cs in bigs.items():
    L.append(f'- **{b}**：' + '、'.join(f'{c.split("/", 1)[1]}({len(cats[c])})' for c in cs))
L += ['', '---', '', '# 第一部分：產業細類（每檔一個）', '']
for b, cs in bigs.items():
    L += [f'## {b}', '']
    for c in cs:
        L += [f'### {c}（{len(cats[c])}）', '', '、'.join(f'{x} {master[x]["name"]}' for x in sorted(cats[c])), '']
L += ['---', '', '# 第二部分：題材概念股（可重複）', '',
      '★ 網路概念股名單有列、且有實際營收　● 網路名單有列　○ 有營收但較少被當成此題材討論　△ 市場題材（營收未證實）', '']
for g, ts in THEME_GROUP:
    L += [f'## {g}', '']
    for t in ts:
        d = themes[t]
        L += [f'### {t}（{len(d)}）', '',
              '、'.join(f'{mark[strength(d[x])]}{x} {master[x]["name"]}' for x in order(d)), '']
L += ['---', '', '# 第三部分：集團股', '']
for g, d in groups.items():
    L.append(f'- **{g}**（{len(d)}）：' + '、'.join(f'{x} {master[x]["name"]}' for x in order(d)))
low = sorted(c for c in master if per[c]['confidence'] == '低')
L += ['', '---', '', f'## 低信心股票（{len(low)}）', '',
      '這些股票公開資料少或業務難以判斷，分類與題材建議再自行確認：', '',
      '、'.join(f'{c} {master[c]["name"]}' for c in low), '']
open(f'{OUT}/README.md', 'w', encoding='utf-8').write('\n'.join(L))

n_mem = sum(len(d) for d in themes.values())
print('stocks', len(master), 'categories', len(cats), 'themes', len(themes), 'memberships', n_mem,
      'groups', len(groups), 'stocks with theme', len(stock_themes), 'low', len(low), 'second', len(second))
print('empty themes', [t for t, d in themes.items() if not d])
print('evidence', collections.Counter(evidence(e) for d in themes.values() for e in d.values()))
