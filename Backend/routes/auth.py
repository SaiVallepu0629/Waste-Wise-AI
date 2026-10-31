import hashlib
import os
import time
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy import case, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Backend.auth_schemas import AccessTokenRead, Credentials, UserRead
from Backend.database import get_db
from Backend.models import LoginRateLimit, RevokedToken, User
from Backend.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_ISSUER,
    bearer_scheme,
    create_access_token,
    get_current_user,
    hash_password,
    validate_auth_configuration,
    verify_password,
    verify_unknown_user_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])

LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_EMAIL_LIMIT = 5
LOGIN_ADDRESS_LIMIT = 20
LOGIN_RATE_LIMIT_RETENTION_SECONDS = 24 * 60 * 60


def _token_response(user: User) -> AccessTokenRead:
    return AccessTokenRead(
        access_token=create_access_token(user.id),
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def _login_rate_limit_keys(request: Request, email: str) -> tuple[str, str]:
    client_address = request.client.host if request.client else "unknown"
    address_key = hashlib.sha256(
        f"address\0{client_address}".encode("utf-8")
    ).hexdigest()
    email_key = hashlib.sha256(
        f"email\0{client_address}\0{email}".encode("utf-8")
    ).hexdigest()
    return address_key, email_key


def _check_login_rate_limits(
    db: Session, request: Request, email: str, now: int
) -> tuple[str, str]:
    address_key, email_key = _login_rate_limit_keys(request, email)
    for key in (address_key, email_key):
        record = db.get(LoginRateLimit, key)
        if record is not None and record.blocked_until is not None:
            if record.blocked_until > now:
                retry_after = record.blocked_until - now
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many sign-in attempts. Try again later.",
                    headers={"Retry-After": str(retry_after)},
                )
    return address_key, email_key


def _record_failed_login(
    db: Session, key: str, now: int, limit: int
) -> None:
    reset_window = LoginRateLimit.window_started_at <= now - LOGIN_WINDOW_SECONDS
    next_attempt_count = LoginRateLimit.attempt_count + 1
    statement = sqlite_insert(LoginRateLimit).values(
        key=key,
        window_started_at=now,
        attempt_count=1,
        blocked_until=None,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[LoginRateLimit.key],
        set_={
            "window_started_at": case(
                (reset_window, now), else_=LoginRateLimit.window_started_at
            ),
            "attempt_count": case(
                (reset_window, 1), else_=next_attempt_count
            ),
            "blocked_until": case(
                (reset_window, None),
                (
                    next_attempt_count >= limit,
                    now + LOGIN_WINDOW_SECONDS,
                ),
                else_=LoginRateLimit.blocked_until,
            ),
        },
    )
    db.execute(statement)


def _record_auth_failure(
    db: Session, keys: tuple[str, str], now: int
) -> None:
    db.execute(
        delete(LoginRateLimit).where(
            LoginRateLimit.window_started_at
            <= now - LOGIN_RATE_LIMIT_RETENTION_SECONDS
        )
    )
    _record_failed_login(db, keys[0], now, LOGIN_ADDRESS_LIMIT)
    _record_failed_login(db, keys[1], now, LOGIN_EMAIL_LIMIT)
    db.commit()


def _clear_email_rate_limit(db: Session, key: str) -> None:
    db.execute(delete(LoginRateLimit).where(LoginRateLimit.key == key))
    db.commit()


@router.post(
    "/register",
    response_model=AccessTokenRead,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: Credentials, db: Session = Depends(get_db)) -> AccessTokenRead:
    validate_auth_configuration()
    user = User(
        email=str(payload.email).lower(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from None
    db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=AccessTokenRead)
def login(
    payload: Credentials,
    request: Request,
    db: Session = Depends(get_db),
) -> AccessTokenRead:
    validate_auth_configuration()
    now = int(time.time())
    email = str(payload.email).lower()
    keys = _check_login_rate_limits(db, request, email, now)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        verify_unknown_user_password(payload.password)
        _record_auth_failure(db, keys, now)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not verify_password(payload.password, user.password_hash):
        _record_auth_failure(db, keys, now)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    _clear_email_rate_limit(db, keys[1])
    now = int(datetime.now(timezone.utc).timestamp())
    db.execute(delete(RevokedToken).where(RevokedToken.expires_at <= now))
    db.commit()
    return _token_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    validate_auth_configuration()
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = jwt.decode(
        credentials.credentials,
        os.environ["WASTEWISE_JWT_SECRET"],
        algorithms=[JWT_ALGORITHM],
        issuer=JWT_ISSUER,
        options={"require": ["exp", "jti", "sub", "iss"]},
    )
    token_id = str(claims["jti"])
    if db.get(RevokedToken, token_id) is None:
        db.add(
            RevokedToken(
                jti=token_id,
                user_id=user.id,
                expires_at=int(claims["exp"]),
            )
        )
        db.commit()


@router.get("/me", response_model=UserRead)
def current_profile(user: User = Depends(get_current_user)) -> User:
    return user
