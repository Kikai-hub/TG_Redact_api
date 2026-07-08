import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceType(str, enum.Enum):
    rss = "rss"
    html = "html"


class PostStatus(str, enum.Enum):
    pending = "pending"
    processed = "processed"
    moderated = "moderated"
    published = "published"
    rejected = "rejected"
    error = "error"


class AdminRole(str, enum.Enum):
    viewer = "viewer"
    moderator = "moderator"
    admin = "admin"


class LogLevel(str, enum.Enum):
    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(20))  # SourceType
    url: Mapped[str] = mapped_column(String(1024))
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # CSS selectors etc. for html type
    filters: Mapped[dict] = mapped_column(JSON, default=dict)  # keywords, stop-words, min_length
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    posts: Mapped[list["Post"]] = relationship(back_populates="source")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    original_title: Mapped[str] = mapped_column(String(1024))
    original_text: Mapped[str] = mapped_column(Text)
    original_url: Mapped[str] = mapped_column(String(2048))
    hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_media: Mapped[list] = mapped_column(JSON, default=list)  # list of {"url": str, "type": "photo"|"video"}
    status: Mapped[str] = mapped_column(String(20), default=PostStatus.pending.value, index=True)
    ai_processed_text: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ai_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    moderation_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source: Mapped["Source"] = relationship(back_populates="posts")
    media: Mapped[list["Media"]] = relationship(back_populates="post", cascade="all, delete-orphan")


class Media(Base):
    __tablename__ = "media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    file_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_type: Mapped[str] = mapped_column(String(50))  # photo | video | document
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    post: Mapped["Post"] = relationship(back_populates="media")


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    username: Mapped[str] = mapped_column(String(255), unique=True)
    role: Mapped[str] = mapped_column(String(20), default=AdminRole.viewer.value)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Settings(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(20), default=LogLevel.info.value)
    message: Mapped[str] = mapped_column(Text)
    module: Mapped[str] = mapped_column(String(255))
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
