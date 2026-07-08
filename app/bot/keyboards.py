from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# callback_data format: "mod:<action>:<post_id>" — action in {approve, reject, edit}
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
