from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import models
from app.bot.keyboards import moderation_keyboard
from app.database import SessionLocal
from app.services.formatting import format_post_text
from app.services.logging_service import log
from app.tasks.publishing import publish_post

router = Router()


class ModerationStates(StatesGroup):
    waiting_for_edit = State()


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
        "✅ Опубликовать — отправить в канал\n"
        "❌ Отказаться — отклонить пост"
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
            for status in ("moderated", "published", "rejected", "error")
        }
        active_sources = db.query(models.Source).filter(models.Source.active.is_(True)).count()
        await message.answer(
            f"Активных источников: {active_sources}\n"
            f"На модерации: {counts['moderated']}\n"
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
            publish_post.delay(post.id)
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(f"✅ Пост #{post.id} отправлен на публикацию.")
            log(
                db, "info", f"Post {post.id} approved by {admin.username}", "moderation",
                {"post_id": post.id, "admin": admin.username},
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
        await message.answer(
            format_post_text(ai_data), reply_markup=moderation_keyboard(post.id), parse_mode="HTML"
        )
    finally:
        db.close()
