from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import models
from app.config import get_settings
from app.database import SessionLocal
from app.services import settings_store
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


@celery_app.task(name="app.tasks.cleanup.auto_reject_stale_moderated_posts")
def auto_reject_stale_moderated_posts() -> None:
    """Posts a moderator never got to within moderation_timeout_hours (Settings,
    default 24h) are auto-rejected so they don't sit in the queue forever.
    Timed from Post.created_at — in practice AI processing moves a post into
    "moderated" within seconds of that, so this is effectively "time since it
    first appeared for review"."""
    db = SessionLocal()
    try:
        timeout_hours = settings_store.get_setting(db, "moderation_timeout_hours")
        if not timeout_hours or timeout_hours <= 0:
            return

        cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)
        posts = (
            db.query(models.Post)
            .filter(models.Post.status == models.PostStatus.moderated.value, models.Post.created_at <= cutoff)
            .all()
        )
        if not posts:
            return

        now = datetime.now(timezone.utc)
        for post in posts:
            post.status = models.PostStatus.rejected.value
            post.rejected_at = now
            post.moderation_comment = f"Автоотклонён: не рассмотрен за {timeout_hours} ч."

        count = len(posts)
        db.commit()
        log(
            db, "info", f"Auto-rejected {count} post(s) unmoderated for over {timeout_hours}h", "cleanup",
            {"count": count, "post_ids": [post.id for post in posts]},
        )
    finally:
        db.close()
