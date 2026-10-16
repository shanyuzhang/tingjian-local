import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return uuid.uuid4().hex


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.audio_dir = root / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.path = root / "library.sqlite3"
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, folder TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL, target_language TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '', glossary TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS audio (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id)
                    ON DELETE CASCADE, filename TEXT NOT NULL, offset REAL NOT NULL,
                    duration REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS segments (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id)
                    ON DELETE CASCADE, audio_id TEXT NOT NULL REFERENCES audio(id)
                    ON DELETE CASCADE, start REAL NOT NULL, end REAL NOT NULL,
                    text TEXT NOT NULL, translation TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id)
                    ON DELETE CASCADE, kind TEXT NOT NULL, payload TEXT NOT NULL,
                    client_key TEXT, status TEXT NOT NULL, progress TEXT NOT NULL DEFAULT '',
                    error TEXT, result TEXT, created_at TEXT NOT NULL,
                    UNIQUE(session_id, client_key)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id)
                    ON DELETE CASCADE, question TEXT NOT NULL, answer TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(segments)")}
            if "is_final" not in columns:
                db.execute("ALTER TABLE segments ADD COLUMN is_final INTEGER NOT NULL DEFAULT 1")
            if "speaker" not in columns:
                db.execute("ALTER TABLE segments ADD COLUMN speaker TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def query(self, sql, args=()):
        with self.connection() as db:
            return [dict(row) for row in db.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        with self.connection() as db:
            db.execute(sql, args)

    def session(self, session_id):
        rows = self.query("SELECT * FROM sessions WHERE id=?", (session_id,))
        return rows[0] if rows else None

    def sessions(self):
        return self.query("""
            SELECT s.*, (SELECT COUNT(*) FROM segments WHERE session_id=s.id) AS segment_count,
            (SELECT MAX(end) FROM segments WHERE session_id=s.id) AS duration
            FROM sessions s ORDER BY updated_at DESC
        """)

    def create_session(self, title, folder, language, target_language, glossary):
        sid = new_id()
        self.execute(
            "INSERT INTO sessions(id,title,folder,language,target_language,glossary,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (sid, title, folder, language, target_language, glossary, now(), now()),
        )
        return self.session(sid)

    def segments(self, sid):
        return self.query("SELECT * FROM segments WHERE session_id=? ORDER BY start,id", (sid,))

    def job(self, jid):
        rows = self.query("SELECT * FROM jobs WHERE id=?", (jid,))
        if not rows:
            return None
        row = rows[0]
        row["payload"] = json.loads(row["payload"])
        row["result"] = json.loads(row["result"]) if row["result"] else None
        return row

    def touch(self, sid):
        self.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now(), sid))
