import asyncio
import logging
import os
import uuid
from typing import Dict

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from groq import Groq


logging.basicConfig(level=logging.INFO)

# ====================== НАСТРОЙКИ ======================
# Заполни значения ниже (или оставь пустыми и используй переменные окружения).
# 1) API_TOKEN: токен Telegram-бота от @BotFather
# 2) GROQ_KEY: API-ключ Groq
# 3) ADMIN_GROUP_ID: ID админского чата (обычно начинается с -100...)
# 4) CHANNEL_ID: ID канала для автопубликации (обычно начинается с -100...)
#
# Пример:
# API_TOKEN = "123456:ABCDEF..."
# GROQ_KEY = "gsk_xxx"
# ADMIN_GROUP_ID = -1001234567890
# CHANNEL_ID = -1009876543210
API_TOKEN = ""  # <-- вставь токен бота
GROQ_KEY = ""  # <-- вставь ключ Groq
ADMIN_GROUP_ID = 0  # <-- вставь ID админского чата, например -1001234567890
CHANNEL_ID = 0  # <-- вставь ID канала, например -1009876543210


def _pick_str(var_name: str, local_value: str) -> str:
    return os.getenv(var_name, local_value).strip()


def _pick_int(var_name: str, local_value: int) -> int:
    raw = os.getenv(var_name, str(local_value)).strip()
    return int(raw) if raw else 0


API_TOKEN = _pick_str("API_TOKEN", API_TOKEN)
GROQ_KEY = _pick_str("GROQ_KEY", GROQ_KEY)
ADMIN_GROUP_ID = _pick_int("ADMIN_GROUP_ID", ADMIN_GROUP_ID)
CHANNEL_ID = _pick_int("CHANNEL_ID", CHANNEL_ID)


def validate_config() -> None:
    missing = []
    if not API_TOKEN:
        missing.append("API_TOKEN")
    if not GROQ_KEY:
        missing.append("GROQ_KEY")
    if ADMIN_GROUP_ID == 0:
        missing.append("ADMIN_GROUP_ID")
    if CHANNEL_ID == 0:
        missing.append("CHANNEL_ID")

    if missing:
        raise RuntimeError(
            "Не заполнены настройки: "
            + ", ".join(missing)
            + ".\n"
            + "Вариант 1: задай переменные окружения.\n"
            + "Вариант 2: пропиши значения прямо в main.py (блок НАСТРОЙКИ)."
        )


validate_config()

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
groq_client = Groq(api_key=GROQ_KEY)
pending_messages: Dict[str, str] = {}
BOT_USERNAME = "@bot"


async def get_bot_username() -> str:
    me = await bot.get_me()
    return f"@{me.username}" if me.username else "бот"


def format_channel_text(bot_username: str, text: str) -> str:
    return f"By {bot_username}\n\n{text}"


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

    if not message.text:
        await message.answer("Пока проверяю только текст.")
        return

    verdict = await ai_moderate(message.text)
    username = f"@{message.from_user.username}" if message.from_user and message.from_user.username else "без username"

    channel_text = format_channel_text(BOT_USERNAME, message.text)

    if verdict == "APPROVE":
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=channel_text,
        )
        await message.answer("✅ APPROVE: отправлено в канал")
        return

    request_id = uuid.uuid4().hex[:12]
    pending_messages[request_id] = channel_text

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data=f"approve:{request_id}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"reject:{request_id}"),
            ]
        ]
    )

    await bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=f"📩 {verdict} от {username}:\n\n{message.text}",
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
    text = pending_messages.get(request_id)

    if action not in {"approve", "reject"} or not request_id:
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    if not text:
        await callback.answer("Заявка уже обработана или устарела", show_alert=True)
        return

    if action == "approve":
        await bot.send_message(chat_id=CHANNEL_ID, text=text)
        await callback.message.edit_text(f"{callback.message.text}\n\n✅ Одобрено админом и отправлено в канал")
        await callback.answer("Отправлено в канал")
    else:
        await callback.message.edit_text(f"{callback.message.text}\n\n❌ Отклонено админом")
        await callback.answer("Отклонено")

    pending_messages.pop(request_id, None)


async def main() -> None:
    global BOT_USERNAME
    BOT_USERNAME = await get_bot_username()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
