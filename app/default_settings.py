"""Default values seeded into the `settings` table on first startup.

The web admin can edit all of these at runtime; changes apply to the next
parsing/AI cycle without a restart (tasks re-read Settings from the DB).
"""

DEFAULT_PROMPT = (
    "Ты — профессиональный редактор шуточного новостного паблика. Перепиши сырую "
    "новость в лёгком, ироничном, неформальном тоне, как в популярных развлекательных "
    "телеграм-каналах, но пиши как опытный редактор: кратко и по делу, без вступлений, "
    "повторов и воды — читатель в Telegram не любит простыни текста. Используй уместную "
    "игру слов и сленг, но не искажай фактическую суть новости. Верни ответ СТРОГО в виде "
    "JSON без пояснений и без markdown-обрамления, по следующей схеме."
)

DEFAULT_EXAMPLE_FORMAT = {
    "title": "Короткий цепляющий заголовок, до 80 символов",
    "body": "Основная часть с лёгкой иронией — СТРОГО до 300 символов, только суть, без вступлений и воды",
    "comment": "Короткая ироничная подпись или забавный факт, до 100 символов (опционально)",
    "hashtags": "Ровно 3-4 хэштега через пробел, например: #новости #происшествия #россия",
    "mood_emoji": "Один эмодзи, отражающий настроение комментария — 😂 😱 🔥 😢 🤔 и т.п. (опционально)",
}

DEFAULTS: dict[str, object] = {
    "ai_prompt": DEFAULT_PROMPT,
    "ai_example_format": DEFAULT_EXAMPLE_FORMAT,
    "ai_model": "gpt-4o-mini",
    "ai_temperature": 0.9,
    "ai_max_tokens": 800,
    "target_channel_id": "",
    # Short name of a Telegram custom emoji pack (the part after
    # t.me/addemoji/) — empty disables the feature. When set, the bot looks
    # up a custom emoji from this pack matching the AI's "mood_emoji" and
    # embeds it into the post text via the <tg-emoji> HTML tag (see
    # app/services/telegram_sender.py).
    "emoji_pack_name": "",
    "parse_interval_minutes": 45,
    "dedup_window_days": 7,
    "max_posts_per_cycle": 50,
    "update_requested": None,
}
# ai_provider / ai_api_base are seeded from the AI_PROVIDER / AI_API_BASE env
# vars in settings_store.ensure_defaults_seeded() instead of hardcoded here.
# telegram_bot_token / ai_api_key are secrets — see settings_store.SECRET_KEYS.
