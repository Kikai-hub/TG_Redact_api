from typing import TYPE_CHECKING
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from app.services.parsers.base import BaseParser, RawItem

if TYPE_CHECKING:
    from app.models import Source

USER_AGENT = "Mozilla/5.0 (compatible; NewsAggregatorBot/1.0)"


class HtmlParser(BaseParser):
    """Generic HTML scraper driven entirely by CSS selectors in Source.config:

    item_selector   (required) - selects each news item's root element
    title_selector  - relative selector for the title text
    text_selector   - relative selector for the body text (falls back to title)
    url_selector    - relative selector for the link element (falls back to the item itself)
    url_attr        - attribute holding the link (default "href")
    media_selector  - relative selector for media elements
    media_attr      - attribute holding the media URL (default "src")
    base_url        - base URL for resolving relative links (default: source.url)
    """

    def fetch(self, source: "Source") -> list[RawItem]:
        config = source.config or {}
        item_selector = config.get("item_selector")
        if not item_selector:
            raise ValueError(
                f"Source {source.id} ({source.name}): config.item_selector is required for html sources"
            )

        response = httpx.get(
            source.url, timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        base_url = config.get("base_url", source.url)
        title_selector = config.get("title_selector")
        text_selector = config.get("text_selector")
        url_selector = config.get("url_selector")
        url_attr = config.get("url_attr", "href")
        media_selector = config.get("media_selector")
        media_attr = config.get("media_attr", "src")

        items: list[RawItem] = []
        for node in soup.select(item_selector):
            title = _select_text(node, title_selector)
            text = _select_text(node, text_selector) or title
            url = _select_attr(node, url_selector, url_attr)
            if url:
                url = urljoin(base_url, url)
            media = []
            if media_selector:
                for media_node in node.select(media_selector):
                    src = media_node.get(media_attr)
                    if src:
                        media.append(urljoin(base_url, src))
            if not title or not url:
                continue
            items.append(RawItem(title=title, text=text or "", url=url, media=media))
        return items


def _select_text(node: Tag, selector: str | None) -> str | None:
    target = node.select_one(selector) if selector else node
    if target is None:
        return None
    return target.get_text(separator=" ", strip=True)


def _select_attr(node: Tag, selector: str | None, attr: str) -> str | None:
    target = node.select_one(selector) if selector else node
    if target is None:
        return None
    return target.get(attr)
