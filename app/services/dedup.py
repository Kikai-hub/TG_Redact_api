import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import models


def compute_hash(title: str, url: str) -> str:
    basis = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def is_duplicate(db: Session, post_hash: str, window_days: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    exists = (
        db.query(models.Post.id)
        .filter(models.Post.hash == post_hash, models.Post.created_at >= cutoff)
        .first()
    )
    return exists is not None
