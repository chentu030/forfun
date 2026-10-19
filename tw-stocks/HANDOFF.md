# 交接說明：台股上市櫃細分類與題材股

> 給接手的人或 AI。讀完這份就能接著做，不需要先前的對話紀錄。

## 1. 目標

使用者要把台灣上市櫃股票加入自選股，需要：

1. **產業細類**：越細越好，每檔一個主分類，依「網路上會一起討論的族群」歸類（例如 CPO、低軌衛星、CoWoS、液冷），不照官方產業別。
2. **題材概念股**：一檔可以同時屬於多個題材（使用者後來改的規則）。
3. **集團股**。

## 2. 目前進度（2026-10-19）

已完成，成品在本資料夾：

| 檔案 | 內容 |
|---|---|
| `README.md` | 給人看的總覽：194 個細類、90 個題材、54 個集團、低信心清單 |
| `台股分類總表.csv` | 每檔一列：細類、次要分類、題材、其他標籤、集團、主要業務、營收比重、信心度 |
| `題材成分股.csv` | 每列「題材 → 股票」，含依據（網路名單／有營收／市場題材）與角色 |

涵蓋 1,948 檔上市櫃普通股（上市 1,055、上櫃 893），不含 ETF、權證、特別股、TDR、興櫃。

### 準確度的限制（接手主要要補的）

- **營收比重**：每檔都從 MoneyDJ 抓到（1,947／1,948，中光電投控 3718 沒有），多為 2025 年資料。
- **逐檔上網查新聞，只做了約 200 檔（約一成）**：其餘約 1,750 檔是依營收比重加上 AI 既有知識判斷。剛炒起來、還沒反映在營收上的題材可能漏掉。
- **題材名單**（`work/themes/T1~T8.csv`）是從網路概念股文章與新聞整理的，另經逐筆 QA（刪 23 列、修 35 筆 note）。
- **低信心 152 檔**：`台股分類總表.csv` 的「信心度」= 低，列在 README 文末。
- **細類兩輪不一致 283 檔**：主分類採逐檔研究（`work/biz_out`），另一輪結果（`work/out`）放在「次要分類」欄。
- 新聞資料多停在 2026 年 1–9 月。

## 3. 資料夾結構（`work/`）

| 路徑 | 內容 | 格式 |
|---|---|---|
| `master.csv` | 全部 1,948 檔清單，來源：TWSE ISIN 頁（strMode=2 上市、4 上櫃） | `code,name,market,industry` |
| `biz.tsv` | 每檔營收比重（MoneyDJ 基本資料頁）與登記業務（Yahoo 股市 profile） | tab 分隔：`code,name,revenue_mix,business,source` |
| `taxonomy.md` | 最初設計的分類架構與規則 | |
| `category_vocab.txt` | 細類詞彙（「大類/細類」），183 個 | 一行一個 |
| `theme_vocab.md` | 題材詞彙，90 個，分 9 個大類 | |
| `stock_prompt.md` | 逐檔研究時給 AI 的任務說明（可直接重用） | |
| `batches/P01~P16.csv` | 逐檔研究的分批清單，每批約 122 檔，依官方產業排序 | 同 master.csv |
| `biz_out/P01~P16.csv` | **逐檔研究結果（主資料）** | `code,name,main_business,themes,extra_tags,primary_category,confidence` |
| `out/A~E,G.csv` | 第一輪依官方產業分組的細類結果（F 生技綠能、H 傳產兩組沒完成） | `code,name,market,category,note` |
| `themes/T1~T7.csv` | 網路題材名單（由題材往下找成分股） | `theme,code,name,role,note`，role = 龍頭/核心/相關 |
| `themes/T8.csv` | 集團股名單 | theme =「集團/鴻海」，role = 母公司/子公司/轉投資 |
| `scripts/merge.py` | 合併以上資料、產生三份成品 | |
| `scripts/theme_group.py` | 題材分組（大類 → 題材清單），merge.py 讀取 | |
| `scripts/biz_fetch.py`、`biz_parse.py` | 抓取並解析 MoneyDJ／Yahoo 頁面產生 `biz.tsv`（原始 HTML 約 660MB，沒放進 repo） | |
| `scripts/parse.py` | 解析 TWSE ISIN 頁產生 `master.csv`：`python3 parse.py isin_2.html isin_4.html master.csv`（頁面為 Big5） | |

### `biz_out` 的 themes 欄格式

用 `;` 分隔，每個題材名稱必須精確存在於 `theme_vocab.md`，後面接證據標記：

- `【業務】`：有實際營收或產品
- `【市場】`：主要是媒體或市場把它歸入此題材

例：`液冷散熱【業務】;輝達AI伺服器(GB300/Rubin)【市場】`

### 重新產生成品

在 repo 根目錄的 `tw-stocks/` 下執行：

```
python3 work/scripts/merge.py work .
```

merge.py 會檢查：每檔都有結果、代號都在 master.csv、題材名稱都在詞彙表內。題材別名合併（例如「HBM/記憶體漲價」併入「記憶體/HBM」）寫在 `THEME_ALIAS`，個別剔除寫在 `THEME_DROP`。

## 4. 建議的下一步

### A. 補齊逐檔網路查證（最重要）

不靠搜尋引擎額度的作法：

1. 用程式批次下載每檔的公司介紹頁（例如 nStock 公司小百科、公司官網產品頁）與個股近期新聞標題（例如 Yahoo 股市 `https://tw.stock.yahoo.com/quote/{code}.TW/news`，上櫃用 `.TWO`）。請限制併發（4–6）、加延遲。
2. 依 `work/stock_prompt.md` 的規則，逐檔重新判斷 themes／primary_category／confidence，輸出同樣格式覆寫 `work/biz_out/P*.csv`。
3. 執行 merge.py。

優先順序：低信心 152 檔 → 題材標記為「市場題材」（△）的 513 筆 → 其他。

### B. 其他可改進處

- 細類只有 1 檔的有 15 個（例如 傳產/殯葬、電子/量測儀器），可考慮併入相近類別。
- 「住宅建商」約 70 檔，可再細分（例如依區域或是否為資產股）。
- 283 檔兩輪細類不同，可人工或 AI 擇一。
- 題材名單需要定期更新（建議每季）。

## 5. 歸類原則（維持一致）

- 主細類：選「網路上最常把它跟哪群股票一起討論」的那一個；多題材時看營收占比最高或市場最主要的題材。
- 題材：有實際營收或明確出貨／認證，或財經媒體確實把它當該題材討論才列；只是沾邊、尚無營收的遠期計畫不列。
- 只收上市櫃普通股；興櫃、已下市的不收（例如晶睿 2026/3 已下市併入台達電）。
