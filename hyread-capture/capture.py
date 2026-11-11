#!/usr/bin/env python3
"""HyRead 雜誌批次擷取 — patchright 通過 Cloudflare，可在 GitHub Actions 或本機執行。

用法 (本機):
    python capture.py --books books.json --output D:\HyRead解密書籍 --user 113701013 --pass YOUR_PWD

用法 (GitHub Actions):
    python capture.py --books books.json --output output --chunk 0 --total-chunks 20

環境變數也行: HYREAD_USER, HYREAD_PASS, HYREAD_LIBRARY
"""

import asyncio
import json
import os
import random
import re
import sys
import time
import argparse
from pathlib import Path

PDF_LIB_CDN = "https://cdnjs.cloudflare.com/ajax/libs/pdf-lib/1.17.1/pdf-lib.min.js"
BATCH_SIZE = 10
GAP_SEC = (30, 90)
SERVER_RETRY_SEC = (120, 300)
MAX_SERVER_RETRIES = 10

def safe(s):
    s = re.sub(r"(\d{4})/(\d{2})/(\d{2})", r"\1\2\3", s)
    s = re.sub(r'[<>:"/\\|?*]', "", s)
    return re.sub(r"\s+", " ", s).strip()


async def wait_cf(page, timeout=90):
    """等待 Cloudflare JS challenge / Turnstile 自動通過"""
    for i in range(timeout):
        title = await page.title()
        if "請稍候" not in title and "Just a moment" not in title:
            return True
        if i % 15 == 0 and i > 0:
            print(f"    [CF] 等待中 ({i}s)...")
        try:
            for frame in page.frames:
                cb = frame.locator('[type="checkbox"]')
                if await cb.count() > 0 and await cb.first.is_visible():
                    await cb.first.click()
                    print(f"    [CF] 點擊 checkbox")
                    break
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def wait_server(page, url, max_retries=MAX_SERVER_RETRIES):
    """HyRead Tomcat 回 400 時等待重試（伺服器暫時異常）"""
    for attempt in range(max_retries):
        title = await page.title()
        if "400" not in title and "Bad Request" not in title:
            return True
        wait = random.uniform(*SERVER_RETRY_SEC)
        print(f"    [Server 400] 伺服器暫時異常，{wait:.0f}s 後重試 ({attempt+1}/{max_retries})")
        await asyncio.sleep(wait)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await wait_cf(page, 30)
    return False


async def login(page, library, user, pwd):
    url = f"https://{library}.ebook.hyread.com.tw/"
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    if not await wait_cf(page):
        print("[login] Cloudflare timeout，嘗試繼續")

    body = await page.evaluate("document.body.innerText")
    if "登出" in body or "我的書房" in body:
        print("[login] 已登入")
        return True

    try:
        await page.locator('a:has-text("登入"), button:has-text("登入")').first.click(timeout=8000)
        await page.wait_for_timeout(2000)
    except Exception:
        pass

    pairs = [
        ("#loginId", "#loginPwd"),
        ("#usercode", "#userpwd"),
        ('[name="loginId"]', '[name="loginPwd"]'),
        ('[name="usercode"]', '[name="userpwd"]'),
        ('input[placeholder*="證號"]', 'input[placeholder*="密碼"]'),
        ('input[placeholder*="帳號"]', 'input[placeholder*="密碼"]'),
    ]
    for u_sel, p_sel in pairs:
        try:
            u_el = page.locator(u_sel).first
            if not await u_el.is_visible(timeout=1500):
                continue
            await u_el.fill(user)
            await page.locator(p_sel).first.fill(pwd)
            await page.locator(
                'button[type="submit"], input[type="submit"], '
                'button:has-text("確定"), button:has-text("登入"), '
                '#loginbtn, .btn-login'
            ).first.click()
            await page.wait_for_load_state("domcontentloaded")
            await wait_cf(page)
            print("[login] 登入完成")
            return True
        except Exception:
            continue

    print("[login] 找不到登入表單，嘗試繼續")
    return False


FIND_STORE_JS = """() => {
    const el = document.querySelector('input[type="range"]');
    if (!el) return -1;
    const k = Object.keys(el).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
    let store;
    for (let f = k && el[k]; f; f = f.return) {
        const v = f.memoizedProps && f.memoizedProps.value;
        if (v && v.store && v.store.getState) { store = v.store; break; }
    }
    if (!store) return -1;
    const state = store.getState();
    if (typeof state.dataInterceptor !== 'function') return -2;
    window.__hyStore = store;
    return state.book.spine.length;
}"""

FETCH_BATCH_JS = """async (start, end) => {
    if (!window.__hyPages) window.__hyPages = {};
    const state = window.__hyStore.getState();
    const spine = state.book.spine;
    let ok = 0;
    for (let i = start; i < end; i++) {
        if (window.__hyPages[i]) { ok++; continue; }
        for (let retry = 0; retry < 3; retry++) {
            try {
                const s = spine[i];
                const item = {
                    spineId: s.id, p: s.p, bp: s.bp, cover: s.cover, thumb: s.thumb, src: s.href,
                    type: s['media-type'], layoutPrePaginated: true, isPdf: true,
                    oriSpineIndex: i, spineIndex: i,
                };
                const r = await state.dataInterceptor(item);
                const buf = await (await fetch(r.src)).arrayBuffer();
                const u8 = new Uint8Array(buf, 0, 4);
                if (u8[0] !== 0x25 || u8[1] !== 0x50) throw new Error('not PDF');
                window.__hyPages[i] = buf;
                ok++;
                break;
            } catch (e) {
                if (retry === 2) console.error('Page', i, 'failed:', e);
                await new Promise(r => setTimeout(r, 2000));
            }
        }
    }
    return ok;
}"""

MERGE_JS = """async () => {
    const { PDFDocument } = PDFLib;
    const out = await PDFDocument.create();
    const keys = Object.keys(window.__hyPages).map(Number).sort((a,b)=>a-b);
    for (const i of keys) {
        try {
            const src = await PDFDocument.load(window.__hyPages[i], { ignoreEncryption: true });
            const copied = await out.copyPages(src, src.getPageIndices());
            copied.forEach(p => out.addPage(p));
        } catch (e) {}
    }
    const pgs = out.getPages();
    const count = new Map();
    for (const pg of pgs) {
        const { width, height } = pg.getMediaBox();
        count.set(Math.round(width) + 'x' + Math.round(height),
                   (count.get(Math.round(width) + 'x' + Math.round(height)) || 0) + 1);
    }
    if (count.size) {
        const [W, H] = [...count.entries()].sort((a,b)=>b[1]-a[1])[0][0].split('x').map(Number);
        for (const pg of pgs) {
            const b = pg.getMediaBox();
            if (Math.abs(b.width-W)<2 && Math.abs(b.height-H)<2 && !b.x && !b.y) continue;
            const s = Math.min(W/b.width, H/b.height);
            pg.translateContent(-b.x, -b.y);
            pg.scaleContent(s, s);
            pg.translateContent((W-b.width*s)/2, (H-b.height*s)/2);
            for (const fn of ['setMediaBox','setCropBox','setTrimBox','setBleedBox','setArtBox'])
                pg[fn](0,0,W,H);
        }
    }
    const bytes = await out.save();
    const blob = new Blob([bytes], {type:'application/pdf'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '__hyread__.pdf';
    document.body.appendChild(a); a.click(); a.remove();
    window.__hyPages = {};
    return { captured: keys.length, merged: out.getPageCount(), size: bytes.length };
}"""


async def capture_book(context, book, output_dir):
    url = book["url"]
    page = await context.new_page()
    page.set_default_timeout(120_000)
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if not await wait_cf(page):
            return {"status": "error", "msg": "Cloudflare timeout on detail"}

        title_raw = await page.title()
        if "400" in title_raw or "Bad Request" in title_raw:
            if not await wait_server(page, url, 3):
                return {"status": "server_down", "msg": "伺服器持續 400"}

        title = await page.evaluate("(document.title||'').split(' | ')[0].trim()")
        if not title or "HyRead" in title:
            title = book.get("title", f'hyread_{url.split("id=")[-1]}')
        fname = safe(title) + ".pdf"
        out_path = Path(output_dir) / fname
        if out_path.exists():
            print(f"  [skip] {fname}")
            return {"status": "skipped", "file": fname}

        has_form = await page.evaluate("!!document.forms.onlineReadForm")
        if not has_form:
            return {"status": "error", "msg": "no onlineReadForm"}
        await page.evaluate(
            "document.forms.onlineReadForm.target='_self';"
            "document.forms.onlineReadForm.submit();"
        )

        try:
            await page.wait_for_selector('input[type="range"]', timeout=120_000)
        except Exception:
            if not await wait_cf(page, 60):
                return {"status": "error", "msg": "reader load timeout / CF block"}
            await page.wait_for_selector('input[type="range"]', timeout=60_000)

        await page.wait_for_timeout(2000)
        await page.add_script_tag(url=PDF_LIB_CDN)
        await page.wait_for_timeout(1000)

        spine_count = await page.evaluate(FIND_STORE_JS)
        if spine_count <= 0:
            return {"status": "error", "msg": f"spine={spine_count}"}

        print(f"  [fetch] {spine_count} pages")

        for start in range(0, spine_count, BATCH_SIZE):
            end = min(start + BATCH_SIZE, spine_count)
            ok = await page.evaluate(FETCH_BATCH_JS, start, end, timeout=300_000)
            print(f"    {start+1}-{end}: {ok} ok")

        async with page.expect_download(timeout=600_000) as dl_info:
            result = await page.evaluate(MERGE_JS, timeout=600_000)
        download = await dl_info.value
        await download.save_as(str(out_path))

        miss = spine_count - result["captured"]
        if miss > 0:
            new_name = safe(title) + f" (缺{miss}頁).pdf"
            new_path = Path(output_dir) / new_name
            out_path.rename(new_path)
            out_path = new_path

        mb = result["size"] / 1048576
        print(f"  [done] {out_path.name} ({result['merged']}p, {mb:.1f}MB)")
        return {"status": "ok", "file": out_path.name, **result}

    except Exception as e:
        print(f"  [error] {type(e).__name__}: {e}")
        return {"status": "error", "msg": str(e)}
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def run(args):
    from patchright.async_api import async_playwright

    with open(args.books, encoding="utf-8") as f:
        all_books = json.load(f)

    my_books = [b for i, b in enumerate(all_books) if i % args.total_chunks == args.chunk]
    if not my_books:
        print("No books for this chunk"); return

    library = args.library or os.environ.get("HYREAD_LIBRARY", "nycu")
    user = args.user or os.environ.get("HYREAD_USER", "")
    pwd = args.password or os.environ.get("HYREAD_PASS", "")
    os.makedirs(args.output, exist_ok=True)

    print(f"=== HyRead Capture  chunk {args.chunk}/{args.total_chunks}  books {len(my_books)} ===")

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(Path(args.output) / f".profile_{args.chunk}"),
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox",
                  "--disable-setuid-sandbox"],
            viewport={"width": 1280, "height": 900},
            accept_downloads=True,
        )

        if user and pwd:
            lp = context.pages[0] if context.pages else await context.new_page()
            await login(lp, library, user, pwd)
            await lp.close()

        results = []
        server_down_streak = 0

        for idx, book in enumerate(my_books):
            label = book.get("title", book["url"])
            print(f"\n[{idx+1}/{len(my_books)}] {label}")

            if server_down_streak >= 3:
                wait = random.uniform(300, 600)
                print(f"  [cooldown] 伺服器連續 {server_down_streak} 次 400，冷卻 {wait:.0f}s")
                await asyncio.sleep(wait)

            for attempt in range(2):
                res = await capture_book(context, book, args.output)
                if res["status"] == "server_down":
                    server_down_streak += 1
                    break
                if res["status"] != "error" or attempt == 1:
                    break
                print(f"  [retry] attempt {attempt+2}")
                await asyncio.sleep(5)

            if res["status"] == "ok":
                server_down_streak = 0
            results.append(res)

            if idx < len(my_books) - 1 and res["status"] not in ("skipped", "server_down"):
                gap = random.uniform(*GAP_SEC)
                print(f"  [gap] {gap:.0f}s")
                await asyncio.sleep(gap)

        await context.close()

    ok = sum(1 for r in results if r["status"] == "ok")
    skip = sum(1 for r in results if r["status"] == "skipped")
    err = sum(1 for r in results if r["status"] == "error")
    down = sum(1 for r in results if r["status"] == "server_down")
    print(f"\n=== Done: {ok} captured, {skip} skipped, {err} errors, {down} server_down ===")

    summary_path = Path(args.output) / f"_summary_{args.chunk}.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description="HyRead batch capture with patchright")
    p.add_argument("--books", required=True, help="books.json path")
    p.add_argument("--output", default="output", help="Output directory")
    p.add_argument("--library", default="", help="Library code (default: nycu)")
    p.add_argument("--user", default="", help="Card number")
    p.add_argument("--password", default="", help="Password")
    p.add_argument("--chunk", type=int, default=0, help="Chunk index (0-based)")
    p.add_argument("--total-chunks", type=int, default=1, help="Total chunks for matrix")
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
