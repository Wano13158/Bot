import os

# ====================== НАСТРОЙКИ ======================
# Укажи значения ниже или передай их через переменные окружения.
# 1) API_TOKEN: токен Telegram-бота от @BotFather
# 2) GROQ_KEY: API-ключ Groq
# 3) ADMIN_GROUP_ID: ID админского чата (обычно начинается с -100...)
# 4) CHANNEL_ID: ID канала для автопубликации (обычно начинается с -100...)
API_TOKEN = ""
GROQ_KEY = ""
ADMIN_GROUP_ID = 0
CHANNEL_ID = 0


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
            + "Вариант 2: пропиши значения прямо в config.py."
        )
