from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Source


@dataclass
class RawItem:
    title: str
    text: str
    url: str
    published_at: datetime | None = None
    media: list[str] = field(default_factory=list)


class BaseParser:
    """A parser turns a Source's remote content into a list of RawItem.

    Adding a new source type (e.g. Telethon-based Telegram channels) means
    implementing this interface and registering it in
    app/services/parsers/__init__.py::PARSERS — no other pipeline code changes.
    """

    def fetch(self, source: "Source") -> list[RawItem]:
        raise NotImplementedError
