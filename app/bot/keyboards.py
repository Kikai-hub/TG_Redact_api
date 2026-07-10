from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# callback_data format: "mod:<action>:<post_id>" — action in
# {approve, reject, edit, publish_now, schedule, back}
CALLBACK_PREFIX = "mod"


def moderation_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Доработать", callback_data=f"{CALLBACK_PREFIX}:edit:{post_id}"),
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"{CALLBACK_PREFIX}:approve:{post_id}"),
                InlineKeyboardButton(text="❌ Отказаться", callback_data=f"{CALLBACK_PREFIX}:reject:{post_id}"),
            ]
        ]
    )


def publish_choice_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Сейчас", callback_data=f"{CALLBACK_PREFIX}:publish_now:{post_id}"),
                InlineKeyboardButton(text="🕒 По времени", callback_data=f"{CALLBACK_PREFIX}:schedule:{post_id}"),
                InlineKeyboardButton(text="◀️ Назад", callback_data=f"{CALLBACK_PREFIX}:back:{post_id}"),
            ]
        ]
    )


# callback_data format: "modall:<action>" — action in {confirm, cancel}
REJECT_ALL_CALLBACK_PREFIX = "modall"


def reject_all_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Да, отклонить все", callback_data=f"{REJECT_ALL_CALLBACK_PREFIX}:confirm"
                ),
                InlineKeyboardButton(text="Отмена", callback_data=f"{REJECT_ALL_CALLBACK_PREFIX}:cancel"),
            ]
        ]
    )


# Persistent menu shown at the bottom of the chat (not tied to any one message,
# unlike the inline keyboards above) — the bot's take on "tabs".
NEW_POSTS_BUTTON = "🆕 Новые"
SCHEDULED_BUTTON = "🕒 Отложка"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=NEW_POSTS_BUTTON), KeyboardButton(text=SCHEDULED_BUTTON)]],
        resize_keyboard=True,
    )


def post_list_keyboard(items: list[tuple[int, str]], callback_prefix: str) -> InlineKeyboardMarkup:
    """items: (post_id, label) pairs, one button per row. callback_data becomes
    '<callback_prefix>:<post_id>', e.g. callback_prefix="new:open" -> "new:open:123"."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"{callback_prefix}:{post_id}")]
            for post_id, label in items
        ]
    )
