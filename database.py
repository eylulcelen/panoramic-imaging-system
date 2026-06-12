"""
database.py — SQLite setup and helper functions.

Tables:
  users    (id, username, password_hash, created_at)
  captures (id, user_id, filename, date, size_bytes)
  log_analytics (user_id, path, method, ip, status_code, duration_ms)
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
                           
            CREATE TABLE IF NOT EXISTS log_analytics (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                path        TEXT,
                method      TEXT,
                timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
                ip          TEXT,
                status_code INTEGER,
                duration_ms INTEGER
            );
        """)
        try:
            conn.execute("ALTER TABLE log_analytics ADD COLUMN details TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE log_analytics ADD COLUMN error_msg TEXT")
        except sqlite3.OperationalError:
            pass
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
        conn.execute("DELETE FROM captures     WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM log_analytics WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users        WHERE id      = ?", (user_id,))
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

# ─────────────────────────────────────────────
#  Analytics helpers
# ─────────────────────────────────────────────

def log_analytics(user_id, path, method, ip, status_code, duration_ms, details=None, error_msg=None):
    try:
        if user_id is None:
            return

        with get_conn() as conn:
            conn.execute("""
                INSERT INTO log_analytics
                (user_id, path, method, ip, status_code, duration_ms, details, error_msg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, path, method, ip, status_code, duration_ms, details, error_msg))

    except Exception as e:
        print("LOG ERROR:", e)
        
def get_analytics():
    with get_conn() as conn:
        return conn.execute("""
            SELECT
                 l.timestamp,
                 l.user_id,
                 u.username,
                 l.path,
                 l.method,
                 l.status_code, 
                 l.duration_ms,
                 l.details,
                 l.error_msg,
                CASE
                    WHEN path = '/' THEN 'Dashboard Open'
                    WHEN path = '/login' THEN 'Login Attempt'
                    WHEN path = '/api/capture' THEN 'Capture Panorama'
                    WHEN path = '/api/gallery' THEN 'Gallery Open'
                    WHEN path = '/api/status' THEN 'Camera Status Check'
                    WHEN path = '/logout' THEN 'Logout'
                    ELSE path
                END as action
            FROM log_analytics l
            LEFT JOIN users u ON l.user_id = u.id
            ORDER BY l.timestamp DESC
        """).fetchall()

def get_chart_data():
    with get_conn() as conn:
        captures_by_day = conn.execute("""
            SELECT date(timestamp) as d, COUNT(*) as c 
            FROM log_analytics 
            WHERE path = '/api/capture' AND error_msg IS NULL 
            GROUP BY d 
            ORDER BY d ASC 
            LIMIT 7
        """).fetchall()

        top_actions = conn.execute("""
            SELECT 
                CASE
                    WHEN path = '/' THEN 'Dashboard'
                    WHEN path = '/login' THEN 'Login'
                    WHEN path = '/api/capture' THEN 'Capture'
                    WHEN path = '/api/gallery' THEN 'Gallery'
                    WHEN path = '/api/status' THEN 'Camera Check'
                    WHEN path = '/logout' THEN 'Logout'
                    ELSE path
                END as action,
                COUNT(*) as c 
            FROM log_analytics 
            GROUP BY action 
            ORDER BY c DESC 
            LIMIT 5
        """).fetchall()

        return {
            "dates": [row["d"] for row in captures_by_day],
            "capture_counts": [row["c"] for row in captures_by_day],
            "action_labels": [row["action"] for row in top_actions],
            "action_counts": [row["c"] for row in top_actions]
        }