import asyncio
import logging
import uuid
from typing import Dict, TypedDict

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from groq import Groq

from config import API_TOKEN, GROQ_KEY, ADMIN_GROUP_ID, CHANNEL_ID, validate_config

logging.basicConfig(level=logging.INFO)

validate_config()

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
groq_client = Groq(api_key=GROQ_KEY)
class PendingMessage(TypedDict):
    content_type: str
    text: str
    file_id: str
    user_id: int


pending_messages: Dict[str, PendingMessage] = {}
BOT_USERNAME = "@bot"


async def get_bot_username() -> str:
    me = await bot.get_me()
    return f"@{me.username}" if me.username else "бот"


def format_channel_text(bot_username: str, text: str) -> str:
    return f"By {bot_username}\n\n{text}"


async def send_to_channel(content_type: str, text: str, file_id: str) -> None:
    if content_type == "photo":
        await bot.send_photo(chat_id=CHANNEL_ID, photo=file_id, caption=text or None)
        return
    if content_type == "video":
        await bot.send_video(chat_id=CHANNEL_ID, video=file_id, caption=text or None)
        return
    if content_type == "animation":
        await bot.send_animation(chat_id=CHANNEL_ID, animation=file_id, caption=text or None)
        return
    if content_type == "document":
        await bot.send_document(chat_id=CHANNEL_ID, document=file_id, caption=text or None)
        return
    if content_type == "sticker":
        await bot.send_sticker(chat_id=CHANNEL_ID, sticker=file_id)
        return
    if content_type == "video_note":
        await bot.send_video_note(chat_id=CHANNEL_ID, video_note=file_id)
        return
    await bot.send_message(chat_id=CHANNEL_ID, text=text)


async def ai_moderate(text: str) -> str:
    prompt = (
        "Ты ИИ-модератор Telegram-канала.\n\n"

        "ПРАВИЛА:\n"
        "Отклоняй (REJECT), если есть:\n"
        "- личные данные (телефоны, юзернеймы, аккаунты)\n"
        "- призывы к насилию\n"
        "- 18+ контент\n"
        "- нацистская или экстремистская символика\n"
        "- геолокации или адреса\n"
        "- номера машин\n"
        "- никотин или снюс\n"
        "- фейки или дезинформация\n\n"

        "Одобряй (APPROVE):\n"
        "- нейтральные, обычные сообщения\n"
        "- вопросы, общение, школьные темы\n\n"

        "Если сомневаешься — MAYBE .\n\n"

        "ОТВЕТ СТРОГО:\n"
        "APPROVE или MAYBE или REJECT\n\n"

        f"Текст: {text}"
    )

    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

    for model in models:
        try:
            response = groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            verdict = (response.choices[0].message.content or "").strip().upper()

            if "APPROVE" in verdict:
                return "APPROVE"
            if "REJECT" in verdict:
                return "REJECT"
            if "MAYBE" in verdict:
                return "MAYBE"
        except Exception:
            logging.exception("Groq error in model %s", model)

    return "MAYBE"


@dp.message(CommandStart())
async def start_handler(message: types.Message) -> None:
    await message.answer("Отправь текст, я проверю и отправлю куда нужно.")


@dp.message()
async def handle_text(message: types.Message) -> None:
    if message.chat.id in {ADMIN_GROUP_ID, CHANNEL_ID}:
        return

    is_photo = bool(message.photo)
    is_video = bool(message.video)
    is_animation = bool(message.animation)
    is_document = bool(message.document)
    is_sticker = bool(message.sticker)
    is_video_note = bool(message.video_note)
    source_text = message.text or message.caption or ""

    supported_media = any([is_photo, is_video, is_animation, is_document, is_sticker, is_video_note])

    if not source_text and not supported_media:
        await message.answer("Поддерживаю текст, фото, видео, gif, файлы, стикеры и видео-кружки.")
        return

    verdict = await ai_moderate(source_text) if source_text else "MAYBE"

    # Медиа не публикуем автоматически только по подписи:
    # даже при APPROVE отправляем на ручную проверку админам.
    if supported_media and verdict == "APPROVE":
        verdict = "MAYBE"
    username = f"@{message.from_user.username}" if message.from_user and message.from_user.username else "без username"

    channel_text = format_channel_text(BOT_USERNAME, source_text) if source_text else ""
    if is_photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
    elif is_video:
        content_type = "video"
        file_id = message.video.file_id
    elif is_animation:
        content_type = "animation"
        file_id = message.animation.file_id
    elif is_document:
        content_type = "document"
        file_id = message.document.file_id
    elif is_sticker:
        content_type = "sticker"
        file_id = message.sticker.file_id
    elif is_video_note:
        content_type = "video_note"
        file_id = message.video_note.file_id
    else:
        content_type = "text"
        file_id = ""

    if verdict == "APPROVE":
        await send_to_channel(content_type=content_type, text=channel_text, file_id=file_id)
        await message.answer("✅ APPROVE: отправлено в канал")
        return

    request_id = uuid.uuid4().hex[:12]
    pending_messages[request_id] = {
        "content_type": content_type,
        "text": channel_text if channel_text else source_text,
        "file_id": file_id,
        "user_id": message.from_user.id if message.from_user else message.chat.id,
    }

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data=f"approve:{request_id}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"reject:{request_id}"),
            ]
        ]
    )

    admin_text = f"📩 {verdict} от {username}:\n\n{source_text or '(без текста)'}"
    if is_photo:
        await bot.send_photo(
            chat_id=ADMIN_GROUP_ID,
            photo=file_id,
            caption=admin_text,
            reply_markup=keyboard,
        )
    elif is_video:
        await bot.send_video(
            chat_id=ADMIN_GROUP_ID,
            video=file_id,
            caption=admin_text,
            reply_markup=keyboard,
        )
    elif is_animation:
        await bot.send_animation(
            chat_id=ADMIN_GROUP_ID,
            animation=file_id,
            caption=admin_text,
            reply_markup=keyboard,
        )
    elif is_document:
        await bot.send_document(
            chat_id=ADMIN_GROUP_ID,
            document=file_id,
            caption=admin_text,
            reply_markup=keyboard,
        )
    elif is_sticker:
        await bot.send_sticker(
            chat_id=ADMIN_GROUP_ID,
            sticker=file_id,
            reply_markup=keyboard,
        )
        await bot.send_message(chat_id=ADMIN_GROUP_ID, text=admin_text)
    elif is_video_note:
        await bot.send_video_note(
            chat_id=ADMIN_GROUP_ID,
            video_note=file_id,
            reply_markup=keyboard,
        )
        await bot.send_message(chat_id=ADMIN_GROUP_ID, text=admin_text)
    else:
        await bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            text=admin_text,
            reply_markup=keyboard,
        )
    await message.answer(f"🛡 {verdict}: отправлено админам")


@dp.callback_query()
async def moderation_callback(callback: types.CallbackQuery) -> None:
    if not callback.data:
        await callback.answer("Некорректная команда", show_alert=True)
        return
    if not callback.message:
        await callback.answer("Сообщение не найдено", show_alert=True)
        return

    action, _, request_id = callback.data.partition(":")
    if action not in {"approve", "reject"} or not request_id:
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    pending = pending_messages.pop(request_id, None)
    if not pending:
        await callback.answer("Заявка уже обработана или устарела", show_alert=True)
        return

    # Сразу убираем кнопки, чтобы исключить повторное нажатие.
    await callback.message.edit_reply_markup(reply_markup=None)

    status_text = (
        "✅ Одобрено админом и отправлено в канал"
        if action == "approve"
        else "❌ Отклонено админом"
    )

    if action == "approve":
        await send_to_channel(
            content_type=pending["content_type"],
            text=pending["text"],
            file_id=pending["file_id"],
        )
        await bot.send_message(
            chat_id=pending["user_id"],
            text="✅ Твое сообщение принято админом и отправлено в канал.",
        )
        await callback.answer("Отправлено в канал")
    else:
        await bot.send_message(
            chat_id=pending["user_id"],
            text="❌ Твое сообщение отклонено админом.",
        )
        await callback.answer("Отклонено")

    if callback.message.photo:
        base_caption = callback.message.caption or ""
        await callback.message.edit_caption(caption=f"{base_caption}\n\n{status_text}")
    elif callback.message.text:
        base_text = callback.message.text or ""
        await callback.message.edit_text(f"{base_text}\n\n{status_text}")
    else:
        await bot.send_message(chat_id=ADMIN_GROUP_ID, text=status_text)


async def main() -> None:
    global BOT_USERNAME
    BOT_USERNAME = await get_bot_username()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
