from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.organization import User
from app.schemas.auth import (
    ChangePasswordRequest,
    CurrentUserRead,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenPair,
)
from app.services.security import (
    authenticate_login,
    client_ip,
    decode_token,
    hash_password,
    issue_token_pair,
    revoke_refresh_token_jti,
    revoke_user_refresh_tokens,
    rotate_refresh_token,
    verify_password,
    write_audit,
)

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    # The brute-force throttle is durable and per-account (see authenticate_login):
    # counters live on the user row so it survives restarts, cannot be bypassed by
    # rotating source IPs, and never grows an unbounded in-memory structure.
    outcome = authenticate_login(db, payload.username, payload.password)
    ip_address = client_ip(request)
    user_agent = request.headers.get("user-agent")
    if outcome.status == "locked":
        # Account under a short, auto-expiring lock. Audit the throttled attempt and
        # tell the client when it may retry.
        write_audit(
            db,
            None,
            "login.locked",
            "session",
            details={
                "username": payload.username.strip().lower(),
                "retry_after": outcome.retry_after,
            },
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.commit()
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts, please try again later",
            headers={"Retry-After": str(outcome.retry_after or 60)},
        )
    if outcome.status != "ok" or outcome.user is None:
        write_audit(
            db,
            None,
            "login.failed",
            "session",
            details={"username": payload.username.strip().lower()},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = outcome.user
    access, refresh, expires_in = issue_token_pair(db, user)
    write_audit(db, user, "login", "session")
    db.commit()
    return TokenPair(access_token=access, refresh_token=refresh, expires_in=expires_in)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    access, refresh_token, expires_in = rotate_refresh_token(db, payload.refresh_token)
    return TokenPair(
        access_token=access, refresh_token=refresh_token, expires_in=expires_in
    )


@router.post("/change-password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=422,
            detail="New password must differ from the current password",
        )
    now = datetime.now(UTC)
    user.password_hash = hash_password(payload.new_password)
    # A completed self-service change clears the forced-change gate, invalidates every
    # already-issued access token, and drops any brute-force lock left on the account.
    user.must_change_password = False
    user.tokens_valid_after = now
    user.failed_login_count = 0
    user.locked_until = None
    sessions_revoked = revoke_user_refresh_tokens(db, user.id, now)
    write_audit(
        db,
        user,
        "password.change",
        "user",
        user.id,
        department_id=user.department_id,
        details={"sessions_revoked": sessions_revoked, "self_service": True},
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()


@router.post("/logout", status_code=204)
def logout(
    payload: LogoutRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    try:
        claims = decode_token(payload.refresh_token, "refresh")
    except HTTPException:
        # Nothing to revoke for an unparseable/expired token; keep logout idempotent so
        # a client can always clear its local session.
        return
    # Only allow a session to revoke its own refresh token, never another user's.
    if str(claims.get("sub")) == str(user.id):
        revoke_refresh_token_jti(db, claims["jti"])
        write_audit(db, user, "logout", "session")
        db.commit()


@router.get("/me", response_model=CurrentUserRead)
def me(user: User = Depends(get_current_user)) -> User:
    return user
