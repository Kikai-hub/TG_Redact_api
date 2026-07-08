#!/bin/sh
set -e

case "$1" in
  migrate)
    alembic upgrade head
    exec python scripts/seed_settings.py
    ;;
  web)
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  bot)
    exec python -m app.bot.main
    ;;
  worker)
    exec celery -A app.tasks.celery_app.celery_app worker --loglevel=info
    ;;
  beat)
    exec celery -A app.tasks.celery_app.celery_app beat --loglevel=info
    ;;
  *)
    exec "$@"
    ;;
esac
