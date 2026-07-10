import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from app.models import Source

_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}

_BACKGROUND_IMAGE_RE = re.compile(r"background-image\s*:\s*url\((['\"]?)(.*?)\1\)")


def extract_background_image_url(style: str) -> str | None:
    """Pulls the URL out of an inline `background-image: url(...)` style
    declaration — how lazy-loaded galleries embed media instead of an
    `<img src>` (e.g. every photo/video thumbnail on Telegram's t.me/s/
    channel preview)."""
    match = _BACKGROUND_IMAGE_RE.search(style)
    return match.group(2) if match else None


def guess_media_type(url: str, mime_type: str = "") -> str:
    """Best-effort photo/video classification: prefers a MIME type when the
    source provides one (e.g. RSS <enclosure type="...">), otherwise falls
    back to the URL's file extension. Defaults to "photo" when neither is
    conclusive — matches the more common case for news sources and preserves
    prior behavior for URLs we can't classify."""
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("image/"):
        return "photo"
    ext = PurePosixPath(urlparse(url).path).suffix.lower()
    if ext in _VIDEO_EXTENSIONS:
        return "video"
    return "photo"


@dataclass
class MediaItem:
    url: str
    type: str = "photo"  # "photo" | "video"


@dataclass
class RawItem:
    title: str
    text: str
    url: str
    published_at: datetime | None = None
    media: list[MediaItem] = field(default_factory=list)


class BaseParser:
    """A parser turns a Source's remote content into a list of RawItem.

    Adding a new source type (e.g. Telethon-based Telegram channels) means
    implementing this interface and registering it in
    app/services/parsers/__init__.py::PARSERS — no other pipeline code changes.
    """

    def fetch(self, source: "Source") -> list[RawItem]:
        raise NotImplementedError
