# 05. API 規格書

**文件版本**：v1.0（2026-07-13）｜**Base URL**：`/api/v1`
實作後以 FastAPI 自動生成的 OpenAPI（`/docs`）為準；本文件定義端點框架與慣例。

---

## 1. 通用規格

| 項目 | 規格 |
|---|---|
| 認證 | `Authorization: Bearer <JWT>`；access token 30 分鐘、refresh token 7 天輪替 |
| 分頁 | 請求 `page`（1 起）、`page_size`（預設 20、上限 100）；回應 `{ "items": [...], "total": 123, "page": 1, "page_size": 20 }` |
| 排序 | `sort=-updated_at,name`（`-` 為降冪） |
| 時間 | ISO 8601 含時區，如 `2026-07-13T10:30:00+08:00` |
| 錯誤格式 | `{ "error": { "code": "VALIDATION_ERROR", "message": "…", "field_errors": {"email": "格式不正確"} } }` |
| 常用錯誤碼 | `401 UNAUTHORIZED`、`403 FORBIDDEN`、`404 NOT_FOUND`、`409 CONFLICT`（重複）、`422 VALIDATION_ERROR`、`429 RATE_LIMITED` |
| 權限標記 | 下表「權限」欄：A=Admin、H=HR、M=主管（限自己部門/自己的單） |

## 2. 認證 Auth

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| POST | `/auth/login` | 帳密登入 → `{access_token, refresh_token, user}`；連續失敗鎖定 | 公開 |
| POST | `/auth/refresh` | 換發 access token | 持 refresh |
| POST | `/auth/logout` | 註銷 refresh token | 登入者 |
| GET | `/me` | 目前使用者資訊與權限 | 登入者 |
| PATCH | `/me/password` | 修改密碼 | 登入者 |

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
| GET | `/requisitions` | 清單；`?status=&department_id=&mine=true` | A H M(自己/本部門) |
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

## 7. 報表 Reports

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| GET | `/reports/funnel` | 招募漏斗（推薦→聯繫→面試→錄取）`?from&to&department_id` | A H |
| GET | `/reports/time-to-fill` | 各職缺開缺→補齊天數 | A H |
| GET | `/reports/sources` | 來源成效（p104 / p1111 / 內推 的入庫數與錄取率） | A H |
| GET | `/reports/talent-pool` | 人才庫組成（技能 Top N、年資/地區/學歷分佈、月增量） | A H |

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
