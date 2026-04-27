import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
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


async def ai_moderate(text: str) -> str:
    prompt = (
        "Ты модератор предложки в Телеграм-канал. "
        "Ответь ОДНИМ словом: APPROVE / REJECT / MAYBE.\n\n"
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
    if not message.text:
        await message.answer("Пока проверяю только текст.")
        return

    verdict = await ai_moderate(message.text)
    username = f"@{message.from_user.username}" if message.from_user and message.from_user.username else "без username"

    if verdict == "APPROVE":
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=message.text,
        )
        await message.answer("✅ APPROVE: отправлено в канал")
        return

    await bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=f"📩 {verdict} от {username}:\n\n{message.text}",
    )
    await message.answer(f"🛡 {verdict}: отправлено админам")


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
