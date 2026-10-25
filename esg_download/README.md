# esg-carbon-sink

用 GitHub Actions 平行下載台灣上市櫃永續報告書（2013～2025，共 9,695 份），
PDF、逐頁全文、自然碳匯關鍵字段落上傳到 Google Cloud Storage。

- `manifest.json`：報告清單（來源：證交所 ESG 平台、公開資訊觀測站）
- `worker.py`：每個 job 處理 manifest 的一個 shard，可重跑（已完成的會跳過）
- `extract.py`：抽字與關鍵字段落
- 執行：Actions → download-reports → Run workflow
