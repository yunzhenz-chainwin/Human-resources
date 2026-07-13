from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.organization import User
from app.schemas.auth import CurrentUserRead, LoginRequest, RefreshRequest, TokenPair
from app.services.security import authenticate, issue_token_pair, rotate_refresh_token, write_audit

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    user = authenticate(db, payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
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
