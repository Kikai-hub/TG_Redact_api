from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app import models
from app.bot.keyboards import (
    NEW_POSTS_BUTTON,
    SCHEDULED_BUTTON,
    edit_choice_keyboard,
    main_menu_keyboard,
    media_edit_keyboard,
    moderation_keyboard,
    post_list_keyboard,
    publish_choice_keyboard,
    reject_all_confirm_keyboard,
)
from app.database import SessionLocal
from app.services import settings_store
from app.services.formatting import format_post_text
from app.services.logging_service import log
from app.services.telegram_sender import send_moderation_message
from app.tasks.publishing import publish_post

router = Router()

SCHEDULE_TIME_FORMAT = "%d.%m.%Y %H:%M"
SCHEDULE_TIME_FORMAT_HINT = "ДД.ММ.ГГГГ ЧЧ:ММ"

# Server runs in UTC (Netherlands); moderators type times in their own local
# clock (Moscow, MSK = UTC+3, fixed year-round — Russia doesn't observe DST).
# Scheduling input/confirmation is shown in MSK; storage/comparison stays UTC.
MODERATOR_TZ = timezone(timedelta(hours=3), name="MSK")

NEW_POSTS_LIST_LIMIT = 10
SHORT_LABEL_LENGTH = 28

# Telegram's hard limit on how many items a media group (album) can carry —
# also used here as the cap on how many files a moderator can attach to one post.
MAX_MEDIA_PER_POST = 10

_MEDIA_KIND_RU = {"photo": "фото", "video": "видео"}


class ModerationStates(StatesGroup):
    waiting_for_edit = State()
    waiting_for_media = State()
    waiting_for_schedule_time = State()


def _get_admin(db, telegram_id: int) -> models.Admin | None:
    return (
        db.query(models.Admin)
        .filter(models.Admin.telegram_id == telegram_id, models.Admin.active.is_(True))
        .first()
    )


def _post_title(post: models.Post) -> str:
    return (post.ai_processed_text or {}).get("title") or post.original_title or "(без текста)"


def _short_label(text: str, length: int = SHORT_LABEL_LENGTH) -> str:
    text = " ".join(text.split())
    return text if len(text) <= length else text[:length].rstrip() + "…"


def _media_edit_prompt_text(post: models.Post) -> str:
    media = post.raw_media or []
    if media:
        lines = [f"Текущие медиафайлы поста #{post.id} ({len(media)} шт.):"]
        lines += [
            f"{i + 1}. {_MEDIA_KIND_RU.get(item.get('type', 'photo'), 'файл')}" for i, item in enumerate(media)
        ]
    else:
        lines = [f"У поста #{post.id} пока нет медиафайлов."]
    lines += [
        "",
        "Пришлите новое фото или видео, чтобы добавить его к посту.",
        "Чтобы удалить текущий файл — нажмите кнопку с его номером ниже.",
        "Когда закончите — нажмите «✅ Готово».",
    ]
    return "\n".join(lines)


async def _open_post_card(message: Message, db, post: models.Post, keyboard: InlineKeyboardMarkup | None) -> None:
    """Sends the post's full text + media as a fresh message — reused by the
    "🆕 Новые"/"🕒 Отложка" list callbacks and by the edit flow. keyboard=None
    renders a read-only preview (used for already-scheduled posts, where the
    moderation actions no longer apply)."""
    token = settings_store.get_secret_setting(db, "telegram_bot_token")
    text = format_post_text(post.ai_processed_text)
    if token:
        await send_moderation_message(token, message.chat.id, text, keyboard, post.raw_media)
    else:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я бот-модератор новостного агрегатора.\n"
        f"Новые посты на модерации смотри по кнопке «{NEW_POSTS_BUTTON}», "
        f"запланированные — по кнопке «{SCHEDULED_BUTTON}» внизу экрана.\n"
        "Используй /help чтобы узнать список команд.",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/start — приветствие\n"
        "/help — эта справка\n"
        "/status — текущее состояние системы\n\n"
        f"«{NEW_POSTS_BUTTON}» — последние {NEW_POSTS_LIST_LIMIT} постов, ожидающих модерации\n"
        f"«{SCHEDULED_BUTTON}» — посты, запланированные к публикации\n\n"
        "Открыв пост из любого из этих списков, используй кнопки под сообщением:\n"
        "✏️ Доработать — выбрать «Текст» (новый текст для поля body) или «Фото/Видео» "
        "(добавить новые файлы или удалить текущие — например, если фото из Telegram-канала "
        "не загрузилось)\n"
        "✅ Опубликовать — выбрать 'Сейчас' или 'По времени' (отложенная публикация)\n"
        "❌ Отказаться — отклонить пост\n\n"
        f"Для отложенной публикации присылай дату и время в формате {SCHEDULE_TIME_FORMAT_HINT} "
        "по московскому времени (МСК) — сервер стоит в Нидерландах и хранит всё в UTC, "
        "но бот сам пересчитает.\n\n"
        "/reject_all — отклонить разом все посты, ожидающие модерации"
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    db = SessionLocal()
    try:
        admin = _get_admin(db, message.from_user.id)
        if admin is None:
            await message.answer("Вы не зарегистрированы как модератор/администратор.")
            return
        counts = {
            status: db.query(models.Post).filter(models.Post.status == status).count()
            for status in ("moderated", "scheduled", "published", "rejected", "error")
        }
        active_sources = db.query(models.Source).filter(models.Source.active.is_(True)).count()
        await message.answer(
            f"Активных источников: {active_sources}\n"
            f"На модерации: {counts['moderated']}\n"
            f"Запланировано: {counts['scheduled']}\n"
            f"Опубликовано: {counts['published']}\n"
            f"Отклонено: {counts['rejected']}\n"
            f"Ошибок обработки: {counts['error']}"
        )
    finally:
        db.close()


@router.message(F.text == NEW_POSTS_BUTTON)
async def cmd_new_posts(message: Message, state: FSMContext) -> None:
    # Tapping a menu button always wins over any in-progress edit/schedule input
    # (both are plain-text handlers gated on FSM state, registered further down) —
    # clear it so a stray leftover state doesn't hijack the moderator's next message.
    await state.clear()
    db = SessionLocal()
    try:
        admin = _get_admin(db, message.from_user.id)
        if admin is None:
            await message.answer("Вы не зарегистрированы как модератор/администратор.")
            return

        posts = (
            db.query(models.Post)
            .filter(models.Post.status == models.PostStatus.moderated.value)
            .order_by(models.Post.id.desc())
            .limit(NEW_POSTS_LIST_LIMIT)
            .all()
        )
        if not posts:
            await message.answer("Новых постов на модерации нет.")
            return

        items = [(post.id, f"#{post.id} — {_short_label(_post_title(post))}") for post in posts]
        await message.answer(
            f"🆕 Новые посты на модерации ({len(posts)}):",
            reply_markup=post_list_keyboard(items, "new:open"),
        )
    finally:
        db.close()


@router.message(F.text == SCHEDULED_BUTTON)
async def cmd_scheduled_posts(message: Message, state: FSMContext) -> None:
    await state.clear()
    db = SessionLocal()
    try:
        admin = _get_admin(db, message.from_user.id)
        if admin is None:
            await message.answer("Вы не зарегистрированы как модератор/администратор.")
            return

        posts = (
            db.query(models.Post)
            .filter(models.Post.status == models.PostStatus.scheduled.value)
            .order_by(models.Post.scheduled_at.asc())
            .all()
        )
        if not posts:
            await message.answer("Отложенных постов нет.")
            return

        items = []
        for post in posts:
            when = post.scheduled_at.astimezone(MODERATOR_TZ).strftime("%d.%m %H:%M") if post.scheduled_at else "?"
            by = post.scheduled_by or "—"
            label = f"#{post.id} {_short_label(_post_title(post))} · {when} МСК · @{by}"
            items.append((post.id, label))

        await message.answer(
            f"🕒 Отложенные посты ({len(posts)}):",
            reply_markup=post_list_keyboard(items, "sched:open"),
        )
    finally:
        db.close()


@router.callback_query(F.data.startswith("new:open:"))
async def handle_open_new_post(callback: CallbackQuery) -> None:
    post_id = int(callback.data.rsplit(":", 1)[1])
    db = SessionLocal()
    try:
        admin = _get_admin(db, callback.from_user.id)
        if admin is None:
            await callback.answer("Вы не зарегистрированы как модератор/администратор.", show_alert=True)
            return
        post = db.get(models.Post, post_id)
        if post is None or post.status != models.PostStatus.moderated.value:
            await callback.answer("Пост уже обработан.", show_alert=True)
            return
        await _open_post_card(callback.message, db, post, moderation_keyboard(post.id))
        await callback.answer()
    finally:
        db.close()


@router.callback_query(F.data.startswith("sched:open:"))
async def handle_open_scheduled_post(callback: CallbackQuery) -> None:
    post_id = int(callback.data.rsplit(":", 1)[1])
    db = SessionLocal()
    try:
        admin = _get_admin(db, callback.from_user.id)
        if admin is None:
            await callback.answer("Вы не зарегистрированы как модератор/администратор.", show_alert=True)
            return
        post = db.get(models.Post, post_id)
        if post is None or post.status != models.PostStatus.scheduled.value:
            await callback.answer("Пост уже обработан.", show_alert=True)
            return
        await _open_post_card(callback.message, db, post, None)
        await callback.answer()
    finally:
        db.close()


@router.message(Command("reject_all"))
async def cmd_reject_all(message: Message) -> None:
    db = SessionLocal()
    try:
        admin = _get_admin(db, message.from_user.id)
        if admin is None or admin.role not in ("moderator", "admin"):
            await message.answer("Недостаточно прав.")
            return

        count = db.query(models.Post).filter(models.Post.status == models.PostStatus.moderated.value).count()
        if count == 0:
            await message.answer("На модерации нет постов.")
            return

        await message.answer(
            f"На модерации {count} пост(ов). Точно отклонить все разом?",
            reply_markup=reject_all_confirm_keyboard(),
        )
    finally:
        db.close()


@router.callback_query(F.data.startswith("modall:"))
async def handle_reject_all_callback(callback: CallbackQuery) -> None:
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await callback.message.edit_text("Отменено.")
        await callback.answer()
        return

    db = SessionLocal()
    try:
        admin = _get_admin(db, callback.from_user.id)
        if admin is None or admin.role not in ("moderator", "admin"):
            await callback.answer("Недостаточно прав", show_alert=True)
            return

        posts = db.query(models.Post).filter(models.Post.status == models.PostStatus.moderated.value).all()
        count = len(posts)
        now = datetime.now(timezone.utc)
        for post in posts:
            post.status = models.PostStatus.rejected.value
            post.rejected_at = now
        db.commit()
        log(
            db, "info", f"{count} post(s) bulk-rejected by {admin.username}", "moderation",
            {"admin": admin.username, "count": count},
        )
        await callback.message.edit_text(f"❌ Отклонено постов: {count}.")
        await callback.answer()
    finally:
        db.close()


@router.callback_query(F.data.startswith("mod:"))
async def handle_moderation_callback(callback: CallbackQuery, state: FSMContext) -> None:
    _, action, post_id_str = callback.data.split(":")
    post_id = int(post_id_str)

    db = SessionLocal()
    try:
        admin = _get_admin(db, callback.from_user.id)
        if admin is None or admin.role not in ("moderator", "admin"):
            await callback.answer("Недостаточно прав", show_alert=True)
            return

        post = db.get(models.Post, post_id)
        if post is None:
            await callback.answer("Пост не найден", show_alert=True)
            return
        if post.status != models.PostStatus.moderated.value:
            await callback.answer("Пост уже обработан другим модератором", show_alert=True)
            return

        if action == "approve":
            await callback.message.edit_reply_markup(reply_markup=publish_choice_keyboard(post.id))
            await callback.answer()

        elif action == "back":
            await callback.message.edit_reply_markup(reply_markup=moderation_keyboard(post.id))
            await callback.answer()

        elif action == "publish_now":
            publish_post.delay(post.id)
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(f"✅ Пост #{post.id} отправлен на публикацию.")
            log(
                db, "info", f"Post {post.id} approved by {admin.username}", "moderation",
                {"post_id": post.id, "admin": admin.username},
            )
            await callback.answer()

        elif action == "schedule":
            await state.update_data(scheduling_post_id=post.id)
            await state.set_state(ModerationStates.waiting_for_schedule_time)
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(
                f"Укажите дату и время публикации поста #{post.id} в формате {SCHEDULE_TIME_FORMAT_HINT} "
                "(по московскому времени, МСК). Например: 10.07.2026 18:30"
            )
            await callback.answer()

        elif action == "reject":
            post.status = models.PostStatus.rejected.value
            post.rejected_at = datetime.now(timezone.utc)
            db.commit()
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(f"❌ Пост #{post.id} отклонён.")
            log(
                db, "info", f"Post {post.id} rejected by {admin.username}", "moderation",
                {"post_id": post.id, "admin": admin.username},
            )
            await callback.answer()

        elif action == "edit":
            await callback.message.edit_reply_markup(reply_markup=edit_choice_keyboard(post.id))
            await callback.answer()

        elif action == "edit_text":
            await state.update_data(editing_post_id=post.id)
            await state.set_state(ModerationStates.waiting_for_edit)
            await callback.message.answer(f"Пришлите новый текст для поста #{post.id} (заменит поле 'body').")
            await callback.answer()

        elif action == "edit_media":
            await state.update_data(editing_post_id=post.id)
            await state.set_state(ModerationStates.waiting_for_media)
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(
                _media_edit_prompt_text(post), reply_markup=media_edit_keyboard(post.id, post.raw_media)
            )
            await callback.answer()
        else:
            await callback.answer()
    finally:
        db.close()


@router.message(ModerationStates.waiting_for_edit)
async def handle_edit_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    post_id = data.get("editing_post_id")
    await state.clear()

    db = SessionLocal()
    try:
        admin = _get_admin(db, message.from_user.id)
        post = db.get(models.Post, post_id) if post_id else None
        if admin is None or post is None:
            await message.answer("Не удалось применить правку — пост или права не найдены.")
            return

        ai_data = dict(post.ai_processed_text or {})
        ai_data["body"] = message.text
        post.ai_processed_text = ai_data
        post.moderation_comment = f"Отредактировано {admin.username}"
        db.commit()
        log(db, "info", f"Post {post.id} edited by {admin.username}", "moderation", {"post_id": post.id})

        await message.answer("Обновлённый пост:")
        await _open_post_card(message, db, post, moderation_keyboard(post.id))
    finally:
        db.close()


@router.callback_query(F.data.startswith("medit:"))
async def handle_media_edit_callback(callback: CallbackQuery, state: FSMContext) -> None:
    _, action, post_id_str, *rest = callback.data.split(":")
    post_id = int(post_id_str)

    db = SessionLocal()
    try:
        admin = _get_admin(db, callback.from_user.id)
        if admin is None or admin.role not in ("moderator", "admin"):
            await callback.answer("Недостаточно прав", show_alert=True)
            return

        post = db.get(models.Post, post_id)
        if post is None or post.status != models.PostStatus.moderated.value:
            await callback.answer("Пост уже обработан", show_alert=True)
            return

        if action == "del":
            index = int(rest[0])
            media = list(post.raw_media or [])
            if not (0 <= index < len(media)):
                await callback.answer("Этот файл уже удалён.", show_alert=True)
                return
            removed = media.pop(index)
            post.raw_media = media
            db.commit()
            log(
                db, "info", f"Media removed from post {post.id} by {admin.username}", "moderation",
                {"post_id": post.id, "admin": admin.username, "type": removed.get("type")},
            )
            await callback.message.edit_text(
                _media_edit_prompt_text(post), reply_markup=media_edit_keyboard(post.id, post.raw_media)
            )
            await callback.answer()

        elif action == "done":
            await state.clear()
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("Медиафайлы обновлены. Обновлённый пост:")
            await _open_post_card(callback.message, db, post, moderation_keyboard(post.id))
            await callback.answer()
        else:
            await callback.answer()
    finally:
        db.close()


@router.message(ModerationStates.waiting_for_media)
async def handle_edit_media(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    post_id = data.get("editing_post_id")

    db = SessionLocal()
    try:
        admin = _get_admin(db, message.from_user.id)
        post = db.get(models.Post, post_id) if post_id else None
        if admin is None or post is None:
            await state.clear()
            await message.answer("Не удалось применить правку — пост или права не найдены.")
            return
        if post.status != models.PostStatus.moderated.value:
            await state.clear()
            await message.answer("Пост уже обработан другим модератором.")
            return

        if message.photo:
            file_id, media_type = message.photo[-1].file_id, "photo"
        elif message.video:
            file_id, media_type = message.video.file_id, "video"
        else:
            await message.answer(
                "Пришлите фото или видео, либо нажмите «✅ Готово» под сообщением со списком медиафайлов."
            )
            return

        media = list(post.raw_media or [])
        if len(media) >= MAX_MEDIA_PER_POST:
            await message.answer(
                f"Достигнут лимит {MAX_MEDIA_PER_POST} медиафайлов на пост (ограничение Telegram для альбомов). "
                "Удалите лишние кнопками выше, прежде чем добавлять новые."
            )
            return

        media.append({"url": file_id, "type": media_type})
        post.raw_media = media
        db.commit()
        log(
            db, "info", f"Media added to post {post.id} by {admin.username}", "moderation",
            {"post_id": post.id, "admin": admin.username, "type": media_type},
        )

        await message.answer(
            _media_edit_prompt_text(post), reply_markup=media_edit_keyboard(post.id, post.raw_media)
        )
    finally:
        db.close()


@router.message(ModerationStates.waiting_for_schedule_time)
async def handle_schedule_time(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    post_id = data.get("scheduling_post_id")

    try:
        scheduled_at_msk = datetime.strptime((message.text or "").strip(), SCHEDULE_TIME_FORMAT).replace(
            tzinfo=MODERATOR_TZ
        )
    except ValueError:
        await message.answer(
            f"Не смог разобрать дату и время. Пришлите в формате {SCHEDULE_TIME_FORMAT_HINT}, "
            "например: 10.07.2026 18:30"
        )
        return

    scheduled_at = scheduled_at_msk.astimezone(timezone.utc)

    if scheduled_at <= datetime.now(timezone.utc):
        await message.answer("Это время уже в прошлом. Пришлите дату и время в будущем (по МСК).")
        return

    await state.clear()

    db = SessionLocal()
    try:
        admin = _get_admin(db, message.from_user.id)
        post = db.get(models.Post, post_id) if post_id else None
        if admin is None or post is None:
            await message.answer("Не удалось запланировать — пост или права не найдены.")
            return
        if post.status != models.PostStatus.moderated.value:
            await message.answer("Пост уже обработан другим модератором.")
            return

        post.status = models.PostStatus.scheduled.value
        post.scheduled_at = scheduled_at
        post.scheduled_by = admin.username
        db.commit()
        log(
            db, "info", f"Post {post.id} scheduled for {scheduled_at.isoformat()} by {admin.username}",
            "moderation", {"post_id": post.id, "admin": admin.username, "scheduled_at": scheduled_at.isoformat()},
        )
        await message.answer(
            f"🕒 Пост #{post.id} запланирован на {scheduled_at_msk.strftime(SCHEDULE_TIME_FORMAT)} МСК "
            f"({scheduled_at.strftime(SCHEDULE_TIME_FORMAT)} UTC — так это время будет выглядеть в веб-панели)."
        )
    finally:
        db.close()
