from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import models
from app.bot.keyboards import moderation_keyboard, publish_choice_keyboard
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


class ModerationStates(StatesGroup):
    waiting_for_edit = State()
    waiting_for_schedule_time = State()


def _get_admin(db, telegram_id: int) -> models.Admin | None:
    return (
        db.query(models.Admin)
        .filter(models.Admin.telegram_id == telegram_id, models.Admin.active.is_(True))
        .first()
    )


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я бот-модератор новостного агрегатора.\nИспользуй /help чтобы узнать список команд."
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/start — приветствие\n"
        "/help — эта справка\n"
        "/status — текущее состояние системы\n\n"
        "Когда придёт новость на модерацию, используй кнопки под сообщением:\n"
        "✏️ Доработать — прислать новый текст для поля body\n"
        "✅ Опубликовать — выбрать 'Сейчас' или 'По времени' (отложенная публикация)\n"
        "❌ Отказаться — отклонить пост\n\n"
        f"Для отложенной публикации присылай дату и время в формате {SCHEDULE_TIME_FORMAT_HINT} "
        "по московскому времени (МСК) — сервер стоит в Нидерландах и хранит всё в UTC, "
        "но бот сам пересчитает."
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
            db.commit()
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(f"❌ Пост #{post.id} отклонён.")
            log(
                db, "info", f"Post {post.id} rejected by {admin.username}", "moderation",
                {"post_id": post.id, "admin": admin.username},
            )
            await callback.answer()

        elif action == "edit":
            await state.update_data(editing_post_id=post.id)
            await state.set_state(ModerationStates.waiting_for_edit)
            await callback.message.answer(f"Пришлите новый текст для поста #{post.id} (заменит поле 'body').")
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
        token = settings_store.get_secret_setting(db, "telegram_bot_token")
        if token:
            await send_moderation_message(
                token, message.chat.id, format_post_text(ai_data), moderation_keyboard(post.id), post.raw_media
            )
        else:
            await message.answer(
                format_post_text(ai_data), reply_markup=moderation_keyboard(post.id), parse_mode="HTML"
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
