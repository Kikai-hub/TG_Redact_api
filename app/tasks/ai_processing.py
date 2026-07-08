import asyncio

from app import models
from app.database import SessionLocal
from app.services import settings_store
from app.services.ai_client import AIProcessingError, process_with_ai
from app.services.formatting import format_post_text
from app.services.logging_service import log
from app.services.telegram_sender import send_moderation_message
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.ai_processing.process_pending_posts")
def process_pending_posts() -> None:
    db = SessionLocal()
    try:
        posts = db.query(models.Post.id).filter(models.Post.status == models.PostStatus.processed.value).all()
        for (post_id,) in posts:
            process_single_post.delay(post_id)
    finally:
        db.close()


@celery_app.task(name="app.tasks.ai_processing.process_single_post", bind=True, max_retries=1)
def process_single_post(self, post_id: int) -> None:
    db = SessionLocal()
    try:
        post = db.get(models.Post, post_id)
        if post is None or post.status != models.PostStatus.processed.value:
            return

        prompt = settings_store.get_setting(db, "ai_prompt")
        example_format = settings_store.get_setting(db, "ai_example_format")
        model = settings_store.get_setting(db, "ai_model")
        temperature = settings_store.get_setting(db, "ai_temperature")
        max_tokens = settings_store.get_setting(db, "ai_max_tokens")
        provider = settings_store.get_setting(db, "ai_provider")
        api_base = settings_store.get_setting(db, "ai_api_base")
        api_key = settings_store.get_secret_setting(db, "ai_api_key")

        try:
            ai_data = process_with_ai(
                prompt, example_format, post.original_title, post.original_text, model, temperature, max_tokens,
                provider, api_key, api_base,
            )
        except AIProcessingError as exc:
            if self.request.retries < self.max_retries:
                log(
                    db, "warning", f"AI processing failed for post {post.id}, retrying: {exc}",
                    "ai_processing", {"post_id": post.id},
                )
                raise self.retry(exc=exc, countdown=10)
            post.status = models.PostStatus.error.value
            db.commit()
            log(db, "error", f"AI processing failed for post {post.id}: {exc}", "ai_processing", {"post_id": post.id})
            return
        except Exception as exc:
            post.status = models.PostStatus.error.value
            db.commit()
            log(db, "error", f"AI request error for post {post.id}: {exc}", "ai_processing", {"post_id": post.id})
            return

        post.ai_processed_text = ai_data
        post.status = models.PostStatus.moderated.value
        db.commit()
        log(db, "info", f"AI processed post {post.id}", "ai_processing", {"post_id": post.id})

        notify_moderators(db, post)
    finally:
        db.close()


def notify_moderators(db, post: models.Post) -> None:
    from app.bot.keyboards import moderation_keyboard

    token = settings_store.get_secret_setting(db, "telegram_bot_token")
    if not token:
        log(
            db, "error", "Telegram bot token is not configured (Settings); post left unmoderated",
            "ai_processing", {"post_id": post.id},
        )
        return

    moderators = (
        db.query(models.Admin)
        .filter(
            models.Admin.active.is_(True),
            models.Admin.role.in_(["moderator", "admin"]),
            models.Admin.telegram_id.isnot(None),
        )
        .all()
    )
    if not moderators:
        log(
            db, "warning", "No active moderators with telegram_id configured; post left unmoderated",
            "ai_processing", {"post_id": post.id},
        )
        return

    text = format_post_text(post.ai_processed_text)
    keyboard = moderation_keyboard(post.id)
    for moderator in moderators:
        try:
            asyncio.run(send_moderation_message(token, moderator.telegram_id, text, keyboard, post.raw_media))
        except Exception as exc:
            log(
                db, "error", f"Failed to notify moderator {moderator.telegram_id} about post {post.id}: {exc}",
                "ai_processing", {"post_id": post.id},
            )
