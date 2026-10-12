"""Хранилище ручных песен (SQLite)."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "songs.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Создаёт таблицу custom_songs, если её ещё нет."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_songs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                artist     TEXT NOT NULL,
                chords     TEXT NOT NULL,
                added_by   INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def add_song(title: str, artist: str, chords: str, added_by: int) -> int:
    """Добавляет песню в базу. Возвращает id."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO custom_songs (title, artist, chords, added_by) VALUES (?, ?, ?, ?)",
            (title, artist, chords, added_by),
        )
        return cur.lastrowid


def delete_song(song_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM custom_songs WHERE id = ?", (song_id,))
        return cur.rowcount > 0


def find_songs(query: str, limit: int = 5) -> list[dict]:
    """Ищет песни по подстроке в названии или исполнителе."""
    words = [w.lower() for w in query.split() if len(w) > 1]
    if not words:
        return []

    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, artist, chords FROM custom_songs"
        ).fetchall()

    results = []
    for row in rows:
        haystack = f"{row['title']} {row['artist']}".lower()
        if all(w in haystack for w in words):
            results.append({
                "id": row["id"],
                "title": row["title"],
                "artist": row["artist"],
                "chords": row["chords"],
                "source": "custom",
            })
            if len(results) >= limit:
                break
    return results


def get_song_by_id(song_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, title, artist, chords FROM custom_songs WHERE id = ?",
            (song_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "artist": row["artist"],
        "chords": row["chords"],
        "source": "custom",
    }


def list_all(limit: int = 20) -> list[dict]:
    """Список всех песен для команды /list."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, artist FROM custom_songs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"id": r["id"], "title": r["title"], "artist": r["artist"]} for r in rows]


# ---------- отладка ----------

if __name__ == "__main__":
    init_db()
    print("База инициализирована:", DB_PATH)
    add_song("Тест", "Тестовый исполнитель", "Am C G D", 123)
    print("Добавлено. Всего в базе:")
    for s in list_all():
        print(f"  [{s['id']}] {s['artist']} — {s['title']}")
    print("\nПоиск 'тест':", find_songs("тест"))