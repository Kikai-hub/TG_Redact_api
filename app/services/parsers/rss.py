import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.services.parsers.base import BaseParser, MediaItem, RawItem, guess_media_type

if TYPE_CHECKING:
    from app.models import Source

USER_AGENT = "Mozilla/5.0 (compatible; NewsAggregatorBot/1.0)"


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
            media = _extract_media(entry) or _fetch_fallback_media(url)
            items.append(
                RawItem(
                    title=title,
                    text=_extract_text(entry),
                    url=url,
                    published_at=_parse_date(entry),
                    media=media,
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


def _fetch_fallback_media(article_url: str) -> list[MediaItem]:
    """Some feeds (e.g. iz.ru's) carry no <enclosure>/<media:content> at all
    and no <img> in the description either, even though the article itself
    has a lead image — the feed just never included it. Rather than lose the
    image, this fetches the article page itself and pulls its og:image, the
    lead-image meta tag virtually every news site sets for link previews
    regardless of what its feed carries. Best-effort and silent on failure
    (site unreachable, no og:image present, etc.) — same as before this
    fallback existed, the post just goes out without media."""
    try:
        response = httpx.get(article_url, timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
    except httpx.HTTPError:
        return []

    soup = BeautifulSoup(response.text, "lxml")
    tag = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
    url = tag.get("content") if tag else None
    if not url:
        return []
    return [MediaItem(url=url, type=guess_media_type(url))]
