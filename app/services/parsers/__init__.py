from app.services.parsers.base import BaseParser, RawItem
from app.services.parsers.html import HtmlParser
from app.services.parsers.rss import RssParser

PARSERS: dict[str, BaseParser] = {
    "rss": RssParser(),
    "html": HtmlParser(),
}


def get_parser(source_type: str) -> BaseParser:
    parser = PARSERS.get(source_type)
    if parser is None:
        raise ValueError(f"No parser registered for source type '{source_type}'")
    return parser


__all__ = ["BaseParser", "RawItem", "PARSERS", "get_parser"]
