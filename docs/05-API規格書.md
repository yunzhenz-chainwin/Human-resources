# 05. API 規格書

**文件版本**：v1.1（2026-07-16）｜**Base URL**：`/api/v1`
實作後以 FastAPI 自動生成的 OpenAPI（`/docs`）為準；本文件定義端點框架與慣例。

---

## 1. 通用規格

| 項目 | 規格 |
|---|---|
| 認證 | `Authorization: Bearer <JWT>`；access token 30 分鐘、refresh token 7 天輪替 |
| 分頁 | 請求 `page`（1 起）、`page_size`（預設 20、上限 100）；回應 `{ "items": [...], "total": 123, "page": 1, "page_size": 20 }` |
| 輕量分頁 | 部分清單端點（`GET /requisitions`、`GET /applications`）改採選用 `limit`/`offset` 查詢參數，回應為裸陣列，過濾後真實總數置於 `X-Total-Count` response header |
| 排序 | `sort=-updated_at,name`（`-` 為降冪） |
| 時間 | ISO 8601 含時區，如 `2026-07-13T10:30:00+08:00` |
| 錯誤格式 | `{ "error": { "code": "VALIDATION_ERROR", "message": "…", "field_errors": {"email": "格式不正確"} } }` |
| 常用錯誤碼 | `401 UNAUTHORIZED`、`403 FORBIDDEN`、`404 NOT_FOUND`、`409 CONFLICT`（重複）、`422 VALIDATION_ERROR`、`429 RATE_LIMITED` |
| 權限標記 | 下表「權限」欄：A=Admin、H=HR、M=主管（限自己部門/自己的單） |

## 2. 認證 Auth

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| POST | `/auth/login` | 帳密登入 → `{access_token, refresh_token, expires_in}`；連續失敗達門檻回 `429` + `Retry-After`（帳號級短時自動過期鎖） | 公開 |
| POST | `/auth/refresh` | 換發 access token | 持 refresh |
| POST | `/auth/logout` | 撤銷所持 refresh token（僅限本人、冪等） | 登入者 |
| POST | `/auth/change-password` | 修改密碼 `{current_password, new_password}`（`new_password` ≥ 12 碼）；成功後清除 `must_change_password`、撤銷全部 refresh token、令既發 access token 失效 | 登入者 |
| GET | `/me` | 目前使用者資訊與權限（含 `must_change_password`） | 登入者 |

> **強制改密流程**：IT 重設密碼（`POST /admin/users/{id}/reset-password`）或管理員設定密碼後，該帳號 `must_change_password` 生效並即時令既發 token 失效；使用者首次登入後、正式使用前須先呼叫 `POST /auth/change-password` 改密。完成改密前，除 `/auth/change-password`、`/auth/logout`、`/me` 外的受管端點一律回 `403`。

## 3. 人才 Candidates

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| POST | `/candidates/search` | 複合條件搜尋（body 見 §3.1） | A H |
| GET | `/candidates/{id}` | 人才詳情（含子表）；讀取寫入稽核 | A H M(遮罩) |
| POST | `/candidates` | 手動建檔 | A H |
| PATCH | `/candidates/{id}` | 更新欄位 | A H |
| DELETE | `/candidates/{id}` | 軟刪除 | A H |
| POST | `/candidates/{id}/status` | 變更狀態 `{status, note}`，寫入活動紀錄 | A H |
| GET / POST | `/candidates/{id}/activities` | 聯繫紀錄查詢 / 新增 | A H |
| POST / DELETE | `/candidates/{id}/tags` | 貼標 / 移除標籤 | A H |
| POST | `/candidates/merge` | 合併重複 `{primary_id, duplicate_id}` | A H |
| GET | `/candidates/{id}/matches` | 此人才適合的招募中職缺（反向配對） | A H |
| GET | `/candidates/{id}/files` | 原始履歷檔清單與預簽名下載網址 | A H |
| POST | `/candidates/{id}/anonymize` | 匿名化（當事人請求/到期處理） | A |
| POST | `/candidates/export` | 匯出 CSV/XLSX（非同步產檔，稽核記錄） | A H |

### 3.1 搜尋請求範例

```json
POST /candidates/search
{
  "keyword": "python 後端",
  "filters": {
    "skills_all": ["Python"],
    "skills_any": ["FastAPI", "Django"],
    "min_years": 3,
    "cities": ["台北市", "新北市", "桃園市"],
    "education_gte": "bachelor",
    "expected_salary_lte": 70000,
    "status_in": ["new", "talent_pool"],
    "sources": ["p104"],
    "tags": ["2026校園徵才"],
    "updated_after": "2026-01-01"
  },
  "sort": "-updated_at",
  "page": 1,
  "page_size": 20
}
```

## 4. 履歷檔案 Resumes

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| POST | `/resumes/upload` | multipart 多檔/ZIP 上傳 → 回傳各檔 `resume_id` 與佇列狀態 | A H |
| GET | `/resumes` | 清單；`?parse_status=needs_review` 取校對佇列 | A H |
| GET | `/resumes/{id}` | 解析結果（`parsed_payload` + 逐欄信心 + 原檔預覽網址） | A H |
| PUT | `/resumes/{id}/parsed` | 校對修改解析欄位（存回 payload） | A H |
| POST | `/resumes/{id}/confirm` | 確認入庫：`{mode: "create" \| "update", candidate_id?}` | A H |
| POST | `/resumes/{id}/reparse` | 重新解析（解析器修復後） | A H |
| GET | `/resumes/{id}/file` | 原始檔預簽名下載 | A H |
| GET | `/resumes/stats` | 匯入統計（今日/本週：成功、待校對、失敗） | A H |

## 5. 職缺需求 Requisitions

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| GET | `/requisitions` | 清單；`?status=&department_id=&mine=true`；選用 `limit`/`offset`，總數見 `X-Total-Count` header | A H M(自己/本部門) |
| POST | `/requisitions` | 建立（`draft` 或直接 `submit`） | A H M |
| GET | `/requisitions/{id}` | 詳情（含技能條件、簽核軌跡） | A H M(自己) |
| PATCH | `/requisitions/{id}` | 修改（限 draft / returned） | A H M(自己) |
| POST | `/requisitions/{id}/submit` | 送審 | M(自己) H |
| POST | `/requisitions/{id}/approve` | 核准 → 觸發首次配對 | A H |
| POST | `/requisitions/{id}/return` | 退回 `{reason}` | A H |
| POST | `/requisitions/{id}/close` | 結案 `{result: filled \| cancelled, note}` | A H |
| GET | `/requisitions/{id}/matches` | 推薦名單；`?min_score=&status=` | A H M(自己) |
| POST | `/requisitions/{id}/rematch` | 手動重新配對 | A H |

## 6. 配對 Matches

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| POST | `/matches/{id}/feedback` | 主管回饋 `{status: "interview" \| "rejected_by_manager", reason?}` | M(自己職缺) |
| POST | `/matches/{id}/status` | HR 更新進度（contacted / offered / hired…） | A H |
| GET | `/requisitions/{id}/matching-criteria` | 讀取職缺媒合條件（`MatchingCriteria`，見 §6.2） | A H M(自己) |
| PUT | `/requisitions/{id}/matching-criteria` | 更新媒合條件並即時重配對 | A H |

### 6.1 推薦名單回應範例

```json
{
  "items": [{
    "match_id": 501,
    "candidate": { "id": 88, "code": "T2026-00088", "name": "王○明",
                   "current_title": "後端工程師", "total_years": 6.0,
                   "phone": "0912***678", "email": "m***@gmail.com" },
    "total_score": 92.5,
    "rank": 1,
    "status": "recommended",
    "score_breakdown": {
      "skill":     { "weight": 0.4,  "score": 1.0, "hit": ["Python","FastAPI","PostgreSQL"], "miss": [] },
      "relevance": { "weight": 0.2,  "score": 0.85 },
      "years":     { "weight": 0.15, "score": 1.0, "note": "6y 落於 5–10y" },
      "salary":    { "weight": 0.1,  "score": 0.7 },
      "education": { "weight": 0.1,  "score": 1.0 },
      "location":  { "weight": 0.05, "score": 1.0 }
    }
  }],
  "total": 20, "page": 1, "page_size": 20
}
```
> 聯絡資訊依角色遮罩（`mask.manager_contact` 設定）；HR 取得完整值。
> `score_breakdown.near_miss=true` 標示「僅差一項硬條件、但整體分數 ≥ 60」的 stretch 人選，供 HR 覆核。

### 6.2 媒合條件 MatchingCriteria

`required_skills`、`preferred_skills`、`min_years`、`education_req`、`work_city`、`salary_min`、`salary_max`，以及硬門檻開關 `require_skills`、`require_years`、`require_education`、`require_location`（預設全開）。

新增 `required_skill_ratio`（0–1，預設 `1.0`）：`1.0` 表示須具備全部 required 技能；調低則命中比例達標即通過技能硬門檻，用於放行「只差一兩項」的強配對。地點硬門檻已放寬為「接受鄰近城市」，與地點軟分數一致。

## 7. 報表 Reports

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| GET | `/reports/funnel` | 招募漏斗（推薦→聯繫→面試→錄取）`?from&to&department_id` | A H |
| GET | `/reports/time-to-fill` | 各職缺開缺→補齊天數 | A H |
| GET | `/reports/sources` | 來源成效（p104 / p1111 / 內推 的入庫數與錄取率） | A H |
| GET | `/reports/talent-pool` | 人才庫組成（技能 Top N、年資/地區/學歷分佈、月增量） | A H |
| GET | `/reports/matching-evaluation` | 媒合品質評估（見 §7.1）；`?requisition_id=`（省略＝全公司彙總） | A H M(本部門) |

### 7.1 媒合評估報表 matching-evaluation

以 `match_results` 的人工標記結果為真值（`interview`／`offered`／`hired` 為正向，`rejected_by_manager`／`withdrawn` 為負向），量測排序與硬門檻是否可靠。回應欄位：

| 欄位 | 說明 |
|---|---|
| `sample_size` / `labeled_outcomes` | 樣本數與已標記筆數 |
| `precision_at_k` | `{ "5": …, "10": … }`，前 K 名推薦的正向比例 |
| `recall_at_k` | `{ "5": …, "10": … }`，用於抓被 gate 誤殺的好人選 |
| `gate_false_negatives` | 被硬門檻淘汰、事後卻獲正向結果的人數（gate 誤殺） |
| `score_calibration[]` | 分數分桶（如 0–20…80–100）對應的實際正向率 |
| `rank_effectiveness` | 排名有效性：名次越前是否對應越高正向率 |
| `notes[]` | 樣本不足或門檻警示等提示 |

需累積約 30 筆標記結果，指標才足以支撐自動調權重；未達門檻時 `notes` 會提示樣本不足。權限：HR/admin 可查全公司，主管限本部門（`requisition_id` 省略時回傳其可視範圍彙總）。

## 8. 通知 Notifications

| Method | Path | 說明 |
|---|---|---|
| GET | `/notifications?unread=true` | 我的通知 |
| POST | `/notifications/{id}/read`、`/notifications/read-all` | 標記已讀 |

觸發事件：需求單送審/核准/退回、解析批次完成、待校對積壓 > N 件、新推薦人選入榜、主管回饋、保存期限將至。

## 9. 後台 Admin

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| CRUD | `/admin/users` | 使用者管理（停用而非刪除） | A |
| CRUD | `/admin/departments` | 部門樹 | A |
| CRUD | `/admin/skills` | 技能字典；`POST /admin/skills/merge` 合併別名 | A H |
| CRUD | `/admin/tags` | 標籤管理 | A H |
| GET / PUT | `/admin/settings` | 系統參數（權重、門檻、保存期限、遮罩開關） | A |
| GET | `/admin/audit-logs` | 稽核查詢 `?user_id=&action=&entity=&from&to` | A |
