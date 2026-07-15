# TalentHub 功能與部署稽核報告

日期：2026-07-15（Asia/Taipei）

## 結論

TalentHub 已完成受控公司內網部署，可交由主管進行 LAN／VPN 驗收。正式資料庫已升級至
`c83f2a6d4e70`，防火牆規則有效，三個 Windows 開機啟動工作正在執行。此版本仍是 HTTP
內網試用部署，不應直接將 5173／5174／8010 轉發到公網。

主管入口：

- HR／主管後台：`http://WIN-K5M743HA9UN:5173/`
- IP 備援：`http://10.201.7.12:5173/`
- 公開求職站：`http://WIN-K5M743HA9UN:5174/`

## 已完成與已驗證

- 部門主管可新增、查看、編輯、刪除自己部門的職缺。
- 主管可上傳履歷並指定自己部門職缺，確認後建立正式應徵關聯。
- HR 手動新增人才時，依序選擇部門與職缺並建立正式應徵紀錄。
- 第一關面試由 HR／admin 維護日期、結果、建議與意見。
- 第二關面試由該部門主管／admin 維護日期、結果與主管意見。
- 兩關資料獨立保存，含最後更新時間；另一角色只能檢視，不能覆蓋。
- IT／admin 可查全部帳號、角色、部門、啟用狀態、最近登入與密碼重設時間。
- 現有密碼為不可逆 scrypt hash，無法查看原密碼。IT 可產生只顯示一次的 24 字元
  高強度臨時密碼；系統只保存新 hash，撤銷 refresh sessions 並留下不含明文的 audit。
- 主管資料權限限制在自己的部門；跨部門應徵者與面試資料不可讀寫。
- 防火牆只允許 `10.201.7.0/24` 存取 TCP 5173、5174；API 8010 只綁定
  `127.0.0.1`，由前端 proxy 存取。
- 三個 Windows Scheduled Tasks 已使用 SYSTEM 身分執行，支援開機啟動與失敗重試。

## 驗證結果

- 後端完整測試：97 passed。
- Playwright 使用者旅程：6/6 passed。
- Ruff、Vue typecheck、兩個前端正式 build、`git diff --check`：通過。
- 部署檢測：localhost、主機名稱、LAN IP、兩個前端與 API proxy 全部 HTTP 200。
- SQLite `integrity_check=ok`；Alembic current=`c83f2a6d4e70`。
- Live smoke：HR 可讀 7 筆應徵及兩關欄位；產品設計主管只讀到本部門 2 筆；
  IT 可讀 9 個帳號及新增的登入／密碼時間欄位。
- 升級前備份：`backend/talenthub-dev.before-two-stage-20260715-101742.db`。

## 目前資料盤點

| 資料 | 數量 |
|---|---:|
| 啟用／現有帳號 | 9 |
| 部門 | 6 |
| 職缺 | 11 |
| 人才 | 19 |
| 應徵紀錄 | 7 |
| 履歷 | 10 |

已確認 10 份履歷實體檔案存在，沒有無效帳號、無效職缺或重複 normalized
email／phone。目前有 1 筆應徵指向已軟刪除人才，列於 High #4。

## 功能矩陣

| 功能 | HR／Admin | 部門主管 | IT | 公開求職者 | 狀態 |
|---|---|---|---|---|---|
| 登入、refresh、角色權限 | 全公司 | 自己部門 | 系統管理 | 不適用 | 已完成 |
| 人才資料 | CRUD | 關聯人才唯讀 | 不直接讀招募資料 | 可投遞 | 有刪除一致性問題 |
| 履歷上傳與解析 | 全公司 | 指定自己部門職缺 | 不讀履歷 | 可上傳 | 已完成 |
| 原始履歷下載 | 未提供 | 未提供 | 未提供 | 未提供 | 待開發 |
| 職缺 CRUD／細項 | 全公司／核准 | 自己部門 | DB 診斷 | 公開職缺唯讀 | 已完成 |
| HR 手動指派部門／職缺 | 可 | 不可 | 不可 | 不適用 | 已完成 |
| 第一關 HR 面試 | 可編輯 | 唯讀 | 不可 | 不可 | 已完成 |
| 第二關主管面試 | admin 可覆核 | 本部門可編輯 | 不可 | 不可 | 已完成 |
| 媒合條件與重算 | 可 | 本部門應徵者 | 不可 | 不可 | 已完成 |
| 招募報表 | 全公司 | 自己部門 | 不可 | 不可 | 有統計精準度問題 |
| 帳號管理 | HR 僅 HR／主管 | 不可 | 全部帳號 | 不可 | 已完成 |
| 密碼管理 | 不可回看 | 不可 | 一次性安全重設 | 不可 | 已完成 |
| 系統設定、audit、DB 診斷 | admin | 不可 | 可 | 不可 | 已完成 |
| LAN 主管網址 | 可 | 可 | 可 | 公開站可用 | 已部署、待主管端實測 |
| 公網正式服務 | — | — | — | — | 尚未達標 |

## Critical／正式上公網前的阻擋事項

### C1. 目前只有 HTTP 內網服務，不能直接暴露至公網

目前為 Vite 開發服務與 HTTP，沒有公司憑證、HTTPS reverse proxy、WAF／Zero Trust、
正式網域及完整監控。直接公開會讓帳密、履歷、面試意見與臨時密碼承受攔截風險。

建議：目前只在公司 LAN／VPN 使用。若主管需從外網使用，由公司 IT 建立 HTTPS、固定
網域、VPN／Zero Trust、反向代理、憑證續期與監控；不可對外開放 8010 或裸露 Vite port。

## High

### H1. 臨時密碼不會強制首次登入更換

IT 重設後的密碼只顯示一次，但會持續有效。尚無 `must_change_password`、使用者自行改密碼
API 或 MFA。建議新增首次登入改密碼流程，改密碼後撤銷全部 session；高風險重設操作應要求
IT 再驗證自己的密碼或 MFA。

### H2. 帳號最低密碼只有 5 字元，登入沒有 rate limit／鎖定

建議最低 12 字元、封鎖常見密碼、登入限流、失敗登入 audit、暫時鎖定及 MFA。

### H3. 匿名公開投遞可用既有 email／phone 更新人才與履歷

知道他人 email／電話者可能污染既有姓名、城市、職稱、cover letter 或 resume。建議加入
email／簡訊驗證；重複投遞建立新版本，不允許匿名覆寫既有資料。

### H4. 軟刪除人才仍保留有效應徵

Live DB 的 application #5 指向已軟刪除 candidate #17（Emma）。部門 workspace 會排除，
`/applications` 仍可能顯示，造成頁面不一致及 PII 保留。建議有有效應徵時禁止刪除，或同步
將應徵改為 withdrawn，並在所有查詢統一排除已刪人才。

### H5. 職缺、應徵與兩關面試缺少中央狀態機

目前仍可能把人才指派到 draft／closed／filled 職缺、未完成 HR 第一關就填第二關、HR 第一關
直接選 hired／offered，或清空面試後保留 offered／hired。建議建立單一流程：

`submitted → HR interview → HR advance → manager interview → offered/rejected → hired`

並依職缺狀態與角色限制可選結果。

### H6. 履歷掃毒在 development 設定中關閉，公開上傳沒有流量限制

目前 scanner=none／allow_unavailable，且無 CAPTCHA、rate limit 或 worker queue。建議 production
使用 ClamAV fail-closed、限制檔案批次與頻率、加入 CAPTCHA，解析改由背景 worker 執行。

### H7. 尚無自動化備份與還原演練

本輪有手動升級前備份，但沒有每日加密備份、異機保存、保留週期或 restore drill。正式多人
使用建議 PostgreSQL，並備份 DB 與履歷目錄。

### H8. `.env` 仍保留 bootstrap admin 設定

檔案已被 Git ignore，但主機檔案外洩仍有風險。確認 bootstrap 完成後移除相關值，並透過 IT
安全重設 admin 密碼。

## Medium

1. HR 手動 intake 使用多段 API，不是單一 transaction；中途失敗會留下部分完成資料。
2. HR intake 不檢查既有 email／phone，且聯絡資料可全空，可能產生重複人才。
3. intake 上傳履歷未直接寫入該 `JobApplication.resume_id`，多版本履歷關聯不夠明確。
4. 沒有受權限保護的原始履歷下載端點，目前只能看解析結果。
5. 主管可修改已核准／公開職缺而不重新送 HR 核准，也可刪除無應徵者的公開職缺。
6. HR 職缺 status 是任意字串，缺少 Literal／DB constraint；filled／closed 不會自動寫時間欄位。
7. `time-to-fill` 依賴 `filled_at`，只改 status 不會進報表；來源報表可能使用 Candidate.source
   而非實際應徵來源。
8. 人才與履歷前端只取前 100 筆；應徵清單與部門 workspace 無 pagination，大量資料時會
   看不全或回應過大。
9. `/health` 只回固定 ok，未檢查 DB、migration、儲存空間或掃毒服務。
10. 登入／refresh／列表／照片讀取等 audit 不完整；失敗登入未記錄，登入 IP／UA 多為 null。
11. 兩關 UI 各保留最新值；完整歷程只在 audit，沒有 UI 時間軸、地點、會議連結、面試官、
    通知或提醒。
12. IT 將帳號 email 改成重複值時，部分路徑可能回 500 而不是清楚的 409。
13. Docker／Nginx 尚缺 CSP、HSTS、frame protection 等 headers；正式環境也未關閉 API docs。
14. `run_backend.py` 含 Administrator 專屬 OCR 路徑，換伺服器或 Windows 帳號可能失效。
15. 公開職缺沒有同時檢查 department.is_active；停用部門的公開職缺仍可能顯示。

## Low／已知限制

1. 文件寫 Argon2id，實作是 scrypt，需統一文件。
2. 求職頁沒有完整 deep link、瀏覽器上一頁整合與每個職缺固定 SEO URL。
3. 瀏覽器自動化僅涵蓋 Chromium，未涵蓋 Safari、Firefox、手機與無障礙掃描。
4. 測試有 Starlette `httpx` deprecation warning；目前不影響功能。
5. 尚無負載測試、弱點掃描、依賴與 container image 掃描。

## 主管端仍需實測

1. 從主管實際電腦開啟 `http://WIN-K5M743HA9UN:5173/`。
2. 若主機名稱無法解析，改用 `http://10.201.7.12:5173/`。
3. 確認帳號只看到自己部門的人才、職缺與面試。
4. 確認 HR 第一關意見可看但主管不能改；主管第二關可儲存日期、結果與意見。
5. 確認主管電腦的時區、公司 proxy、VPN、VLAN 與端點防護不會阻擋 5173。
6. 用實際 PDF／DOCX 履歷測試上傳與解析。

## 公司 IT 後續事項

- 為主機保留固定 IP／DHCP reservation，或建立內部 DNS `talenthub`。
- 建立服務監控、log rotation、磁碟容量告警與資料保留政策。
- 建立 DB／履歷每日備份、異機保存與還原演練。
- 啟用 ClamAV、登入防護與負載測試。
- 若需外網，建置 HTTPS、固定網域、VPN／Zero Trust 與 reverse proxy。
- 移除 bootstrap 憑證並輪替所有測試／共用密碼。
