from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.default_settings import DEFAULTS
from app.services import crypto

# Stored encrypted via app.services.crypto. Their plaintext must never be
# returned by get_all_settings() or included in any API/HTML response body —
# use get_secret_setting() only where the plaintext is actually needed to
# make an outbound request (Telegram/AI API calls), and is_secret_configured()
# to show status without exposing the value.
SECRET_KEYS = {"telegram_bot_token", "ai_api_key"}


def get_setting(db: Session, key: str):
    if key in SECRET_KEYS:
        raise ValueError(f"'{key}' is a secret setting; use get_secret_setting() instead")
    row = db.get(models.Settings, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key)


def get_all_settings(db: Session) -> dict:
    """Non-secret settings only — see SECRET_KEYS."""
    rows = {
        row.key: row.value for row in db.query(models.Settings).all() if row.key not in SECRET_KEYS
    }
    env = get_settings()
    merged = dict(DEFAULTS)
    merged.setdefault("ai_provider", env.ai_provider)
    merged.setdefault("ai_api_base", env.ai_api_base)
    merged.update(rows)
    return merged


def set_setting(db: Session, key: str, value) -> None:
    if key in SECRET_KEYS:
        raise ValueError(f"'{key}' is a secret setting; use set_secret_setting() instead")
    row = db.get(models.Settings, key)
    if row is None:
        row = models.Settings(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


def get_secret_setting(db: Session, key: str) -> str | None:
    if key not in SECRET_KEYS:
        raise ValueError(f"'{key}' is not a registered secret setting")
    row = db.get(models.Settings, key)
    if row is None or not row.value:
        return None
    return crypto.decrypt(row.value)


def set_secret_setting(db: Session, key: str, plaintext: str | None) -> None:
    """plaintext=None or "" clears the stored secret."""
    if key not in SECRET_KEYS:
        raise ValueError(f"'{key}' is not a registered secret setting")
    encrypted = crypto.encrypt(plaintext) if plaintext else ""
    row = db.get(models.Settings, key)
    if row is None:
        row = models.Settings(key=key, value=encrypted)
        db.add(row)
    else:
        row.value = encrypted
    db.commit()


def is_secret_configured(db: Session, key: str) -> bool:
    if key not in SECRET_KEYS:
        raise ValueError(f"'{key}' is not a registered secret setting")
    row = db.get(models.Settings, key)
    return bool(row and row.value)


def ensure_defaults_seeded(db: Session) -> None:
    """Idempotent. Run once at startup (also gated on the `migrate` service
    in docker-compose, before app/bot/worker/beat start) so those processes
    never race against missing default rows."""
    existing_keys = {row.key for row in db.query(models.Settings.key).all()}
    changed = False

    for key, value in DEFAULTS.items():
        if key not in existing_keys:
            db.add(models.Settings(key=key, value=value))
            changed = True

    env = get_settings()
    for key, value in (("ai_provider", env.ai_provider), ("ai_api_base", env.ai_api_base)):
        if key not in existing_keys:
            db.add(models.Settings(key=key, value=value))
            changed = True

    for key, value in (("telegram_bot_token", env.telegram_bot_token), ("ai_api_key", env.ai_api_key)):
        if key not in existing_keys and value:
            db.add(models.Settings(key=key, value=crypto.encrypt(value)))
            changed = True

    if changed:
        db.commit()
