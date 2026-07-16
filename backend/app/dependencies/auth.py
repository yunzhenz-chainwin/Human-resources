from collections.abc import Callable
from datetime import UTC

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.organization import User
from app.models.recruitment import JobApplication, JobRequisition
from app.services.security import client_ip, decode_token, write_audit

bearer = HTTPBearer(auto_error=False)

# Endpoints a user under a forced password change may still reach: the change-password
# flow itself, logout, and reading their own profile (so the client can detect the
# forced-change state). Matched as path suffixes so they work regardless of the mount
# prefix (e.g. "/api/v1/auth/me").
_PASSWORD_CHANGE_EXEMPT_SUFFIXES = (
    "/auth/change-password",
    "/auth/logout",
    "/auth/me",
)


def _password_change_exempt(request: Request | None) -> bool:
    if request is None:
        return False
    path = request.url.path.rstrip("/")
    return any(path.endswith(suffix) for suffix in _PASSWORD_CHANGE_EXEMPT_SUFFIXES)


def get_current_user(
    request: Request,
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
    # Reject access tokens issued before the account's password was last changed or
    # reset. tokens_valid_after is NULL for accounts that never rotated, so existing
    # sessions are left untouched.
    tokens_valid_after = user.tokens_valid_after
    if tokens_valid_after is not None:
        if tokens_valid_after.tzinfo is None:
            tokens_valid_after = tokens_valid_after.replace(tzinfo=UTC)
        issued_at = payload.get("iat")
        # Floor BOTH sides to whole seconds. iat is already second-resolution, so a
        # token minted in the same wall-clock second as the reset must not be falsely
        # rejected on sub-second drift.
        if issued_at is None or int(issued_at) < int(tokens_valid_after.timestamp()):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired, please sign in again",
                headers={"WWW-Authenticate": "Bearer"},
            )
    # A forced credential change blocks normal endpoints until the user actually changes
    # the password; only the exempt endpoints above stay reachable. must_change_password
    # defaults to False, so existing accounts and sessions are unaffected.
    if user.must_change_password and not _password_change_exempt(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required",
        )
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
    # A non-global user without a department must never match NULL-department rows,
    # so reject before the comparison (mirrors require_department_manager).
    if user.role != "manager" or user.department_id is None:
        raise HTTPException(status_code=403, detail="Outside department scope")
    if user.department_id != department_id:
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
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return user
