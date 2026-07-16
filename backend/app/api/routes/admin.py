import json
import secrets
import string
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    cast,
    func,
    inspect,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_system_admin, require_user_admin
from app.models.candidate import Candidate
from app.models.organization import Department, User
from app.models.recruitment import JobRequisition
from app.models.security import (
    AuditLog,
    RefreshToken,
    SkillCatalog,
    SystemIssue,
    SystemSetting,
    Tag,
)
from app.schemas.admin import (
    AuditRead,
    CatalogCreate,
    CatalogRead,
    DatabaseColumnRead,
    DatabaseOverviewRead,
    DatabaseRowDetailRead,
    DatabaseRowMutationRead,
    DatabaseRowWrite,
    DatabaseTablePreviewRead,
    DatabaseTableRead,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    SettingRead,
    SettingWrite,
    SystemIssueCreate,
    SystemIssueRead,
    SystemIssueUpdate,
    TemporaryPasswordResetRead,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.security import client_ip, hash_password, write_audit

router = APIRouter(prefix="/admin")
admin_user = require_system_admin
user_admin = require_user_admin

_TEMP_PASSWORD_LENGTH = 24
_TEMP_PASSWORD_SPECIALS = "!@#$%^&*-_=+"

_REDACTED_COLUMN_MARKERS = (
    "password", "hash", "token", "secret", "api_key", "private_key",
    "encryption_key", "raw_text", "parsed_text",
)

# These columns contain recruiting PII or secret values even though their names
# do not contain one of the generic markers above.  The IT database browser is a
# diagnostics surface, not an alternative path around recruiting RBAC.
_TABLE_REDACTED_COLUMNS: dict[str, frozenset[str]] = {
    "system_settings": frozenset({"value"}),
    "resume_files": frozenset(
        {
            "storage_key",
            "original_filename",
            "parsed_payload",
            "field_confidence",
            "source_evidence",
            "error_message",
            "resume_url",
            "resume_text",
        }
    ),
    "candidates": frozenset(
        {
            "name",
            "gender",
            "birth_year",
            "birth_date",
            "email",
            "email_norm",
            "phone",
            "phone_norm",
            "city",
            "address",
            "current_title",
            "current_company",
            "expected_title",
            "expected_cities",
            "expected_salary_min",
            "expected_salary_max",
            "source_note",
            "photo_path",
            "photo_content_type",
            "summary",
            "blacklist_reason",
        }
    ),
}

# Only these recruiting fields may be revealed by an explicitly authorized IT
# preview. Authentication secrets, normalized identifiers, storage paths and
# resume contents remain redacted under every circumstance.
_TABLE_REVEALABLE_COLUMNS: dict[str, frozenset[str]] = {
    "candidates": frozenset(
        {
            "name",
            "gender",
            "birth_year",
            "birth_date",
            "email",
            "phone",
            "city",
            "address",
            "current_title",
            "current_company",
            "expected_title",
            "expected_cities",
            "expected_salary_min",
            "expected_salary_max",
            "source_note",
            "summary",
            "blacklist_reason",
        }
    ),
    "resume_files": frozenset(
        {
            "original_filename",
            "parsed_payload",
            "field_confidence",
            "source_evidence",
            "error_message",
        }
    ),
}

# Keep database identifiers stable for migrations/integrations while presenting
# operational names that are understandable to IT and HR stakeholders.
_TABLE_PRESENTATION: dict[str, tuple[str, str]] = {
    "alembic_version": ("資料庫版本", "目前資料庫結構版本與遷移紀錄"),
    "audit_logs": ("操作稽核紀錄", "後台重要操作與異動軌跡"),
    "candidate_activities": ("人才活動紀錄", "人才聯繫、面談與狀態異動歷程"),
    "candidate_educations": ("人才學歷", "履歷解析或人工維護的學歷資料"),
    "candidate_experiences": ("人才工作經歷", "履歷解析或人工維護的工作經歷"),
    "candidate_skills": ("人才技能", "人才具備的技能與熟練度"),
    "candidates": ("人才主檔", "人才基本資料與聯絡資訊"),
    "departments": ("部門資料", "公司部門與組織歸屬"),
    "job_applications": ("職缺應徵紀錄", "人才、職缺與使用履歷的關聯"),
    "job_requisitions": ("職缺資料", "招募職缺、需求條件與媒合權重"),
    "match_results": ("人才媒合結果", "人才與職缺的媒合分數及評分明細"),
    "refresh_tokens": ("登入更新權杖", "登入工作階段的安全更新權杖"),
    "resume_files": ("履歷檔案與解析紀錄", "每份履歷的檔案索引、來源、解析內容及人才關聯"),
    "skill_catalog": ("技能目錄", "系統可用的標準技能清單"),
    "system_issues": ("系統維護問題", "IT 問題追蹤、預計時程與處理進度"),
    "system_settings": ("系統設定", "平台功能與安全性設定"),
    "tags": ("人才標籤", "人才分類與搜尋標籤"),
    "users": ("後台登入人員", "IT、HR 與主管帳號及權限"),
}


@dataclass(frozen=True)
class _TableEditorPolicy:
    editable_columns: frozenset[str]
    can_create: bool = True
    can_update: bool = True
    can_delete: bool = True


# Raw editing is deliberately limited to operational, non-secret tables. PII,
# authentication, resume binaries and generated matching data keep using their
# domain workflows so this tool cannot bypass validation or privacy controls.
_TABLE_EDITOR_POLICIES: dict[str, _TableEditorPolicy] = {
    "departments": _TableEditorPolicy(
        frozenset({"name", "parent_id", "is_active"})
    ),
    "skill_catalog": _TableEditorPolicy(
        frozenset({"name", "is_active"})
    ),
    "tags": _TableEditorPolicy(
        frozenset({"name", "category", "is_active"})
    ),
    "job_requisitions": _TableEditorPolicy(
        frozenset(
            {
                "req_no",
                "title",
                "department_id",
                "headcount",
                "employment_type",
                "work_city",
                "work_address",
                "salary_min",
                "salary_max",
                "salary_type",
                "min_years",
                "education_req",
                "language_req",
                "jd",
                "summary",
                "skills",
                "urgency",
                "needed_by",
                "status",
                "match_weights",
            }
        )
    ),
    "candidate_educations": _TableEditorPolicy(
        frozenset(
            {
                "candidate_id",
                "school",
                "major",
                "degree",
                "start_ym",
                "end_ym",
                "is_graduated",
                "sort_order",
            }
        )
    ),
    "candidate_experiences": _TableEditorPolicy(
        frozenset(
            {
                "candidate_id",
                "company",
                "title",
                "industry",
                "start_ym",
                "end_ym",
                "years",
                "description",
                "sort_order",
            }
        )
    ),
    "candidate_skills": _TableEditorPolicy(
        frozenset({"candidate_id", "skill"})
    ),
    "candidate_activities": _TableEditorPolicy(
        frozenset({"candidate_id", "user_id", "type", "content", "happened_at"})
    ),
    "job_applications": _TableEditorPolicy(
        frozenset(
            {
                "requisition_id",
                "candidate_id",
                "resume_id",
                "cover_letter",
                "linkedin_url",
                "portfolio_url",
                "status",
                "source",
            }
        )
    ),
    "match_results": _TableEditorPolicy(
        frozenset({"status", "feedback_reason", "feedback_by", "feedback_at"}),
        can_create=False,
        can_delete=False,
    ),
}

_TABLE_PROTECTION_REASONS: dict[str, str] = {
    "alembic_version": "資料庫版本由 Migration 管理，禁止人工修改。",
    "audit_logs": "稽核紀錄必須保持不可竄改。",
    "candidates": "包含人才個資，請由人才庫頁面新增、編輯或刪除。",
    "refresh_tokens": "登入權杖由認證系統管理。",
    "resume_files": "履歷必須經由上傳與履歷辨識流程建立，避免檔案與資料列不同步。",
    "system_issues": "請由本頁的問題紀錄功能維護，以保留日期與進度驗證。",
    "system_settings": "系統設定可能包含秘密值，請由系統設定功能維護。",
    "users": "帳號必須由帳號與權限功能維護，確保密碼正確雜湊。",
}


def _table_presentation(table_name: str) -> tuple[str, str]:
    return _TABLE_PRESENTATION.get(table_name, (table_name, "系統資料表"))


def _is_redacted_column(table_name: str, column_name: str) -> bool:
    normalized = column_name.lower()
    return normalized in _TABLE_REDACTED_COLUMNS.get(table_name, ()) or any(
        marker in normalized for marker in _REDACTED_COLUMN_MARKERS
    )


def _is_revealable_column(table_name: str, column_name: str) -> bool:
    return column_name.lower() in _TABLE_REVEALABLE_COLUMNS.get(table_name, ())


def _table_editor_policy(table_name: str) -> _TableEditorPolicy | None:
    return _TABLE_EDITOR_POLICIES.get(table_name)


def _editable_table(
    db: Session, table_name: str, action: str
) -> tuple[Table, _TableEditorPolicy]:
    connection = db.connection()
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        raise HTTPException(status_code=404, detail="Database table not found")
    policy = _table_editor_policy(table_name)
    allowed = policy and bool(getattr(policy, f"can_{action}", False))
    if not allowed:
        reason = _TABLE_PROTECTION_REASONS.get(
            table_name, "This table is read-only in the maintenance editor."
        )
        raise HTTPException(status_code=403, detail=reason)
    return Table(table_name, MetaData(), autoload_with=connection), policy


def _single_primary_key(table: Table):
    primary_keys = list(table.primary_key.columns)
    if len(primary_keys) != 1:
        raise HTTPException(
            status_code=422,
            detail="Only tables with one primary key can be edited here",
        )
    return primary_keys[0]


def _convert_database_value(column, value: Any) -> Any:
    if value is None or (value == "" and column.nullable):
        return None
    try:
        if isinstance(column.type, JSON):
            return json.loads(value) if isinstance(value, str) else value
        if isinstance(column.type, Boolean):
            if isinstance(value, bool):
                return value
            normalized = str(value).strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
            raise ValueError("must be true or false")
        if isinstance(column.type, Integer):
            return int(value)
        if isinstance(column.type, Numeric):
            return Decimal(str(value))
        if isinstance(column.type, DateTime):
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if isinstance(column.type, Date):
            if isinstance(value, date):
                return value
            return date.fromisoformat(str(value))
        if isinstance(column.type, String):
            return str(value)
        return value
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid value for column {column.name}: {exc}",
        ) from exc


def _prepare_database_values(
    table: Table, policy: _TableEditorPolicy, raw_values: dict[str, Any]
) -> dict[str, Any]:
    unknown = set(raw_values) - policy.editable_columns
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Columns are not editable: {', '.join(sorted(unknown))}",
        )
    values = {
        key: _convert_database_value(table.c[key], value)
        for key, value in raw_values.items()
    }
    if table.name == "skill_catalog" and "name" in values:
        values["name"] = str(values["name"]).strip()
        values["name_norm"] = values["name"].casefold()
    if table.name == "candidate_skills" and "skill" in values:
        values["skill"] = str(values["skill"]).strip()
        values["skill_norm"] = values["skill"].casefold()
    if (
        table.name == "job_requisitions"
        and values.get("status") in {"approved", "sourcing", "interviewing"}
        and "published_at" in table.c
    ):
        values["published_at"] = datetime.now(UTC)
    if "updated_at" in table.c:
        values["updated_at"] = datetime.now(UTC)
    return values


def _database_row(table: Table, primary_key, row_id: Any, db: Session) -> dict[str, Any]:
    visible = [
        column
        for column in table.columns
        if not _is_redacted_column(table.name, column.name)
    ]
    row = db.execute(
        select(*visible).select_from(table).where(primary_key == row_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Database row not found")
    return dict(row._mapping)


def _database_related_context(
    row: dict[str, Any], db: Session, reveal_pii: bool
) -> dict[str, Any]:
    """Return safe labels for foreign keys without exposing authentication data."""
    related: dict[str, Any] = {}
    candidate_id = row.get("candidate_id")
    if candidate_id is not None:
        candidate = db.get(Candidate, candidate_id)
        if candidate:
            candidate_summary: dict[str, Any] = {
                "id": candidate.id,
                "code": candidate.code,
            }
            if reveal_pii:
                candidate_summary["name"] = candidate.name
            related["candidate"] = candidate_summary

    requisition_id = row.get("target_requisition_id") or row.get("requisition_id")
    if requisition_id is not None:
        requisition = db.get(JobRequisition, requisition_id)
        if requisition:
            related["requisition"] = {
                "id": requisition.id,
                "req_no": requisition.req_no,
                "title": requisition.title,
                "department_id": requisition.department_id,
                "department_name": requisition.department_name,
            }

    for field, label in (
        ("uploaded_by", "uploader"),
        ("source_reviewed_by", "source_reviewer"),
        ("requested_by", "requester"),
        ("approved_by", "approver"),
    ):
        user_id = row.get(field)
        if user_id is None:
            continue
        user = db.get(User, user_id)
        if user:
            related[label] = {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "role": user.role,
            }
    return related


def _enforce_hr_user_scope(actor: User, target_role: str, target: User | None = None) -> None:
    if actor.role != "hr":
        return
    if target_role not in {"hr", "manager"} or (
        target is not None and target.role not in {"hr", "manager"}
    ):
        raise HTTPException(status_code=403, detail="HR can only manage HR and manager accounts")


def _department(db: Session, department_id: int | None) -> Department | None:
    if department_id is None:
        return None
    department = db.get(Department, department_id)
    if not department:
        raise HTTPException(status_code=422, detail="Department not found")
    return department


def _require_manager_department(role: str, department_id: int | None) -> None:
    if role == "manager" and department_id is None:
        raise HTTPException(
            status_code=422,
            detail="Department manager accounts must belong to a department",
        )


def _commit_audit(
    db: Session,
    actor: User,
    action: str,
    resource_type: str,
    resource_id: str | int,
    details: dict | None = None,
) -> None:
    write_audit(db, actor, action, resource_type, resource_id, details=details)
    db.commit()


def _generate_temporary_password() -> str:
    """Generate a copy-friendly password with strong entropy and mixed classes."""
    characters = string.ascii_letters + string.digits + _TEMP_PASSWORD_SPECIALS
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(_TEMP_PASSWORD_SPECIALS),
    ]
    password.extend(
        secrets.choice(characters) for _ in range(_TEMP_PASSWORD_LENGTH - len(password))
    )
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


def _user_reads(db: Session, users: list[User]) -> list[UserRead]:
    if not users:
        return []
    user_ids = [user.id for user in users]
    last_logins = dict(
        db.execute(
            select(AuditLog.actor_user_id, func.max(AuditLog.created_at))
            .where(
                AuditLog.action == "login",
                AuditLog.actor_user_id.in_(user_ids),
            )
            .group_by(AuditLog.actor_user_id)
        ).all()
    )
    password_changes = dict(
        db.execute(
            select(AuditLog.resource_id, func.max(AuditLog.created_at))
            .where(
                AuditLog.resource_type == "user",
                AuditLog.action.in_(("password.reset", "password.set")),
                AuditLog.resource_id.in_([str(user_id) for user_id in user_ids]),
            )
            .group_by(AuditLog.resource_id)
        ).all()
    )
    return [
        UserRead.model_validate(user).model_copy(
            update={
                "last_login_at": last_logins.get(user.id),
                "password_changed_at": password_changes.get(str(user.id), user.created_at),
            }
        )
        for user in users
    ]


@router.get("/users", response_model=list[UserRead])
def list_users(
    actor: User = Depends(user_admin), db: Session = Depends(get_db)
) -> list[UserRead]:
    query = select(User).order_by(User.id)
    if actor.role == "hr":
        query = query.where(User.role.in_(("hr", "manager")))
    return _user_reads(db, list(db.scalars(query).all()))


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    actor: User = Depends(user_admin),
    db: Session = Depends(get_db),
) -> User:
    username = payload.username.strip().lower()
    _enforce_hr_user_scope(actor, payload.role)
    _require_manager_department(payload.role, payload.department_id)
    if db.scalar(
        select(User).where(or_(User.username == username, User.email == payload.email))
    ):
        raise HTTPException(status_code=409, detail="Username or email already exists")
    _department(db, payload.department_id)
    user = User(
        username=username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
        role=payload.role,
        department_id=payload.department_id,
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
        _commit_audit(db, actor, "create", "user", user.id, {"role": user.role})
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Username or email already exists"
        ) from exc
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    actor: User = Depends(user_admin),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    values = payload.model_dump(exclude_unset=True)
    password = values.pop("password", None)
    password_confirm = values.pop("password_confirm", None)
    if password:
        if actor.role not in {"admin", "it"}:
            raise HTTPException(
                status_code=403,
                detail="Only system administrators can set passwords",
            )
        if password_confirm is None or not secrets.compare_digest(password, password_confirm):
            raise HTTPException(status_code=422, detail="Password confirmation does not match")
    elif password_confirm is not None:
        raise HTTPException(status_code=422, detail="Password is required with confirmation")
    _enforce_hr_user_scope(actor, values.get("role", user.role), user)
    _require_manager_department(
        values.get("role", user.role),
        values.get("department_id", user.department_id),
    )
    if "department_id" in values:
        _department(db, values["department_id"])
    for key, value in values.items():
        setattr(user, key, value.strip() if isinstance(value, str) else value)
    if actor.id == user.id and not user.is_active:
        raise HTTPException(status_code=422, detail="Admin cannot deactivate own account")

    if values:
        write_audit(db, actor, "update", "user", user.id, details={"fields": sorted(values)})
    if password:
        user.password_hash = hash_password(password)
        # An administrator-chosen password is known to the administrator, so force the
        # owner to set their own on next use.
        user.must_change_password = True
        revoked_at = datetime.now(UTC)
        # Invalidate already-issued access tokens immediately, not just refresh tokens.
        user.tokens_valid_after = revoked_at
        revoked = db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
        sessions_revoked = max(int(revoked.rowcount or 0), 0)
        write_audit(
            db,
            actor,
            "password.set",
            "user",
            user.id,
            department_id=user.department_id,
            details={
                "target_username": user.username,
                "sessions_revoked": sessions_revoked,
                "administrator_chosen_password": True,
            },
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/users/{user_id}/reset-password",
    response_model=TemporaryPasswordResetRead,
)
def reset_user_password(
    user_id: int,
    request: Request,
    response: Response,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> TemporaryPasswordResetRead:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    temporary_password = _generate_temporary_password()
    user.password_hash = hash_password(temporary_password)
    # The temporary password is handed to IT, so the owner must set their own on next
    # login before regaining access to normal endpoints.
    user.must_change_password = True
    revoked_at = datetime.now(UTC)
    # Invalidate already-issued access tokens immediately, not just refresh tokens.
    user.tokens_valid_after = revoked_at
    revoked = db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=revoked_at)
    )
    sessions_revoked = max(int(revoked.rowcount or 0), 0)
    audit = write_audit(
        db,
        actor,
        "password.reset",
        "user",
        user.id,
        department_id=user.department_id,
        details={
            "target_username": user.username,
            "sessions_revoked": sessions_revoked,
            "temporary_password_issued": True,
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return TemporaryPasswordResetRead(
        user_id=user.id,
        username=user.username,
        temporary_password=temporary_password,
        password_changed_at=audit.created_at,
        sessions_revoked=sessions_revoked,
    )


@router.get("/departments", response_model=list[DepartmentRead])
def list_departments(
    _: User = Depends(user_admin), db: Session = Depends(get_db)
) -> list[Department]:
    return list(db.scalars(select(Department).order_by(Department.name)).all())


@router.post("/departments", response_model=DepartmentRead, status_code=201)
def create_department(
    payload: DepartmentCreate,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> Department:
    if db.scalar(select(Department).where(Department.name == payload.name.strip())):
        raise HTTPException(status_code=409, detail="Department already exists")
    _department(db, payload.parent_id)
    item = Department(name=payload.name.strip(), parent_id=payload.parent_id, is_active=True)
    db.add(item)
    try:
        db.flush()
        _commit_audit(db, actor, "create", "department", item.id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Department already exists") from exc
    db.refresh(item)
    return item


@router.patch("/departments/{department_id}", response_model=DepartmentRead)
def update_department(
    department_id: int,
    payload: DepartmentUpdate,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> Department:
    item = _department(db, department_id)
    values = payload.model_dump(exclude_unset=True)
    if values.get("parent_id") == department_id:
        raise HTTPException(status_code=422, detail="Department cannot be its own parent")
    if "parent_id" in values:
        _department(db, values["parent_id"])
    for key, value in values.items():
        setattr(item, key, value.strip() if isinstance(value, str) else value)
    _commit_audit(db, actor, "update", "department", item.id)
    db.refresh(item)
    return item


@router.get("/skills", response_model=list[CatalogRead])
def list_skills(
    _: User = Depends(admin_user), db: Session = Depends(get_db)
) -> list[SkillCatalog]:
    return list(db.scalars(select(SkillCatalog).order_by(SkillCatalog.name)).all())


@router.post("/skills", response_model=CatalogRead, status_code=201)
def create_skill(
    payload: CatalogCreate,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> SkillCatalog:
    normalized = payload.name.strip().casefold()
    if db.scalar(select(SkillCatalog).where(SkillCatalog.name_norm == normalized)):
        raise HTTPException(status_code=409, detail="Skill already exists")
    item = SkillCatalog(name=payload.name.strip(), name_norm=normalized, is_active=True)
    db.add(item)
    try:
        db.flush()
        _commit_audit(db, actor, "create", "skill", item.id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Skill already exists") from exc
    db.refresh(item)
    return item


@router.delete("/skills/{skill_id}", status_code=204)
def deactivate_skill(
    skill_id: int,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> None:
    item = db.get(SkillCatalog, skill_id)
    if not item:
        raise HTTPException(status_code=404, detail="Skill not found")
    item.is_active = False
    _commit_audit(db, actor, "deactivate", "skill", item.id)


@router.get("/tags", response_model=list[CatalogRead])
def list_tags(
    _: User = Depends(admin_user), db: Session = Depends(get_db)
) -> list[Tag]:
    return list(db.scalars(select(Tag).order_by(Tag.category, Tag.name)).all())


@router.post("/tags", response_model=CatalogRead, status_code=201)
def create_tag(
    payload: CatalogCreate,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> Tag:
    name, category = payload.name.strip(), payload.category.strip().lower()
    if db.scalar(select(Tag).where(Tag.name == name, Tag.category == category)):
        raise HTTPException(status_code=409, detail="Tag already exists")
    item = Tag(name=name, category=category, is_active=True)
    db.add(item)
    try:
        db.flush()
        _commit_audit(db, actor, "create", "tag", item.id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Tag already exists") from exc
    db.refresh(item)
    return item


@router.delete("/tags/{tag_id}", status_code=204)
def deactivate_tag(
    tag_id: int,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> None:
    item = db.get(Tag, tag_id)
    if not item:
        raise HTTPException(status_code=404, detail="Tag not found")
    item.is_active = False
    _commit_audit(db, actor, "deactivate", "tag", item.id)


@router.get("/settings", response_model=list[SettingRead])
def list_settings(
    _: User = Depends(admin_user), db: Session = Depends(get_db)
) -> list[SettingRead]:
    items = db.scalars(select(SystemSetting).order_by(SystemSetting.key)).all()
    return [
        SettingRead(
            key=item.key,
            value=None if item.is_secret else item.value,
            description=item.description,
            is_secret=item.is_secret,
        )
        for item in items
    ]


@router.put("/settings/{key}", response_model=SettingRead)
def write_setting(
    key: str,
    payload: SettingWrite,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> SettingRead:
    if not key or len(key) > 100:
        raise HTTPException(status_code=422, detail="Invalid setting key")
    item = db.get(SystemSetting, key)
    if item is None:
        item = SystemSetting(key=key)
        db.add(item)
    item.value = payload.value
    item.description = payload.description
    item.is_secret = payload.is_secret
    _commit_audit(db, actor, "upsert", "setting", key)
    return SettingRead(
        key=item.key,
        value=None if item.is_secret else item.value,
        description=item.description,
        is_secret=item.is_secret,
    )


@router.get("/audit-logs", response_model=list[AuditRead])
def list_audit_logs(
    action: str | None = None,
    resource_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    statement = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        statement = statement.where(AuditLog.action == action)
    if resource_type:
        statement = statement.where(AuditLog.resource_type == resource_type)
    return list(db.scalars(statement).all())


@router.get("/system-issues", response_model=list[SystemIssueRead])
def list_system_issues(
    status: str | None = None,
    severity: str | None = None,
    _: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> list[SystemIssue]:
    statement = select(SystemIssue).order_by(SystemIssue.updated_at.desc())
    if status:
        statement = statement.where(SystemIssue.status == status)
    if severity:
        statement = statement.where(SystemIssue.severity == severity)
    return list(db.scalars(statement).all())


@router.post("/system-issues", response_model=SystemIssueRead, status_code=201)
def create_system_issue(
    payload: SystemIssueCreate,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> SystemIssue:
    values = payload.model_dump()
    for key, value in values.items():
        if isinstance(value, str):
            values[key] = value.strip()
    issue = SystemIssue(
        **values,
        created_by_user_id=actor.id,
        updated_by_user_id=actor.id,
    )
    db.add(issue)
    db.flush()
    _commit_audit(db, actor, "create", "system_issue", issue.id)
    db.refresh(issue)
    return issue


@router.patch("/system-issues/{issue_id}", response_model=SystemIssueRead)
def update_system_issue(
    issue_id: int,
    payload: SystemIssueUpdate,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> SystemIssue:
    issue = db.get(SystemIssue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="System issue not found")
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(issue, key, value.strip() if isinstance(value, str) else value)
    issue.updated_by_user_id = actor.id
    _commit_audit(
        db,
        actor,
        "update",
        "system_issue",
        issue.id,
        {"fields": sorted(values)},
    )
    db.refresh(issue)
    return issue


@router.get("/database/overview", response_model=DatabaseOverviewRead)
def database_overview(
    _: User = Depends(admin_user), db: Session = Depends(get_db)
) -> DatabaseOverviewRead:
    """Return schema metadata only; never expose URLs, credentials, or row values."""
    connection = db.connection()
    connection.execute(select(1))
    inspector = inspect(connection)
    dialect = connection.dialect.name
    version_info = connection.dialect.server_version_info
    version = ".".join(str(part) for part in version_info) if version_info else None
    metadata = MetaData()
    tables: list[DatabaseTableRead] = []
    for table_name in sorted(inspector.get_table_names()):
        display_name, description = _table_presentation(table_name)
        editor_policy = _table_editor_policy(table_name)
        columns = inspector.get_columns(table_name)
        primary_keys = set(
            (inspector.get_pk_constraint(table_name) or {}).get("constrained_columns") or []
        )
        row_count: int | None
        try:
            table = Table(table_name, metadata, autoload_with=connection)
            row_count = db.scalar(select(func.count()).select_from(table))
        except Exception:  # pragma: no cover - permissions vary by production DB
            row_count = None
        tables.append(
            DatabaseTableRead(
                name=table_name,
                display_name=display_name,
                description=description,
                row_count=row_count,
                columns=[
                    DatabaseColumnRead(
                        name=column["name"],
                        type=str(column["type"]),
                        nullable=bool(column.get("nullable", True)),
                        primary_key=column["name"] in primary_keys,
                        redacted=_is_redacted_column(table_name, column["name"]),
                        revealable=_is_revealable_column(table_name, column["name"]),
                        editable=bool(
                            editor_policy
                            and column["name"] in editor_policy.editable_columns
                        ),
                    )
                    for column in columns
                ],
                can_create=bool(editor_policy and editor_policy.can_create),
                can_update=bool(editor_policy and editor_policy.can_update),
                can_delete=bool(editor_policy and editor_policy.can_delete),
                editable_columns=(
                    sorted(editor_policy.editable_columns) if editor_policy else []
                ),
                protection_reason=(
                    None
                    if editor_policy
                    else _TABLE_PROTECTION_REASONS.get(
                        table_name,
                        "系統產生或關聯性高的資料表目前僅提供安全檢視。",
                    )
                ),
            )
        )
    return DatabaseOverviewRead(
        healthy=True,
        dialect=dialect,
        server_version=version,
        transport_security="local process" if dialect == "sqlite" else "deployment managed",
        tables=tables,
    )


@router.get("/database/tables/{table_name}/rows", response_model=DatabaseTablePreviewRead)
def database_table_preview(
    table_name: str,
    request: Request,
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    reveal_pii: bool = Query(False),
    pii_access_reason: str | None = Header(default=None, alias="X-PII-Access-Reason"),
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> DatabaseTablePreviewRead:
    """Preview rows for IT diagnostics with audited, narrowly scoped PII reveal."""
    connection = db.connection()
    inspector = inspect(connection)
    # Reflect only inspector-discovered names; never interpolate route input into SQL.
    if table_name not in inspector.get_table_names():
        raise HTTPException(status_code=404, detail="Database table not found")
    table = Table(table_name, MetaData(), autoload_with=connection)
    display_name, description = _table_presentation(table_name)
    reason = unquote(pii_access_reason or "").strip()
    revealable_columns = _TABLE_REVEALABLE_COLUMNS.get(table_name, frozenset())
    if reveal_pii and not revealable_columns:
        raise HTTPException(status_code=403, detail="This table does not allow PII reveal")
    if reveal_pii and not 5 <= len(reason) <= 200:
        raise HTTPException(
            status_code=422,
            detail="PII access reason must contain between 5 and 200 characters",
        )
    redacted_columns = [
        c.name
        for c in table.columns
        if _is_redacted_column(table_name, c.name)
        and not (reveal_pii and c.name in revealable_columns)
    ]
    visible = [c for c in table.columns if c.name not in redacted_columns]
    searchable = [c for c in visible if isinstance(c.type, String)]
    normalized_search = (search or "").strip()
    count_statement = select(func.count()).select_from(table)
    rows_statement = select(*visible).select_from(table)
    if normalized_search and searchable:
        condition = or_(*(cast(c, String).ilike(f"%{normalized_search}%") for c in searchable))
        count_statement = count_statement.where(condition)
        rows_statement = rows_statement.where(condition)
    primary_keys = list(table.primary_key.columns)
    if primary_keys:
        rows_statement = rows_statement.order_by(*(c.desc() for c in primary_keys))
    rows_statement = rows_statement.offset((page - 1) * page_size).limit(page_size)
    rows = [dict(row._mapping) for row in db.execute(rows_statement)]
    if reveal_pii:
        write_audit(
            db,
            actor,
            "pii.database_preview",
            "database_table",
            table_name,
            details={
                "reason": reason,
                "page": page,
                "row_count": len(rows),
                "revealed_columns": sorted(revealable_columns),
            },
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        db.commit()
    response.headers["Cache-Control"] = "no-store"
    return DatabaseTablePreviewRead(
        table_name=table_name,
        display_name=display_name,
        description=description,
        page=page,
        page_size=page_size,
        total=int(db.scalar(count_statement) or 0),
        searchable_columns=[c.name for c in searchable],
        visible_columns=[c.name for c in visible],
        redacted_columns=redacted_columns,
        pii_revealed=reveal_pii,
        rows=rows,
    )


@router.get(
    "/database/tables/{table_name}/rows/{row_id}",
    response_model=DatabaseRowDetailRead,
)
def database_row_detail(
    table_name: str,
    row_id: str,
    request: Request,
    response: Response,
    reveal_pii: bool = Query(False),
    pii_access_reason: str | None = Header(default=None, alias="X-PII-Access-Reason"),
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> DatabaseRowDetailRead:
    """Show one complete safe row and human-readable relationship context."""
    connection = db.connection()
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        raise HTTPException(status_code=404, detail="Database table not found")
    table = Table(table_name, MetaData(), autoload_with=connection)
    primary_key = _single_primary_key(table)
    normalized_id = _convert_database_value(primary_key, row_id)
    reason = unquote(pii_access_reason or "").strip()
    revealable_columns = _TABLE_REVEALABLE_COLUMNS.get(table_name, frozenset())
    if reveal_pii and not revealable_columns:
        raise HTTPException(status_code=403, detail="This table does not allow PII reveal")
    if reveal_pii and not 5 <= len(reason) <= 200:
        raise HTTPException(
            status_code=422,
            detail="PII access reason must contain between 5 and 200 characters",
        )

    redacted_columns = [
        column.name
        for column in table.columns
        if _is_redacted_column(table_name, column.name)
        and not (reveal_pii and column.name in revealable_columns)
    ]
    visible = [column for column in table.columns if column.name not in redacted_columns]
    result = db.execute(
        select(*visible).select_from(table).where(primary_key == normalized_id)
    ).first()
    if result is None:
        raise HTTPException(status_code=404, detail="Database row not found")
    row = dict(result._mapping)
    related = _database_related_context(row, db, reveal_pii)

    if reveal_pii:
        write_audit(
            db,
            actor,
            "pii.database_row_detail",
            "database_row",
            f"{table_name}:{normalized_id}",
            details={
                "reason": reason,
                "revealed_columns": sorted(revealable_columns),
            },
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        db.commit()
    response.headers["Cache-Control"] = "no-store"
    display_name, _description = _table_presentation(table_name)
    return DatabaseRowDetailRead(
        table_name=table_name,
        display_name=display_name,
        row_id=normalized_id,
        pii_revealed=reveal_pii,
        redacted_columns=redacted_columns,
        row=row,
        related=related,
    )


@router.post(
    "/database/tables/{table_name}/rows",
    response_model=DatabaseRowMutationRead,
    status_code=201,
)
def create_database_row(
    table_name: str,
    payload: DatabaseRowWrite,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> DatabaseRowMutationRead:
    table, policy = _editable_table(db, table_name, "create")
    primary_key = _single_primary_key(table)
    values = _prepare_database_values(table, policy, payload.values)
    try:
        result = db.execute(table.insert().values(**values))
        row_id = result.inserted_primary_key[0]
        write_audit(
            db,
            actor,
            "database_row_create",
            table_name,
            row_id,
            details={"fields": sorted(payload.values)},
        )
        db.commit()
        row = _database_row(table, primary_key, row_id, db)
        return DatabaseRowMutationRead(table_name=table_name, row_id=row_id, row=row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The row violates a unique, required, or relationship constraint",
        ) from exc
    except StatementError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail="One or more values are invalid") from exc


@router.patch(
    "/database/tables/{table_name}/rows/{row_id}",
    response_model=DatabaseRowMutationRead,
)
def update_database_row(
    table_name: str,
    row_id: str,
    payload: DatabaseRowWrite,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> DatabaseRowMutationRead:
    table, policy = _editable_table(db, table_name, "update")
    primary_key = _single_primary_key(table)
    normalized_id = _convert_database_value(primary_key, row_id)
    _database_row(table, primary_key, normalized_id, db)
    values = _prepare_database_values(table, policy, payload.values)
    try:
        db.execute(table.update().where(primary_key == normalized_id).values(**values))
        write_audit(
            db,
            actor,
            "database_row_update",
            table_name,
            normalized_id,
            details={"fields": sorted(payload.values)},
        )
        db.commit()
        row = _database_row(table, primary_key, normalized_id, db)
        return DatabaseRowMutationRead(
            table_name=table_name, row_id=normalized_id, row=row
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The change violates a unique, required, or relationship constraint",
        ) from exc
    except StatementError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail="One or more values are invalid") from exc


@router.delete(
    "/database/tables/{table_name}/rows/{row_id}",
    response_model=DatabaseRowMutationRead,
)
def delete_database_row(
    table_name: str,
    row_id: str,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> DatabaseRowMutationRead:
    table, _policy = _editable_table(db, table_name, "delete")
    primary_key = _single_primary_key(table)
    normalized_id = _convert_database_value(primary_key, row_id)
    _database_row(table, primary_key, normalized_id, db)
    try:
        db.execute(table.delete().where(primary_key == normalized_id))
        write_audit(
            db,
            actor,
            "database_row_delete",
            table_name,
            normalized_id,
        )
        db.commit()
        return DatabaseRowMutationRead(
            table_name=table_name, row_id=normalized_id, row=None
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The row is still referenced by other records and cannot be deleted",
        ) from exc
