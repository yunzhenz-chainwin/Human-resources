# 人才庫定期清理 Worker

人才資料的保存期限由 `candidate.retention_years` 設定，預設為 2 年；管理者可在人才庫政策中設定 1–20 年，單筆人才也可以覆寫保存年限。到期後 worker 會分批清理人才個資與履歷檔，並透過 durable outbox 重試儲存檔刪除失敗的工作。

## 正式環境啟用

在實際 API 服務使用的 `.env` 設定：

```env
TALENT_RETENTION_WORKER_ENABLED=true
TALENT_RETENTION_WORKER_INITIAL_DELAY_SECONDS=30
TALENT_RETENTION_WORKER_INTERVAL_SECONDS=86400
TALENT_RETENTION_BATCH_SIZE=500
TALENT_RETENTION_MAX_BATCHES_PER_RUN=20
```

`TALENT_RETENTION_WORKER_ENABLED` 預設為 `false`，避免開發環境意外刪除資料。正式環境只應在一個 API instance 啟用；若多個 instance 都啟用，PostgreSQL advisory lock 會確保同一批清理不會重複執行，但仍建議只啟用一個 instance 以降低背景工作量。

修改環境變數後請重新啟動 API 服務。worker 啟動後會等待 initial delay，再依 interval 執行清理；每次最多處理 `batch_size × max_batches_per_run` 筆，避免單次工作占用過久。

## 驗證與安全操作

- 後台「預演到期清理」只會列出影響筆數，不會刪除資料。
- 清理 API 預設也是 dry-run；只有明確傳入執行參數才會實際清理。
- 每次實際清理會寫入 audit log。
- 啟用前先確認資料庫備份、履歷儲存路徑與 outbox 重試監控。

本機可執行 retention 測試：

```powershell
python -m pytest backend/tests/test_talent_retention.py -q
```
