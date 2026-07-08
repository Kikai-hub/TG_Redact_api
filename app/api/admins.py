from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import hash_password, require_role

router = APIRouter(prefix="/admins", tags=["admins"])


@router.get("", response_model=list[schemas.AdminOut])
def list_admins(db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    return db.query(models.Admin).order_by(models.Admin.id).all()


@router.post("", response_model=schemas.AdminOut)
def create_admin(
    payload: schemas.AdminCreate, db: Session = Depends(get_db), _admin=Depends(require_role("admin"))
):
    if db.query(models.Admin).filter(models.Admin.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    admin = models.Admin(
        username=payload.username,
        telegram_id=payload.telegram_id,
        role=payload.role,
        active=payload.active,
        password_hash=hash_password(payload.password) if payload.password else None,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


@router.patch("/{admin_id}", response_model=schemas.AdminOut)
def update_admin(
    admin_id: int,
    payload: schemas.AdminUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    admin = db.get(models.Admin, admin_id)
    if admin is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    for field, value in data.items():
        setattr(admin, field, value)
    if password:
        admin.password_hash = hash_password(password)
    db.commit()
    db.refresh(admin)
    return admin


@router.delete("/{admin_id}")
def delete_admin(admin_id: int, db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    admin = db.get(models.Admin, admin_id)
    if admin is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    db.delete(admin)
    db.commit()
    return {"ok": True}
