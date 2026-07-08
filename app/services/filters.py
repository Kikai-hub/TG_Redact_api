from app.services.parsers.base import RawItem


def passes_filters(item: RawItem, filters: dict) -> bool:
    """filters keys (all optional): keywords (list[str], must match >=1),
    stop_words (list[str], any match excludes), min_length (int, on item.text)."""
    text = f"{item.title} {item.text}".lower()

    min_length = filters.get("min_length")
    if min_length and len(item.text) < min_length:
        return False

    keywords = filters.get("keywords") or []
    if keywords and not any(keyword.lower() in text for keyword in keywords):
        return False

    stop_words = filters.get("stop_words") or []
    if stop_words and any(word.lower() in text for word in stop_words):
        return False

    return True
