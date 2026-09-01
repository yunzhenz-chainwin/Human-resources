# samples — 測試樣本資料

本目錄收錄 TalentHub 開發／測試用的樣本資料。所有內容皆為虛構，僅供功能驗證與 Demo，**不對應任何真實個人**。

```
samples/
└── db-seed/   # 資料庫種子資料（JSON 原始資料 + PostgreSQL 種子腳本）
```

（HTML／PDF 履歷樣本不隨 repo 提供；履歷匯入測試請自備合法取得的檔案。）

## db-seed/candidates_seed.json

10 位虛構人才的結構化原始資料：人才主檔（基本資料、期望條件、自傳）加上學歷、經歷、技能、語言、證照區塊，可作為產生測試履歷或撰寫匯入腳本的資料來源。注意：語言與證照只存在於 JSON——現行資料庫**刻意未建** `candidate_languages`／`candidate_certifications` 表。

## db-seed/candidates_seed.sql

依 2026-07 初版 schema 撰寫的 PostgreSQL 種子腳本，寫入上述 10 筆人才與技能字典。**與現行 migrations 已有差異，直接執行會失敗**：

- 寫入的 `skills` 表已不存在；現行技能字典是 `skill_catalog`（唯一鍵為 `name_norm`，非 `name`）。
- 現行 `candidate_skills` 直接存 `skill`／`skill_norm` 文字欄位，沒有 `skill_id` 與 `source`。
- `candidate_languages`、`candidate_certifications` 兩表從未建立。
- `candidates.expected_cities` 現為 JSON 欄位，腳本中的 `ARRAY[...]` 字面值型別不符。

（`candidates` 其餘欄位與 `candidate_educations`、`candidate_experiences` 仍與現行 schema 相符。）若確有需要，請先對照 `backend/alembic/versions/` 調整後再執行；日常開發請改用系統內建種子：

```powershell
Set-Location backend
$env:APP_ENV = "development"   # production／staging 會拒絕 seeding
python seed_initial_data.py
```

## 參考與提醒

- 資料庫設計說明見手冊第 03 章（[docs/TalentHub_系統文件與交接手冊.docx](../docs/TalentHub_系統文件與交接手冊.docx)）；實際結構以 `backend/app/models/` 與 `backend/alembic/versions/` 為準。
- **全部資料為虛構**：姓名、聯絡方式、學經歷、公司與自傳皆為測試用途捏造，與真實個人無涉，不得用於任何正式用途。
- 這批樣本為理想化的乾淨資料，僅適合功能連通性測試；正式上線的履歷解析器仍必須以合法取得、經授權且去識別的真實平台（104／1111 等）下載樣本校準版面與欄位擷取規則。
