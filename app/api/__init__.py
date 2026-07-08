from fastapi import APIRouter

from app.api import admins, auth, dashboard, logs, posts, settings, sources

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(sources.router)
api_router.include_router(posts.router)
api_router.include_router(admins.router)
api_router.include_router(settings.router)
api_router.include_router(logs.router)
api_router.include_router(dashboard.router)
