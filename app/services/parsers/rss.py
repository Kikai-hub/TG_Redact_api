import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import feedparser
from bs4 import BeautifulSoup

from app.services.parsers.base import BaseParser, MediaItem, RawItem, guess_media_type

if TYPE_CHECKING:
    from app.models import Source


class RssParser(BaseParser):
    """Handles both RSS/Atom feeds and WordPress/Medium-style blogs that
    expose a feed (the vast majority do), covering TZ's "blog" source type
    without a separate WordPress-specific integration.
    """

    def fetch(self, source: "Source") -> list[RawItem]:
        parsed = feedparser.parse(source.url)
        items: list[RawItem] = []
        for entry in parsed.entries:
            title = (entry.get("title") or "").strip()
            url = entry.get("link") or ""
            if not title or not url:
                continue
            items.append(
                RawItem(
                    title=title,
                    text=_extract_text(entry),
                    url=url,
                    published_at=_parse_date(entry),
                    media=_extract_media(entry),
                )
            )
        return items


def _strip_html(html: str) -> str:
    return BeautifulSoup(html, "lxml").get_text(separator=" ", strip=True)


def _extract_text(entry) -> str:
    content = entry.get("content")
    if content:
        return _strip_html(content[0].value)
    summary = entry.get("summary")
    if summary:
        return _strip_html(summary)
    return ""


def _parse_date(entry) -> datetime | None:
    struct_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if not struct_time:
        return None
    return datetime.fromtimestamp(time.mktime(struct_time), tz=timezone.utc)


def _medium_to_type(medium: str) -> str | None:
    """Media RSS's medium attribute (image | video | audio | document | executable)."""
    if medium == "video":
        return "video"
    if medium == "image":
        return "photo"
    return None


def _extract_media(entry) -> list[MediaItem]:
    media: list[MediaItem] = []
    for enclosure in entry.get("enclosures", []) or []:
        href = enclosure.get("href")
        if href:
            media.append(MediaItem(url=href, type=guess_media_type(href, enclosure.get("type", ""))))
    for item in entry.get("media_content", []) or []:
        url = item.get("url")
        if not url:
            continue
        media_type = _medium_to_type(item.get("medium", "")) or guess_media_type(url, item.get("type", ""))
        media.append(MediaItem(url=url, type=media_type))
    return media
