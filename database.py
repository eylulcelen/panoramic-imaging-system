"""
database.py — SQLite setup and helper functions.

Tables:
  users    (id, username, password_hash, created_at)
  captures (id, user_id, filename, date, size_bytes)
"""

import sqlite3
import hashlib
import os
from datetime import datetime

DB_PATH     = "panoptic.db"
GALLERY_DIR = "captures"


# ─────────────────────────────────────────────
#  Connection
# ─────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ─────────────────────────────────────────────
#  Init
# ─────────────────────────────────────────────

def init_db():
    """Create tables if they don't exist yet."""
    os.makedirs(GALLERY_DIR, exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                username     TEXT    NOT NULL UNIQUE,
                password_hash TEXT   NOT NULL,
                created_at   TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS captures (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id),
                filename   TEXT    NOT NULL,
                date       TEXT    NOT NULL,
                size_bytes INTEGER NOT NULL
            );
        """)
    print("[db] Database ready →", DB_PATH)


# ─────────────────────────────────────────────
#  Password hashing
# ─────────────────────────────────────────────

def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ─────────────────────────────────────────────
#  User helpers
# ─────────────────────────────────────────────

def create_user(username: str, password: str) -> tuple[bool, str]:
    """Create a new user. Returns (success, message)."""
    if not username or not password:
        return False, "Username and password cannot be empty."
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username.strip(), _hash(password), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
        return True, f"User '{username}' created."
    except sqlite3.IntegrityError:
        return False, f"Username '{username}' is already taken."


def verify_user(username: str, password: str):
    """Return user row if credentials match, else None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND password_hash = ?",
            (username.strip(), _hash(password))
        ).fetchone()
    return row


def get_all_users():
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, username, created_at FROM users ORDER BY created_at DESC"
        ).fetchall()


def delete_user(user_id: int) -> tuple[bool, str]:
    with get_conn() as conn:
        # delete captures from disk first
        rows = conn.execute(
            "SELECT filename FROM captures WHERE user_id = ?", (user_id,)
        ).fetchall()
        for r in rows:
            path = os.path.join(GALLERY_DIR, r["filename"])
            if os.path.exists(path):
                os.remove(path)
        conn.execute("DELETE FROM captures WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users    WHERE id      = ?", (user_id,))
    return True, "User deleted."


# ─────────────────────────────────────────────
#  Capture helpers
# ─────────────────────────────────────────────

def save_capture(user_id: int, filename: str, size_bytes: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO captures (user_id, filename, date, size_bytes) VALUES (?, ?, ?, ?)",
            (user_id, filename,
             datetime.now().strftime("%d %b %Y %H:%M"), size_bytes)
        )


def get_user_captures(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM captures WHERE user_id = ? ORDER BY id DESC",
            (user_id,)
        ).fetchall()


def delete_capture(capture_id: int, user_id: int) -> tuple[bool, str]:
    """Delete a capture — enforces ownership so users can't delete others' files."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT filename FROM captures WHERE id = ? AND user_id = ?",
            (capture_id, user_id)
        ).fetchone()
        if not row:
            return False, "Capture not found."
        path = os.path.join(GALLERY_DIR, row["filename"])
        if os.path.exists(path):
            os.remove(path)
        conn.execute("DELETE FROM captures WHERE id = ?", (capture_id,))
    return True, "Capture deleted."