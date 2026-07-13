from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_roles
from app.models.organization import Department, User
from app.models.security import AuditLog, SkillCatalog, SystemSetting, Tag
from app.schemas.admin import (
    AuditRead,
    CatalogCreate,
    CatalogRead,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    SettingRead,
    SettingWrite,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.security import hash_password, write_audit

router = APIRouter(prefix="/admin")
admin_user = require_roles("admin")


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
    _: User = Depends(admin_user), db: Session = Depends(get_db)
) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)).all())


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> User:
    username = payload.username.strip().lower()
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
    actor: User = Depends(admin_user),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    values = payload.model_dump(exclude_unset=True)
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
    _: User = Depends(admin_user), db: Session = Depends(get_db)
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
