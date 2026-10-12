"""Загрузка токена из .env."""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN не найден. Проверь, что в корне проекта есть .env "
        "со строкой BOT_TOKEN=твой_токен"
    )