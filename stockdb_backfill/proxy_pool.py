"""
共用代理池（2026-10-22 從 注意股&處置股\\warning_disposition_crawler.py 的 ProxyManager 抽出）
==========================================================================================
新爬蟲用法：
    import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from proxy_pool import Fetcher
    F = Fetcher(use_proxy=True, test_url="https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate=20240531&response=json")
    r = F.get(url)                       # 或 F.post(url, data={...})
    rows = F.stable(lambda force_direct: parse(F.get(url, force_direct=force_direct)))   # 驗貨：連抓兩次相同才採用

規則（和原本爬蟲相同）：
  - 代理來源：3 個公開清單；驗證後存共用快取 上市櫃資料爬蟲程式碼\\shared_proxy_cache.json（1 小時內算新鮮）。
  - 每個代理各自限速 5 秒 3 次；直連 5 秒 3 次。
  - 代理回 403、HTML、連線錯誤 → 標記壞掉換下一個；可用數 < 20 時背景補充。
  - 代理模式拿不到穩定結果 → 改直連做一次權威確認（防代理竄改或回傳錯誤內容）。
  - daily_run 會設 MAX_PROXIES=10（只需少量代理）；回補歷史時可設大一點。
"""
import hashlib, json, os, random, threading, time
from datetime import datetime

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared_proxy_cache.json")
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
]


class _RateLimiter:
    def __init__(self, n=3, per=5.0):
        self.n, self.per, self.lock, self.ts = n, per, threading.Lock(), {}

    def wait(self, key):
        with self.lock:
            now = time.time()
            ts = [t for t in self.ts.get(key, []) if now - t < self.per]
            if len(ts) >= self.n:
                w = self.per - (now - ts[0])
                if w > 0:
                    time.sleep(w)
                ts = [t for t in ts if time.time() - t < self.per]
            ts.append(time.time())
            self.ts[key] = ts


class ProxyManager:
    VALIDATE_TIMEOUT = 8
    VALIDATE_THREADS = 150
    VALIDATE_TIME_LIMIT = 300

    def __init__(self, test_url, test_ok=lambda r: r.status_code == 200 and not r.text.strip().startswith("<")):
        self.test_url, self.test_ok = test_url, test_ok
        self.max_valid = int(os.environ.get("MAX_PROXIES", "100"))
        self.lock = threading.Lock()
        self.proxies, self.bad, self._idx, self._fetched = [], set(), 0, False

    def _load_cache(self):
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
            return data.get("proxies", [])
        except Exception:
            return []

    def _save_cache(self):
        with self.lock:
            active = [p for p in self.proxies if p not in self.bad]
        try:
            tmp = CACHE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"proxies": active, "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f)
            os.replace(tmp, CACHE_FILE)
        except Exception:
            pass

    def _validate(self, candidates, target):
        valid, vlock, stop = [], threading.Lock(), [False]

        def check(p):
            if stop[0]:
                return
            try:
                r = requests.get(self.test_url, proxies={"http": f"http://{p}", "https": f"http://{p}"},
                                 timeout=self.VALIDATE_TIMEOUT, headers=HEADERS)
                if self.test_ok(r):
                    with vlock:
                        valid.append(p)
                        if len(valid) >= target:
                            stop[0] = True
            except Exception:
                pass

        threads = []
        for p in candidates:
            if stop[0]:
                break
            t = threading.Thread(target=check, args=(p,), daemon=True)
            threads.append(t)
            t.start()
            if len(threads) >= self.VALIDATE_THREADS:
                threads[0].join(timeout=1)
                threads = [t for t in threads if t.is_alive()]
        deadline = time.time() + self.VALIDATE_TIME_LIMIT
        for t in threads:
            t.join(timeout=max(0, deadline - time.time()))
        return valid

    def fetch(self):
        cached = self._load_cache()
        valid = self._validate(cached, self.max_valid) if cached else []
        print(f"  [代理] 快取 {len(cached)} 個，存活 {len(valid)} 個", flush=True)
        need = self.max_valid - len(valid)
        if need > 0 and len(valid) < max(10, self.max_valid // 3):
            pool = set()
            for src in PROXY_SOURCES:
                try:
                    for line in requests.get(src, timeout=10).text.splitlines():
                        line = line.strip()
                        if ":" in line:
                            pool.add(line)
                except Exception:
                    pass
            fresh = [p for p in pool if p not in set(cached)]
            random.shuffle(fresh)
            valid += self._validate(fresh, need)
        with self.lock:
            self.proxies, self._fetched = valid, True
        self._save_cache()
        print(f"  [代理] ✓ 可用 {len(valid)} 個", flush=True)

    def get(self):
        with self.lock:
            avail = [p for p in self.proxies if p not in self.bad]
            if not avail:
                self.bad.clear()
                avail = self.proxies[:]
            if not avail:
                return None
            self._idx += 1
            return avail[self._idx % len(avail)]

    def report_bad(self, p):
        if p:
            with self.lock:
                self.bad.add(p)

    @property
    def available(self):
        with self.lock:
            return len([p for p in self.proxies if p not in self.bad])


class Fetcher:
    """GET/POST：代理模式（預設）或直連；拿不到時自動改直連。"""

    def __init__(self, use_proxy=True, test_url=None, timeout=20, direct_delay=None):
        self.use_proxy = use_proxy and bool(test_url)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.direct_rl = _RateLimiter()
        self.proxy_rl = _RateLimiter()
        self.direct_delay = direct_delay
        self.pm = ProxyManager(test_url) if self.use_proxy else None
        self._refill_lock = threading.Lock()
        self._last_refill = 0.0

    def _ensure(self):
        if not self.pm._fetched:
            self.pm.fetch()
        elif self.pm.available < 20 and time.time() - self._last_refill > 90 and self._refill_lock.acquire(blocking=False):
            self._last_refill = time.time()

            def bg():
                try:
                    self.pm.fetch()
                finally:
                    self._refill_lock.release()
            threading.Thread(target=bg, daemon=True).start()

    @staticmethod
    def _bad_response(r):
        return r.status_code in (403, 429) or r.status_code >= 500 or not r.content

    def request(self, method, url, force_direct=False, accept=None, **kw):
        """accept(resp) -> bool：額外檢查內容（例如 JSON stat 正常、或 content-type 是 CSV）。"""
        ok = accept or (lambda r: not r.text.lstrip().startswith("<"))
        if self.use_proxy and not force_direct:
            self._ensure()
            for _ in range(4):
                p = self.pm.get()
                if not p:
                    break
                self.proxy_rl.wait(p)
                try:
                    r = self.session.request(method, url, proxies={"http": f"http://{p}", "https": f"http://{p}"},
                                             timeout=self.timeout, **kw)
                    if self._bad_response(r) or not ok(r):
                        self.pm.report_bad(p)
                        continue
                    return r
                except Exception:
                    self.pm.report_bad(p)
            # 代理都失敗 → 直連
        for attempt in range(3):
            self.direct_rl.wait("direct")
            if self.direct_delay:
                time.sleep(self.direct_delay)
            try:
                r = self.session.request(method, url, timeout=max(self.timeout, 30), **kw)
                if self._bad_response(r):
                    w = 60 * (attempt + 1)
                    print(f"      ⚠ 直連被限速（HTTP {r.status_code}），等 {w} 秒", flush=True)
                    time.sleep(w)
                    continue
                return r
            except Exception:
                time.sleep(10 * (attempt + 1))
        return None

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, data=None, **kw):
        return self.request("POST", url, data=data, **kw)

    def stable(self, fetch_fn, max_pulls=6):
        """驗貨：fetch_fn(force_direct) 回傳 list/None。連抓到兩次相同內容才採用；代理確認不了就直連再確認。"""
        def pull(force_direct):
            seen = {}
            empty = False
            for _ in range(max_pulls):
                rows = fetch_fn(force_direct)
                if rows is None:
                    continue
                if not rows:
                    empty = True
                    if not self.use_proxy or force_direct:
                        return [], True
                    continue
                sig = hashlib.md5(repr(rows).encode("utf-8")).hexdigest()
                seen[sig] = seen.get(sig, 0) + 1
                if seen[sig] >= 2:
                    return rows, True
                if not self.use_proxy or force_direct:
                    return rows, True    # 直連一次就算數
            return ([] if empty else None), False
        rows, ok = pull(False)
        if self.use_proxy and not ok:
            rows, ok = pull(True)
        return rows
