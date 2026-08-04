from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import User
from app.models.security import SystemIssue

SYSTEM_ISSUE_SEED: tuple[dict[str, Any], ...] = (
    {
        "title": "掃描式或圖片式 PDF 仍需人工覆核低信心欄位",
        "description": "外部履歷沒有文字層時必須依賴 OCR；姓名、技能及排版複雜欄位可能辨識錯誤。",
        "page": "/resumes",
        "category": "optimization",
        "severity": "medium",
        "status": "open",
        "progress_percent": 55,
        "expected_completion_date": date(2026, 8, 15),
        "reproduction_steps": "上傳低解析度、傾斜或多欄排版的掃描 PDF，檢查低信心欄位。",
        "resolution_notes": "持續蒐集人工修正結果，後續評估版面分析、影像前處理與欄位級信心門檻。",
    },
    {
        "title": "正式環境應由 SQLite 遷移至受管資料庫",
        "description": "目前開發環境使用 SQLite，適合單機測試但不適合多人並行與正式備援。",
        "page": "/admin/database",
        "category": "maintenance",
        "severity": "high",
        "status": "open",
        "progress_percent": 20,
        "expected_completion_date": date(2026, 10, 31),
        "reproduction_steps": "檢視 IT 維運中心資料庫類型；開發環境顯示 sqlite。",
        "resolution_notes": "上線前規劃 PostgreSQL、備份還原演練、監控告警與最小權限帳號。",
    },
    {
        "title": "履歷確認入庫後人才庫未更新",
        "description": "履歷曾錯誤配對到已軟刪除人才，導致確認成功但人才庫查詢不到。",
        "page": "/candidates",
        "category": "bug",
        "severity": "high",
        "status": "resolved",
        "progress_percent": 100,
        "expected_completion_date": date(2026, 7, 8),
        "reproduction_steps": "刪除人才後，再確認具相同 Email 或電話的履歷。",
        "resolution_notes": (
            "去重查詢排除 deleted_at 非空資料，明確指定已刪除人才時回傳 409，"
            "並在切換人才庫時重新同步。"
        ),
    },
    {
        "title": "僅靠品牌文字造成 104／1111 履歷來源誤判",
        "description": "一般履歷可能包含求職平台文字，舊規則曾把品牌字樣當成官方匯出格式證明。",
        "page": "/resumes",
        "category": "bug",
        "severity": "high",
        "status": "resolved",
        "progress_percent": 100,
        "expected_completion_date": date(2026, 7, 9),
        "reproduction_steps": "上傳含 104 或 1111 字樣、但並非平台範本的自製履歷。",
        "resolution_notes": (
            "改為內容證據加權、版型特徵與信心差距門檻；"
            "無法驗證時一律要求人工覆核。"
        ),
    },
    {
        "title": "圖片式 PDF 缺少文字層導致欄位辨識失敗",
        "description": "瀏覽器將履歷畫面輸出成整頁圖片，PDF 文字層為空，原解析流程無法擷取欄位。",
        "page": "/templates/resume-reference-template.html",
        "category": "feature",
        "severity": "high",
        "status": "resolved",
        "progress_percent": 100,
        "expected_completion_date": date(2026, 7, 11),
        "reproduction_steps": "下載目前內容 PDF 後檢查文字層，再上傳至履歷辨識中心。",
        "resolution_notes": (
            "啟用繁中／英文 OCR，並讓新版內部範本嵌入結構化欄位，"
            "上傳時優先精準還原。"
        ),
    },
    {
        "title": "IT 與 HR 權限介面及帳號管理範圍未分離",
        "description": "早期介面未完整區分 IT 系統維運、HR 全公司招募及主管部門範圍。",
        "page": "/admin",
        "category": "bug",
        "severity": "critical",
        "status": "resolved",
        "progress_percent": 100,
        "expected_completion_date": date(2026, 7, 5),
        "reproduction_steps": "分別以 IT、HR、主管帳號登入並比較可存取功能。",
        "resolution_notes": (
            "建立角色權限檢查；IT 管系統、HR 管全公司招募與 HR/主管帳號、"
            "主管僅讀取所屬部門。"
        ),
    },
    {
        "title": "公開投遞需綁定版本化同意書並同步撤回狀態",
        "description": (
            "公開頁需顯示目前生效條款、保存候選人同意版本，撤回後立即停止正式媒合。"
        ),
        "page": "/consent",
        "category": "feature",
        "severity": "critical",
        "status": "resolved",
        "progress_percent": 100,
        "expected_completion_date": date(2026, 8, 4),
        "reproduction_steps": (
            "由公開頁加入人才庫，再於後台撤回同意，確認版本紀錄與媒合 gate。"
        ),
        "resolution_notes": (
            "公開投遞綁定生效 notice；同意與撤回同步 candidate 狀態、日期與保存期限，"
            "並以回歸測試確認撤回後不再列入正式媒合。"
        ),
    },
    {
        "title": "主管候選人個資遮罩與原始履歷下載權限收斂",
        "description": (
            "部門主管只需查看本部門實際應徵者的工作證據；聯絡資訊需遮罩且原始履歷限 HR。"
        ),
        "page": "/matching",
        "category": "maintenance",
        "severity": "high",
        "status": "resolved",
        "progress_percent": 100,
        "expected_completion_date": date(2026, 8, 4),
        "reproduction_steps": (
            "以主管帳號開啟本部門候選人詳情，檢查 Email、電話與履歷下載／預覽端點。"
        ),
        "resolution_notes": (
            "保留部門與實際應徵範圍，主管回應中的聯絡資訊改為遮罩，"
            "原始履歷下載與預覽僅開放 HR／相容管理員。"
        ),
    },
    {
        "title": "登出需撤銷伺服器 refresh token",
        "description": "前端登出不可只清除瀏覽器狀態，必須同步撤銷後端 refresh token。",
        "page": "/auth",
        "category": "bug",
        "severity": "high",
        "status": "resolved",
        "progress_percent": 100,
        "expected_completion_date": date(2026, 8, 4),
        "reproduction_steps": "登入後登出，再嘗試以原 refresh token 取得新 access token。",
        "resolution_notes": (
            "登出流程先 best-effort 呼叫後端 logout，再清除 sessionStorage；"
            "後續仍建議改用 httpOnly cookie。"
        ),
    },
    {
        "title": "Gemini 面試題輸入改採嚴格工作證據白名單",
        "description": (
            "雲端 AI 僅能收到職稱、年資、技能與必要結構化證據，不傳自由文字履歷描述。"
        ),
        "page": "/matching",
        "category": "maintenance",
        "severity": "high",
        "status": "resolved",
        "progress_percent": 100,
        "expected_completion_date": date(2026, 8, 4),
        "reproduction_steps": "產生 HR／主管面試題並檢查送往 Gemini 的 prompt 快照。",
        "resolution_notes": (
            "Gemini 維持預設關閉；prompt 改採 allow-list 並保留規則式 fallback、"
            "格式驗證與逐題版本管理。"
        ),
    },
    {
        "title": "最新招募與面試功能完成 PR、全量 CI 與 UAT 發布",
        "description": (
            "最新功能仍在功能分支；須經 PostgreSQL migration、全量測試與瀏覽器驗收後進主線。"
        ),
        "page": "GitHub / UAT",
        "category": "maintenance",
        "severity": "high",
        "status": "investigating",
        "progress_percent": 85,
        "expected_completion_date": date(2026, 8, 5),
        "reproduction_steps": "建立 PR 並檢查 backend-postgres 與 Browser E2E workflow。",
        "resolution_notes": (
            "功能分支已完成本機整合驗證；待 PR 審查、主線合併與內網 UAT 簽核。"
        ),
    },
    {
        "title": "正式環境 HTTPS、ClamAV、備份還原與集中監控",
        "description": (
            "內網 UAT 不等於正式環境；上線前需完成傳輸加密、掃毒、備份與告警能力。"
        ),
        "page": "/admin",
        "category": "maintenance",
        "severity": "critical",
        "status": "open",
        "progress_percent": 35,
        "expected_completion_date": date(2026, 8, 31),
        "reproduction_steps": (
            "依部署清單驗證 HTTPS、掃描不可用時拒收、每日備份與實際還原演練。"
        ),
        "resolution_notes": (
            "需公司 IT 提供憑證、備份位置、監控平台與正式 PostgreSQL／物件儲存環境。"
        ),
    },
    {
        "title": "保存期限政策與背景清除工作正式啟用",
        "description": (
            "需確認保存起算點、撤回處理與刪除／匿名化政策，並在正式環境啟用排程。"
        ),
        "page": "/admin",
        "category": "maintenance",
        "severity": "high",
        "status": "investigating",
        "progress_percent": 70,
        "expected_completion_date": date(2026, 8, 14),
        "reproduction_steps": (
            "先以 dry-run 檢查到期人數與檔案，再於測試資料執行清除及失敗重試。"
        ),
        "resolution_notes": (
            "功能與 durable deletion outbox 已具備；待 HR／法務確認政策並由 IT 啟用 worker。"
        ),
    },
    {
        "title": "法務核准並啟用公開告知同意書版本",
        "description": (
            "正式資料庫尚無生效中的告知同意書；公開投遞目前安全地 fail-closed，"
            "不會在缺少有效條款時收件。"
        ),
        "page": "/admin",
        "category": "maintenance",
        "severity": "critical",
        "status": "investigating",
        "progress_percent": 60,
        "expected_completion_date": date(2026, 8, 14),
        "reproduction_steps": (
            "呼叫 GET /api/v1/public/consent-notices/active；未啟用版本時應回傳 503。"
        ),
        "resolution_notes": (
            "由法務定稿公司名稱、目的、資料類別、期間、對象、方式與當事人權利後，"
            "再由授權的 IT／HR 管理者於告知同意條款頁建立並啟用版本。"
        ),
    },
)

# Rerunning the catalog may refresh explanatory text, but workflow fields are
# owned by IT once an issue exists and must never be reset by a seed script.
_REFRESHABLE_FIELDS = frozenset(
    {"description", "page", "category", "severity", "reproduction_steps"}
)


def seed_system_issues(db: Session) -> tuple[int, int]:
    """Insert/update the maintained issue catalog, keyed idempotently by title."""
    actor = db.scalar(select(User).where(User.username == "it"))
    actor_id = actor.id if actor else None
    created = updated = 0
    for payload in SYSTEM_ISSUE_SEED:
        issue = db.scalar(select(SystemIssue).where(SystemIssue.title == payload["title"]))
        if issue is None:
            issue = SystemIssue(**payload, created_by_user_id=actor_id, updated_by_user_id=actor_id)
            db.add(issue)
            created += 1
        else:
            for key in _REFRESHABLE_FIELDS:
                setattr(issue, key, payload[key])
            issue.updated_by_user_id = actor_id
            updated += 1
    db.commit()
    return created, updated
