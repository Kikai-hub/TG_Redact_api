from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.security import require_role
from app.services import settings_store
from app.services.ai_client import AIProcessingError, process_with_ai

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_settings_values(db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    return settings_store.get_all_settings(db)


@router.get("/secrets-status")
def get_secrets_status(db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    """Never returns secret values — only whether each is configured."""
    return {key: settings_store.is_secret_configured(db, key) for key in settings_store.SECRET_KEYS}


@router.put("")
def update_settings_values(
    payload: schemas.SettingsUpdate, db: Session = Depends(get_db), _admin=Depends(require_role("admin"))
):
    for key, value in payload.values.items():
        if key in settings_store.SECRET_KEYS:
            settings_store.set_secret_setting(db, key, value)
        else:
            settings_store.set_setting(db, key, value)
    return settings_store.get_all_settings(db)


@router.post("/test-ai")
def test_ai(
    sample_title: str,
    sample_text: str,
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    values = settings_store.get_all_settings(db)
    api_key = settings_store.get_secret_setting(db, "ai_api_key")
    try:
        result = process_with_ai(
            values["ai_prompt"],
            values["ai_example_format"],
            sample_title,
            sample_text,
            values["ai_model"],
            values["ai_temperature"],
            values["ai_max_tokens"],
            values["ai_provider"],
            api_key,
            values["ai_api_base"],
        )
    except AIProcessingError as exc:
        return {"error": str(exc)}
    return {"result": result}
