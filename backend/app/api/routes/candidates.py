from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.dependencies.auth import (
    audit_pii_read,
    candidate_scope_clause,
    enforce_candidate_scope,
    get_current_user,
    require_recruiting_manager,
    require_recruiting_user,
)
from app.models import Candidate, CandidateActivity, Department, User
from app.schemas.hr import (
    CandidateActivityCreate,
    CandidateActivityRead,
    CandidateCreate,
    CandidateRead,
    CandidateUpdate,
)
from app.services.applications import normalize_email, normalize_phone
from app.services.security import write_audit

router = APIRouter(prefix="/candidates")
settings = get_settings()

PHOTO_TYPES = {
    "image/jpeg": ("jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "image/png": ("png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/webp": (
        "webp",
        lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    ),
}


def _photo_candidate(db: Session, user: User, candidate_id: int) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if not candidate or candidate.deleted_at:
        raise HTTPException(status_code=404, detail="Candidate not found")
    enforce_candidate_scope(db, user, candidate_id)
    return candidate


def _activity_candidate(db: Session, user: User, candidate_id: int) -> Candidate:
    """Resolve a candidate without revealing out-of-scope candidate existence."""
    enforce_candidate_scope(db, user, candidate_id)
    candidate = db.get(Candidate, candidate_id)
    if not candidate or candidate.deleted_at:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


def _activity_read(
    activity: CandidateActivity,
    author: User | None,
    department: Department | None,
) -> CandidateActivityRead:
    return CandidateActivityRead(
        id=activity.id,
        candidate_id=activity.candidate_id,
        user_id=activity.user_id,
        author_name=author.display_name if author else None,
        author_role=author.role if author else None,
        author_department_id=author.department_id if author else None,
        author_department_name=department.name if department else None,
        type=activity.type,
        content=activity.content,
        happened_at=activity.happened_at,
        created_at=activity.created_at,
    )


def _validated_photo(data: bytes, content_type: str | None) -> tuple[str, str]:
    normalized_type = (content_type or "").lower().split(";", 1)[0].strip()
    definition = PHOTO_TYPES.get(normalized_type)
    if not definition or not definition[1](data):
        raise HTTPException(
            status_code=415, detail="Only valid JPEG, PNG, or WebP photos are allowed"
        )
    try:
        document = fitz.open(stream=data, filetype=definition[0])
        if document.page_count != 1:
            raise ValueError("not a single image")
        pixmap = document[0].get_pixmap()
        width, height = pixmap.width, pixmap.height
        invalid_dimensions = (
            width < 32
            or height < 32
            or width > 8000
            or height > 8000
            or width * height > 25_000_000
        )
        if invalid_dimensions:
            raise ValueError("invalid dimensions")
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail="Photo is damaged or has unsupported dimensions"
        ) from exc
    return normalized_type, definition[0]


@router.get("", response_model=list[CandidateRead])
def list_candidates(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Candidate]:
    query = (
        select(Candidate)
        .where(Candidate.deleted_at.is_(None), candidate_scope_clause(user))
        .order_by(Candidate.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(db.scalars(query).all())


@router.post("", response_model=CandidateRead, status_code=status.HTTP_201_CREATED)
def create_candidate(
    payload: CandidateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> Candidate:
    now = datetime.now(UTC)
    candidate = Candidate(
        code=f"T{now.year}-{now.strftime('%m%d%H%M%S%f')[-10:]}",
        name=payload.name,
        email=str(payload.email) if payload.email else None,
        email_norm=normalize_email(str(payload.email) if payload.email else None),
        phone=payload.phone,
        phone_norm=normalize_phone(payload.phone),
        city=payload.city,
        current_title=payload.current_title,
        total_years=payload.total_years,
        source=payload.source,
        status="new",
    )
    db.add(candidate)
    db.flush()
    write_audit(
        db,
        user,
        "candidate_create",
        "candidate",
        candidate.id,
        details={"code": candidate.code, "source": candidate.source},
    )
    db.commit()
    db.refresh(candidate)
    return candidate


@router.get("/{candidate_id}", response_model=CandidateRead)
def get_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    _audited_user: object = Depends(audit_pii_read),
) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if not candidate or candidate.deleted_at:
        raise HTTPException(status_code=404, detail="人才不存在")
    return candidate


@router.patch("/{candidate_id}", response_model=CandidateRead)
def update_candidate(
    candidate_id: int,
    payload: CandidateUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if not candidate or candidate.deleted_at:
        raise HTTPException(status_code=404, detail="人才不存在")
    updates = payload.model_dump(exclude_unset=True)
    if "email" in updates:
        candidate.email_norm = normalize_email(updates["email"])
    if "phone" in updates:
        candidate.phone_norm = normalize_phone(updates["phone"])
    for field, value in updates.items():
        setattr(candidate, field, value)
    write_audit(
        db,
        user,
        "candidate_update",
        "candidate",
        candidate.id,
        details={"code": candidate.code, "fields": sorted(updates)},
    )
    db.commit()
    db.refresh(candidate)
    return candidate


@router.put("/{candidate_id}/photo", response_model=CandidateRead)
async def upload_candidate_photo(
    candidate_id: int,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> Candidate:
    candidate = _photo_candidate(db, user, candidate_id)
    data = await photo.read(settings.candidate_photo_max_bytes + 1)
    await photo.close()
    if not data:
        raise HTTPException(status_code=422, detail="Photo file is empty")
    if len(data) > settings.candidate_photo_max_bytes:
        raise HTTPException(status_code=413, detail="Photo exceeds the 5 MB limit")
    content_type, extension = _validated_photo(data, photo.content_type)

    storage = Path(settings.candidate_photo_storage_path).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    new_path = (storage / f"{candidate_id}-{uuid4().hex}.{extension}").resolve()
    if storage not in new_path.parents:
        raise HTTPException(status_code=500, detail="Invalid photo storage path")
    new_path.write_bytes(data)
    previous_path = Path(candidate.photo_path).resolve() if candidate.photo_path else None
    try:
        candidate.photo_path = str(new_path)
        candidate.photo_content_type = content_type
        candidate.photo_updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(candidate)
    except Exception:
        new_path.unlink(missing_ok=True)
        raise
    if previous_path and previous_path != new_path and storage in previous_path.parents:
        previous_path.unlink(missing_ok=True)
    return candidate


@router.get("/{candidate_id}/photo", response_class=FileResponse)
def get_candidate_photo(
    candidate_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    candidate = _photo_candidate(db, user, candidate_id)
    if not candidate.photo_path:
        raise HTTPException(status_code=404, detail="Candidate photo not found")
    storage = Path(settings.candidate_photo_storage_path).resolve()
    photo_path = Path(candidate.photo_path).resolve()
    if storage not in photo_path.parents or not photo_path.is_file():
        raise HTTPException(status_code=404, detail="Candidate photo not found")
    return FileResponse(
        photo_path,
        media_type=candidate.photo_content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.delete("/{candidate_id}/photo", status_code=status.HTTP_204_NO_CONTENT)
def delete_candidate_photo(
    candidate_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> None:
    candidate = _photo_candidate(db, user, candidate_id)
    storage = Path(settings.candidate_photo_storage_path).resolve()
    previous_path = Path(candidate.photo_path).resolve() if candidate.photo_path else None
    candidate.photo_path = None
    candidate.photo_content_type = None
    candidate.photo_updated_at = None
    db.commit()
    if previous_path and storage in previous_path.parents:
        previous_path.unlink(missing_ok=True)


@router.post(
    "/{candidate_id}/activities",
    response_model=CandidateActivityRead,
    status_code=status.HTTP_201_CREATED,
)
def create_activity(
    candidate_id: int,
    payload: CandidateActivityCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> CandidateActivityRead:
    if user.role == "manager" and payload.next_status is not None:
        raise HTTPException(
            status_code=403,
            detail="Department managers cannot change candidate status through activities",
        )
    candidate = _activity_candidate(db, user, candidate_id)
    activity = CandidateActivity(
        candidate_id=candidate_id,
        user_id=user.id,
        type=payload.type,
        content=payload.content,
        happened_at=payload.happened_at or datetime.now(UTC),
    )
    db.add(activity)
    db.flush()
    if payload.next_status:
        candidate.status = payload.next_status
    write_audit(
        db,
        user,
        "candidate.activity.create",
        "candidate_activity",
        activity.id,
        user.department_id,
        details={
            "candidate_id": candidate_id,
            "activity_type": payload.type,
            "candidate_status_changed": bool(payload.next_status),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(activity)
    author = db.get(User, activity.user_id) if activity.user_id is not None else None
    department = (
        db.get(Department, author.department_id)
        if author and author.department_id is not None
        else None
    )
    return _activity_read(activity, author, department)


@router.get("/{candidate_id}/activities", response_model=list[CandidateActivityRead])
def list_activities(
    candidate_id: int,
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> list[CandidateActivityRead]:
    _activity_candidate(db, user, candidate_id)
    statement = (
        select(CandidateActivity, User, Department)
        .outerjoin(User, User.id == CandidateActivity.user_id)
        .outerjoin(Department, Department.id == User.department_id)
        .where(CandidateActivity.candidate_id == candidate_id)
        .order_by(CandidateActivity.happened_at.desc(), CandidateActivity.id.desc())
        .limit(page_size)
    )
    return [
        _activity_read(activity, author, department)
        for activity, author, department in db.execute(statement).all()
    ]


@router.post(
    "/{candidate_id}/contacts",
    response_model=CandidateActivityRead,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_contact_alias(
    candidate_id: int,
    payload: CandidateActivityCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_user),
) -> CandidateActivityRead:
    return create_activity(candidate_id, payload, request, db, user)


@router.delete("/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_recruiting_manager),
) -> None:
    candidate = db.get(Candidate, candidate_id)
    if not candidate or candidate.deleted_at:
        raise HTTPException(status_code=404, detail="人才不存在")
    storage = Path(settings.candidate_photo_storage_path).resolve()
    previous_path = Path(candidate.photo_path).resolve() if candidate.photo_path else None
    candidate.photo_path = None
    candidate.photo_content_type = None
    candidate.photo_updated_at = None
    candidate.deleted_at = datetime.now(UTC)
    write_audit(
        db,
        user,
        "candidate_delete",
        "candidate",
        candidate.id,
        details={"code": candidate.code},
    )
    db.commit()
    if previous_path and storage in previous_path.parents:
        previous_path.unlink(missing_ok=True)
