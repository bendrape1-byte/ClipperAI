import sqlite3
from contextlib import contextmanager

DB_PATH = "clip_engine.db"


@contextmanager
def get_connection():
    """Open a connection, commit on success, always close."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clip_profiles (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT    NOT NULL,
                host_name         TEXT    NOT NULL,
                host_description  TEXT,
                guest_name        TEXT,
                guest_description TEXT,
                topic             TEXT,
                tone              TEXT,
                audience          TEXT,
                priorities        TEXT,
                avoid             TEXT,
                additional_notes  TEXT,
                created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS media_assets (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                filename          TEXT    NOT NULL,
                original_file_path TEXT   NOT NULL,
                audio_file_path   TEXT,
                duration_seconds  REAL,
                status            TEXT    NOT NULL DEFAULT 'uploaded',
                profile_id        INTEGER REFERENCES clip_profiles(id),
                source_type       TEXT    NOT NULL DEFAULT 'upload',
                source_url        TEXT,
                title             TEXT,
                thumbnail_url     TEXT,
                channel_name      TEXT,
                created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transcripts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id  INTEGER NOT NULL REFERENCES media_assets(id),
                language        TEXT,
                transcript_json TEXT,
                words_json      TEXT,
                full_text       TEXT,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clip_candidates (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                media_asset_id    INTEGER NOT NULL REFERENCES media_assets(id),
                start_sec         REAL    NOT NULL,
                end_sec           REAL    NOT NULL,
                title             TEXT,
                hook              TEXT,
                reasoning         TEXT,
                score             INTEGER,
                transcript_excerpt TEXT,
                preview_path      TEXT,
                status            TEXT    NOT NULL DEFAULT 'pending',
                created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # Add columns to existing tables if they were created before these fields existed
        for col, definition in [
            ("preview_path", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'pending'"),
            ("srt_path", "TEXT"),
            ("vertical_path", "TEXT"),
            ("vertical_status", "TEXT"),
            ("captioned_path", "TEXT"),
            ("vertical_captioned_path", "TEXT"),
            ("broll_path", "TEXT"),
            ("vertical_broll_path", "TEXT"),
            ("produced_path", "TEXT"),
            ("vertical_produced_path", "TEXT"),
            ("production_status", "TEXT"),
            ("production_step", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE clip_candidates ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass
        for col, definition in [
            ("profile_id", "INTEGER REFERENCES clip_profiles(id)"),
            ("source_type", "TEXT NOT NULL DEFAULT 'upload'"),
            ("source_url", "TEXT"),
            ("title", "TEXT"),
            ("thumbnail_url", "TEXT"),
            ("channel_name", "TEXT"),
            ("clips_rendered", "INTEGER NOT NULL DEFAULT 0"),
            ("clips_total",    "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE media_assets ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("ALTER TABLE transcripts ADD COLUMN words_json TEXT")
        except sqlite3.OperationalError:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS broll_suggestions (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                clip_id              INTEGER NOT NULL REFERENCES clip_candidates(id),
                start_sec            REAL    NOT NULL,
                end_sec              REAL    NOT NULL,
                search_query         TEXT    NOT NULL,
                reason               TEXT,
                pexels_video_id      INTEGER,
                pexels_url           TEXT,
                pexels_thumbnail_url TEXT,
                photographer_name    TEXT,
                broll_file_path      TEXT,
                status               TEXT    NOT NULL DEFAULT 'suggested',
                created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        try:
            conn.execute("ALTER TABLE broll_suggestions ADD COLUMN transition_sfx INTEGER NOT NULL DEFAULT 1")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE broll_suggestions ADD COLUMN search_queries TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE broll_suggestions ADD COLUMN start_word TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE broll_suggestions ADD COLUMN end_word TEXT")
        except sqlite3.OperationalError:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sfx_library (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT    NOT NULL,
                filename         TEXT    NOT NULL,
                file_path        TEXT    NOT NULL,
                duration_seconds REAL    NOT NULL,
                category         TEXT    NOT NULL DEFAULT 'transition',
                is_default       INTEGER NOT NULL DEFAULT 0,
                created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        for col, definition in [
            ("transition_sfx_id", "INTEGER REFERENCES sfx_library(id)"),
            ("transition_style",  "TEXT NOT NULL DEFAULT 'crossfade'"),
        ]:
            try:
                conn.execute(f"ALTER TABLE clip_profiles ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass


def create_media_asset(filename: str, original_file_path: str,
                       status: str = 'uploaded', source_type: str = 'upload',
                       source_url: str = None) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO media_assets (filename, original_file_path, status, source_type, source_url) VALUES (?, ?, ?, ?, ?)",
            (filename, original_file_path, status, source_type, source_url),
        )
        return cursor.lastrowid


def get_media_asset(media_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM media_assets WHERE id = ?", (media_id,)
        ).fetchone()
        return dict(row) if row else None


def create_transcript(media_asset_id: int, language: str, transcript_json: str,
                      full_text: str, words_json: str = "[]"):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO transcripts (media_asset_id, language, transcript_json, words_json, full_text) VALUES (?, ?, ?, ?, ?)",
            (media_asset_id, language, transcript_json, words_json, full_text),
        )


def get_transcript_by_media_id(media_asset_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM transcripts WHERE media_asset_id = ?", (media_asset_id,)
        ).fetchone()
        return dict(row) if row else None


def create_clip_candidate(media_asset_id: int, start_sec: float, end_sec: float,
                          title: str, hook: str, reasoning: str, score: int,
                          transcript_excerpt: str):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO clip_candidates
               (media_asset_id, start_sec, end_sec, title, hook, reasoning, score, transcript_excerpt)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (media_asset_id, start_sec, end_sec, title, hook, reasoning, score, transcript_excerpt),
        )


def get_clip_candidate(clip_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM clip_candidates WHERE id = ?", (clip_id,)
        ).fetchone()
        return dict(row) if row else None


def update_clip_candidate(clip_id: int, **fields):
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [clip_id]
    with get_connection() as conn:
        conn.execute(
            f"UPDATE clip_candidates SET {set_clause} WHERE id = ?", values
        )


def get_clips_by_media_id(media_asset_id: int):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM clip_candidates WHERE media_asset_id = ? ORDER BY score DESC",
            (media_asset_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_clips_by_media_id(media_asset_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM clip_candidates WHERE media_asset_id = ?", (media_asset_id,))


def update_media_asset(media_id: int, **fields):
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [media_id]
    with get_connection() as conn:
        conn.execute(
            f"UPDATE media_assets SET {set_clause} WHERE id = ?", values
        )


def increment_clips_rendered(media_id: int):
    """Atomically increment clips_rendered by 1."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE media_assets SET clips_rendered = clips_rendered + 1 WHERE id = ?",
            (media_id,),
        )
