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
            for key, value in payload.items():
                setattr(issue, key, value)
            issue.updated_by_user_id = actor_id
            updated += 1
    db.commit()
    return created, updated
