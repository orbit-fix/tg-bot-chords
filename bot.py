"""Telegram-бот: аккорды для гитары с транспонированием и квинтами."""
import asyncio
import logging

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import BOT_TOKEN
from parser_5lad import find_song as find_5lad, get_song as get_5lad
from parser_mytabs import find_song as find_mytabs, get_song as get_mytabs
import storage
from chords import transpose, to_power

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Твой админ-ID
ADMIN_ID = 1586063545

# Состояние пользователей
USER_STATE: dict[int, dict] = {}

# Шаблон для /add
ADD_TEMPLATE = """Скопируй этот шаблон, заполни и отправь боту:

Название: 
Исполнитель: 
Аккорды:

(всё, что после "Аккорды:" — текст с аккордами)"""
def find_song_cascade(query: str) -> tuple[list[dict], str]:
    """Каскадный поиск: ручная база → 5lad → mytabs.

    :return: (список_результатов, источник)
    """
    # 1) Ручная база
    custom = storage.find_songs(query, limit=5)
    if custom:
        return custom, "custom"

    # 2) 5lad.net
    try:
        results = find_5lad(query, limit=5)
        if results:
            return results, "5lad"
    except Exception as e:
        logging.warning(f"5lad ошибка: {e}")

    # 3) mytabs.ru
    try:
        results = find_mytabs(query, limit=5)
        if results:
            return results, "mytabs"
    except Exception as e:
        logging.warning(f"mytabs ошибка: {e}")

    return [], ""


async def notify_admin_not_found(user: types.User, query: str) -> None:
    """Отправляет админу уведомление о ненайденном запросе."""
    username = f"@{user.username}" if user.username else user.full_name
    try:
        await bot.send_message(
            ADMIN_ID,
            f"🔍 Запрос не найден\n"
            f"От: {username} (id {user.id})\n"
            f"Запрос: «{query}»\n\n"
            f"Добавить: /add",
        )
    except Exception as e:
        logging.warning(f"Не удалось уведомить админа: {e}")

# ---------- вспомогательные ----------

def render_text(state: dict) -> str:
    """Применяет текущие настройки к оригинальному тексту песни."""
    text = state["original"]
    if state["semitones"] != 0:
        text = transpose(text, state["semitones"])
    if state["mode"] == "power":
        text = to_power(text)
    return text


def build_keyboard(user_id: int) -> InlineKeyboardMarkup:
    state = USER_STATE.get(user_id)
    current_semitones = state["semitones"] if state else 0
    current_mode = state["mode"] if state else "normal"
    shift_label = f"+{current_semitones}" if current_semitones > 0 else str(current_semitones)

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="−2", callback_data="trans:-2"),
            InlineKeyboardButton(text="−1", callback_data="trans:-1"),
            InlineKeyboardButton(text=f"🎼 {shift_label}", callback_data="noop"),
            InlineKeyboardButton(text="+1", callback_data="trans:+1"),
            InlineKeyboardButton(text="+2", callback_data="trans:+2"),
        ],
        [
            InlineKeyboardButton(
                text=("✅ " if current_mode == "normal" else "") + "🎸 Обычные",
                callback_data="mode:normal",
            ),
            InlineKeyboardButton(
                text=("✅ " if current_mode == "power" else "") + "⚡ Квинты",
                callback_data="mode:power",
            ),
        ],
        [InlineKeyboardButton(text="🔄 Сброс", callback_data="reset")],
    ])


async def edit_song_message(callback: types.CallbackQuery, user_id: int) -> None:
    state = USER_STATE.get(user_id)
    if not state or "original" not in state:
        await callback.answer("Состояние потеряно, начни заново через /song")
        return

    header = f"🎵 {state['artist']} — {state['title']}\n\n"
    body = render_text(state)
    full = header + body
    if len(full) > 4000:
        full = full[:4000] + "\n\n… (обрезано)"

    try:
        await callback.message.edit_text(
            full,
            reply_markup=build_keyboard(user_id),
            parse_mode=None,
        )
    except Exception as e:
        logging.debug(f"edit_text: {e}")


# ---------- команды ----------

@dp.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    await message.answer(
        "Привет! Я помогу найти аккорды для гитары 🎸\n\n"
        "Команды:\n"
        "/song <название> — найти аккорды\n"
        "/help — помощь"
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
    await message.answer(
        "Как пользоваться:\n"
        "1. /song Название песни (можно с исполнителем)\n"
        "2. Выбери песню из списка\n"
        "3. Управляй кнопками:\n"
        "   • ±1 / ±2 — сдвинуть тональность\n"
        "   • 🎸 / ⚡ — переключить обычные/квинты\n"
        "   • 🔄 — сброс\n\n"
        "Примеры:\n"
        "/song Баста Сансара\n"
        "/song Кис-кис Молчи\n"
        "/song Кино Группа крови"
    )


@dp.message(Command("song"))
async def cmd_song(message: types.Message, command: CommandObject) -> None:
    query = (command.args or "").strip()
    if not query:
        await message.answer("Укажи название: /song Баста Сансара")
        return

    await message.answer(f"🔍 Ищу «{query}»...")

    # Каскадный поиск
    results, source = find_song_cascade(query)

    if not results:
        # Ничего не нашлось — уведомляем админа
        await notify_admin_not_found(message.from_user, query)
        await message.answer(
            "Не нашёл 😔 Попробуй по-другому:\n"
            "• /song Кино Группа крови\n"
            "• /song Баста Сансара\n\n"
            "Можешь также написать название точнее или добавить исполнителя."
        )
        return

    # Показываем результаты с пометкой источника
    source_label = {
        "custom": "⭐ Моя база",
        "5lad": "🌐 5lad.net",
        "mytabs": "🌐 mytabs.ru",
    }.get(source, "")

    USER_STATE[message.from_user.id] = {
        "search_results": results,
        "source": source,
    }

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{r['artist']} — {r['title']}"[:60],
            callback_data=f"song:{i}",
        )]
        for i, r in enumerate(results)
    ])

    await message.answer(
        f"Нашёл варианты ({source_label}):",
        reply_markup=keyboard,
    )

# ---------- админ-команды ----------

@dp.message(Command("add"))
async def cmd_add(message: types.Message) -> None:
    if message.from_user.id != ADMIN_ID:
        await message.answer("Эта команда только для администратора.")
        return

    await message.answer(ADD_TEMPLATE)


@dp.message(Command("list"))
async def cmd_list(message: types.Message) -> None:
    if message.from_user.id != ADMIN_ID:
        await message.answer("Эта команда только для администратора.")
        return

    songs = storage.list_all(limit=30)
    if not songs:
        await message.answer("База пуста. Добавь песни через /add")
        return

    lines = [f"[{s['id']}] {s['artist']} — {s['title']}" for s in songs]
    await message.answer("Сохранённые песни:\n\n" + "\n".join(lines))


@dp.message(Command("del"))
async def cmd_del(message: types.Message, command: CommandObject) -> None:
    if message.from_user.id != ADMIN_ID:
        await message.answer("Эта команда только для администратора.")
        return

    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Укажи ID: /del 5")
        return

    ok = storage.delete_song(int(arg))
    if ok:
        await message.answer(f"✅ Удалено: id {arg}")
    else:
        await message.answer(f"Не найдено: id {arg}")


# ---------- парсинг /add (текст в формате шаблона) ----------

def parse_add_template(text: str) -> dict | None:
    """Парсит текст в формате:
        Название: ...
        Исполнитель: ...
        Аккорды:
        ...многострочный текст...
    """
    lines = text.splitlines()
    title = None
    artist = None
    chords_lines = []
    mode = None  # "meta" или "chords"

    for line in lines:
        low = line.lower().strip()
        if low.startswith("название:"):
            title = line.split(":", 1)[1].strip()
            mode = "meta"
        elif low.startswith("исполнитель:"):
            artist = line.split(":", 1)[1].strip()
            mode = "meta"
        elif low.startswith("аккорды:"):
            mode = "chords"
            tail = line.split(":", 1)[1].strip()
            if tail:
                chords_lines.append(tail)
        elif mode == "chords":
            chords_lines.append(line)

    if not title or not artist or not chords_lines:
        return None

    chords = "\n".join(chords_lines).strip()
    if not chords:
        return None

    return {"title": title, "artist": artist, "chords": chords}


@dp.message(F.text & ~F.text.startswith("/"))
async def on_plain_text(message: types.Message) -> None:
    """Обрабатывает обычные сообщения: если это шаблон /add — сохраняем."""
    if message.from_user.id != ADMIN_ID:
        return

    text = message.text or ""
    if "Название:" not in text and "название:" not in text:
        return
    if "Аккорды:" not in text and "аккорды:" not in text:
        return

    parsed = parse_add_template(text)
    if not parsed:
        await message.answer("Не получилось распарсить. Проверь формат: /add")
        return

    song_id = storage.add_song(
        title=parsed["title"],
        artist=parsed["artist"],
        chords=parsed["chords"],
        added_by=message.from_user.id,
    )
    await message.answer(
        f"✅ Сохранено: {parsed['artist']} — {parsed['title']} (id={song_id})"
    )


# ---------- обработка кнопок ----------

@dp.callback_query(F.data.startswith("song:"))
async def on_song_choice(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id
    state = USER_STATE.get(user_id)
    if not state or "search_results" not in state:
        await callback.answer("Список устарел, начни заново через /song")
        return

    try:
        index = int(callback.data.split(":", 1)[1])
        chosen = state["search_results"][index]
    except (ValueError, IndexError):
        await callback.answer("Ошибка выбора, начни заново")
        return

    await callback.answer("Загружаю аккорды...")
    # Смотрим, из какого источника песня
    state = USER_STATE.get(user_id, {})
    source = state.get("source", "5lad")

    if source == "custom":
        # У custom уже есть текст в chosen
        song = {
            "title": chosen.get("title", "Неизвестно"),
            "artist": chosen.get("artist", "Неизвестно"),
            "chords": chosen.get("chords", ""),
        }
    elif source == "mytabs":
        song = get_mytabs(chosen["url"])
    else:
        song = get_5lad(chosen["url"])
    if not song:
        await callback.message.answer("Не удалось загрузить песню 😔")
        return

    USER_STATE[user_id] = {
        "original": song["chords"],
        "title": song["title"],
        "artist": song["artist"],
        "semitones": 0,
        "mode": "normal",
    }

    try:
        await callback.message.delete()
    except Exception:
        pass

    header = f"🎵 {song['artist']} — {song['title']}\n\n"
    body = song["chords"]
    full = header + body
    if len(full) > 4000:
        full = full[:4000] + "\n\n… (обрезано)"

    await callback.message.answer(full, reply_markup=build_keyboard(user_id))


@dp.callback_query(F.data.startswith("custom:"))
async def on_custom_choice(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id
    try:
        song_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Ошибка")
        return

    song = storage.get_song_by_id(song_id)
    if not song:
        await callback.answer("Песня не найдена в базе")
        return

    USER_STATE[user_id] = {
        "original": song["chords"],
        "title": song["title"],
        "artist": song["artist"],
        "semitones": 0,
        "mode": "normal",
    }

    try:
        await callback.message.delete()
    except Exception:
        pass

    header = f"⭐ {song['artist']} — {song['title']}\n\n"
    body = song["chords"]
    full = header + body
    if len(full) > 4000:
        full = full[:4000] + "\n\n… (обрезано)"

    await callback.message.answer(full, reply_markup=build_keyboard(user_id))


@dp.callback_query(F.data == "noop")
async def on_noop(callback: types.CallbackQuery) -> None:
    await callback.answer()


@dp.callback_query(F.data.startswith("trans:"))
async def on_transpose(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id
    state = USER_STATE.get(user_id)
    if not state or "original" not in state:
        await callback.answer("Сначала выбери песню через /song")
        return

    try:
        delta = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Ошибка")
        return

    new_shift = state["semitones"] + delta
    if not -11 <= new_shift <= 11:
        await callback.answer("Дальше некуда 🙂")
        return

    state["semitones"] = new_shift
    await callback.answer(f"Тональность: {new_shift:+d}")
    await edit_song_message(callback, user_id)


@dp.callback_query(F.data.startswith("mode:"))
async def on_mode(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id
    state = USER_STATE.get(user_id)
    if not state or "original" not in state:
        await callback.answer("Сначала выбери песню через /song")
        return

    new_mode = callback.data.split(":", 1)[1]
    if new_mode not in ("normal", "power"):
        await callback.answer("Ошибка")
        return

    state["mode"] = new_mode
    label = "⚡ Квинты" if new_mode == "power" else "🎸 Обычные"
    await callback.answer(label)
    await edit_song_message(callback, user_id)


@dp.callback_query(F.data == "reset")
async def on_reset(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id
    state = USER_STATE.get(user_id)
    if not state or "original" not in state:
        await callback.answer("Сначала выбери песню через /song")
        return

    state["semitones"] = 0
    state["mode"] = "normal"
    await callback.answer("Сброшено")
    await edit_song_message(callback, user_id)


# ---------- запуск ----------

async def main() -> None:
    storage.init_db()
    print("Бот запущен. Нажми Ctrl+C для остановки.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())