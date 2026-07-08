from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import get_current_admin

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=schemas.DashboardStats)
def dashboard_stats(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    total_today = db.query(models.Post).filter(models.Post.created_at >= today_start).count()
    published_today = db.query(models.Post).filter(models.Post.published_at >= today_start).count()
    rejected_today = (
        db.query(models.Post)
        .filter(models.Post.status == "rejected", models.Post.created_at >= today_start)
        .count()
    )
    pending = db.query(models.Post).filter(models.Post.status == "moderated").count()
    active_sources = db.query(models.Source).filter(models.Source.active.is_(True)).count()
    total_sources = db.query(models.Source).count()

    return schemas.DashboardStats(
        total_posts_today=total_today,
        published_today=published_today,
        rejected_today=rejected_today,
        pending_moderation=pending,
        active_sources=active_sources,
        total_sources=total_sources,
    )
