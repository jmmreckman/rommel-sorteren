import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rommel.db"

USERS = ("ayla", "jurian")

# Vaste volgorde van kleuren die automatisch aan nieuwe categorieen wordt
# toegekend, zodat je er als gebruiker aan went welke kleur bij welke
# categorie hoort.
CATEGORY_PALETTE = [
    "#4d7ea8", "#4d8a6a", "#c98a3c", "#a8524d",
    "#6a5acd", "#178a8a", "#8a6d4d", "#4d4d8a",
    "#a84d8a", "#4da89e",
]

DEFAULT_CATEGORIES = [
    # (naam, vraagt om een naam erbij, vraagt om een toelichting, overrulet de partner, volgorde)
    ("Kringloop / rommelmarkt", 0, 0, 0, 1),
    ("Zelf bewaren", 0, 0, 0, 2),
    ("Naar vrienden/familie", 1, 0, 0, 3),
    ("Grofvuil / milieuplein", 0, 0, 0, 4),
    ("Overig", 0, 1, 1, 5),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    requires_name INTEGER NOT NULL DEFAULT 0,
    requires_note INTEGER NOT NULL DEFAULT 0,
    overrules INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    color TEXT NOT NULL DEFAULT '#888888',
    garage_sale INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drive_file_id TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    thumb_small TEXT NOT NULL,
    thumb_medium TEXT NOT NULL,
    drive_link TEXT,
    tags TEXT NOT NULL DEFAULT '',
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

-- Wie interesse heeft getoond in een garage-sale-product (publieke pagina,
-- geen account nodig - dus gewoon een vrij ingevulde naam).
CREATE TABLE IF NOT EXISTS garage_sale_interest (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(photos)")}
        if "tags" not in cols:
            conn.execute("ALTER TABLE photos ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
        cat_cols = {row["name"] for row in conn.execute("PRAGMA table_info(categories)")}
        if "garage_sale" not in cat_cols:
            conn.execute("ALTER TABLE categories ADD COLUMN garage_sale INTEGER NOT NULL DEFAULT 0")
        if "requires_note" not in cat_cols:
            conn.execute("ALTER TABLE categories ADD COLUMN requires_note INTEGER NOT NULL DEFAULT 0")
        if "overrules" not in cat_cols:
            conn.execute("ALTER TABLE categories ADD COLUMN overrules INTEGER NOT NULL DEFAULT 0")
        conn.execute("DROP TABLE IF EXISTS deleted_drive_files")
        existing = conn.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"]
        if existing == 0:
            seeded = [
                (name, requires_name, requires_note, overrules, order,
                 CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)])
                for i, (name, requires_name, requires_note, overrules, order) in enumerate(DEFAULT_CATEGORIES)
            ]
            conn.executemany(
                """INSERT INTO categories (name, requires_name, requires_note, overrules, sort_order, color)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                seeded,
            )
        else:
            # bestaande installatie: voeg de nieuwe "Overig" categorie toe als hij er nog niet is
            overig = conn.execute("SELECT id FROM categories WHERE LOWER(name)=LOWER(?)", ("Overig",)).fetchone()
            if not overig:
                next_order = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 n FROM categories").fetchone()["n"]
                count = conn.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"]
                color = CATEGORY_PALETTE[count % len(CATEGORY_PALETTE)]
                conn.execute(
                    """INSERT INTO categories (name, requires_name, requires_note, overrules, sort_order, color)
                       VALUES ('Overig', 0, 1, 1, ?, ?)""",
                    (next_order, color),
                )


def other_user(user: str) -> str:
    return "jurian" if user == "ayla" else "ayla"


def choices_match(a, b) -> bool:
    if a["category_id"] != b["category_id"]:
        return False
    na = (a["person_name"] or "").strip().lower()
    nb = (b["person_name"] or "").strip().lower()
    return na == nb
