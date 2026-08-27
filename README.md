# TalentHub — 企業人才庫與智慧媒合系統

> 協助 HR 建立公司自有人才資料庫：自動解析 104 / 1111 下載的履歷並結構化入庫、
> 讓各部門主管線上提出職缺需求、由系統自動配對推薦人選——縮短找才時間、提高媒合精準度。

**文件版本**：v1.3（2026-08-04）｜**狀態**：本機整合驗證通過；待 PR、內網 UAT 與正式環境強化

---

## 一句話說明

各部門主管線上開需求單 → 候選人由公開頁本人填寫並同意，或由 HR 合法匯入履歷 → 系統解析及人工校對 →
配對引擎以工作條件產生可解釋推薦 → HR／主管分階段面試與回饋 → 依同意版本及保存期限管理人才資料。

## 核心模組

| 模組 | 說明 |
|---|---|
| 人才資料庫 | 集中管理所有接觸過的求職者：搜尋、標籤、狀態追蹤、聯繫紀錄、原始履歷檔 |
| 履歷自動匯入 | 104 / 1111 下載檔（PDF）與一般履歷自動解析欄位，低信心欄位進人工校對 |
| 職缺需求管理 | 主管精靈式填寫需求單 → 簽核 → 職缺看板全程追蹤 |
| 智慧配對引擎 | 硬條件過濾 + 加權計分（0–100 分附原因），自動產生推薦名單 |
| 公開投遞與同意 | 候選人本人填寫資料，綁定生效中的版本化告知／同意內容；撤回後停止正式媒合 |
| 面試協作 | HR 初談與部門主管面談分權記錄；依職位與核准的工作證據產生可追溯題目 |

## 給主管的 60 秒說明

TalentHub 是公司內部的招募工作平台，不是取代 HR 的自動錄取工具。它把「人才資料、履歷校對、開缺、媒合、面試與稽核」放在同一套流程，讓主管看到候選人與職缺的適配原因，最終判斷仍由 HR 與用人主管負責。系統目前已具備主要 MVP、角色權限、可解釋媒合、分階段面試、版本化同意與保存期限清理能力；正式承載真實個資前，仍要完成 PR／CI、三角色 UAT、法務確認，以及由 IT 佈署 HTTPS、ClamAV、正式資料庫、加密備份與集中監控。

### 2026-08-04 交付狀態

| 已完成或已實作 | 仍需公司配合／正式驗收 |
|---|---|
| HR／IT／主管角色隔離；主管聯絡資訊遮罩及原始履歷限制 | 建立 PR、通過 CI、合併主線並完成三角色內網 UAT |
| 公開本人填寫、版本化同意存證、撤回停止媒合 | 法務定稿告知內容、保存起算與撤回後處置政策 |
| 規則式媒合、評估報表、職位限定及逐題重生面試題 | 以取得授權且去識別的履歷樣本校準解析與媒合 |
| 登出撤銷 refresh token；Gemini 預設關閉且輸入採工作證據白名單 | HTTPS、PostgreSQL、ClamAV、加密備份／還原演練、監控告警 |
| 保存期限清理 worker 與失敗重試 outbox | 正式環境啟用排程前先做 dry-run 並取得 HR／法務簽核 |

## 文件導覽

| 文件 | 內容 |
|---|---|
| [docs/00-文件導覽與保留原則.docx](docs/00-文件導覽與保留原則.docx) | 文件閱讀順序、主來源、不可刪除項目、專題 Runbook 與二進位快照保留規則 |
| [docs/01-專案規劃書.docx](docs/01-專案規劃書.docx) | 背景痛點、目標 KPI、角色、範圍、使用情境、風險 |
| [docs/02-系統架構設計.docx](docs/02-系統架構設計.docx) | 架構圖、技術選型、模組切分、配對引擎、部署方案 |
| [docs/03-資料庫設計.docx](docs/03-資料庫設計.docx) | ERD、全部資料表欄位定義、索引與去重策略 |
| [docs/04-履歷解析與匯入流程.docx](docs/04-履歷解析與匯入流程.docx) | 104/1111 欄位對應、解析管線、信心分數、校對與去重 |
| [docs/05-API規格書.docx](docs/05-API規格書.docx) | REST API 全端點清單、通用規格、範例 |
| [docs/06-前端頁面與後台規劃.docx](docs/06-前端頁面與後台規劃.docx) | 頁面清單、權限矩陣、關鍵畫面 wireframe |
| [docs/07-開發時程與里程碑.docx](docs/07-開發時程與里程碑.docx) | 階段甘特圖、里程碑驗收條件、資源與成本概估 |
| [docs/08-個資保護與資訊安全.docx](docs/08-個資保護與資訊安全.docx) | 個資法遵循、同意與保存期限、RBAC 遮罩、資安措施 |
| [docs/10-系統元件與資料庫使用手冊.docx](docs/10-系統元件與資料庫使用手冊.docx) | DB、資料表、前後端、PostgreSQL 部署、Local／S3-MinIO 儲存及 ClamAV 掃描手冊 |
| [docs/11-人才職缺媒合試行方案.docx](docs/11-人才職缺媒合試行方案.docx) | 媒合引擎現況、準確率強化、媒合評估報表、下一步 |
| [docs/12-後續工作與延伸建議.docx](docs/12-後續工作與延伸建議.docx) | 後續規劃總表（待辦＋做法合併）：每項含說明／價值、做法與製作順序、估時、完成定義、相依、風險，及波次與主管摘要 |
| [docs/13-結構化面試評分與盲評操作規格.docx](docs/13-結構化面試評分與盲評操作規格.docx) | 逐題 1–5 分、草稿／提交／重開、修訂軌跡、雙方盲評及 UAT 阻擋項 |

## 技術棧（建議，理由見 docs/02）

- **前端**：Vue 3 + TypeScript + Vite
- **後端**：Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic
- **資料庫**：PostgreSQL 16；本機與 E2E 可使用 SQLite
- **檔案儲存**：MinIO（S3 相容）或公司 NAS
- **部署**：Docker Compose（公司內網主機）

## 預計程式碼結構（Phase 1 建立）

```
TalentHub/
├── backend/                 # FastAPI 應用
│   ├── app/
│   │   ├── api/             # 路由（依模組分檔）
│   │   ├── models/          # SQLAlchemy 資料模型
│   │   ├── schemas/         # Pydantic 請求/回應
│   │   ├── services/        # 商業邏輯（matching、dedup…）
│   │   ├── parsers/         # Parser104 / Parser1111 / GenericParser
│   │   └── workers/         # Celery 任務（解析、排程、通知）
│   ├── tests/               # 含解析器樣本回歸測試
│   └── alembic/             # DB migration
├── frontend/                # HR／主管／Admin 管理後台（Vue 3 SPA）
├── career-frontend/         # 公開職涯網站與履歷投遞（Vue 3 SPA）
├── deploy/                  # docker-compose.yml、nginx、.env 範本
└── docs/                    # 本規劃文件
```

## 里程碑速覽（詳見 docs/07）

| 里程碑 | 時間點 | 內容 |
|---|---|---|
| M1–M4 | 已提前完成 | 人才庫、履歷解析／校對、需求單、媒合、報表與面試協作 MVP |
| M4.5 | 2026-08-04 | 同意流程、主管隱私、登出撤權、AI 最小揭露與 IT 問題追蹤強化 |
| M5-A | 2026-08-05 目標 | 功能分支 PR、全量 CI、主線合併與內網 UAT |
| M5-B | 依 IT／法務排程 | 正式環境與法遵簽核完成後才承載真實個資 |

## 重要前提（法遵）

本系統**不做**自動登入 104 / 1111 爬取履歷（違反平台會員條款、帳號有停權風險、個資法上屬高風險蒐集）。
採用的流程是：優先由候選人在公開頁本人填寫並同意；若來自人力銀行，則由 HR 以**企業會員身分合法下載**應徵者履歷檔，再手動上傳、解析、校對與確認入庫。監控資料夾自動匯入仍是後續項目，不應宣稱已上線。詳見 docs/04 與 docs/08。

## 目前驗收重點

1. 由 IT、HR、主管三種角色走完公開投遞、同意／撤回、履歷校對、職缺、媒合、面試與登出流程。
2. 提供取得授權且去識別化的 104／1111 履歷樣本，持續校準版本化 parser。
3. 在預備環境啟用 PostgreSQL、MinIO 與 ClamAV，依文件執行 migration、備份還原與 smoke test。
4. 由 HR／法務確認告知文字、保存期限及刪除政策，再由 IT 啟用正式排程。

## 開發環境快速啟動

目前已建立 Phase 1 的前後端骨架。首次使用先複製環境設定：

```powershell
Copy-Item .env.example .env
```

首次啟動前，請在 `.env` 設定長度至少 32 bytes 的 `AUTH_SECRET_KEY`，並暫時設定
`BOOTSTRAP_ADMIN_USERNAME`、`BOOTSTRAP_ADMIN_EMAIL`、`BOOTSTRAP_ADMIN_PASSWORD`（至少 12 字元）。
首次管理員建立後，請移除三個 bootstrap 帳密設定；系統沒有公開註冊端點。

有 Docker 的環境可從專案根目錄啟動完整服務：

```powershell
docker compose -f deploy/docker-compose.yml up --build
```

- HR 管理後台：<http://localhost:8080>
- 公開職涯網站：<http://localhost:8081>
- API 文件：<http://localhost:8000/docs>
- 健康檢查：<http://localhost:8000/api/v1/health>

沒有 Docker 時可分別啟動：

```powershell
python -m pip install -e "backend[dev]"
Set-Location backend
$env:DATABASE_URL = "sqlite:///./talenthub-dev.db"
python -m alembic upgrade head
# run_backend.py 會在 8010 埠啟動並處理 OCR 工具的 PATH；兩個前端的
# dev proxy 預設就指向 http://127.0.0.1:8010。
python run_backend.py
```

```powershell
Set-Location frontend
npm ci
npm run dev
```

另開一個終端機啟動公開職涯網站：

```powershell
Set-Location career-frontend
npm ci
npm run dev
```

預設開發 port：HR 後台 `5173`、公開網站 `5174`、API `8010`（Docker 部署時
容器內為 `8000`）。若 API port 已被其他程式使用，可設定
`VITE_API_PROXY_TARGET` 後再啟動前端。

驗證指令：

```powershell
Set-Location backend
python -m pytest -q
python -m ruff check .
Set-Location ../frontend
npm run build
Set-Location ../career-frontend
npm run build
Set-Location ../e2e
npm test
```
