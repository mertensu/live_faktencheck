"""
SQLite database module for persistent storage.

Uses aiosqlite for async SQLite access. Stores fact-checks, sessions and access
codes, with JSON serialization for complex fields (quellen, guests).
"""

import json
import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent / "data" / "factcheck.db"


class Database:
    """Async SQLite database for fact-checks, sessions and access codes."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = str(db_path)
        self.db: aiosqlite.Connection | None = None

    async def connect(self):
        """Open the database connection and configure pragmas."""
        # Ensure data directory exists for file-based DBs
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row

        await self.init_schema()
        logger.info(f"Database connected: {self.db_path}")

    async def close(self):
        """Close the database connection."""
        if self.db:
            await self.db.close()
            self.db = None
            logger.info("Database closed")

    async def init_schema(self):
        """Create tables if they don't exist."""
        await self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;

            CREATE TABLE IF NOT EXISTS fact_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sprecher TEXT NOT NULL DEFAULT '',
                behauptung TEXT NOT NULL DEFAULT '',
                consistency TEXT NOT NULL DEFAULT '',
                begruendung TEXT NOT NULL DEFAULT '',
                quellen TEXT NOT NULL DEFAULT '[]',
                timestamp TEXT NOT NULL,
                session_id TEXT,
                status TEXT NOT NULL DEFAULT '',
                double_check INTEGER NOT NULL DEFAULT 0,
                critique_note TEXT NOT NULL DEFAULT '',
                check_depth TEXT NOT NULL DEFAULT 'deep'
            );

            CREATE INDEX IF NOT EXISTS idx_fact_checks_speaker_claim
                ON fact_checks (sprecher, behauptung);

            -- Legacy: written by the removed block pipeline (<= v0.2.0). Kept so
            -- existing databases keep their rows; nothing reads or writes it now.
            CREATE TABLE IF NOT EXISTS pending_claims_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_id TEXT NOT NULL UNIQUE,
                timestamp TEXT NOT NULL,
                claims_count INTEGER NOT NULL DEFAULT 0,
                claims TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                session_id TEXT,
                source_id TEXT,
                headline TEXT,
                text_preview TEXT,
                info TEXT
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id       TEXT PRIMARY KEY,
                title            TEXT NOT NULL DEFAULT '',
                date             TEXT NOT NULL DEFAULT '',
                guests           TEXT NOT NULL DEFAULT '[]',
                context          TEXT NOT NULL DEFAULT '',
                type             TEXT NOT NULL DEFAULT 'show',
                conversation_type TEXT NOT NULL DEFAULT 'debate',
                excluded_speakers TEXT NOT NULL DEFAULT '[]',
                auto_check       INTEGER NOT NULL DEFAULT 0,
                status           TEXT NOT NULL DEFAULT 'active',
                visibility       TEXT NOT NULL DEFAULT 'private',
                owner_code       TEXT,
                created_at       TEXT NOT NULL,
                ended_at         TEXT
            );

            CREATE TABLE IF NOT EXISTS codes (
                code                TEXT PRIMARY KEY,
                name                TEXT NOT NULL,
                active              INTEGER NOT NULL DEFAULT 1,
                created_at          TEXT NOT NULL,
                quick_checks_used   INTEGER NOT NULL DEFAULT 0,
                quick_check_limit   INTEGER DEFAULT 3,
                audio_seconds_used  INTEGER NOT NULL DEFAULT 0,
                audio_seconds_limit INTEGER DEFAULT 300
            );
        """)
        await self.db.commit()

        # Migrations: add columns to existing fact_checks tables
        for migration in [
            "ALTER TABLE fact_checks ADD COLUMN status TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE fact_checks ADD COLUMN double_check INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE fact_checks ADD COLUMN critique_note TEXT NOT NULL DEFAULT ''",
            # Existing rows are full/deep checks; the live fast lane writes 'fast'.
            "ALTER TABLE fact_checks ADD COLUMN check_depth TEXT NOT NULL DEFAULT 'deep'",
        ]:
            try:
                await self.db.execute(migration)
                await self.db.commit()
            except Exception:
                pass  # Column already exists

        # Migration: extra AssemblyAI keyterms per session (names mentioned in the show).
        try:
            await self.db.execute("ALTER TABLE sessions ADD COLUMN keyterms TEXT NOT NULL DEFAULT '[]'")
            await self.db.commit()
        except Exception:
            pass  # Column already exists

        # Migrations: add Quick Check quota columns to existing codes tables.
        # Quick Check is gone (v0.3.0); the columns stay so existing rows are untouched.
        for migration in [
            "ALTER TABLE codes ADD COLUMN quick_checks_used INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE codes ADD COLUMN quick_check_limit INTEGER DEFAULT 3",
        ]:
            try:
                await self.db.execute(migration)
                await self.db.commit()
            except Exception:
                pass  # Column already exists

        # Migration: add Live-Audio quota columns to existing codes tables.
        # DEFAULT 300 backfills existing codes to 5 min (fail-closed) — NOT NULL/unlimited.
        for migration in [
            "ALTER TABLE codes ADD COLUMN audio_seconds_used INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE codes ADD COLUMN audio_seconds_limit INTEGER DEFAULT 300",
        ]:
            try:
                await self.db.execute(migration)
                await self.db.commit()
            except Exception:
                pass  # Column already exists

        # Migration: add conversation_type to existing sessions tables
        for migration in [
            "ALTER TABLE sessions ADD COLUMN conversation_type TEXT NOT NULL DEFAULT 'debate'",
        ]:
            try:
                await self.db.execute(migration)
                await self.db.commit()
            except Exception:
                pass  # Column already exists

        # Migration: add excluded_speakers to existing sessions tables
        for migration in [
            "ALTER TABLE sessions ADD COLUMN excluded_speakers TEXT NOT NULL DEFAULT '[]'",
        ]:
            try:
                await self.db.execute(migration)
                await self.db.commit()
            except Exception:
                pass  # Column already exists

        # Migration: add auto_check to existing sessions tables
        for migration in [
            "ALTER TABLE sessions ADD COLUMN auto_check INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                await self.db.execute(migration)
                await self.db.commit()
            except Exception:
                pass  # Column already exists

        # Migration: rename episode_key -> session_id (SQLite >= 3.25)
        for table in ("fact_checks", "pending_claims_blocks"):
            cursor = await self.db.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in await cursor.fetchall()]
            if "episode_key" in cols and "session_id" not in cols:
                await self.db.execute(
                    f"ALTER TABLE {table} RENAME COLUMN episode_key TO session_id"
                )
                await self.db.commit()

    # =========================================================================
    # Fact-Checks CRUD
    # =========================================================================

    def _fact_check_params(self, data: dict) -> tuple:
        """Extract the ordered parameter tuple for INSERT/UPDATE of a fact-check."""
        return (
            data.get("sprecher", ""),
            data.get("behauptung", ""),
            data.get("consistency", ""),
            data.get("begruendung", ""),
            json.dumps(data.get("quellen", []), ensure_ascii=False),
            data["timestamp"],
            data.get("session_id"),
            data.get("status", ""),
            int(bool(data.get("double_check", False))),
            data.get("critique_note", ""),
            data.get("check_depth", "deep"),
        )

    async def add_fact_check(self, fact_check: dict) -> int:
        """Insert a fact-check and return its auto-generated ID."""
        cursor = await self.db.execute(
            """INSERT INTO fact_checks
               (sprecher, behauptung, consistency, begruendung, quellen, timestamp, session_id, status,
                double_check, critique_note, check_depth)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            self._fact_check_params(fact_check),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get_fact_checks(self, session_id: str | None = None, status: str | None = None) -> list[dict]:
        """Return fact-checks, optionally filtered by session_id and/or status.
        Excludes discarded claims by default (unless status='discarded' is requested)."""
        conditions = []
        params: list = []
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        else:
            conditions.append("status != 'discarded'")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        cursor = await self.db.execute(
            f"SELECT * FROM fact_checks {where} ORDER BY id", params
        )
        rows = await cursor.fetchall()
        return [self._row_to_fact_check(row) for row in rows]

    async def get_fact_check_by_id(self, fact_check_id: int) -> dict | None:
        """Return a single fact-check by ID, or None."""
        cursor = await self.db.execute(
            "SELECT * FROM fact_checks WHERE id = ?", (fact_check_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_fact_check(row) if row else None

    async def update_fact_check(self, fact_check_id: int, data: dict) -> bool:
        """Update a fact-check by ID. Returns True if a row was updated."""
        cursor = await self.db.execute(
            """UPDATE fact_checks
               SET sprecher = ?, behauptung = ?, consistency = ?,
                   begruendung = ?, quellen = ?, timestamp = ?, session_id = ?, status = ?,
                   double_check = ?, critique_note = ?, check_depth = ?
               WHERE id = ?""",
            (*self._fact_check_params(data), fact_check_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def count_fact_checks(self) -> int:
        """Return the total number of fact-checks."""
        cursor = await self.db.execute("SELECT COUNT(*) FROM fact_checks")
        row = await cursor.fetchone()
        return row[0]

    async def delete_fact_check(self, fact_check_id: int) -> bool:
        """Delete a fact-check by ID. Returns True if a row was deleted."""
        cursor = await self.db.execute(
            "DELETE FROM fact_checks WHERE id = ?", (fact_check_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    def _row_to_fact_check(self, row: aiosqlite.Row) -> dict:
        """Convert a database row to a fact-check dict with parsed JSON."""
        return {
            "id": row["id"],
            "sprecher": row["sprecher"],
            "behauptung": row["behauptung"],
            "consistency": row["consistency"],
            "begruendung": row["begruendung"],
            "quellen": json.loads(row["quellen"]),
            "timestamp": row["timestamp"],
            "session_id": row["session_id"],
            "status": row["status"],
            "double_check": bool(row["double_check"]),
            "critique_note": row["critique_note"],
            "check_depth": row["check_depth"],
        }

    # =========================================================================
    # Sessions CRUD
    # =========================================================================

    def _row_to_session(self, row) -> dict:
        return {
            "session_id": row["session_id"],
            "title": row["title"],
            "date": row["date"],
            "guests": json.loads(row["guests"]),
            "context": row["context"],
            "type": row["type"],
            "conversation_type": row["conversation_type"],
            "excluded_speakers": json.loads(row["excluded_speakers"]),
            "keyterms": json.loads(row["keyterms"]) if "keyterms" in row.keys() else [],
            "auto_check": bool(row["auto_check"]),
            "status": row["status"],
            "visibility": row["visibility"],
            "owner_code": row["owner_code"],
            "created_at": row["created_at"],
            "ended_at": row["ended_at"],
        }

    async def add_session(self, session: dict) -> str:
        """Insert a session. Returns its session_id."""
        from datetime import datetime
        await self.db.execute(
            """INSERT INTO sessions
               (session_id, title, date, guests, context,
                type, conversation_type, excluded_speakers, keyterms, auto_check, status, visibility, owner_code,
                created_at, ended_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session["session_id"],
                session.get("title", ""),
                session.get("date", ""),
                json.dumps(session.get("guests", []), ensure_ascii=False),
                session.get("context", ""),
                session.get("type", "show"),
                session.get("conversation_type", "debate"),
                json.dumps(session.get("excluded_speakers", []), ensure_ascii=False),
                json.dumps(session.get("keyterms", []), ensure_ascii=False),
                int(bool(session.get("auto_check", False))),
                session.get("status", "active"),
                session.get("visibility", "private"),
                session.get("owner_code"),
                session.get("created_at", datetime.now().isoformat()),
                session.get("ended_at"),
            ),
        )
        await self.db.commit()
        return session["session_id"]

    async def get_session(self, session_id: str) -> dict | None:
        cursor = await self.db.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_session(row) if row else None

    async def list_sessions(self) -> list[dict]:
        cursor = await self.db.execute("SELECT * FROM sessions ORDER BY created_at DESC")
        return [self._row_to_session(r) for r in await cursor.fetchall()]

    async def count_active_sessions(self, within_minutes: int = 30) -> int:
        """Count sessions that are actually live: status 'active' AND touched within the
        window (created just now, or a fact-check produced recently). The bare 'active'
        flag never clears — nothing calls the end endpoint — so counting it alone reports
        every session ever started. ISO-8601 timestamps compare lexicographically."""
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(minutes=within_minutes)).isoformat()
        cursor = await self.db.execute(
            """
            SELECT COUNT(*) FROM sessions s
            WHERE s.status = 'active'
              AND (
                s.created_at >= ?
                OR EXISTS (
                    SELECT 1 FROM fact_checks f
                    WHERE f.session_id = s.session_id AND f.timestamp >= ?
                )
              )
            """,
            (cutoff, cutoff),
        )
        row = await cursor.fetchone()
        return row[0]

    async def end_session(self, session_id: str) -> bool:
        from datetime import datetime
        cursor = await self.db.execute(
            "UPDATE sessions SET status = 'ended', ended_at = ? WHERE session_id = ?",
            (datetime.now().isoformat(), session_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def seed_session_if_absent(self, session: dict) -> None:
        """Insert a session only if its session_id does not already exist."""
        existing = await self.get_session(session["session_id"])
        if existing is None:
            await self.add_session(session)

    # =========================================================================
    # Access Codes CRUD
    # =========================================================================

    async def add_code(
        self,
        code: str,
        name: str,
        audio_seconds_limit: int | None = 300,
    ) -> None:
        """Insert an access code (no-op if the code already exists).

        audio_seconds_limit: lifetime live-audio cap in seconds; None means unlimited.
        """
        from datetime import datetime
        await self.db.execute(
            "INSERT OR IGNORE INTO codes "
            "(code, name, active, created_at, audio_seconds_limit) "
            "VALUES (?, ?, 1, ?, ?)",
            (code, name, datetime.now().isoformat(), audio_seconds_limit),
        )
        await self.db.commit()

    async def get_code(self, code: str) -> dict | None:
        """Return an active code row, or None if unknown/inactive."""
        cursor = await self.db.execute(
            "SELECT * FROM codes WHERE code = ? AND active = 1", (code,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def deactivate_code(self, code: str) -> bool:
        """Set a code inactive. Returns True if a row was changed."""
        cursor = await self.db.execute(
            "UPDATE codes SET active = 0 WHERE code = ?", (code,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def list_codes(self) -> list[dict]:
        """Return all codes (active and inactive)."""
        cursor = await self.db.execute("SELECT * FROM codes ORDER BY created_at")
        return [dict(r) for r in await cursor.fetchall()]

    async def count_codes(self) -> int:
        """Return the total number of codes (active and inactive)."""
        cursor = await self.db.execute("SELECT COUNT(*) FROM codes")
        row = await cursor.fetchone()
        return row[0]

    async def increment_audio_seconds(self, code: str, seconds: int) -> None:
        """Add transcribed audio seconds to a code's lifetime counter."""
        await self.db.execute(
            "UPDATE codes SET audio_seconds_used = audio_seconds_used + ? WHERE code = ?",
            (seconds, code),
        )
        await self.db.commit()
