# PostgreSQL 部署與驗證

正式環境以 PostgreSQL 16 為唯一資料庫。SQLite 僅供快速單元測試，不代表正式相容性驗證。

## 本機 Docker Compose

先建立環境檔，並在非開發環境更換所有密碼與 `AUTH_SECRET_KEY`：

```powershell
Copy-Item .env.example .env
docker compose -f deploy/docker-compose.yml up --build -d
docker compose -f deploy/docker-compose.yml ps
```

啟動順序由 Compose 保證：PostgreSQL 通過 `pg_isready` 後執行一次
`alembic upgrade head`；migration 成功後才啟動 API。API 容器另外呼叫
`/api/v1/health` 判斷自身健康狀態。

檢查 migration 與 PostgreSQL schema：

```powershell
docker compose -f deploy/docker-compose.yml run --rm migrate alembic current
docker compose -f deploy/docker-compose.yml exec backend python scripts/postgres_schema_smoke.py
```

`postgres_schema_smoke.py` 會確認：

- 實際連線 dialect 是 PostgreSQL；
- DB revision 與程式 migration head 完全一致；
- 核心資料表、BIGINT 主鍵自增與 job application 外鍵存在。

## CI

`.github/workflows/backend-postgres.yml` 會建立全新的 PostgreSQL 16 service，依序執行：

1. 確認 Alembic 僅有一個 head；
2. 對空資料庫執行 `alembic upgrade head`；
3. 執行 schema smoke；
4. 在同一個 PostgreSQL DB 跑 pytest；
5. 執行 Ruff。

部署前應以這個 workflow 成功作為必要條件。資料庫備份、TLS、密碼輪替及
最小權限帳號仍需由實際託管環境設定，不能使用 `.env.example` 的開發密碼。
