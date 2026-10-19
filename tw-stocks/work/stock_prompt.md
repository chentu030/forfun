# 逐檔業務研究任務說明

S=tw-stocks/work（repo 內的路徑）

輸入：
- 你的批次：$S/batches/<BATCH>.csv（code,name,market,industry）
- 公司資料：$S/biz.tsv（tab 分隔：code,name,revenue_mix 營收比重,business 登記業務,source）
- 題材詞彙表：$S/theme_vocab.md（約 110 個題材）
- 產業細類詞彙：$S/category_vocab.txt（「大類/細類」）

對批次中「每一檔」股票：
1. 讀 biz.tsv 的營收比重與業務。若資料不足、看不懂產品實際用途、或懷疑有近期新題材（AI、CPO、低軌衛星、機器人、重電、無人機、液冷、BBU…），用 WebSearch 查「代號 公司名 產品 應用」「公司名 概念股」，必要時 WebFetch 新聞或公司官網。小型冷門股也要查到能判斷為止。
2. 寫出 main_business：主要產品與營收比重摘要（15-50 字，例如「AI伺服器電源45%、筆電電源30%、車用15%」）。
3. themes：從題材詞彙表挑出所有「確實適用」的題材，用「;」分隔，可 0 個或多個。標準：該業務有實際營收或明確量產/出貨/認證，或網路財經媒體確實把它當該題材討論。只是沾邊、尚未有營收的遠期計畫不要列。每個題材後面接證據標記：【業務】= 有營收/產品；【市場】= 主要是媒體/市場把它歸入此題材。例：「液冷散熱【業務】;輝達AI伺服器(GB300/Rubin)【市場】」
4. extra_tags：詞彙表沒有但網路常討論的題材（如「電子紙」「BMC」「漲價概念」），可留空，用「;」分隔。
5. primary_category：從 category_vocab.txt 挑「唯一一個」最能代表它、且網路最常把它跟哪群股票一起討論的細類；都不合適可新造「大類/細類」。
6. confidence：高 / 中 / 低。

輸出：$S/biz_out/<BATCH>.csv，UTF-8，欄位：code,name,main_business,themes,extra_tags,primary_category,confidence
筆數必須與輸入一致、code 不重複，寫完用 python 驗證。也驗證 themes 中每個題材名稱（去掉【業務】【市場】標記後）都精確存在於 theme_vocab.md。
回報（簡短）：筆數、低信心檔數與名單、新造的 primary_category。
