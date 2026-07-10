from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import get_current_admin, require_role

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("", response_model=list[schemas.PostOut])
def list_posts(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    query = db.query(models.Post)
    if status_filter:
        query = query.filter(models.Post.status == status_filter)
    return query.order_by(models.Post.id.desc()).offset(offset).limit(limit).all()


@router.get("/{post_id}", response_model=schemas.PostOut)
def get_post(post_id: int, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    post = db.get(models.Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.post("/{post_id}/approve")
def approve_post(
    post_id: int, db: Session = Depends(get_db), admin=Depends(require_role("admin", "moderator"))
):
    from app.tasks.publishing import publish_post

    post = db.get(models.Post, post_id)
    if post is None or post.status != models.PostStatus.moderated.value:
        raise HTTPException(status_code=400, detail="Post is not awaiting moderation")
    publish_post.delay(post.id)
    return {"ok": True}


@router.post("/{post_id}/reject")
def reject_post(
    post_id: int, db: Session = Depends(get_db), admin=Depends(require_role("admin", "moderator"))
):
    post = db.get(models.Post, post_id)
    if post is None or post.status != models.PostStatus.moderated.value:
        raise HTTPException(status_code=400, detail="Post is not awaiting moderation")
    post.status = models.PostStatus.rejected.value
    post.rejected_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.patch("/{post_id}", response_model=schemas.PostOut)
def edit_post(
    post_id: int,
    payload: schemas.PostModerationUpdate,
    db: Session = Depends(get_db),
    admin=Depends(require_role("admin", "moderator")),
):
    post = db.get(models.Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    post.ai_processed_text = payload.ai_processed_text
    if payload.moderation_comment is not None:
        post.moderation_comment = payload.moderation_comment
    db.commit()
    db.refresh(post)
    return post
