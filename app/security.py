from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.database import get_db

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

COOKIE_NAME = "access_token"

# bcrypt only uses the first 72 bytes of the input; truncate explicitly so
# long passphrases don't raise instead of silently losing their tail.
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    truncated = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    truncated = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(truncated, hashed.encode("utf-8"))


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except JWTError:
        return None


def resolve_admin(username: str | None, db: Session) -> models.Admin | None:
    if not username:
        return None
    return db.query(models.Admin).filter(models.Admin.username == username, models.Admin.active.is_(True)).first()


def resolve_admin_from_raw_token(raw_token: str | None, db: Session) -> models.Admin | None:
    username = decode_token(raw_token) if raw_token else None
    return resolve_admin(username, db)


def get_current_admin(
    token: str | None = Depends(oauth2_scheme),
    session_cookie: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: Session = Depends(get_db),
) -> models.Admin:
    admin = resolve_admin_from_raw_token(token or session_cookie, db)
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return admin


def get_optional_admin(
    token: str | None = Depends(oauth2_scheme),
    session_cookie: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: Session = Depends(get_db),
) -> models.Admin | None:
    return resolve_admin_from_raw_token(token or session_cookie, db)


def require_role(*roles: str):
    def dependency(admin: models.Admin = Depends(get_current_admin)) -> models.Admin:
        if admin.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return admin

    return dependency
