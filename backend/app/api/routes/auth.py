import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.organization import User
from app.schemas.auth import CurrentUserRead, LoginRequest, RefreshRequest, TokenPair
from app.services.security import authenticate, issue_token_pair, rotate_refresh_token, write_audit

router = APIRouter(prefix="/auth")

# In-process failed-login throttle keyed by username+client IP. The store lives in
# module memory, so it is scoped to a single worker process -- sufficient for the
# current single-process LAN deployment (a multi-process/HA setup would need a
# shared store such as Redis). The limit is intentionally lenient so ordinary
# retries succeed; only sustained brute-force from one username+IP is slowed down.
_LOGIN_FAILURE_LIMIT = 10
_LOGIN_FAILURE_WINDOW_SECONDS = 300
_login_failures: dict[str, list[float]] = {}
_login_failures_lock = threading.Lock()


def _login_rate_key(username: str, request: Request) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"{username.strip().lower()}|{client_ip}"


def _recent_login_failures(key: str, now: float) -> list[float]:
    window = _LOGIN_FAILURE_WINDOW_SECONDS
    return [ts for ts in _login_failures.get(key, ()) if now - ts < window]


def _enforce_login_rate_limit(key: str) -> None:
    now = time.monotonic()
    with _login_failures_lock:
        recent = _recent_login_failures(key, now)
        _login_failures[key] = recent
        if len(recent) >= _LOGIN_FAILURE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts, please try again later",
                headers={"Retry-After": str(_LOGIN_FAILURE_WINDOW_SECONDS)},
            )


def _record_login_failure(key: str) -> None:
    now = time.monotonic()
    with _login_failures_lock:
        recent = _recent_login_failures(key, now)
        recent.append(now)
        _login_failures[key] = recent


def _clear_login_failures(key: str) -> None:
    with _login_failures_lock:
        _login_failures.pop(key, None)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    rate_key = _login_rate_key(payload.username, request)
    _enforce_login_rate_limit(rate_key)
    user = authenticate(db, payload.username, payload.password)
    if not user:
        _record_login_failure(rate_key)
        write_audit(
            db,
            None,
            "login.failed",
            "session",
            details={"username": payload.username.strip().lower()},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _clear_login_failures(rate_key)
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


@router.get("/me", response_model=CurrentUserRead)
def me(user: User = Depends(get_current_user)) -> User:
    return user
