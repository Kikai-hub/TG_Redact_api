from sqlalchemy.orm import Session

from app import models


def log(db: Session, level: str, message: str, module: str, details: dict | None = None) -> None:
    db.add(models.Log(level=level, message=message, module=module, details=details))
    db.commit()
