"""
三大法人買賣金額（市場合計，官方精確值）爬蟲
==========================================
上市：證交所 三大法人買賣金額統計表
      GET  https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate=YYYYMMDD&response=json
      列：自營商(自行買賣)、自營商(避險)、投信、外資及陸資(不含外資自營商)、外資自營商、合計
      （2017 年以前沒有「外資自營商」列，外資列名稱為「外資及陸資」）
上櫃：櫃買中心 三大法人買賣金額彙總表（日報表）
      POST https://www.tpex.org.tw/www/zh-tw/insti/summary   type=Daily&prod=1|0&date=YYYY/MM/DD&response=json
      prod=1 上櫃股票、prod=0 上櫃有價證券（含權證、ETF、ETN、TDR…）；兩種都抓，用「類別」欄區分。
      早年 prod=1（上櫃股票）可能沒資料，只會有「上櫃有價證券」。

存檔（單位：元，欄位保留官方原名，數字去千分位）：
  StockDB/三大法人市場合計/官方/上市/YYYYMMDD.csv   單位名稱,買進金額,賣出金額,買賣差額
  StockDB/三大法人市場合計/官方/上櫃/YYYYMMDD.csv   類別,單位名稱,買進金額(元),賣出金額(元),買賣超(元)

用法:
  python official_market_total_crawler.py                       # 從最後一個檔案的隔天補到今天，並重抓最近 2 個交易日
  python official_market_total_crawler.py 20160104 20261022     # 指定期間（已存在的檔案跳過）
  python official_market_total_crawler.py 20261021 20261021 --force   # 重抓覆蓋
  可加 --twse 或 --tpex 只抓一個市場；預設走代理模式（proxy_pool.Fetcher），加 --direct 改直連。
  代理數量：環境變數 MAX_PROXIES（daily_run 設 10，回補可設 50）。

限速：代理模式每個代理 5 秒 3 次，結果需連抓兩次相同（stable 驗貨），代理確認不了就直連再確認；
      直連 5 秒 3 次＋證交所每次再隔 2 秒；被擋 (403/429/5xx) 等 60→120→180 秒。
"""
import csv, os, sys, time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from proxy_pool import Fetcher  # noqa: E402

STOCKDB = os.environ.get("STOCKDB_ROOT") or r"C:\Users\User\Desktop\StockDB"   # GitHub Actions 回補時用環境變數改路徑
BASE = os.path.join(STOCKDB, "三大法人市場合計", "官方")
TRADING_DAYS_CSV = os.path.join(STOCKDB, "台股交易日.csv")
FIRST_DAY = date(2016, 1, 4)
RECENT_REFETCH = 2
TEST_URL = {
    "twse": "https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate=20240531&response=json",
    "tpex": "https://www.tpex.org.tw/www/zh-tw/insti/summary?type=Daily&prod=1&date=2024/05/31&response=json",
}
FETCH = {}   # host → proxy_pool.Fetcher，main() 建立


def setup(use_proxy):
    for host, url in TEST_URL.items():
        FETCH[host] = Fetcher(use_proxy=use_proxy, test_url=url,
                              direct_delay=2.0 if host == "twse" else 0.5)


def _json_ok(r):
    try:
        j = r.json()
        return isinstance(j, dict) and "stat" in j
    except ValueError:
        return False


def get_json(host, method, url, force_direct=False, **kw):
    """經 Fetcher（代理或直連）取 JSON；拿不到回傳 None。"""
    r = FETCH[host].request(method, url, force_direct=force_direct, accept=_json_ok, **kw)
    try:
        return r.json() if r is not None else None
    except ValueError:
        if force_direct or not FETCH[host].use_proxy:
            print(f"    ! {host} 直連回傳非 JSON，等 60 秒", flush=True)
            time.sleep(60)
        return None


REASON = {}


def why(host, j):
    REASON[host] = f"stat={j.get('stat')!r} date={j.get('date')!r}"


def num(x):
    return str(x).replace(",", "").strip()


# ── 上市 ─────────────────────────────────────────────
def fetch_twse(d, fd=False):
    j = get_json("twse", "GET", "https://www.twse.com.tw/rwd/zh/fund/BFI82U",
                 params={"type": "day", "dayDate": d.strftime("%Y%m%d"), "response": "json"},
                 force_direct=fd, headers={"Referer": "https://www.twse.com.tw/zh/trading/foreign/bfi82u.html"})
    if j is None:
        return None
    if j.get("stat") != "OK" or not j.get("data") or j.get("date") != d.strftime("%Y%m%d"):
        why("twse", j)
        return []
    header = [str(f).strip() for f in j["fields"]]
    rows = [[str(r[0]).strip()] + [num(x) for x in r[1:]] for r in j["data"] if len(r) >= 4 and str(r[0]).strip()]
    return [header] + rows


# ── 上櫃 ─────────────────────────────────────────────
TPEX_PROD = [("1", "上櫃股票"), ("0", "上櫃有價證券")]


def fetch_tpex(d, fd=False):
    out, header = [], None
    for prod, label in TPEX_PROD:
        j = get_json("tpex", "POST", "https://www.tpex.org.tw/www/zh-tw/insti/summary",
                     data={"type": "Daily", "prod": prod, "date": d.strftime("%Y/%m/%d"), "response": "json"},
                     force_direct=fd, headers={"Referer": "https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/summary/day.html"})
        if j is None:
            return None
        if j.get("stat") != "ok" or j.get("date") != d.strftime("%Y%m%d"):
            why("tpex", j)
            continue
        for tb in j.get("tables", []):
            if not tb.get("data"):
                continue
            header = ["類別"] + [str(f).strip() for f in tb["fields"]]
            for r in tb["data"]:
                if len(r) < 4 or not str(r[0]).strip():
                    continue
                out.append([label, str(r[0]).replace("\u3000", "").strip()] + [num(x) for x in r[1:]])
    return [header] + out if out else []


MARKETS = {"上市": fetch_twse, "上櫃": fetch_tpex}


def path_of(mk, d):
    return os.path.join(BASE, mk, d.strftime("%Y%m%d") + ".csv")


def save(mk, d, rows):
    p = path_of(mk, d)
    for k in range(4):
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerows(rows)
            os.replace(tmp, p)
            return True
        except OSError as e:
            print(f"    ! 寫檔失敗 {p}: {e}，30 秒後重試", flush=True)
            time.sleep(30)
    return False


def trading_days(start, end):
    with open(TRADING_DAYS_CSV, encoding="utf-8-sig") as f:
        return [d for d in (datetime.strptime(r["交易日期"], "%Y-%m-%d").date() for r in csv.DictReader(f))
                if start <= d <= end]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    setup(use_proxy="--direct" not in sys.argv)
    mks = [m for m, flag in (("上市", "--twse"), ("上櫃", "--tpex")) if flag in sys.argv] or list(MARKETS)
    today = date.today()
    recent = set()
    if len(args) >= 2:
        start = datetime.strptime(args[0], "%Y%m%d").date()
        end = datetime.strptime(args[1], "%Y%m%d").date()
    else:
        lasts = []
        for mk in mks:
            dd = os.path.join(BASE, mk)
            have = sorted(f[:8] for f in os.listdir(dd) if f.endswith(".csv")) if os.path.isdir(dd) else []
            lasts.append(datetime.strptime(have[-1], "%Y%m%d").date() + timedelta(days=1) if have else FIRST_DAY)
        start, end = min(lasts), today
        recent = set(trading_days(today - timedelta(days=15), today)[-RECENT_REFETCH:])
    start = max(start, FIRST_DAY)
    days = sorted(set(trading_days(start, end)) | recent)
    todo = [(d, [mk for mk in mks if force or d in recent or not os.path.exists(path_of(mk, d))]) for d in days]
    todo = [(d, m) for d, m in todo if m]
    print(f"三大法人市場合計（官方）：{start}～{end} 交易日 {len(days)} 天，待抓 {len(todo)} 天 → {BASE}", flush=True)
    ok = empty = fail = 0
    retry = []

    def one(d, mk, final):
        nonlocal ok, empty, fail
        host = "twse" if mk == "上市" else "tpex"
        rows = FETCH[host].stable(lambda fd: MARKETS[mk](d, fd))
        if rows is None:
            if final:
                fail += 1
                print(f"  ✗ {d} {mk} 連線失敗", flush=True)
            else:
                retry.append((d, mk))
        elif not rows:
            if d < today and d not in recent and not final:
                retry.append((d, mk))
            else:
                empty += 1
                if d < today and d not in recent:
                    print(f"  - {d} {mk} 無資料（{REASON.get('twse' if mk == '上市' else 'tpex')}）", flush=True)
        elif save(mk, d, rows):
            ok += 1
        else:
            print("寫檔一直失敗（D 槽斷線？），中止", flush=True)
            sys.exit(2)

    for i, (d, ms) in enumerate(todo, 1):
        for mk in ms:
            one(d, mk, False)
        if i % 50 == 0:
            print(f"  [{i}/{len(todo)}] 到 {d}  成功 {ok} 待重試 {len(retry)} 失敗 {fail}", flush=True)
    if retry:
        print(f"  重試 {len(retry)} 筆（先等 60 秒）", flush=True)
        time.sleep(60)
        for d, mk in retry:
            one(d, mk, True)
    print(f"完成：成功 {ok}、無資料 {empty}、失敗 {fail}", flush=True)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
