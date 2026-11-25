import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TZ = ZoneInfo("Europe/Istanbul")
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "kitap.db"


def today_string():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def get_db(db_path=None):
    path = DB_PATH if db_path is None else Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    conn = get_db(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT,
            publisher TEXT,
            cover_filename TEXT,
            page_count INTEGER,
            isbn TEXT,
            publication_year TEXT,
            product_url TEXT,
            status TEXT CHECK(status IN ('okunacak','okunuyor','okundu')) DEFAULT 'okunacak',
            current_page INTEGER NOT NULL DEFAULT 0,
            rating INTEGER NOT NULL DEFAULT 0,
            note TEXT,
            finish_date TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reading_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            page INTEGER NOT NULL,
            logged_at TEXT NOT NULL,
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        INSERT OR IGNORE INTO settings(key, value) VALUES ('annual_target', '24');
        """
    )
    conn.commit()
    conn.close()


def get_setting(key, default=None, db_path=None):
    conn = get_db(db_path)
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value, db_path=None):
    conn = get_db(db_path)
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()
