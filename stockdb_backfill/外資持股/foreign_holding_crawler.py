"""
外資及陸資持股統計（個股每日）爬蟲
================================
上市：證交所 外資及陸資投資持股統計
      GET  https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date=YYYYMMDD&selectType=ALLBUT0999&response=json
      欄位：證券代號、證券名稱、國際證券編碼、發行股數、外資及陸資尚可投資股數、全體外資及陸資持有股數、
            外資及陸資尚可投資比率、全體外資及陸資持股比率、外資及陸資共用法令投資上限比率、
            陸資法令投資上限比率、與前日異動原因(註)、最近一次上市公司申報外資及陸資持股異動日期
      （ALLBUT0999 = 全部，不含權證、牛熊證；含 ETF）
上櫃：櫃買中心 櫃檯買賣股票僑外資及陸資持股比例排行表
      POST https://www.tpex.org.tw/www/zh-tw/insti/qfii   date=YYYY/MM/DD&response=json
      欄位：排行、代號、名稱、發行股數(A)、僑外資及陸資尚可投資股數B=A*F-C、僑外資及陸資持有股數(C)、
            僑外資及陸資尚可投資比率(D=B/A)、僑外資及陸資持股比率(E=C/A)、法令投資上限比率(F)、備註
      櫃買每日 18:00 與 22:00 更新，所以預設模式會重抓最近 2 個交易日。

存檔（欄位保留官方原名；數字去千分位、比率去掉 %，單位：股、%）：
  StockDB/外資持股/上市/YYYYMMDD.csv
  StockDB/外資持股/上櫃/YYYYMMDD.csv

用法:
  python foreign_holding_crawler.py                       # 從最後一個檔案的隔天補到今天，並重抓最近 2 個交易日
  python foreign_holding_crawler.py 20160104 20261022     # 指定期間（已存在的檔案跳過）
  python foreign_holding_crawler.py 20261021 20261021 --force   # 重抓覆蓋
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
BASE = os.path.join(STOCKDB, "外資持股")
TRADING_DAYS_CSV = os.path.join(STOCKDB, "台股交易日.csv")
FIRST_DAY = date(2016, 1, 4)
RECENT_REFETCH = 2
TEST_URL = {
    "twse": "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date=20240531&selectType=ALLBUT0999&response=json",
    "tpex": "https://www.tpex.org.tw/www/zh-tw/insti/qfii?date=2024/05/31&response=json",
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


def pnum(x):
    return str(x).replace(",", "").replace("%", "").strip()


# ── 上市 ─────────────────────────────────────────────
def fetch_twse(d, fd=False):
    j = get_json("twse", "GET", "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS",
                 params={"date": d.strftime("%Y%m%d"), "selectType": "ALLBUT0999", "response": "json"},
                 force_direct=fd, headers={"Referer": "https://www.twse.com.tw/zh/trading/foreign/mi-qfiis.html"})
    if j is None:
        return None
    if j.get("stat") != "OK" or not j.get("data") or j.get("date") != d.strftime("%Y%m%d"):
        why("twse", j)
        return []
    header = [str(f).strip() for f in j["fields"]]
    rows = [[str(r[0]).strip(), str(r[1]).strip(), str(r[2]).strip()] + [pnum(x) for x in r[3:]] for r in j["data"] if len(r) >= 8]
    return [header] + rows


# ── 上櫃 ─────────────────────────────────────────────
def fetch_tpex(d, fd=False):
    j = get_json("tpex", "POST", "https://www.tpex.org.tw/www/zh-tw/insti/qfii",
                 data={"date": d.strftime("%Y/%m/%d"), "response": "json"},
                 force_direct=fd, headers={"Referer": "https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/summary/day.html"})
    if j is None:
        return None
    if j.get("stat") != "ok" or j.get("date") != d.strftime("%Y%m%d"):
        why("tpex", j)
        return []
    for tb in j.get("tables", []):
        if tb.get("data"):
            header = [str(f).strip() for f in tb["fields"]]
            rows = [[str(r[0]).strip(), str(r[1]).strip(), str(r[2]).strip()] + [pnum(x) for x in r[3:9]]
                    + [str(x).strip() for x in r[9:]] for r in tb["data"] if len(r) >= 9]
            return [header] + rows
    why("tpex", {"stat": "ok", "date": "空表"})
    return []


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
    print(f"外資持股：{start}～{end} 交易日 {len(days)} 天，待抓 {len(todo)} 天 → {BASE}", flush=True)
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
