from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import api_router
from app.database import SessionLocal
from app.services.settings_store import ensure_defaults_seeded
from app.web.routes import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        ensure_defaults_seeded(db)
    finally:
        db.close()
    yield


app = FastAPI(title="Новостной агрегатор", lifespan=lifespan)


class NoStoreMiddleware(BaseHTTPMiddleware):
    """This whole app is a private admin panel (JWT-cookie/bearer auth) —
    nothing outside /static is safe for a shared browser cache or proxy to
    retain, especially the Settings/Admins pages and any API response."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(NoStoreMiddleware)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "web" / "static")), name="static")

app.include_router(api_router)
app.include_router(web_router)
