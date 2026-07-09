"""Default values seeded into the `settings` table on first startup.

The web admin can edit all of these at runtime; changes apply to the next
parsing/AI cycle without a restart (tasks re-read Settings from the DB).
"""

DEFAULT_PROMPT = (
    "Ты — редактор шуточного новостного паблика. Перепиши сырую новость в "
    "лёгком, ироничном, неформальном тоне, как в популярных развлекательных "
    "телеграм-каналах. Используй уместную игру слов и сленг, но не искажай "
    "фактическую суть новости. Верни ответ СТРОГО в виде JSON без пояснений "
    "и без markdown-обрамления, по следующей схеме."
)

DEFAULT_EXAMPLE_FORMAT = {
    "title": "Короткий заголовок (до 80 символов)",
    "intro": "Забавное вступление с юмором, 1-2 предложения",
    "body": "Основная часть с ироничными комментариями, до 500 символов",
    "comment": "Смешная подпись или забавный факт (опционально)",
    "hashtags": "#хэштеги #через #пробел",
}

DEFAULTS: dict[str, object] = {
    "ai_prompt": DEFAULT_PROMPT,
    "ai_example_format": DEFAULT_EXAMPLE_FORMAT,
    "ai_model": "gpt-4o-mini",
    "ai_temperature": 0.9,
    "ai_max_tokens": 800,
    "target_channel_id": "",
    "parse_interval_minutes": 45,
    "dedup_window_days": 7,
    "max_posts_per_cycle": 50,
    "update_requested": None,
}
# ai_provider / ai_api_base are seeded from the AI_PROVIDER / AI_API_BASE env
# vars in settings_store.ensure_defaults_seeded() instead of hardcoded here.
# telegram_bot_token / ai_api_key are secrets — see settings_store.SECRET_KEYS.
