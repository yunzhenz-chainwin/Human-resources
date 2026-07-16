import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.organization import User
from app.models.security import AuditLog, RefreshToken

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=64
    )
    return "$".join(
        ("scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), salt.hex(), digest.hex())
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, expected_hex = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(expected_hex)),
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected_hex))
    except (ValueError, TypeError):
        return False


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    secret = get_settings().auth_secret_key.encode()
    if len(secret) < 32:
        raise RuntimeError("AUTH_SECRET_KEY must contain at least 32 bytes")
    return secret


def encode_token(user: User, token_type: str, lifetime: timedelta, jti: str) -> str:
    now = datetime.now(UTC)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user.id),
        "type": token_type,
        "role": user.role,
        "department_id": user.department_id,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "jti": jti,
    }
    segments = (
        _b64encode(json.dumps(header, separators=(",", ":")).encode()),
        _b64encode(json.dumps(payload, separators=(",", ":")).encode()),
    )
    signing_input = ".".join(segments)
    signature = _b64encode(hmac.new(_secret(), signing_input.encode(), hashlib.sha256).digest())
    return f"{signing_input}.{signature}"


def decode_token(token: str, expected_type: str) -> dict:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        header_segment, payload_segment, signature = token.split(".")
        signing_input = f"{header_segment}.{payload_segment}"
        expected = _b64encode(
            hmac.new(_secret(), signing_input.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise unauthorized
        header = json.loads(_b64decode(header_segment))
        payload = json.loads(_b64decode(payload_segment))
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise unauthorized
        if payload.get("type") != expected_type or int(payload["exp"]) <= int(
            datetime.now(UTC).timestamp()
        ):
            raise unauthorized
        int(payload["sub"])
        return payload
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise unauthorized from exc


# Constant, precomputed hash used to keep authenticate() timing uniform: even when
# the username is unknown we still run one scrypt verification, so response time does
# not reveal whether an account exists and an attacker cannot cheaply skip the KDF.
_DUMMY_PASSWORD_HASH = hash_password("authenticate-timing-uniformity-placeholder")


def authenticate(db: Session, username: str, password: str) -> User | None:
    normalized = username.strip().lower()
    user = db.scalar(
        select(User).where(
            or_(User.username == normalized, User.email == normalized), User.is_active.is_(True)
        )
    )
    if user is None:
        # Unknown account: still perform a dummy verification so the request takes a
        # comparable amount of time to a real (failed) password check.
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return None
    return user if verify_password(password, user.password_hash) else None


def issue_token_pair(db: Session, user: User) -> tuple[str, str, int]:
    settings = get_settings()
    access_jti, refresh_jti = uuid4().hex, uuid4().hex
    access_seconds = settings.auth_access_minutes * 60
    refresh_lifetime = timedelta(days=settings.auth_refresh_days)
    access = encode_token(user, "access", timedelta(seconds=access_seconds), access_jti)
    refresh = encode_token(user, "refresh", refresh_lifetime, refresh_jti)
    db.add(
        RefreshToken(
            user_id=user.id,
            jti_hash=hashlib.sha256(refresh_jti.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + refresh_lifetime,
        )
    )
    db.commit()
    return access, refresh, access_seconds


def rotate_refresh_token(db: Session, token: str) -> tuple[str, str, int]:
    payload = decode_token(token, "refresh")
    token_row = db.scalar(
        select(RefreshToken).where(
            RefreshToken.jti_hash == hashlib.sha256(payload["jti"].encode()).hexdigest()
        )
    )
    now = datetime.now(UTC)
    if token_row is None:
        raise HTTPException(status_code=401, detail="Refresh token is revoked or expired")
    expires_at = token_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        raise HTTPException(status_code=401, detail="Refresh token is revoked or expired")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User is inactive")
    # Atomically claim this token so only one rotation can ever succeed. A zero
    # rowcount means it was already revoked, i.e. a rotated token is being replayed;
    # treat that as compromise and revoke the account's entire refresh-token family.
    claimed = db.execute(
        update(RefreshToken)
        .where(RefreshToken.id == token_row.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    if not claimed.rowcount:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token reuse detected")
    return issue_token_pair(db, user)


def write_audit(
    db: Session,
    actor: User | None,
    action: str,
    resource_type: str,
    resource_id: str | int | None = None,
    department_id: int | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_user_id=actor.id if actor else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        department_id=department_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent,
        created_at=datetime.now(UTC),
    )
    db.add(log)
    return log


def bootstrap_admin(db: Session) -> User | None:
    """Idempotently create the first admin only from explicit environment settings."""
    settings = get_settings()
    values = (
        settings.bootstrap_admin_username,
        settings.bootstrap_admin_email,
        settings.bootstrap_admin_password,
    )
    if not all(values):
        return None
    if len(settings.bootstrap_admin_password or "") < 12:
        raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must contain at least 12 characters")
    existing = db.scalar(
        select(User).where(
            or_(
                User.username == settings.bootstrap_admin_username.lower(),
                User.email == settings.bootstrap_admin_email.lower(),
            )
        )
    )
    if existing:
        return existing
    admin = User(
        username=settings.bootstrap_admin_username.lower(),
        email=settings.bootstrap_admin_email.lower(),
        password_hash=hash_password(settings.bootstrap_admin_password),
        display_name=settings.bootstrap_admin_display_name,
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.flush()
    write_audit(db, admin, "bootstrap", "user", admin.id)
    db.commit()
    db.refresh(admin)
    return admin
