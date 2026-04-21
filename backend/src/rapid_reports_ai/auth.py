"""Authentication utilities for JWT-based auth"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database.connection import get_db
from .database.models import User

# Security settings
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

# Password hashing
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Get the current authenticated user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    try:
        # Convert user_id to UUID if it's a string
        import uuid as uuid_lib
        if isinstance(user_id, str):
            user_uuid = uuid_lib.UUID(user_id)
        else:
            user_uuid = user_id
    except ValueError:
        raise credentials_exception
    
    user = db.query(User).filter(User.id == user_uuid, User.is_active == True).first()
    if user is None:
        raise credentials_exception
    return user


# ---------------------------------------------------------------------------
# Admin action URL signing (approve / reject from email)
# ---------------------------------------------------------------------------
import hmac as _hmac
import hashlib as _hashlib
from typing import Literal as _Literal
import uuid as _uuid

AdminAction = _Literal["approve", "reject"]
_ALLOWED_ADMIN_ACTIONS: tuple[str, ...] = ("approve", "reject")


def _admin_hmac(user_id: _uuid.UUID, action: str) -> str:
    secret = os.getenv("SECRET_KEY", "")
    if not secret:
        raise RuntimeError("SECRET_KEY not set; cannot sign admin action token")
    msg = f"{user_id}:{action}".encode()
    return _hmac.new(secret.encode(), msg, _hashlib.sha256).hexdigest()


def sign_admin_action(user_id: _uuid.UUID, action: AdminAction) -> str:
    """Produce an HMAC token authorising a one-off admin action for a user."""
    if action not in _ALLOWED_ADMIN_ACTIONS:
        raise ValueError(f"Unknown admin action: {action}")
    return _admin_hmac(user_id, action)


def verify_admin_token(user_id: _uuid.UUID, action: AdminAction, token: str) -> bool:
    """Constant-time compare of a supplied token against the expected HMAC."""
    if action not in _ALLOWED_ADMIN_ACTIONS:
        return False
    expected = _admin_hmac(user_id, action)
    return _hmac.compare_digest(expected, token)
