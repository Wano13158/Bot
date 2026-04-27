import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from groq import Groq


logging.basicConfig(level=logging.INFO)

# Пример конфигурации (вставь свои значения в переменные окружения):
# CONFIG_EXAMPLE = {
#     "API_TOKEN": "123456:telegram_bot_token",
#     "GROQ_KEY": "gsk_xxx",
#     "ADMIN_GROUP_ID": "-1001234567890",
#     "CHANNEL_ID": "-1001234567891",
# }

API_TOKEN = os.getenv("API_TOKEN")
GROQ_KEY = os.getenv("GROQ_KEY")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

if not API_TOKEN or not GROQ_KEY or not ADMIN_GROUP_ID or not CHANNEL_ID:
    raise RuntimeError("Set API_TOKEN, GROQ_KEY, ADMIN_GROUP_ID, CHANNEL_ID in env")

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
