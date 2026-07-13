# samples — 測試樣本資料

本目錄收錄 TalentHub 開發／測試階段使用的樣本資料，涵蓋資料庫種子、HTML 履歷與 PDF 履歷三種形式。所有內容皆用於功能驗證與 Demo，**不對應任何真實個人**。

## 目錄結構

```
samples/
├── db-seed/       # 資料庫種子資料（JSON 原始資料 + PostgreSQL 種子腳本）
├── resumes-html/  # HTML 版履歷（供版面預覽、樣式調校、快速渲染）
└── resumes-pdf/   # PDF 版履歷（供 HR 履歷匯入流程模擬測試）
```

### db-seed/

- `candidates_seed.json`：10 位虛構人才的結構化原始資料（人才主檔、學歷、經歷、技能、語言、證照、自傳）。作為其他樣本與腳本的單一資料來源。
- `candidates_seed.sql`：PostgreSQL 種子腳本，將上述 10 筆資料連同技能字典寫入資料庫。

  執行方式：

  ```bash
  psql -d talenthub -f candidates_seed.sql
  ```

  **前置條件**：須先完成 schema migration（建立 `candidates`、`skills`、`candidate_*` 等資料表與序列），本腳本才能執行。欄位名稱與枚舉值均依 `docs/03-資料庫設計.md`。

### resumes-html/

10 份對應 `candidates_seed.json` 的 HTML 履歷，供版面預覽、樣式調校與瀏覽器快速渲染使用。可直接開啟檢視，或作為前端履歷呈現元件的樣板來源。

### resumes-pdf/

10 份對應同一批人才的 PDF 履歷，作為 **HR 履歷匯入流程** 的測試素材。

## 10 份 PDF 之後如何模擬 HR 匯入

待 **M2 履歷解析功能** 完成後，即可用這 10 份 PDF 模擬真實 HR 的匯入操作：

1. 由 HR 於系統「履歷匯入」介面，將 `resumes-pdf/` 內的 PDF 拖入（或批次上傳）系統。
2. 系統建立 `resume_files` 記錄並觸發解析（`parse_status`：pending → processing）。
3. 解析器輸出結構化 `parsed_payload` 與逐欄位信心分數；低於門檻者進入人工校對（needs_review）。
4. HR 於校對介面確認欄位無誤後入庫，產生 `candidates` 與各子表資料，`resume_files` 轉為 confirmed。
5. 由於 PDF 內容與 `candidates_seed.json` 對應，可據此驗證解析結果的正確性與召回率。

## 聲明與提醒

- **全部資料為虛構**：本目錄中所有人才姓名、聯絡方式、學經歷、公司與自傳皆為測試用途捏造，與真實個人無涉，不得用於任何正式用途。
- **正式解析器仍需以 Phase 0 蒐集的真實下載樣本校準版面**：這批 PDF／HTML 為理想化的乾淨樣本，版面規整、欄位齊全，僅適合功能連通性測試。正式上線的履歷解析器仍必須以 Phase 0 蒐集的真實平台（104／1111 等）下載樣本校準版面與欄位擷取規則，方能反映實際版型的多樣性與雜訊。
