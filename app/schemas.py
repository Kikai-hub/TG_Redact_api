from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SourceBase(BaseModel):
    name: str
    type: str  # rss | html
    url: str
    config: dict = {}
    filters: dict = {}
    active: bool = True


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    config: dict | None = None
    filters: dict | None = None
    active: bool | None = None


class SourceOut(SourceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    last_checked: datetime | None
    created_at: datetime


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_path: str | None
    file_type: str
    size: int | None
    url: str | None


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    original_title: str
    original_text: str
    original_url: str
    status: str
    ai_processed_text: dict | None
    ai_category: str | None
    ai_tags: list | None
    moderation_comment: str | None
    created_at: datetime
    published_at: datetime | None
    media: list[MediaOut] = []


class PostModerationUpdate(BaseModel):
    ai_processed_text: dict
    moderation_comment: str | None = None


class AdminBase(BaseModel):
    username: str
    telegram_id: int | None = None
    role: str = "viewer"
    active: bool = True


class AdminCreate(AdminBase):
    password: str | None = None


class AdminUpdate(BaseModel):
    telegram_id: int | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = None


class AdminOut(AdminBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    added_at: datetime


class LoginRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    level: str
    message: str
    module: str
    details: dict | None


class SettingsUpdate(BaseModel):
    values: dict


class DashboardStats(BaseModel):
    total_posts_today: int
    published_today: int
    rejected_today: int
    pending_moderation: int
    active_sources: int
    total_sources: int
