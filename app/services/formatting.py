from html import escape


def format_post_text(ai_data: dict) -> str:
    """Renders the AI's 5-field JSON into Telegram HTML parse_mode text.
    Fields are HTML-escaped since they come from an untrusted AI response
    and are sent with parse_mode="HTML"."""
    title = escape(str(ai_data.get("title", "")))
    intro = escape(str(ai_data.get("intro", "")))
    body = escape(str(ai_data.get("body", "")))
    comment = ai_data.get("comment")
    hashtags = ai_data.get("hashtags")

    parts = [f"<b>{title}</b>", "", intro, "", body]
    if comment:
        parts += ["", f"<i>{escape(str(comment))}</i>"]
    if hashtags:
        parts += ["", escape(str(hashtags))]
    return "\n".join(parts)
