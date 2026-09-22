import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rommel.db"

USERS = ("ayla", "jurian")

DEFAULT_CATEGORIES = [
    # (naam, vraagt om een naam erbij, volgorde)
    ("Kringloop / rommelmarkt", 0, 1),
    ("Zelf bewaren", 0, 2),
    ("Naar vrienden/familie", 1, 3),
    ("Grofvuil / milieuplein", 0, 4),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    requires_name INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drive_file_id TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    thumb_small TEXT NOT NULL,
    thumb_medium TEXT NOT NULL,
    drive_link TEXT,
    added_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS choices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    user TEXT NOT NULL CHECK(user IN ('ayla','jurian')),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    person_name TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(photo_id, user)
);
"""


@contextmanager
def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)
        existing = conn.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"]
        if existing == 0:
            conn.executemany(
                "INSERT INTO categories (name, requires_name, sort_order) VALUES (?, ?, ?)",
                DEFAULT_CATEGORIES,
            )


def other_user(user: str) -> str:
    return "jurian" if user == "ayla" else "ayla"


def choices_match(a, b) -> bool:
    if a["category_id"] != b["category_id"]:
        return False
    na = (a["person_name"] or "").strip().lower()
    nb = (b["person_name"] or "").strip().lower()
    return na == nb
