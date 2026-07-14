from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.organization import User
from app.models.recruitment import JobApplication, JobRequisition
from app.services.security import decode_token, write_audit

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials, "access")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User is inactive")
    return user


def require_roles(*roles: str) -> Callable:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user

    return dependency


SYSTEM_ADMIN_ROLES = frozenset({"admin", "it"})
USER_ADMIN_ROLES = frozenset({"admin", "it", "hr"})
GLOBAL_RECRUITING_ROLES = frozenset({"admin", "hr"})
RECRUITING_ROLES = frozenset({"admin", "hr", "manager"})


def require_system_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in SYSTEM_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="System administrator role required")
    return user


def require_user_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in USER_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="User administrator role required")
    return user


def require_recruiting_user(user: User = Depends(get_current_user)) -> User:
    if user.role not in RECRUITING_ROLES:
        raise HTTPException(status_code=403, detail="Recruiting access required")
    return user


def require_recruiting_manager(user: User = Depends(get_current_user)) -> User:
    if user.role not in GLOBAL_RECRUITING_ROLES:
        raise HTTPException(status_code=403, detail="HR management role required")
    return user


def require_department_manager(user: User = Depends(get_current_user)) -> User:
    if user.role != "manager" or user.department_id is None:
        raise HTTPException(status_code=403, detail="Department manager access required")
    return user


def enforce_department_scope(user: User, department_id: int | None) -> None:
    if user.role in GLOBAL_RECRUITING_ROLES:
        return
    if user.role != "manager" or user.department_id != department_id:
        raise HTTPException(status_code=403, detail="Outside department scope")


def candidate_scope_clause(user: User):
    """Limit a manager to people who actually applied to their department's jobs."""
    if user.role in GLOBAL_RECRUITING_ROLES:
        return True
    if user.role != "manager" or user.department_id is None:
        return False
    applied = exists(
        select(JobApplication.id)
        .join(JobRequisition, JobRequisition.id == JobApplication.requisition_id)
        .where(
            JobApplication.candidate_id == candidate_id_column(),
            JobRequisition.department_id == user.department_id,
        )
    )
    return applied


def candidate_id_column():
    # Local import avoids an import cycle while keeping one canonical scope rule.
    from app.models.candidate import Candidate

    return Candidate.id


def enforce_candidate_scope(db: Session, user: User, candidate_id: int) -> None:
    from app.models.candidate import Candidate

    if user.role in GLOBAL_RECRUITING_ROLES:
        return
    allowed = db.scalar(
        select(Candidate.id).where(
            Candidate.id == candidate_id,
            candidate_scope_clause(user),
        )
    )
    if allowed is None:
        raise HTTPException(status_code=403, detail="Outside candidate scope")


def audit_pii_read(
    candidate_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Attach to any candidate-detail route that returns personal information."""
    enforce_candidate_scope(db, user, candidate_id)
    write_audit(
        db,
        user,
        "pii.read",
        "candidate",
        candidate_id,
        user.department_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return user
