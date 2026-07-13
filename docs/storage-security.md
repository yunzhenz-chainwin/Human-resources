# 履歷檔案儲存與惡意檔案掃描

履歷上傳固定經過以下順序：隔離區串流寫入與大小限制、PDF/DOC/DOCX 簽章驗證、ClamAV 掃描、正式儲存、文字解析。感染檔案或嚴格政策下的掃描失敗不會進入正式儲存，也不會傳給解析器。

## 掃描政策

- 本機預設：`APP_ENV=development`、`RESUME_SCANNER=none`、`RESUME_SCAN_POLICY=allow_unavailable`。這是明確的開發例外，並非已完成掃描。
- 本機嚴格模式：設定 `RESUME_SCANNER=clamav`、`RESUME_SCAN_POLICY=fail`。
- staging／production：掃描器 unavailable 或 error 一律 fail-closed（HTTP 503），即使誤設 `allow_unavailable` 也不會跳過。
- ClamAV 發現感染檔案一律拒絕（HTTP 422），並清除隔離檔。

## 儲存 Provider

- `local`：以隨機 UUID key 寫入 `RESUME_STORAGE_PATH`，並阻擋絕對路徑、`..` 與反斜線 traversal。
- `s3`：使用 boto3，支援 AWS S3 或 MinIO 的上傳、下載暫存與刪除。設定 `S3_BUCKET`、endpoint、region、access key、secret key 與 TLS 開關。
- 原始檔名只作為資料庫顯示資訊，永遠不作為實際 storage key，因此同名履歷不會互相覆蓋。

可用獨立的 `deploy/compose.storage.yml` 啟動 MinIO 與 ClamAV。正式環境應固定映像版本、改用 secret manager，並限制 9000、9001、3310 連接埠只供內部網路使用。
