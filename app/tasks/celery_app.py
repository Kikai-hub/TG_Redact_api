from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "newsbot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.parsing",
        "app.tasks.ai_processing",
        "app.tasks.publishing",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)

# Beat ticks every 5 minutes; the task itself decides which sources are
# actually due, comparing Source.last_checked against the
# Settings.parse_interval_minutes value the web UI controls (TZ 2.5.7).
# This avoids needing a DB-backed dynamic beat scheduler for a value that
# only needs minute-granularity reconfiguration.
celery_app.conf.beat_schedule = {
    "tick-fetch-active-sources": {
        "task": "app.tasks.parsing.fetch_all_active_sources",
        "schedule": crontab(minute="*/5"),
    },
    "tick-publish-due-scheduled-posts": {
        "task": "app.tasks.publishing.publish_due_scheduled_posts",
        "schedule": crontab(minute="*"),
    },
}
