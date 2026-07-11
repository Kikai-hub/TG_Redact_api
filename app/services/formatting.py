from html import escape


def format_post_text(ai_data: dict, mood_emoji_html: str | None = None) -> str:
    """Renders the AI's JSON into Telegram HTML parse_mode text. Fields are
    HTML-escaped since they come from an untrusted AI response and are sent
    with parse_mode="HTML".

    mood_emoji_html (see telegram_sender._resolve_mood_emoji_html — the
    <tg-emoji> tag for a custom emoji matching ai_data["mood_emoji"]) is
    appended onto the comment line rather than shown on its own: it was
    picked to match the comment's tone, so it's only meaningful alongside it —
    if there's no comment, it's dropped instead of appearing out of context."""
    title = escape(str(ai_data.get("title", "")))
    body = escape(str(ai_data.get("body", "")))
    comment = ai_data.get("comment")
    hashtags = ai_data.get("hashtags")

    parts = [f"<b>{title}</b>", "", body]
    if comment:
        comment_line = f"<i>{escape(str(comment))}</i>"
        if mood_emoji_html:
            comment_line += f" {mood_emoji_html}"
        parts += ["", comment_line]
    if hashtags:
        parts += ["", escape(str(hashtags))]
    return "\n".join(parts)
