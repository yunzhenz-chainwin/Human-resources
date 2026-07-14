from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import MetaData, String, Table, cast, func, inspect, or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_system_admin, require_user_admin
from app.models.organization import Department, User
from app.models.security import AuditLog, SkillCatalog, SystemIssue, SystemSetting, Tag
from app.schemas.admin import (
    AuditRead,
    CatalogCreate,
    CatalogRead,
    DatabaseColumnRead,
    DatabaseOverviewRead,
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
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.security import hash_password, write_audit

router = APIRouter(prefix="/admin")
admin_user = require_system_admin
user_admin = require_user_admin

_REDACTED_COLUMN_MARKERS = (
    "password", "hash", "token", "secret", "api_key", "private_key",
    "encryption_key", "raw_text", "parsed_text",
)

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


def _table_presentation(table_name: str) -> tuple[str, str]:
    return _TABLE_PRESENTATION.get(table_name, (table_name, "系統資料表"))


def _is_redacted_column(column_name: str) -> bool:
    normalized = column_name.lower()
    return any(marker in normalized for marker in _REDACTED_COLUMN_MARKERS)


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


@router.get("/users", response_model=list[UserRead])
def list_users(
    actor: User = Depends(user_admin), db: Session = Depends(get_db)
) -> list[User]:
    query = select(User).order_by(User.id)
    if actor.role == "hr":
        query = query.where(User.role.in_(("hr", "manager")))
    return list(db.scalars(query).all())


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    actor: User = Depends(user_admin),
    db: Session = Depends(get_db),
) -> User:
    username = payload.username.strip().lower()
    _enforce_hr_user_scope(actor, payload.role)
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
    db.flush()
    _commit_audit(db, actor, "create", "user", user.id, {"role": user.role})
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    actor: User = Depends(user_admin),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    values = payload.model_dump(exclude_unset=True)
    _enforce_hr_user_scope(actor, values.get("role", user.role), user)
    if "department_id" in values:
        _department(db, values["department_id"])
    if password := values.pop("password", None):
        user.password_hash = hash_password(password)
    for key, value in values.items():
        setattr(user, key, value.strip() if isinstance(value, str) else value)
    if actor.id == user.id and not user.is_active:
        raise HTTPException(status_code=422, detail="Admin cannot deactivate own account")
    _commit_audit(db, actor, "update", "user", user.id, {"fields": sorted(values)})
    db.refresh(user)
    return user


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
    db.flush()
    _commit_audit(db, actor, "create", "department", item.id)
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
    db.flush()
    _commit_audit(db, actor, "create", "skill", item.id)
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
    db.flush()
    _commit_audit(db, actor, "create", "tag", item.id)
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
                        redacted=_is_redacted_column(column["name"]),
                    )
                    for column in columns
                ],
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
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    _: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> DatabaseTablePreviewRead:
    """Preview rows for IT diagnostics without exposing secrets."""
    connection = db.connection()
    inspector = inspect(connection)
    # Reflect only inspector-discovered names; never interpolate route input into SQL.
    if table_name not in inspector.get_table_names():
        raise HTTPException(status_code=404, detail="Database table not found")
    table = Table(table_name, MetaData(), autoload_with=connection)
    display_name, description = _table_presentation(table_name)
    redacted_columns = [c.name for c in table.columns if _is_redacted_column(c.name)]
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
        rows=[dict(row._mapping) for row in db.execute(rows_statement)],
    )
