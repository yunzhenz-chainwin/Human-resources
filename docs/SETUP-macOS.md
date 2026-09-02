# 在 macOS 上重建 TalentHub 開發環境

這份文件是把專案從 Windows 主機搬到 MacBook 之後的重建步驟。
Windows 端的說明仍以 README 與 `docs/TalentHub_交接手冊.docx` 為準。

## 1. 安裝相依工具（只需一次）

```bash
# 尚未安裝 Homebrew 的話先裝
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.12 node git
brew install tesseract tesseract-lang poppler          # 掃描型 PDF 的 OCR
brew install --cask font-noto-sans-cjk                 # PDF 匯出的繁中字型
```

`tesseract-lang` 內含 `chi_tra`（繁體中文）訓練資料，履歷 OCR 需要它。
字型若不裝，系統會退回 macOS 內建的 PingFang；PDF 仍可產出，但部分字形是簡體樣式。

## 2. 取得程式碼

```bash
git clone <新帳號的 repo 網址> ~/Human-resources
cd ~/Human-resources
```

## 3. 一次完成初始化

```bash
./setup-mac.sh
```

這支腳本會檢查上述工具、建立 `.venv`、安裝後端與兩個前端的相依套件、
產生 `backend/.env`（含隨機 `AUTH_SECRET_KEY`），最後執行 `alembic upgrade head`。
可重複執行，已完成的步驟會自動略過。

## 4. 還原 Windows 主機上的資料（若有帶隨身碟／AirDrop 檔案）

沒有進版控的三樣東西必須另外複製，不會、也不應該出現在 GitHub：

| 來源（Windows） | 目的地（Mac） | 內容 |
|---|---|---|
| `backend/.env` | `backend/.env` | Gemini API key、`AUTH_SECRET_KEY` |
| `backend/talenthub-preserved-accounts.db` | `backend/talenthub-preserved-accounts.db` | 既有帳號與人才資料 |
| `backend/storage/` | `backend/storage/` | 已上傳的原始履歷檔 |

```bash
cd ~/Human-resources
unzip ~/Downloads/talenthub-local-data.zip -d .
cd backend && ../.venv/bin/python -m alembic upgrade head   # 補上搬移期間的 migration
```

覆蓋 `backend/.env` 之後，`AUTH_SECRET_KEY` 會換回 Windows 主機那一把，
既有帳號的密碼與 refresh token 才能繼續使用。若改用 `setup-mac.sh` 產生的新金鑰，
所有人都得重新登入。

## 5. 啟動

```bash
./start-dev.sh      # 後端 8010、HR 後台 5173、公開職涯網站 5174
./stop-dev.sh       # 只會停掉驗證過確實是 TalentHub 的行程
./restart-dev.sh
```

| 服務 | 網址 |
|---|---|
| HR 管理後台 | <http://127.0.0.1:5173/> |
| 公開職涯網站 | <http://127.0.0.1:5174/> |
| API 健康檢查 | <http://127.0.0.1:8010/api/v1/health> |

各服務的輸出寫在 `.dev-logs/<port>.log`。

## 6. 首次沒有既有資料庫時建立管理員

系統沒有公開註冊端點。在 `backend/.env` 暫時填入三個 bootstrap 變數：

```
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=<至少 12 字元>
```

啟動一次後端讓帳號建立，然後把這三行刪掉再重啟。

## 7. 驗證

```bash
cd backend && APP_ENV=development ../.venv/bin/python -m pytest -q && ../.venv/bin/python -m ruff check .
cd ../frontend && npm run build
cd ../career-frontend && npm run build
cd ../e2e && npm ci && npx playwright install && npm test
```

`APP_ENV=development` 是必要的：若沿用 Windows 主機那份 `APP_ENV=production` 的 `backend/.env`，
demo／initial data 與主管履歷流程共 5 個測試會因為正式環境停用 demo seeding 而失敗，
那是設定造成的預期結果，不是程式壞掉。

## macOS 與 Windows 的差異

- 啟動腳本：Windows 用 `start-dev.ps1` / `.bat`，macOS 用 `start-dev.sh`，兩邊行為對齊。
- OCR 執行檔：`backend/run_backend.py` 依作業系統選預設路徑，macOS 走 Homebrew 的
  `/opt/homebrew/bin` 與 `/usr/local/bin`；裝在別處時用 `OCR_TOOL_DIRS` 指定。
- PDF 字型：`PDF_CJK_FONT_PATH`（粗體另有 `PDF_CJK_FONT_BOLD_PATH`）可直接指定字型檔。
- `deploy/windows-lan/` 內的內網服務註冊只適用於 Windows 主機，Mac 上不需要也不會用到。
