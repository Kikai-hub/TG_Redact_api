from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import models
from app.config import get_settings
from app.database import SessionLocal
from app.services.logging_service import log
from app.tasks.celery_app import celery_app

REJECTED_RETENTION_DAYS = 7


@celery_app.task(name="app.tasks.cleanup.purge_old_rejected_posts")
def purge_old_rejected_posts() -> None:
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=REJECTED_RETENTION_DAYS)
        posts = (
            db.query(models.Post)
            .filter(models.Post.status == models.PostStatus.rejected.value, models.Post.rejected_at <= cutoff)
            .all()
        )
        if not posts:
            return

        media_root = Path(get_settings().media_root)
        for post in posts:
            for media_item in post.media:
                if not media_item.file_path:
                    continue
                file_path = Path(media_item.file_path)
                if not file_path.is_absolute():
                    file_path = media_root / file_path
                try:
                    file_path.unlink(missing_ok=True)
                except OSError:
                    pass
            db.delete(post)

        count = len(posts)
        db.commit()
        log(
            db, "info", f"Purged {count} rejected post(s) older than {REJECTED_RETENTION_DAYS} days", "cleanup",
            {"count": count},
        )
    finally:
        db.close()
