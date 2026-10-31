from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from Backend.database import get_db
from Backend.models import RevokedToken, User

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "wastewise-ai"
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.environ.get("WASTEWISE_ACCESS_TOKEN_MINUTES", "30")
)
if not 1 <= ACCESS_TOKEN_EXPIRE_MINUTES <= 60:
    raise RuntimeError("WASTEWISE_ACCESS_TOKEN_MINUTES must be between 1 and 60.")

password_hash = PasswordHash.recommended()
_DUMMY_PASSWORD_HASH = password_hash.hash("not-a-real-user-password")
bearer_scheme = HTTPBearer(auto_error=False)


def validate_auth_configuration() -> None:
    secret = os.environ.get("WASTEWISE_JWT_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        raise RuntimeError(
            "Set WASTEWISE_JWT_SECRET to a random secret of at least 32 bytes."
        )


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def verify_unknown_user_password(password: str) -> None:
    password_hash.verify(password, _DUMMY_PASSWORD_HASH)


def create_access_token(user_id: int) -> str:
    validate_auth_configuration()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {
            "sub": str(user_id),
            "jti": str(uuid4()),
            "iat": now,
            "exp": expires_at,
            "iss": JWT_ISSUER,
        },
        os.environ["WASTEWISE_JWT_SECRET"],
        algorithm=JWT_ALGORITHM,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication is required or the access token is invalid.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized

    try:
        validate_auth_configuration()
        claims = jwt.decode(
            credentials.credentials,
            os.environ["WASTEWISE_JWT_SECRET"],
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iat", "jti", "sub", "iss"]},
        )
        user_id = int(claims["sub"])
        token_id = str(claims["jti"])
        if user_id < 1:
            raise ValueError("Invalid user ID claim.")
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized from None

    if db.get(RevokedToken, token_id) is not None:
        raise unauthorized
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized
    return user
