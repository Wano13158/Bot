import asyncio
import base64
import logging
import uuid
from typing import Any, Dict, TypedDict

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


def format_channel_text(bot_username: str, text: str, author: str) -> str:
    return f"✨ Публикация через {bot_username}\n👤 {author}\n\n{text}"


async def get_bot_username() -> str:
    me = await bot.get_me()
    return f"@{me.username}" if me.username else "бот"


async def _telegram_file_as_data_url(file_id: str) -> str | None:
    try:
        file = await bot.get_file(file_id)
        file_bytes = await bot.download_file(file.file_path)
        encoded = base64.b64encode(file_bytes.read()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception:
        logging.exception("Cannot read telegram file for vision moderation")
        return None


async def ai_moderate(text: str, image_file_id: str | None = None) -> str:
    policy = (
        "Ты ИИ-модератор Telegram-канала. Верни только APPROVE, MAYBE или REJECT. "
        "REJECT если есть личные данные, насилие, 18+, экстремизм, точные адреса/геолокации, "
        "номера машин, никотин/снюс, фейки/дезинформация. "
        "APPROVE для нейтрального контента. Если не уверен — MAYBE."
    )

    if image_file_id:
        data_url = await _telegram_file_as_data_url(image_file_id)
        if data_url:
            try:
                response = groq_client.chat.completions.create(
                    model="meta-llama/llama-4-scout-17b-16e-instruct",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"{policy}\nТекст: {text or '(нет)'}"},
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ],
                        }
                    ],
                )
                verdict = (response.choices[0].message.content or "").upper()
                if "APPROVE" in verdict:
                    return "APPROVE"
                if "REJECT" in verdict:
                    return "REJECT"
                return "MAYBE"
            except Exception:
                logging.exception("Groq vision moderation failed")

    prompt = f"{policy}\nТекст: {text}"
    for model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
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


async def send_to_channel(content_type: str, text: str, file_id: str) -> None:
    caption = text or None
    if content_type == "photo":
        await bot.send_photo(CHANNEL_ID, photo=file_id, caption=caption)
    elif content_type == "video":
        await bot.send_video(CHANNEL_ID, video=file_id, caption=caption)
    elif content_type == "animation":
        await bot.send_animation(CHANNEL_ID, animation=file_id, caption=caption)
    elif content_type == "document":
        await bot.send_document(CHANNEL_ID, document=file_id, caption=caption)
    elif content_type == "sticker":
        await bot.send_sticker(CHANNEL_ID, sticker=file_id)
    elif content_type == "video_note":
        await bot.send_video_note(CHANNEL_ID, video_note=file_id)
    elif content_type == "audio":
        await bot.send_audio(CHANNEL_ID, audio=file_id, caption=caption)
    elif content_type == "voice":
        await bot.send_voice(CHANNEL_ID, voice=file_id, caption=caption)
    else:
        await bot.send_message(CHANNEL_ID, text=text or "(пусто)")


@dp.message(CommandStart())
async def start_handler(message: types.Message) -> None:
    await message.answer("Отправь текст/медиа — проверю и опубликую или отправлю админам.")


@dp.message()
async def handle_text(message: types.Message) -> None:
    if message.chat.id in {ADMIN_GROUP_ID, CHANNEL_ID}:
        return

    username = f"@{message.from_user.username}" if message.from_user and message.from_user.username else "без username"
    source_text = message.text or message.caption or ""

    content_type = "text"
    file_id = ""
    image_for_check = None

    if message.photo:
        content_type = "photo"; file_id = message.photo[-1].file_id; image_for_check = file_id
    elif message.video:
        content_type = "video"; file_id = message.video.file_id
    elif message.animation:
        content_type = "animation"; file_id = message.animation.file_id
    elif message.document:
        content_type = "document"; file_id = message.document.file_id
    elif message.sticker:
        content_type = "sticker"; file_id = message.sticker.file_id
    elif message.video_note:
        content_type = "video_note"; file_id = message.video_note.file_id
    elif message.audio:
        content_type = "audio"; file_id = message.audio.file_id
    elif message.voice:
        content_type = "voice"; file_id = message.voice.file_id
    elif message.contact:
        content_type = "text"; source_text = f"Контакт: {message.contact.phone_number}"
    elif message.location:
        content_type = "text"; source_text = f"Локация: {message.location.latitude}, {message.location.longitude}"
    elif message.venue:
        content_type = "text"; source_text = f"Место: {message.venue.title} — {message.venue.address}"
    elif message.poll:
        opts = ", ".join(o.text for o in message.poll.options)
        content_type = "text"; source_text = f"Опрос: {message.poll.question} [{opts}]"

    if not source_text and content_type == "text":
        await message.answer("Поддерживаю: текст, фото, видео, gif, файлы, стикеры, аудио, голосовые, кружки, контакт, гео, venue, опрос.")
        return

    verdict = await ai_moderate(source_text, image_for_check)
    if content_type != "text" and verdict == "APPROVE":
        verdict = "MAYBE"

    channel_text = format_channel_text(BOT_USERNAME, source_text, username) if source_text else ""

    if verdict == "APPROVE":
        await send_to_channel(content_type, channel_text, file_id)
        await message.answer("✅ APPROVE: отправлено в канал")
        return

    request_id = uuid.uuid4().hex[:12]
    pending_messages[request_id] = {"content_type": content_type, "text": channel_text or source_text, "file_id": file_id, "user_id": message.from_user.id if message.from_user else message.chat.id}

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Принять", callback_data=f"approve:{request_id}"), InlineKeyboardButton(text="❌ Отказать", callback_data=f"reject:{request_id}")]])
    admin_text = f"📩 {verdict} от {username}\n🧩 Тип: {content_type}\n\n{source_text or '(без текста)'}"

    if content_type == "photo":
        await bot.send_photo(ADMIN_GROUP_ID, photo=file_id, caption=admin_text, reply_markup=keyboard)
    elif content_type == "video":
        await bot.send_video(ADMIN_GROUP_ID, video=file_id, caption=admin_text, reply_markup=keyboard)
    elif content_type == "animation":
        await bot.send_animation(ADMIN_GROUP_ID, animation=file_id, caption=admin_text, reply_markup=keyboard)
    elif content_type == "document":
        await bot.send_document(ADMIN_GROUP_ID, document=file_id, caption=admin_text, reply_markup=keyboard)
    elif content_type == "audio":
        await bot.send_audio(ADMIN_GROUP_ID, audio=file_id, caption=admin_text, reply_markup=keyboard)
    elif content_type == "voice":
        await bot.send_voice(ADMIN_GROUP_ID, voice=file_id, caption=admin_text, reply_markup=keyboard)
    else:
        await bot.send_message(ADMIN_GROUP_ID, text=admin_text, reply_markup=keyboard)

    await message.answer(f"🛡 {verdict}: отправлено админам")


@dp.callback_query()
async def moderation_callback(callback: types.CallbackQuery) -> None:
    if not callback.data or not callback.message:
        await callback.answer("Некорректная команда", show_alert=True)
        return

    action, _, request_id = callback.data.partition(":")
    if action not in {"approve", "reject"} or not request_id:
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    pending = pending_messages.pop(request_id, None)
    if not pending:
        await callback.answer("Заявка уже обработана", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    status_text = "✅ Одобрено админом" if action == "approve" else "❌ Отклонено админом"

    if action == "approve":
        await send_to_channel(pending["content_type"], pending["text"], pending["file_id"])
        await bot.send_message(pending["user_id"], text="✅ Твоё сообщение принято админом и отправлено в канал.")
        await callback.answer("Отправлено в канал")
    else:
        await bot.send_message(pending["user_id"], text="❌ Твоё сообщение отклонено админом.")
        await callback.answer("Отклонено")

    if callback.message.text:
        await callback.message.edit_text((callback.message.text or "") + f"\n\n{status_text}")


async def main() -> None:
    global BOT_USERNAME
    BOT_USERNAME = await get_bot_username()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
