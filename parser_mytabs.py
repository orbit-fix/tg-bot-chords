"""Парсер mytabs.ru — поиск через угадывание слага исполнителя.

У mytabs.ru нет общего указателя исполнителей (только встроенный Яндекс-поиск,
который парсить нельзя). Поэтому пробуем несколько вариантов URL.
"""
import re

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://mytabs.ru"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}

_session = requests.Session()
_session.trust_env = False
_session.headers.update(HEADERS)


def _get(url: str) -> requests.Response | None:
    """GET. Возвращает None, если 404 или другая ошибка."""
    try:
        r = _session.get(url, timeout=15)
        if r.status_code != 200:
            return None
        r.encoding = "utf-8"
        return r
    except requests.RequestException as e:
        print(f"[mytabs] Ошибка {url}: {e}")
        return None


# ---------- транслитерация ----------

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _slugify(text: str) -> str:
    text = text.lower().strip()
    out = []
    for ch in text:
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    slug = "".join(out)
    return re.sub(r"-+", "-", slug).strip("-")


def _slug_variants(slug: str) -> list[str]:
    """Возвращает варианты слага с заменами c/z/s/k.

    Например, 'ksb-music' → ['ksb-music', 'ksb-muzic', 'ksb-musik', ...]
    """
    variants = {slug}
    # c ↔ z
    if "c" in slug:
        variants.add(slug.replace("c", "z"))
    if "z" in slug:
        variants.add(slug.replace("z", "c"))
    # c ↔ k
    if "c" in slug:
        variants.add(slug.replace("c", "k"))
    if "k" in slug:
        variants.add(slug.replace("k", "c"))
    # s ↔ z
    if "s" in slug:
        variants.add(slug.replace("s", "z"))
    # комбинации для коротких слагов
    if len(slug) <= 15:
        for v in list(variants):
            if "c" in v:
                variants.add(v.replace("c", "z"))
            if "z" in v:
                variants.add(v.replace("z", "c"))
    return sorted(variants, key=len)


def _artist_url_variants(artist_name: str) -> list[str]:
    """Возвращает список возможных URL-вариантов страницы исполнителя."""
    slug = _slugify(artist_name)
    if not slug:
        return []

    first = slug[0]
    urls = []
    for variant_slug in _slug_variants(slug):
        urls.append(f"/akkordy/{first}/{variant_slug}")
        urls.append(f"/akkordy/{first}-r/{variant_slug}")

    # Хардкод-алиасы для известных исключений
    KNOWN_ALIASES = {
        "кино": ["v-r/viktor-tsoj"],
        "виктор цой": ["v-r/viktor-tsoj"],
        "ксб мьюзик": ["k/ksb-muzic"],
        "ksb music": ["k/ksb-muzic"],
        "ксб": ["k/ksb-muzic"],
    }
    for alias in KNOWN_ALIASES.get(artist_name.lower().strip(), []):
        urls.append(f"/akkordy/{alias}")

    # Убираем дубликаты, сохраняя порядок
    seen = set()
    unique = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


# ---------- загрузка ----------

def get_artist_songs(artist_url_path: str) -> list[dict]:
    """Загружает страницу исполнителя и парсит список песен.

    :param artist_url_path: например, '/akkordy/c/cupsize'
    """
    url = f"{BASE_URL}{artist_url_path}"
    response = _get(url)
    if not response:
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    songs = []
    seen = set()

    # Ищем ссылки на песни: абсолютные URL с ".html" в конце
    for a in soup.find_all("a", href=True):
        href = a["href"]

        # Может быть: /akkordy/... ИЛИ https://mytabs.ru/akkordy/...
        if not href.endswith(".html"):
            continue
        if "/akkordy/" not in href:
            continue

        # Приводим к абсолютному URL
        if href.startswith("http"):
            full_url = href
        else:
            full_url = f"{BASE_URL}{href}"

        # Отсеиваем ссылки на другие сайты
        if not full_url.startswith(BASE_URL):
            continue
        # Отсеиваем ссылки на песни других исполнителей
        if not full_url.startswith(f"{BASE_URL}{artist_url_path}/"):
            continue

        if full_url in seen:
            continue
        seen.add(full_url)

        title = a.get_text(strip=True)
        if not title or len(title) < 2:
            continue
        songs.append({
            "title": title,
            "url": full_url,
        })

    return songs


def get_song(url: str) -> dict | None:
    """Загружает страницу песни и извлекает аккорды."""
    response = _get(url)
    if not response:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    h1 = soup.find("h1")
    title = "Неизвестно"
    artist = "Неизвестно"
    if h1:
        raw = h1.get_text(" ", strip=True)
        raw = re.sub(r",?\s*аккорды\s*$", "", raw).strip()
        if " - " in raw:
            artist, title = [p.strip() for p in raw.split(" - ", 1)]
        else:
            title = raw

    # Аккорды в <pre> или в div с классом
    pre = soup.find("pre")
    if not pre:
        # Попробуем найти блок с классом, содержащим "chord" или "text"
        pre = soup.find(class_=lambda c: c and any(
            "chord" in x.lower() or "podbor" in x.lower() or "text" in x.lower()
            for x in c
        ))
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
        "source": "mytabs.ru",
    }

def _normalize(text: str) -> str:
    """Нормализует текст для сравнения: нижний регистр, без пробелов и дефисов."""
    return re.sub(r"[\s\-_]+", "", text.lower())

def find_song(query: str, limit: int = 5) -> list[dict]:
    """Ищет песни по фразе. Перебирает разные разбиения на 'исполнитель + песня'."""
    query_words = [w.lower() for w in query.split() if len(w) > 1]
    if not query_words:
        return []

    # Собираем все возможные «имена исполнителей»:
    #   из 1, 2, 3, ..., N слов (с начала)
    #   + из 1 слова (последнее слово — часто тоже исполнитель)
    candidate_names: list[tuple[str, list[str]]] = []
    n = len(query_words)
    for take in range(n, 0, -1):
        name = " ".join(query_words[:take])
        candidate_names.append((name, query_words[:take]))

    # Также отдельно каждое слово (на случай, если исполнитель — одно слово)
    for w in query_words:
        candidate_names.append((w, [w]))

    results = []
    seen_urls = set()

    for name, matched_words in candidate_names:
        for variant in _artist_url_variants(name):
            songs = get_artist_songs(variant)
            if not songs:
                continue

            # Оставшиеся слова запроса ищем в названии песни
            remaining = [w for w in query_words if w not in matched_words]

            for song in songs:
                title_norm = _normalize(song["title"])
                if remaining:
                    if not any(_normalize(w) in title_norm for w in remaining):
                        continue
                if song["url"] in seen_urls:
                    continue
                seen_urls.add(song["url"])
                results.append({
                    "title": song["title"],
                    "artist": name.title(),
                    "url": song["url"],
                })
                if len(results) >= limit:
                    return results

    return results


# ---------- отладка ----------

if __name__ == "__main__":
    tests = [
        "баста сансара",
        "кис кис молчи",
        "кино группа крови",
        "cupsize зппп",
        "синдром главного героя оттепель",
    ]
    for q in tests:
        print(f"=== Поиск: '{q}' ===")
        results = find_song(q)
        if not results:
            print("  (не найдено)")
        for r in results:
            print(f"• {r['artist']} — {r['title']}")
            print(f"  {r['url']}")
        print()