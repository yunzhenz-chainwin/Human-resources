# TalentHub 本機開發一鍵啟動腳本
# 用法:在專案根目錄按右鍵「用 PowerShell 執行」,或直接雙擊 start-dev.bat。
# 會各開一個視窗跑:後端 API(8010)、HR 後台(5173)、求職網站(5174)。

$root = $PSScriptRoot
Write-Host "正在啟動 TalentHub 開發環境三個伺服器..." -ForegroundColor Cyan

# 後端 API(FastAPI / uvicorn),會自動讀 backend\.env(SQLite + admin 帳號)
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$root\backend'; Write-Host '後端 API :8010' -ForegroundColor Cyan; python run_backend.py"
)

# HR 管理後台(Vite dev server,埠 5173)
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$root\frontend'; Write-Host 'HR 後台 :5173' -ForegroundColor Cyan; npm run dev"
)

# 公開求職網站(Vite dev server,埠 5174)
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$root\career-frontend'; Write-Host '求職網站 :5174' -ForegroundColor Cyan; npm run dev"
)

Write-Host ""
Write-Host "三個伺服器已在各自視窗啟動,請等約 10-15 秒讓它們就緒後再開瀏覽器:" -ForegroundColor Green
Write-Host "  HR 後台    : http://localhost:5173   (帳號 admin / 密碼 admin123)"
Write-Host "  求職網站   : http://localhost:5174"
Write-Host "  後端 API   : http://127.0.0.1:8010/docs"
Write-Host ""
Write-Host "關閉服務:把那三個新開的視窗關掉即可。" -ForegroundColor Yellow
Write-Host "(若某個視窗出現 port 已被占用的錯誤,代表該服務已經在跑,可忽略。)" -ForegroundColor DarkGray
