from datetime import datetime, timezone

from app import models
from app.database import SessionLocal
from app.services import filters as filters_service
from app.services import dedup, settings_store
from app.services.logging_service import log
from app.services.parsers import get_parser
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.parsing.fetch_all_active_sources")
def fetch_all_active_sources() -> None:
    db = SessionLocal()
    try:
        interval_minutes = settings_store.get_setting(db, "parse_interval_minutes")
        now = datetime.now(timezone.utc)
        sources = db.query(models.Source).filter(models.Source.active.is_(True)).all()
        for source in sources:
            due = source.last_checked is None or (
                (now - source.last_checked).total_seconds() / 60 >= interval_minutes
            )
            if due:
                fetch_source.delay(source.id)
    finally:
        db.close()


@celery_app.task(name="app.tasks.parsing.fetch_source")
def fetch_source(source_id: int) -> None:
    from app.tasks.ai_processing import process_pending_posts

    db = SessionLocal()
    try:
        source = db.get(models.Source, source_id)
        if source is None or not source.active:
            return

        dedup_window_days = settings_store.get_setting(db, "dedup_window_days")
        max_posts = settings_store.get_setting(db, "max_posts_per_cycle")

        try:
            items = get_parser(source.type).fetch(source)
        except Exception as exc:
            log(db, "error", f"Failed to fetch source '{source.name}': {exc}", "parsing", {"source_id": source.id})
            source.last_checked = datetime.now(timezone.utc)
            db.commit()
            return

        saved = 0
        for item in items:
            if saved >= max_posts:
                break
            if not filters_service.passes_filters(item, source.filters or {}):
                continue
            post_hash = dedup.compute_hash(item.title, item.url)
            if dedup.is_duplicate(db, post_hash, dedup_window_days):
                log(
                    db, "debug", f"Duplicate skipped: {item.title}", "parsing",
                    {"source_id": source.id, "hash": post_hash},
                )
                continue
            db.add(
                models.Post(
                    source_id=source.id,
                    original_title=item.title,
                    original_text=item.text,
                    original_url=item.url,
                    hash=post_hash,
                    raw_media=item.media,
                    status=models.PostStatus.processed.value,
                )
            )
            saved += 1

        source.last_checked = datetime.now(timezone.utc)
        db.commit()
        log(
            db, "info", f"Fetched {len(items)} items, saved {saved} new posts from '{source.name}'",
            "parsing", {"source_id": source.id},
        )

        if saved:
            process_pending_posts.delay()
    finally:
        db.close()
