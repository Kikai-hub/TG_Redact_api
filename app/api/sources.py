from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import get_current_admin, require_role
from app.tasks.parsing import fetch_source

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[schemas.SourceOut])
def list_sources(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    return db.query(models.Source).order_by(models.Source.id.desc()).all()


@router.post("", response_model=schemas.SourceOut)
def create_source(
    payload: schemas.SourceCreate, db: Session = Depends(get_db), _admin=Depends(require_role("admin"))
):
    source = models.Source(**payload.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("/{source_id}", response_model=schemas.SourceOut)
def get_source(source_id: int, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    source = db.get(models.Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.patch("/{source_id}", response_model=schemas.SourceOut)
def update_source(
    source_id: int,
    payload: schemas.SourceUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    source = db.get(models.Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    db.commit()
    db.refresh(source)
    return source


@router.delete("/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    source = db.get(models.Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    db.delete(source)
    db.commit()
    return {"ok": True}


@router.post("/{source_id}/run")
def run_source(
    source_id: int, db: Session = Depends(get_db), _admin=Depends(require_role("admin", "moderator"))
):
    source = db.get(models.Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    fetch_source.delay(source_id)
    return {"ok": True, "message": "Fetch queued"}
