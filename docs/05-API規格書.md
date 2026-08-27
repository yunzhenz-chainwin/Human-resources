# 05. API 規格書

**文件版本**：v1.4（2026-08-27）｜**Base URL**：`/api/v1`
實作後以 FastAPI 自動生成的 OpenAPI（`/docs`）為準；本文件定義端點框架與慣例。

---

## 1. 通用規格

| 項目 | 規格 |
|---|---|
| 認證 | `Authorization: Bearer <JWT>`；access token 15 分鐘、refresh token 7 天輪替 |
| 分頁 | 部分清單（`GET /candidates`、`GET /resumes`）採 `page`（1 起）、`page_size`（預設 20、上限 100），回應為**裸陣列** |
| 輕量分頁 | 另一批清單端點（`GET /requisitions`、`GET /applications`、matches 相關）採選用 `limit`/`offset` 查詢參數，過濾後真實總數置於 `X-Total-Count` response header（`GET /requisitions/{id}/matches` 回 `{items, total}`） |
| 排序 | 各清單為伺服器固定排序（多為 `updated_at`／建立時間降冪、配對依 rank）；尚無 `sort` 查詢參數 |
| 時間 | ISO 8601；資料庫以 UTC 儲存，回應含時區資訊 |
| 錯誤格式 | FastAPI 慣例 `{ "detail": "訊息" }`；`422` 驗證錯誤時 `detail` 為欄位錯誤陣列 |
| 常用錯誤碼 | `401`、`403`、`404`、`409`（重複/狀態衝突）、`413`（檔案過大）、`415`（格式不符）、`422`、`429`（登入鎖定/公開上傳限流）、`503`（掃毒不可用，fail-closed） |
| 權限標記 | 下表「權限」欄：A=相容管理員（admin）、H=HR、M=主管（限自己部門/自己的單）、IT=資訊管理員。IT 僅使用系統管理端點（§10），招募端點（人才、履歷、配對、面試）一律拒絕，不接觸招募個資 |

## 2. 認證 Auth

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| POST | `/auth/login` | 帳密登入 → `{access_token, refresh_token, expires_in}`；連續失敗達門檻回 `429` + `Retry-After`（帳號級短時自動過期鎖） | 公開 |
| POST | `/auth/refresh` | 換發 access token | 持 refresh |
| POST | `/auth/logout` | 撤銷所持 refresh token（僅限本人、冪等） | 登入者 |
| POST | `/auth/change-password` | 修改密碼 `{current_password, new_password}`（`new_password` ≥ 12 碼）；成功後清除 `must_change_password`、撤銷全部 refresh token、令既發 access token 失效 | 登入者 |
| GET | `/auth/me` | 目前使用者資訊與權限（含 `must_change_password`） | 登入者 |

> **強制改密流程**：IT 重設密碼（`POST /admin/users/{id}/reset-password`）或管理員設定密碼後，該帳號 `must_change_password` 生效並即時令既發 token 失效；使用者首次登入後、正式使用前須先呼叫 `POST /auth/change-password` 改密。完成改密前，除 `/auth/change-password`、`/auth/logout`、`/auth/me` 外的受管端點一律回 `403`。

## 3. 人才 Candidates

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| GET | `/candidates` | 清單＋條件搜尋（query 見 §3.1）；主管請改用 `/department/workspace` | A H |
| GET | `/candidates/{id}` | 人才詳情（技能/經歷/學歷、應徵與履歷摘要）；讀取寫入 PII 稽核 | A H M(遮罩，僅見本部門應徵，不含原始履歷) |
| POST | `/candidates` | 手動建檔（自動編號、套用保存期限） | A H |
| PATCH | `/candidates/{id}` | 更新欄位（Email/電話同步正規化鍵） | A H |
| DELETE | `/candidates/{id}` | 軟刪除；仍有進行中應徵回 `409` | A H |
| GET / POST | `/candidates/{id}/activities` | 聯繫／留言紀錄查詢、新增（可附 `next_status` 變更人才狀態；主管可留言但帶 `next_status` 回 `403`） | A H M(範圍內) |
| PUT / GET / DELETE | `/candidates/{id}/photo` | 大頭照上傳（5 MB、JPEG/PNG/WebP）／讀取／移除 | A H（讀取含 M 範圍內） |
| GET / POST | `/candidates/{id}/consents`、POST `/consent/candidate-consents/{id}/withdraw` | 個資同意紀錄查詢／補登／撤回 | A H |
| GET / PUT | `/talent-retention/policy`、PUT `/talent-retention/candidates/{id}`、POST `/talent-retention/purge` | 保存年限政策、個別覆寫與到期清理 | A H |

> 規劃中（尚未實作）：合併重複、貼標／移除標籤、反向配對（人才→職缺）、匿名化、CSV/XLSX 匯出。

### 3.1 搜尋參數範例

```
GET /candidates?q=後端&skill=Python&status=new&min_years=3&city=台北市&department_id=2&page=1&page_size=20
```

`q` 比對姓名／職稱／編號／Email；`skill` 走正規化技能鍵（`skill_norm`）；條件間為 AND；回應為裸陣列。

## 4. 履歷檔案 Resumes

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| POST | `/resumes/upload` | multipart 多檔上傳（PDF/DOC/DOCX，單檔 10 MB，**不支援 ZIP**）；表單欄位 `source_platform`、`candidate_id?`、`requisition_id?`（主管必填職缺）；同步解析後回傳各檔 `resume_id`、`parse_status`、來源判別與 `duplicate` 旗標；掃毒 fail-closed（422/503） | A H M(限本部門職缺) |
| GET | `/resumes` | 清單；`?parse_status=needs_review` 取校對佇列，另有 `source_platform`、`query`、`include_confirmed`、`page/page_size` | A H |
| GET | `/resumes/{id}` | 解析結果（`parsed_payload`、逐欄信心、來源判別依據） | A H |
| PUT | `/resumes/{id}/parsed` | 校對修改解析欄位（存回 payload，改過欄位信心=1.0）；已確認回 `409` | A H |
| PUT | `/resumes/{id}/source` | 人工指定來源平台（來源待確認時必經此步才能入庫） | A H |
| POST | `/resumes/{id}/confirm` | 確認入庫：body 選填 `{candidate_id?}`；未指定時依 email/phone 去重自動「建立或更新」人才（回 `created`）；有目標職缺則同時建立應徵紀錄 | A H |
| POST | `/resumes/{id}/reparse` | 重新解析（解析器修復後）；已確認回 `409` | A H |
| GET | `/resumes/{id}/file` | 原始檔下載（登入直接下載並寫稽核；非預簽名網址） | A H |
| GET | `/resumes/{id}/preview` | 原始 PDF 內嵌預覽（inline；僅 PDF，寫稽核） | A H |

> 原始履歷檔與解析內容一律擋在 HR／相容管理員邊界內：主管呼叫上述讀取端點回 `403`，改用去識別化文件（§4.1）。

### 4.1 去識別化文件 De-identified Resumes

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| POST / GET | `/resumes/{id}/deidentifications` | 上傳去識別化 PDF 版本（版本化保存、自動掃描殘留個資與可讀性）／列出版本 | 上傳 A H；列出含 M(僅已核准) |
| GET | `/candidates/{id}/deidentified-resumes` | 該人才可用的去識別化文件（主管僅見已核准版本） | A H M |
| GET | `/deidentified-resumes/{id}/preview`、`/file` | 預覽／下載去識別化文件 | A H M(已核准) |
| POST | `/deidentified-resumes/{id}/approve`、`/reject` | 核准／退回；`validation_summary.blocker_count > 0`（含 pypdf 無法開啟的 PDF）時不可核准 | A H |
| POST | `/deidentified-resumes/{id}/analyses/recommended-roles`、`/role-match` | 依去識別化內容做職位推薦／單一職缺適配分析 | A H M(部門範圍) |

## 5. 職缺需求 Requisitions

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| GET | `/requisitions` | 清單；`?status=`；選用 `limit`/`offset`，總數見 `X-Total-Count` header；主管自動限本部門 | A H M(本部門) |
| POST | `/requisitions` | 建立（狀態限 `draft` 或 `submitted`；發佈須走核准流程） | A H |
| POST | `/requisitions/lint` | 反歧視用語檢查（就服法 §5 等）：掃描職稱/摘要/JD 並回改寫建議，僅警示不擋存檔 | A H M |
| GET | `/requisitions/{id}` | 詳情（含技能條件、狀態時間戳） | A H M(本部門) |
| PATCH | `/requisitions/{id}` | 修改欄位與**狀態機轉換**（draft→submitted→approved→sourcing/interviewing→filled→closed，submitted 可退回 returned；不合法轉換回 `409`）；`blind_review_enabled`、`composite_score_weights` 規則見 §5.1／§5.2 | A H |
| POST | `/requisitions/{id}/approve` | 核准（draft/submitted/returned → approved；不會自動觸發配對，配對見 §6 rematch） | A H |
| GET | `/requisitions/{id}/matches` | 推薦名單；`?min_score=&status=&source=&include_ineligible=&limit=&offset=` | A H M(自己) |
| POST | `/requisitions/{id}/rematch` | 手動重新配對（重寫履歷分數並於**同一交易**重算綜合參考分） | A H |

> 送審、退回、結案沒有獨立端點，一律以 `PATCH /requisitions/{id}` 的 `status` 轉換完成。
> **部門主管**另走部門端點：`POST /department/requisitions`（建立即為 `submitted` 送審、部門自動鎖定）、
> `PUT /department/requisitions/{id}`、`DELETE /department/requisitions/{id}`（已有應徵者回 `409`）、
> `GET /department/workspace`（本部門職缺＋實際應徵者），權限皆為 M(本部門)。

### 5.1 面試評分揭露規則 `blind_review_enabled`

職缺層級的布林欄位，決定該職缺的面試採盲評（`true`，預設）或 HR 與主管即時互看評分（`false`）。建立與修改走相同規則：

- 只有 `hr` 能把值設成非預設；其他角色送出變更回 `403`。POST 與 PATCH 皆適用，建立時省略或重述預設值不算一次決策，因此送整份表單的 client 不受影響。
- 該職缺一旦有任何面試紀錄正式提交，欄位即鎖定，再變更回 `409`，訊息為「已有面試提交紀錄，評分揭露規則不可變更」。唯讀的 `blind_review_locked` 供前端先行停用控制項。
- 變更成功會寫入 `requisition.blind_review.update` 稽核紀錄（含變更前後值）。

遮罩與釋出時機見 [13-結構化面試評分與盲評操作規格](13-結構化面試評分與盲評操作規格.md) §6。

### 5.2 綜合參考分權重 `composite_score_weights`

職缺層級的選填 JSON 欄位，決定五個分數（`resume` 履歷匹配、`hr_questions`、`hr_overall`、`manager_questions`、`manager_overall`）如何加權成應徵的綜合參考分。`NULL` 代表內建 20/15/25/15/25；部分覆寫只影響指名的鍵。比較與呈現一律使用正規化成總和 1 的 `composite_score_weights_resolved`：以相同比例的另一種寫法重述（如 40/30/50/30/50）不算一次變更。

- 只有 `hr` 能送出真實變更（PATCH `/requisitions/{id}`）；其他角色回 `403`。未知鍵或負值回 `422`；全零總和視同未設定，伺服器退回內建權重。
- 真實變更會立即以新權重重算該職缺**所有**已儲存的綜合分——同一份名單不能一半用舊權重、一半用新權重排序——並寫入 `requisition.composite_score_weights.update` 稽核紀錄，內含前後權重與每筆移動的綜合分（`recomputed_applications`）。
- 綜合分存於應徵：`GET /applications` 回應含 `composite_score`（兩位小數，雙方皆提交後才有值）與 `composite_score_breakdown`（各分量取值、實際套用權重、缺項原因；未齊時 `status="pending_stages"`）。重新配對（rematch）改寫履歷配對分數時，會在同一交易重算綜合分。

計算規則以實作為準（`backend/app/services/interview_scoring.py`）：缺項不以 0 計、同一階段內缺項權重折算給另一分量、其餘缺項重新正規化、Decimal 四捨五入到兩位；雙方提交前不出現任何部分綜合分，與盲評釋出規則一致。評分面的完整規則見 [13-結構化面試評分與盲評操作規格](13-結構化面試評分與盲評操作規格.md) §6（盲評釋出）與 §9 第 8 項（綜合參考分）。

## 6. 配對 Matches

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| GET | `/requisitions/{id}/candidates/{candidate_id}/match` | 單筆讀取該人才在此職缺的配對分數，回應與清單中的單一項目同形（含主管聯絡資訊遮罩）；面試卡片只需一個分數時使用，不必下載整份名單 | A H M(自己) |
| GET | `/requisitions/{id}/candidate-match-overview` | 全體人才總覽（含尚未計算配對者）；`?source=applicants\|talent_pool\|all`，回應含已計算/未計算與應徵/人才庫計數 | A H M(自己) |
| GET | `/requisitions/{id}/match-readiness` | 配對前檢查（樣本量與條件是否足以排序） | A H M(自己) |
| POST | `/matches/{id}/feedback` | 主管回饋 `{status: "interview" \| "rejected_by_manager", reason_category?, note?}`；婉拒必附結構化原因（`reason_category`；`other` 需備註），舊欄位 `reason` 僅保留相容 | M(自己職缺) H A |
| POST | `/matches/{id}/status` | HR 更新進度（contacted / offered / hired…） | A H |
| POST | `/matches/{id}/manual-override` | 未過硬門檻的例外覆核：附結構化原因後推進階段；已過門檻或已錄取回 `409`，寫入稽核 | A H M(自己職缺) |
| GET / PUT | `/requisitions/{id}/matching-weights` | 讀取／調整六面向權重（skill/relevance/years/salary/education/location），PUT 後即時重配對並寫稽核 | A H M(自己) |
| GET | `/requisitions/{id}/matching-criteria` | 讀取職缺媒合條件（`MatchingCriteria`，見 §6.2） | A H M(自己) |
| PUT | `/requisitions/{id}/matching-criteria` | 更新媒合條件並即時重配對 | A H |
| POST | `/requisitions/{id}/matching-criteria/preview` | 試算條件變更的門檻影響（不落地、不改動已存配對） | A H |

單筆讀取沿用清單的權限判斷，不另寫一套：職缺不存在回 `404`、跨部門回 `403`，人才則套用與清單相同的可見範圍條件。凡是尚未計算配對、人才已軟刪除，或人才不在呼叫者可見範圍內，一律回 `404`——刻意不用 `403` 區分，以免回應反過來證實一組呼叫者無權查看的配對確實存在。`min_score`、`status` 等是清單的顯示篩選而非權限，故不套用；成立的保證是：此端點只會回傳同一位呼叫者用清單查詢也能看到的資料列。

### 6.1 推薦名單回應範例

```json
{
  "items": [{
    "id": 501,
    "requisition_id": 12,
    "candidate_id": 88,
    "candidate": { "id": 88, "code": "T2026-00088", "name": "王○明",
                   "current_title": "後端工程師", "total_years": 6.0,
                   "phone": "*******678", "email": "m***@gmail.com" },
    "gate_passed": true,
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
  "total": 20
}
```
> 主管角色一律套用聯絡資訊遮罩（電話保留末 3 碼、Email 保留首字元；由程式固定套用，非系統設定項）；HR／相容管理員取得完整值。
> `score_breakdown.near_miss=true` 標示「僅差一項硬條件、但整體分數 ≥ 60」的 stretch 人選，供 HR 覆核；另附 `recommendation` 與 `highlights` 說明推薦理由。

### 6.2 媒合條件 MatchingCriteria

`required_skills`、`preferred_skills`、`min_years`、`education_req`、`work_city`、`salary_min`、`salary_max`，以及硬門檻開關 `require_skills`、`require_years`、`require_education`、`require_location`（預設全開）。

新增 `required_skill_ratio`（0–1，預設 `1.0`）：`1.0` 表示須具備全部 required 技能；調低則命中比例達標即通過技能硬門檻，用於放行「只差一兩項」的強配對。地點硬門檻已放寬為「接受鄰近城市」，與地點軟分數一致。

## 7. 應徵與結構化面試 Applications / Interviews

應徵紀錄（application）是人才×職缺的正式關聯，面試端點都掛在它底下：

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| GET | `/applications` | 清單；`?requisition_id=&department_id=`＋`limit`/`offset`（總數見 `X-Total-Count`）；回應含 `composite_score`／`composite_score_breakdown`（§5.2）；主管自動限本部門 | A H M(本部門) |
| POST | `/applications` | HR 把人才庫人選指派到職缺（重複指派回 `409`，來源 `manual_hr`） | A H |
| PATCH | `/applications/{id}/assignment` | 更正應徵的職缺/部門歸屬（已有面試或錄取歷程回 `409`） | A H |
| POST | `/applications/{id}/mark-interview-ready` | HR 標記「確定面試」；只要**已存在任何結構化面試紀錄**或舊制階段資料即回 `409`，非面試前狀態亦回 `409` | A H |
| PATCH | `/applications/{id}/interviews/{stage}` | 舊制（非結構化）階段欄位：時間、結果、備註 | H（hr 階段）／M(本部門，manager 階段) |

完整欄位、完成鎖定、修訂與雙方盲評契約見 [13-結構化面試評分與盲評操作規格](13-結構化面試評分與盲評操作規格.md)。下表只保留 API 導覽。

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| GET | `/applications/{id}/interview-question-plan?stage=hr\|manager` | 取得該應徵、階段的最新題組與版本 | A H M（部門範圍） |
| POST | `/applications/{id}/interview-question-plan/generate?stage=...&force=false` | 初次產生或建立新題組版本 | H（HR 階段）／M（主管階段） |
| POST | `/applications/{id}/interview-question-plan/questions/{index}/regenerate?stage=...` | 只重產指定題並建立新版本，其餘題與舊版保留 | H／M（各自階段） |
| POST | `/applications/{id}/interview-question-suggestions` | 依職務證據與選定特質產生額外追問題建議 | A H M（部門範圍） |
| GET | `/applications/{id}/interview-records` | 列出面試紀錄；盲評釋出前遮罩另一方評分結論 | A H M（部門範圍） |
| GET | `/applications/{id}/interview-records/{record_id}` | 讀取單筆紀錄及提交／修訂中繼資料 | A H M（部門範圍） |
| POST | `/applications/{id}/interview-records` | 建立草稿或直接正式提交 | H（HR 階段）／M（主管階段） |
| PATCH | `/applications/{id}/interview-records/{record_id}` | 更新未完成紀錄；`completed` 一般修改回 `409` | H／M（各自階段） |
| POST | `/applications/{id}/interview-records/{record_id}/reopen` | 以 `{ "reason": "..." }` 重開已完成紀錄 | H／M（各自階段） |

正式提交為 `completed` 時：每題必須有 `rating=1..5` 或非空 `not_asked_reason`（兩者互斥），且必填面試總分（`overall_score` 0–100；舊紀錄可用 `overall_rating` 1–5，擇一即可）、`recommendation` 與非空 `summary`；違反回 `422`。IT 不屬招募角色，不能透過面試 API 讀取紀錄。

## 8. 報表 Reports

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| GET | `/reports/funnel` | 招募漏斗（推薦→聯繫→面試→錄取）`?from&to&department_id` | A H M(自動限本部門) |
| GET | `/reports/time-to-fill` | 各職缺開缺→補齊天數 | A H M(自動限本部門) |
| GET | `/reports/sources` | 來源成效（career_site / p104 / p1111 / 內推… 的投遞數與錄取率） | A H M(自動限本部門) |
| GET | `/reports/talent-pool` | 人才庫組成（技能 Top N（`skill_limit`，預設 20）、年資/地區/學歷分佈、月增量） | A H M(自動限本部門) |
| GET | `/reports/matching-evaluation` | 媒合品質評估（見 §8.1）；`?requisition_id=`（省略＝可視範圍彙總） | A H M(本部門) |

### 8.1 媒合評估報表 matching-evaluation

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

## 9. 通知 Notifications（規劃中，尚未實作）

目前系統**沒有站內通知端點**；前端僅以側欄「新增人才」徽章顯示待校對數（由清單即時計算）。以下為規劃框架：

| Method | Path | 說明 |
|---|---|---|
| GET | `/notifications?unread=true` | 我的通知 |
| POST | `/notifications/{id}/read`、`/notifications/read-all` | 標記已讀 |

規劃觸發事件：需求單送審/核准/退回、解析批次完成、待校對積壓 > N 件、新推薦人選入榜、主管回饋、保存期限將至。

## 10. 後台 Admin

系統管理端點由 **IT（資訊管理員）與相容管理員**使用；HR 只開放使用者相關端點（且僅能檢視/管理 `hr`、`manager` 帳號）。

| Method | Path | 說明 | 權限 |
|---|---|---|---|
| GET / POST / PATCH | `/admin/users` | 使用者管理（停用而非刪除，無 DELETE） | IT A（GET/POST/PATCH 含 H，限 hr/manager 帳號） |
| POST | `/admin/users/{id}/reset-password` | 產生 24 碼臨時密碼並強制首登改密（§2） | IT A |
| GET / POST / PATCH | `/admin/departments` | 部門維護（清單含 H） | IT A |
| GET / POST / DELETE | `/admin/skills` | 技能字典（合併別名功能未實作） | IT A |
| GET / POST / DELETE | `/admin/tags` | 標籤管理 | IT A |
| GET / PUT | `/admin/settings`、`/admin/settings/{key}` | 系統參數（鍵值設定，機密值遮罩顯示） | IT A |
| GET | `/admin/audit-logs` | 稽核查詢 `?action=&resource_type=&limit=`（最多 500 筆，時間倒序） | IT A |
| GET / POST / PATCH / DELETE | `/admin/system-issues` | 系統問題追蹤（狀態/嚴重度篩選；不得存放候選人內容） | IT A |
| GET | `/admin/database/overview`、`/admin/database/tables/{name}/rows`、`…/rows/{id}` | 資料庫瀏覽（招募敏感欄位預設遮罩；揭示個資須帶 `X-PII-Access-Reason` 並寫稽核） | IT A |
| POST / PATCH / DELETE | `/admin/database/tables/{name}/rows`、`…/rows/{id}` | 受政策限制的資料列維護（僅白名單資料表） | IT A |
| GET / POST | `/consent/notices`、POST `/consent/notices/{id}/activate` | 個資告知條款版本管理與啟用（公開站讀取用 `GET /public/consent-notices/active`） | 讀 A H M；寫 A H（招募端點，非 /admin） |

## 11. 公開職涯站 Public（免認證）

| Method | Path | 說明 |
|---|---|---|
| GET | `/public/jobs`、`/public/jobs/{id}` | 已發佈職缺清單／詳情 |
| GET | `/public/consent-notices/active` | 現行個資告知條款（送出表單必附其 `id`＋`version`，版本已更換回 `409` 要求重新同意） |
| POST | `/public/applications` | 應徵職缺（multipart 表單＋選附履歷）；`job_id` 省略時等同加入人才庫。**送出即建檔**：人才＋應徵＋履歷一次建立 |
| POST | `/public/talent-pool` | 加入人才庫（Email 或電話擇一必填、必勾同意；同檔重複上傳依 §4 去重規則處理） |
| POST | `/public/applications/json`、`/public/talent-pool/json` | 無檔案的純 JSON 版本 |

公開上傳共用 §4 的格式/大小/掃毒限制，另有每 IP 每分鐘 20 次的上傳限流（超過回 `429`）。
其他專用模組（媒合基準 `/matching-benchmark`、語意影子 `/semantic-shadow`、存活檢查 `/health`）請直接查 OpenAPI。
