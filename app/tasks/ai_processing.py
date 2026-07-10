from app import models
from app.database import SessionLocal
from app.services import settings_store
from app.services.ai_client import AIProcessingError, process_with_ai
from app.services.logging_service import log
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
        # No push notification here by design: moderators pull the queue via the
        # bot's "🆕 Новые" button instead of getting a card per post in their chat.
    finally:
        db.close()
