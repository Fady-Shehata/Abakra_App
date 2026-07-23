"""Security: password hashing, auth dependencies, authorization, audit."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from . import config, models
from .database import get_db

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def audit(db: Session, user_id: Optional[int], action: str, detail: str = "") -> None:
    db.add(models.AuditLog(user_id=user_id, action=action, detail=detail))
    db.commit()


# --------------------------------------------------------------------------- #
# Session-based current user
# --------------------------------------------------------------------------- #
def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[models.User]:
    uid = request.session.get("user_id")
    if not uid:
        return None
    user = db.get(models.User, uid)
    if user and user.is_active:
        return user
    return None


def require_login(request: Request, db: Session = Depends(get_db)) -> models.User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required")
    return user


def require_admin(user: models.User = Depends(require_login)) -> models.User:
    if user.role_name != config.ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_required")
    return user


def require_host(user: models.User = Depends(require_login)) -> models.User:
    if user.role_name not in (config.ROLE_HOST, config.ROLE_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="host_required")
    return user


def can_access_match(user: models.User, match: models.Match) -> bool:
    """Admins access any match; hosts only their assigned matches."""
    if user.role_name == config.ROLE_ADMIN:
        return True
    return match.host_id == user.id


# --------------------------------------------------------------------------- #
# Login throttling helpers
# --------------------------------------------------------------------------- #
def is_locked(user: models.User) -> bool:
    return bool(user.locked_until and user.locked_until > dt.datetime.utcnow())


def register_failed_attempt(db: Session, user: models.User) -> None:
    user.failed_attempts = (user.failed_attempts or 0) + 1
    if user.failed_attempts >= config.MAX_LOGIN_ATTEMPTS:
        user.locked_until = dt.datetime.utcnow() + dt.timedelta(seconds=config.LOGIN_LOCK_SECONDS)
        user.failed_attempts = 0
    db.commit()


def reset_attempts(db: Session, user: models.User) -> None:
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
