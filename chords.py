"""Работа с аккордами: транспонирование и конвертация обычных/квинт."""
import re

# 12 нот в хроматической гамме. Используем диезы как основные.
NOTES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Альтернативные названия — бемоли. Используются, чтобы распознать
# аккорды, записанные как Bb, Eb и т.д.
NOTE_ALIASES = {
    "Cb": "B", "Db": "C#", "Eb": "D#", "Fb": "E",
    "Gb": "F#", "Ab": "G#", "Bb": "A#",
    "H": "B",  # в некоторых табах H = си
}

# Регулярка для аккорда: нота (A-G) + опционально #/b + опционально тип (m, 7, sus4 и т.д.)
CHORD_RE = re.compile(
    r"\b([A-H][#b]?)"       # тоника: A-G, возможно с # или b
    r"(m|maj|min|dim|aug|sus|add|no)?(\d*)?"  # тип: m, maj7, sus4 и т.п.
    r"(\d*)"                # цифры для аккордов типа 7, 9, 11
    r"\b"
)


def _normalize_note(note: str) -> str:
    """Приводит бемоль к диезу: Bb → A#, Eb → D#."""
    if note in NOTE_ALIASES:
        return NOTE_ALIASES[note]
    return note


def _note_index(note: str) -> int:
    """Возвращает индекс ноты в хроматической гамме (0–11)."""
    note = _normalize_note(note)
    return NOTES_SHARP.index(note)


def _transpose_single(chord: str, semitones: int) -> str:
    """Сдвигает один аккорд на N полутонов.

    'Am' + 2 → 'Bm'
    'G'  + 1 → 'G#'
    'D5' - 2 → 'C5'
    """
    m = re.match(r"^([A-H][#b]?)(.*)$", chord)
    if not m:
        return chord

    root, rest = m.group(1), m.group(2)
    if not root or root[0] not in "ABCDEFGH":
        return chord

    try:
        idx = _note_index(root)
    except ValueError:
        return chord

    new_idx = (idx + semitones) % 12
    return NOTES_SHARP[new_idx] + rest


def transpose(text: str, semitones: int) -> str:
    """Транспонирует все аккорды в тексте песни на N полутонов.

    :param text: полный текст с аккордами (как в AmDm)
    :param semitones: сколько полутонов сдвинуть (может быть отрицательным)
    """
    if semitones == 0:
        return text

    def replace(match: re.Match) -> str:
        chord = match.group(0)
        return _transpose_single(chord, semitones)

    return CHORD_RE.sub(replace, text)
# ---------- конвертация обычных ↔ квинт ----------

def _to_power_single(chord: str) -> str:
    """Обычный аккорд → квинт.

    'Am' → 'A5', 'C' → 'C5', 'F#m7' → 'F#5', 'Bb' → 'A#5'
    """
    m = re.match(r"^([A-H][#b]?)", chord)
    if not m:
        return chord
    root = m.group(1)
    if not root or root[0] not in "ABCDEFGH":
        return chord
    root = _normalize_note(root)
    return root + "5"


def to_power(text: str) -> str:
    """Все обычные аккорды в тексте → квинты."""
    return CHORD_RE.sub(lambda m: _to_power_single(m.group(0)), text)


def _from_power_single(chord: str) -> str:
    """Квинт → обычный (мажор по умолчанию).

    'A5' → 'A', 'C5' → 'C', 'N.C.' → 'N.C.' (не трогаем)
    """
    m = re.match(r"^([A-H][#b]?)5$", chord)
    if not m:
        return chord
    root = m.group(1)
    if not root or root[0] not in "ABCDEFGH":
        return chord
    return _normalize_note(root)


def from_power(text: str) -> str:
    """Все квинты в тексте → обычные аккорды (мажор)."""
    return re.sub(
        r"\b([A-H][#b]?)5\b",
        lambda m: _from_power_single(m.group(0)),
        text,
    )