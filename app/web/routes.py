import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.security import (
    COOKIE_NAME,
    create_access_token,
    hash_password,
    resolve_admin_from_raw_token,
    verify_password,
)
from app.services import settings_store
from app.services.ai_client import AIProcessingError, process_with_ai
from app.tasks.parsing import fetch_source

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# Jinja2's default tojson filter escapes non-ASCII to \uXXXX (json.dumps'
# own default) — override so Cyrillic renders readably in the settings page
# (AI example format, test-ai result). Doesn't affect HTML-safety: <, >, &,
# ' are still escaped separately by Jinja2's htmlsafe_json_dumps.
templates.env.policies["json.dumps_kwargs"] = {"ensure_ascii": False, "sort_keys": True}


def _current_admin(request: Request, db: Session) -> models.Admin | None:
    return resolve_admin_from_raw_token(request.cookies.get(COOKIE_NAME), db)


def _require_admin(request: Request, db: Session):
    """Returns (admin, redirect_response). If redirect_response is not None,
    the caller must return it immediately (Jinja2 routes have no middleware-based auth)."""
    admin = _current_admin(request, db)
    if admin is None:
        return None, RedirectResponse("/login", status_code=303)
    return admin, None


def _require_role(request: Request, db: Session, *roles: str):
    """Like _require_admin, but also enforces the admin's role — used for
    pages that manage secrets/users (Settings, Admins) and must not be
    reachable by a logged-in viewer/moderator just by knowing the URL."""
    admin, redirect = _require_admin(request, db)
    if redirect:
        return None, redirect
    if admin.role not in roles:
        return None, PlainTextResponse("Недостаточно прав", status_code=403)
    return admin, None


# ---------------------------------------------------------------- auth ----

@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    if _current_admin(request, db):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    admin = (
        db.query(models.Admin)
        .filter(models.Admin.username == username, models.Admin.active.is_(True))
        .first()
    )
    if admin is None or not admin.password_hash or not verify_password(password, admin.password_hash):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Неверный логин или пароль"}, status_code=401
        )
    token = create_access_token(admin.username)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", max_age=60 * 60 * 12)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


# ----------------------------------------------------------- dashboard ----

@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_admin(request, db)
    if redirect:
        return redirect

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stats = {
        "total_today": db.query(models.Post).filter(models.Post.created_at >= today_start).count(),
        "published_today": db.query(models.Post)
        .filter(models.Post.published_at.isnot(None), models.Post.published_at >= today_start)
        .count(),
        "rejected_today": db.query(models.Post)
        .filter(models.Post.status == "rejected", models.Post.created_at >= today_start)
        .count(),
        "pending": db.query(models.Post).filter(models.Post.status == "moderated").count(),
        "active_sources": db.query(models.Source).filter(models.Source.active.is_(True)).count(),
        "total_sources": db.query(models.Source).count(),
    }
    recent_posts = db.query(models.Post).order_by(models.Post.id.desc()).limit(10).all()
    return templates.TemplateResponse(
        request, "dashboard.html", {"admin": admin, "stats": stats, "recent_posts": recent_posts}
    )


# ------------------------------------------------------------- sources ----

@router.get("/sources")
def sources_list(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_admin(request, db)
    if redirect:
        return redirect
    sources = db.query(models.Source).order_by(models.Source.id.desc()).all()
    return templates.TemplateResponse(
        request, "sources.html", {"admin": admin, "sources": sources, "error": None}
    )


@router.post("/sources")
def sources_create(
    request: Request,
    name: str = Form(...),
    type: str = Form(...),
    url: str = Form(...),
    config: str = Form("{}"),
    filters: str = Form("{}"),
    db: Session = Depends(get_db),
):
    admin, redirect = _require_admin(request, db)
    if redirect:
        return redirect
    try:
        config_dict = json.loads(config or "{}")
        filters_dict = json.loads(filters or "{}")
    except json.JSONDecodeError as exc:
        sources = db.query(models.Source).order_by(models.Source.id.desc()).all()
        return templates.TemplateResponse(
            request,
            "sources.html",
            {"admin": admin, "sources": sources, "error": f"Некорректный JSON: {exc}"},
        )
    db.add(models.Source(name=name, type=type, url=url, config=config_dict, filters=filters_dict))
    db.commit()
    return RedirectResponse("/sources", status_code=303)


@router.post("/sources/{source_id}/toggle")
def sources_toggle(source_id: int, request: Request, db: Session = Depends(get_db)):
    _, redirect = _require_admin(request, db)
    if redirect:
        return redirect
    source = db.get(models.Source, source_id)
    if source:
        source.active = not source.active
        db.commit()
    return RedirectResponse("/sources", status_code=303)


@router.post("/sources/{source_id}/run")
def sources_run(source_id: int, request: Request, db: Session = Depends(get_db)):
    _, redirect = _require_admin(request, db)
    if redirect:
        return redirect
    fetch_source.delay(source_id)
    return RedirectResponse("/sources", status_code=303)


@router.post("/sources/{source_id}/delete")
def sources_delete(source_id: int, request: Request, db: Session = Depends(get_db)):
    _, redirect = _require_admin(request, db)
    if redirect:
        return redirect
    source = db.get(models.Source, source_id)
    if source:
        db.delete(source)
        db.commit()
    return RedirectResponse("/sources", status_code=303)


# --------------------------------------------------------------- posts ----

@router.get("/posts")
def posts_list(request: Request, status: str | None = None, db: Session = Depends(get_db)):
    admin, redirect = _require_admin(request, db)
    if redirect:
        return redirect
    query = db.query(models.Post)
    if status:
        query = query.filter(models.Post.status == status)
    posts = query.order_by(models.Post.id.desc()).limit(100).all()
    return templates.TemplateResponse(
        request, "posts.html", {"admin": admin, "posts": posts, "status": status}
    )


@router.get("/posts/{post_id}")
def post_detail(post_id: int, request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_admin(request, db)
    if redirect:
        return redirect
    post = db.get(models.Post, post_id)
    if post is None:
        return RedirectResponse("/posts", status_code=303)
    history = (
        db.query(models.Log)
        .filter(models.Log.module.in_(["moderation", "ai_processing", "publishing"]))
        .filter(models.Log.details.isnot(None))
        .order_by(models.Log.id.desc())
        .limit(200)
        .all()
    )
    post_history = [entry for entry in history if (entry.details or {}).get("post_id") == post.id]
    return templates.TemplateResponse(
        request, "post_detail.html", {"admin": admin, "post": post, "history": post_history}
    )


@router.post("/posts/{post_id}/approve")
def post_approve(post_id: int, request: Request, db: Session = Depends(get_db)):
    _, redirect = _require_admin(request, db)
    if redirect:
        return redirect
    from app.tasks.publishing import publish_post

    post = db.get(models.Post, post_id)
    if post and post.status == models.PostStatus.moderated.value:
        publish_post.delay(post.id)
    return RedirectResponse(f"/posts/{post_id}", status_code=303)


@router.post("/posts/{post_id}/reject")
def post_reject(post_id: int, request: Request, db: Session = Depends(get_db)):
    _, redirect = _require_admin(request, db)
    if redirect:
        return redirect
    post = db.get(models.Post, post_id)
    if post and post.status == models.PostStatus.moderated.value:
        post.status = models.PostStatus.rejected.value
        db.commit()
    return RedirectResponse(f"/posts/{post_id}", status_code=303)


@router.post("/posts/{post_id}/edit")
def post_edit(
    post_id: int,
    request: Request,
    title: str = Form(...),
    intro: str = Form(""),
    body: str = Form(...),
    comment: str = Form(""),
    hashtags: str = Form(""),
    db: Session = Depends(get_db),
):
    _, redirect = _require_admin(request, db)
    if redirect:
        return redirect
    post = db.get(models.Post, post_id)
    if post:
        post.ai_processed_text = {
            "title": title,
            "intro": intro,
            "body": body,
            "comment": comment,
            "hashtags": hashtags,
        }
        db.commit()
    return RedirectResponse(f"/posts/{post_id}", status_code=303)


# -------------------------------------------------------------- admins ----

@router.get("/admins")
def admins_list(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_role(request, db, "admin")
    if redirect:
        return redirect
    admins = db.query(models.Admin).order_by(models.Admin.id).all()
    return templates.TemplateResponse(
        request, "admins.html", {"admin": admin, "admins": admins, "error": None}
    )


@router.post("/admins")
def admins_create(
    request: Request,
    username: str = Form(...),
    role: str = Form("viewer"),
    telegram_id: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    admin, redirect = _require_role(request, db, "admin")
    if redirect:
        return redirect
    if db.query(models.Admin).filter(models.Admin.username == username).first():
        admins = db.query(models.Admin).order_by(models.Admin.id).all()
        return templates.TemplateResponse(
            request,
            "admins.html",
            {"admin": admin, "admins": admins, "error": "Логин уже используется"},
        )
    db.add(
        models.Admin(
            username=username,
            role=role,
            telegram_id=int(telegram_id) if telegram_id.strip() else None,
            password_hash=hash_password(password) if password else None,
        )
    )
    db.commit()
    return RedirectResponse("/admins", status_code=303)


@router.post("/admins/{admin_id}/toggle")
def admins_toggle(admin_id: int, request: Request, db: Session = Depends(get_db)):
    _, redirect = _require_role(request, db, "admin")
    if redirect:
        return redirect
    target = db.get(models.Admin, admin_id)
    if target:
        target.active = not target.active
        db.commit()
    return RedirectResponse("/admins", status_code=303)


@router.post("/admins/{admin_id}/delete")
def admins_delete(admin_id: int, request: Request, db: Session = Depends(get_db)):
    _, redirect = _require_role(request, db, "admin")
    if redirect:
        return redirect
    target = db.get(models.Admin, admin_id)
    if target:
        db.delete(target)
        db.commit()
    return RedirectResponse("/admins", status_code=303)


# ------------------------------------------------------------ settings ----

def _secrets_status(db: Session) -> dict:
    return {key: settings_store.is_secret_configured(db, key) for key in settings_store.SECRET_KEYS}


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    admin, redirect = _require_role(request, db, "admin")
    if redirect:
        return redirect
    values = settings_store.get_all_settings(db)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"admin": admin, "values": values, "secrets": _secrets_status(db), "test_result": None, "error": None},
    )


@router.post("/settings")
def settings_save(
    request: Request,
    ai_prompt: str = Form(...),
    ai_example_format: str = Form(...),
    ai_provider: str = Form(...),
    ai_api_base: str = Form(""),
    ai_api_key: str = Form(""),
    ai_api_key_clear: bool = Form(False),
    ai_model: str = Form(...),
    ai_temperature: float = Form(...),
    ai_max_tokens: int = Form(...),
    telegram_bot_token: str = Form(""),
    telegram_bot_token_clear: bool = Form(False),
    target_channel_id: str = Form(""),
    parse_interval_minutes: int = Form(...),
    dedup_window_days: int = Form(...),
    max_posts_per_cycle: int = Form(...),
    db: Session = Depends(get_db),
):
    admin, redirect = _require_role(request, db, "admin")
    if redirect:
        return redirect
    try:
        example_format_dict = json.loads(ai_example_format)
    except json.JSONDecodeError as exc:
        values = settings_store.get_all_settings(db)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "admin": admin,
                "values": values,
                "secrets": _secrets_status(db),
                "test_result": None,
                "error": f"Некорректный JSON в примере формата: {exc}",
            },
        )
    settings_store.set_setting(db, "ai_prompt", ai_prompt)
    settings_store.set_setting(db, "ai_example_format", example_format_dict)
    settings_store.set_setting(db, "ai_provider", ai_provider)
    settings_store.set_setting(db, "ai_api_base", ai_api_base)
    settings_store.set_setting(db, "ai_model", ai_model)
    settings_store.set_setting(db, "ai_temperature", ai_temperature)
    settings_store.set_setting(db, "ai_max_tokens", ai_max_tokens)
    settings_store.set_setting(db, "target_channel_id", target_channel_id)
    settings_store.set_setting(db, "parse_interval_minutes", parse_interval_minutes)
    settings_store.set_setting(db, "dedup_window_days", dedup_window_days)
    settings_store.set_setting(db, "max_posts_per_cycle", max_posts_per_cycle)

    # Secret fields: blank submission = leave unchanged; the "clear" checkbox
    # is the only way to wipe a stored secret. The actual/masked value is
    # never pre-filled into the form, so there is nothing to accidentally
    # round-trip back as the "new" secret.
    if ai_api_key_clear:
        settings_store.set_secret_setting(db, "ai_api_key", None)
    elif ai_api_key.strip():
        settings_store.set_secret_setting(db, "ai_api_key", ai_api_key.strip())

    if telegram_bot_token_clear:
        settings_store.set_secret_setting(db, "telegram_bot_token", None)
    elif telegram_bot_token.strip():
        settings_store.set_secret_setting(db, "telegram_bot_token", telegram_bot_token.strip())

    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/test-ai")
def settings_test_ai(
    request: Request,
    sample_title: str = Form(...),
    sample_text: str = Form(...),
    db: Session = Depends(get_db),
):
    admin, redirect = _require_role(request, db, "admin")
    if redirect:
        return redirect
    values = settings_store.get_all_settings(db)
    api_key = settings_store.get_secret_setting(db, "ai_api_key")
    test_result = None
    error = None
    try:
        test_result = process_with_ai(
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
        error = str(exc)
    except Exception as exc:  # network/auth errors from the AI provider
        error = f"Ошибка запроса к AI: {exc}"
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"admin": admin, "values": values, "secrets": _secrets_status(db), "test_result": test_result, "error": error},
    )


# ---------------------------------------------------------------- logs ----

@router.get("/logs")
def logs_page(
    request: Request,
    level: str | None = None,
    module: str | None = None,
    db: Session = Depends(get_db),
):
    admin, redirect = _require_admin(request, db)
    if redirect:
        return redirect
    query = db.query(models.Log)
    if level:
        query = query.filter(models.Log.level == level)
    if module:
        query = query.filter(models.Log.module == module)
    logs = query.order_by(models.Log.id.desc()).limit(300).all()
    return templates.TemplateResponse(
        request, "logs.html", {"admin": admin, "logs": logs, "level": level, "module": module}
    )
