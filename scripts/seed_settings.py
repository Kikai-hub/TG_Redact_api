"""Seed default Settings rows (idempotent).

Run by the `migrate` service right after `alembic upgrade head`, before
app/bot/celery-worker/celery-beat start — so those processes never race
against missing default rows (e.g. ai_provider) on a fresh database.
"""

from app.database import SessionLocal
from app.services.settings_store import ensure_defaults_seeded


def main() -> None:
    db = SessionLocal()
    try:
        ensure_defaults_seeded(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
