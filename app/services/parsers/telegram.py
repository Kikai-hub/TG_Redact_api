from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from app.services.parsers.base import BaseParser, MediaItem, RawItem, extract_background_image_url

if TYPE_CHECKING:
    from app.models import Source

USER_AGENT = "Mozilla/5.0 (compatible; NewsAggregatorBot/1.0)"

_TITLE_MAX_LENGTH = 100
_MAX_PHOTOS_PER_POST = 3


class TelegramParser(BaseParser):
    """Scrapes a public Telegram channel's web preview (t.me/s/<channel>) —
    no bot token or Telethon session needed, since that page is public and
    unauthenticated. Unlike the generic `html` parser, this knows Telegram's
    markup up front: photos/videos are rendered as `background-image` on
    `<a>`/`<i>` elements (photos) or a plain `<video src>` (videos), never an
    `<img>` tag, so a source using the generic parser with an `img` media
    selector silently gets zero media. `source.url` may be a bare channel
    username, `@username`, or any t.me/telegram.me link to the channel.
    """

    def fetch(self, source: "Source") -> list[RawItem]:
        channel = _extract_channel(source.url)
        response = httpx.get(
            f"https://t.me/s/{channel}",
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        items: list[RawItem] = []
        for node in soup.select("div.tgme_widget_message[data-post]"):
            text = _extract_text(node)
            media = _extract_media(node)
            if not text and not media:
                continue
            items.append(
                RawItem(
                    title=_derive_title(text),
                    text=text,
                    url=f"https://t.me/{node['data-post']}",
                    published_at=_extract_date(node),
                    media=media,
                )
            )
        return items


def _extract_channel(source_url: str) -> str:
    value = source_url.strip().lstrip("@")
    if "/" in value:
        path = urlparse(value if "://" in value else f"//{value}").path
        parts = [part for part in path.split("/") if part and part != "s"]
        if parts:
            return parts[0]
    return value


def _extract_text(node: Tag) -> str:
    text_node = node.select_one(".tgme_widget_message_text.js-message_text")
    if text_node is None:
        return ""
    for br in text_node.find_all("br"):
        br.replace_with("\n")
    return text_node.get_text().strip()


def _derive_title(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(first_line) <= _TITLE_MAX_LENGTH:
        return first_line
    return first_line[:_TITLE_MAX_LENGTH].rsplit(" ", 1)[0] + "…"


def _extract_media(node: Tag) -> list[MediaItem]:
    media: list[MediaItem] = []
    photo_count = 0
    for photo in node.select(".tgme_widget_message_photo_wrap"):
        if photo_count >= _MAX_PHOTOS_PER_POST:
            break
        src = extract_background_image_url(photo.get("style") or "")
        if src:
            media.append(MediaItem(url=src, type="photo"))
            photo_count += 1
    for video in node.select("video.tgme_widget_message_video"):
        src = video.get("src")
        if src:
            media.append(MediaItem(url=src, type="video"))
    return media


def _extract_date(node: Tag) -> datetime | None:
    time_node = node.select_one(".tgme_widget_message_date time")
    if time_node is None or not time_node.get("datetime"):
        return None
    try:
        return datetime.fromisoformat(time_node["datetime"])
    except ValueError:
        return None
