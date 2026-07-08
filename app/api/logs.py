from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import get_current_admin

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=list[schemas.LogOut])
def list_logs(
    level: str | None = None,
    module: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    query = db.query(models.Log)
    if level:
        query = query.filter(models.Log.level == level)
    if module:
        query = query.filter(models.Log.module == module)
    if since:
        query = query.filter(models.Log.timestamp >= since)
    return query.order_by(models.Log.id.desc()).limit(limit).all()
