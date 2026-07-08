import asyncio
from datetime import datetime, timezone

from app import models
from app.database import SessionLocal
from app.services import settings_store
from app.services.formatting import format_post_text
from app.services.logging_service import log
from app.services.telegram_sender import publish_to_channel
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.publishing.publish_post", bind=True, max_retries=2)
def publish_post(self, post_id: int) -> None:
    db = SessionLocal()
    try:
        post = db.get(models.Post, post_id)
        if post is None or post.status != models.PostStatus.moderated.value:
            return

        channel_id = settings_store.get_setting(db, "target_channel_id")
        if not channel_id:
            log(db, "error", "target_channel_id is not configured; cannot publish", "publishing", {"post_id": post.id})
            return

        token = settings_store.get_secret_setting(db, "telegram_bot_token")
        if not token:
            log(db, "error", "Telegram bot token is not configured (Settings); cannot publish", "publishing", {"post_id": post.id})
            return

        text = format_post_text(post.ai_processed_text)
        try:
            asyncio.run(publish_to_channel(token, channel_id, text, post.raw_media))
        except Exception as exc:
            log(db, "error", f"Failed to publish post {post.id}: {exc}", "publishing", {"post_id": post.id})
            raise self.retry(exc=exc, countdown=15)

        post.status = models.PostStatus.published.value
        post.published_at = datetime.now(timezone.utc)
        db.commit()
        log(db, "info", f"Published post {post.id}", "publishing", {"post_id": post.id})
    finally:
        db.close()
