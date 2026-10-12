"""Парсер сайта top.5lad.net — поиск песен и загрузка аккордов."""
import re
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://top.5lad.net"
INDEX_URL = f"{BASE_URL}/akkordy/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}

# Игнорируем системный SOCKS-прокси (v2rayN)
_session = requests.Session()
_session.trust_env = False
_session.headers.update(HEADERS)


def _get(url: str) -> requests.Response:
    """GET без использования системного прокси."""
    response = _session.get(url, timeout=20)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response


# ---------- кэш исполнителей ----------

_artists_cache: dict = {
    "data": None,
    "ts": 0,
}

CACHE_TTL = 24 * 60 * 60  # 24 часа


def _load_artists() -> dict[str, str]:
    """Загружает указатель исполнителей. Кэшируется на 24 часа.

    :return: {название_в_нижнем_регистре: slug}
    """
    now = time.time()
    if _artists_cache["data"] and (now - _artists_cache["ts"]) < CACHE_TTL:
        return _artists_cache["data"]

    try:
        response = _get(INDEX_URL)
    except requests.RequestException as e:
        print(f"[5lad.index] Ошибка: {e}")
        return {}

    soup = BeautifulSoup(response.text, "html.parser")
    artists: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        parts = href.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "akkordy":
            name = a.get_text(strip=True).lower()
            slug = parts[1]
            if name:
                artists[name] = slug

    _artists_cache["data"] = artists
    _artists_cache["ts"] = now
    print(f"[5lad.index] Загружено {len(artists)} исполнителей")
    return artists


# ---------- поиск и загрузка ----------

def get_artist_songs(artist_slug: str) -> list[dict]:
    """Возвращает список песен исполнителя."""
    url = f"{BASE_URL}/akkordy/{artist_slug}/"
    try:
        response = _get(url)
    except requests.RequestException as e:
        print(f"[5lad.artist] Ошибка {url}: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    songs = []
    seen = set()

    pattern = re.compile(rf"^/akkordy/{re.escape(artist_slug)}/[^/]+/?$")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not pattern.match(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        title = a.get_text(strip=True)
        if not title or len(title) < 2:
            continue
        songs.append({
            "title": title,
            "url": f"{BASE_URL}{href}",
        })

    return songs


def get_song(url: str) -> dict | None:
    """Загружает страницу песни и извлекает аккорды."""
    try:
        response = _get(url)
    except requests.RequestException as e:
        print(f"[5lad.get_song] Ошибка {url}: {e}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    h1 = soup.find("h1")
    title = "Неизвестно"
    artist = "Неизвестно"
    if h1:
        raw = h1.get_text(" ", strip=True)
        raw = re.sub(r":\s*аккорды.*$", "", raw).strip()
        if " - " in raw:
            artist, title = [p.strip() for p in raw.split(" - ", 1)]
        else:
            title = raw

    pre = soup.find("pre")
    if not pre:
        return None
    chords = pre.get_text()

    return {
        "title": title,
        "artist": artist,
        "chords": chords,
        "comment": "",
        "tone": 0,
        "url": url,
        "source": "5lad.net",
    }


def find_song(query: str, limit: int = 5) -> list[dict]:
    """Ищет песни по фразе через указатель исполнителей.

    Логика:
    1. Загружаем указатель (кэшируется).
    2. Ищем исполнителя: сначала по полной фразе, потом по отдельным словам.
    3. Оставшиеся слова запроса считаем «словами из названия песни».
    4. Ищем песни, где название содержит хотя бы одно из этих слов.
    """
    query_words = [w.lower() for w in query.split() if len(w) > 1]
    if not query_words:
        return []

    artists = _load_artists()
    if not artists:
        return []

    # --- Шаг 1: ищем исполнителя ---
    # Пробуем разные комбинации слов запроса как имя исполнителя
    candidate_artists = []  # (slug, сколько_слов_запроса_совпало)
    seen_slugs = set()

    def _check_artist(name_to_try: str, matched_words: list[str]):
        """Если исполнитель с таким именем есть — добавляем в кандидаты."""
        name_to_try = name_to_try.lower().strip()
        if name_to_try not in artists:
            return
        slug = artists[name_to_try]
        if slug in seen_slugs:
            return
        seen_slugs.add(slug)
        candidate_artists.append((slug, matched_words))

    # 2 слова: "кис кис", "баста сансара"
    if len(query_words) >= 2:
        _check_artist(" ".join(query_words[:2]), query_words[:2])
    # 1 слово: "кис", "баста"
    _check_artist(query_words[0], [query_words[0]])
    # 1 слово (последнее): "молчи", "сансара"
    if len(query_words) > 1:
        _check_artist(query_words[-1], [query_words[-1]])

    # Дополнительно: если слово встречается в имени исполнителя как подстрока
    for w in query_words:
        for name, slug in artists.items():
            if w in name and slug not in seen_slugs:
                seen_slugs.add(slug)
                candidate_artists.append((slug, [w]))

    if not candidate_artists:
        return []

    # --- Шаг 2: загружаем песни кандидатов и фильтруем ---
    results = []
    for slug, matched_words in candidate_artists[:3]:
        songs = get_artist_songs(slug)

        # Оставшиеся слова запроса (не относящиеся к исполнителю) — ищем в названии
        remaining_words = [w for w in query_words if w not in matched_words]

        for song in songs:
            title_lower = song["title"].lower()

            if remaining_words:
                # В названии должно быть хотя бы одно из «оставшихся» слов
                if not any(w in title_lower for w in remaining_words):
                    continue
            else:
                # Если всё ушло в исполнителя — берём все песни
                pass

            if song["url"] in {r["url"] for r in results}:
                continue
            results.append({
                "title": song["title"],
                "artist": slug.replace("-", " ").title(),
                "url": song["url"],
            })
            if len(results) >= limit:
                return results

    return results


# ---------- отладка ----------

if __name__ == "__main__":
    print("=== Поиск 'баста сансара' ===")
    for r in find_song("баста сансара"):
        print(f"• {r['artist']} — {r['title']}")
        print(f"  {r['url']}")

    print("\n=== Поиск 'кис кис молчи' ===")
    for r in find_song("кис кис молчи"):
        print(f"• {r['artist']} — {r['title']}")
        print(f"  {r['url']}")

    print("\n=== Поиск 'кино группа крови' ===")
    for r in find_song("кино группа крови"):
        print(f"• {r['artist']} — {r['title']}")
        print(f"  {r['url']}")

    print("\n=== Загрузка первой найденной ===")
    results = find_song("баста сансара")
    if results:
        song = get_song(results[0]["url"])
        if song:
            print(f"Исполнитель: {song['artist']}")
            print(f"Название: {song['title']}")
            print(f"Первые 200 символов аккордов:")
            print(song["chords"][:200])