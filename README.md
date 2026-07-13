# TalentHub — 企業人才庫與智慧媒合系統

> 協助 HR 建立公司自有人才資料庫：自動解析 104 / 1111 下載的履歷並結構化入庫、
> 讓各部門主管線上提出職缺需求、由系統自動配對推薦人選——縮短找才時間、提高媒合精準度。

**文件版本**：v1.2（2026-07-13）｜**狀態**：可供 HR 驗收測試

---

## 一句話說明

各部門主管線上開需求單 → HR 從 104 / 1111 下載應徵履歷丟進系統 → 系統自動解析欄位建檔 →
配對引擎即時從人才庫算分推薦 → 主管線上回饋 → 面試錄取，人才永久留庫累積。

## 四大核心模組

| 模組 | 說明 |
|---|---|
| 人才資料庫 | 集中管理所有接觸過的求職者：搜尋、標籤、狀態追蹤、聯繫紀錄、原始履歷檔 |
| 履歷自動匯入 | 104 / 1111 下載檔（PDF）與一般履歷自動解析欄位，低信心欄位進人工校對 |
| 職缺需求管理 | 主管精靈式填寫需求單 → 簽核 → 職缺看板全程追蹤 |
| 智慧配對引擎 | 硬條件過濾 + 加權計分（0–100 分附原因），自動產生推薦名單 |

## 文件導覽

| 文件 | 內容 |
|---|---|
| [docs/01-專案規劃書.md](docs/01-專案規劃書.md) | 背景痛點、目標 KPI、角色、範圍、使用情境、風險 |
| [docs/02-系統架構設計.md](docs/02-系統架構設計.md) | 架構圖、技術選型、模組切分、配對引擎、部署方案 |
| [docs/03-資料庫設計.md](docs/03-資料庫設計.md) | ERD、全部資料表欄位定義、索引與去重策略 |
| [docs/04-履歷解析與匯入流程.md](docs/04-履歷解析與匯入流程.md) | 104/1111 欄位對應、解析管線、信心分數、校對與去重 |
| [docs/05-API規格書.md](docs/05-API規格書.md) | REST API 全端點清單、通用規格、範例 |
| [docs/06-前端頁面與後台規劃.md](docs/06-前端頁面與後台規劃.md) | 頁面清單、權限矩陣、關鍵畫面 wireframe |
| [docs/07-開發時程與里程碑.md](docs/07-開發時程與里程碑.md) | 階段甘特圖、里程碑驗收條件、資源與成本概估 |
| [docs/08-個資保護與資訊安全.md](docs/08-個資保護與資訊安全.md) | 個資法遵循、同意與保存期限、RBAC 遮罩、資安措施 |
| [docs/10-系統元件與資料庫使用手冊.md](docs/10-系統元件與資料庫使用手冊.md) | DB、資料表、前後端、PostgreSQL 部署、Local／S3-MinIO 儲存及 ClamAV 掃描手冊 |

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
| M1 | 第 6 週 | 人才庫上線：可手動建檔、複合搜尋、聯繫紀錄 |
| M2 | 第 10 週 | **MVP 試營運**：104/1111 履歷自動匯入 + 校對 |
| M3 | 第 12 週 | 主管需求單與簽核上線 |
| M4 | 第 15 週 | 智慧配對推薦上線 |
| M5 | 第 19 週 | 報表/資安強化完成，全功能正式上線 |

## 重要前提（法遵）

本系統**不做**自動登入 104 / 1111 爬取履歷（違反平台會員條款、帳號有停權風險、個資法上屬高風險蒐集）。
採用的流程是：HR 以**企業會員身分合法下載**應徵者履歷檔 → 系統對「已下載的檔案」全自動解析入庫，
並提供「監控資料夾」讓下載後零手動操作。詳見 docs/04 與 docs/08。

## 目前驗收重點

1. 由 HR 逐頁測試人才庫、履歷校對、職缺、智慧配對、報表與權限管理。
2. 提供去識別化的真實 104／1111 履歷樣本，持續校準版本化 parser。
3. 在預備環境啟用 PostgreSQL、MinIO 與 ClamAV，依文件執行 migration 與 smoke test。
4. 依實際測試回饋調整欄位、篩選條件、配對權重與操作流程。

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
python -m uvicorn app.main:app --reload --port 8000
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

預設開發 port：HR 後台 `5173`、公開網站 `5174`、API `8000`。若 API port
已被其他程式使用，可設定 `VITE_API_PROXY_TARGET` 後再啟動公開網站。

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
