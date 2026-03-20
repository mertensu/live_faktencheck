"""
SQLite database module for persistent storage.

Uses aiosqlite for async SQLite access. Stores fact-checks and pending claim blocks
with JSON serialization for complex fields (quellen, claims).
"""

import json
import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent / "data" / "factcheck.db"


class Database:
    """Async SQLite database for fact-checks and pending claims."""

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
                episode_key TEXT,
                status TEXT NOT NULL DEFAULT '',
                double_check INTEGER NOT NULL DEFAULT 0,
                critique_note TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_fact_checks_speaker_claim
                ON fact_checks (sprecher, behauptung);

            CREATE TABLE IF NOT EXISTS pending_claims_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_id TEXT NOT NULL UNIQUE,
                timestamp TEXT NOT NULL,
                claims_count INTEGER NOT NULL DEFAULT 0,
                claims TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                episode_key TEXT,
                source_id TEXT,
                headline TEXT,
                text_preview TEXT,
                info TEXT
            );
        """)
        await self.db.commit()

        # Migrations: add columns to existing fact_checks tables
        for migration in [
            "ALTER TABLE fact_checks ADD COLUMN status TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE fact_checks ADD COLUMN double_check INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE fact_checks ADD COLUMN critique_note TEXT NOT NULL DEFAULT ''",
        ]:
            try:
                await self.db.execute(migration)
                await self.db.commit()
            except Exception:
                pass  # Column already exists

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
            data.get("episode_key"),
            data.get("status", ""),
            int(bool(data.get("double_check", False))),
            data.get("critique_note", ""),
        )

    async def add_fact_check(self, fact_check: dict) -> int:
        """Insert a fact-check and return its auto-generated ID."""
        cursor = await self.db.execute(
            """INSERT INTO fact_checks
               (sprecher, behauptung, consistency, begruendung, quellen, timestamp, episode_key, status,
                double_check, critique_note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            self._fact_check_params(fact_check),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get_fact_checks(self, episode_key: str | None = None) -> list[dict]:
        """Return all fact-checks, optionally filtered by episode_key."""
        if episode_key:
            cursor = await self.db.execute(
                "SELECT * FROM fact_checks WHERE episode_key = ? ORDER BY id",
                (episode_key,),
            )
        else:
            cursor = await self.db.execute("SELECT * FROM fact_checks ORDER BY id")
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
                   begruendung = ?, quellen = ?, timestamp = ?, episode_key = ?, status = ?,
                   double_check = ?, critique_note = ?
               WHERE id = ?""",
            (*self._fact_check_params(data), fact_check_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def find_fact_check(
        self, speaker: str, claim: str
    ) -> dict | None:
        """Find a fact-check by speaker + claim text (newest first)."""
        cursor = await self.db.execute(
            "SELECT * FROM fact_checks WHERE sprecher = ? AND behauptung = ? ORDER BY id DESC LIMIT 1",
            (speaker, claim),
        )
        row = await cursor.fetchone()
        return self._row_to_fact_check(row) if row else None

    async def count_fact_checks(self) -> int:
        """Return the total number of fact-checks."""
        cursor = await self.db.execute("SELECT COUNT(*) FROM fact_checks")
        row = await cursor.fetchone()
        return row[0]

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
            "episode_key": row["episode_key"],
            "status": row["status"],
            "double_check": bool(row["double_check"]),
            "critique_note": row["critique_note"],
        }

    # =========================================================================
    # Pending Claims Blocks CRUD
    # =========================================================================

    async def add_pending_block(self, block: dict) -> int:
        """Insert a pending claims block. Returns the row ID."""
        cursor = await self.db.execute(
            """INSERT INTO pending_claims_blocks
               (block_id, timestamp, claims_count, claims, status,
                episode_key, source_id, headline, text_preview, info)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                block["block_id"],
                block["timestamp"],
                block.get("claims_count", len(block.get("claims", []))),
                json.dumps(block.get("claims", []), ensure_ascii=False),
                block.get("status", "pending"),
                block.get("episode_key"),
                block.get("source_id"),
                block.get("headline"),
                block.get("text_preview"),
                block.get("info"),
            ),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get_pending_blocks(self, episode_key: str | None = None) -> list[dict]:
        """Return pending blocks, newest first. Optionally filter by episode_key."""
        if episode_key:
            cursor = await self.db.execute(
                "SELECT * FROM pending_claims_blocks WHERE episode_key = ? ORDER BY timestamp DESC",
                (episode_key,),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM pending_claims_blocks ORDER BY timestamp DESC"
            )
        rows = await cursor.fetchall()
        return [self._row_to_pending_block(row) for row in rows]

    async def get_pending_block_by_id(self, block_id: str) -> dict | None:
        """Return a single pending block by block_id, or None."""
        cursor = await self.db.execute(
            "SELECT * FROM pending_claims_blocks WHERE block_id = ?", (block_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_pending_block(row) if row else None

    async def block_id_exists(self, block_id: str) -> bool:
        """Check if a block_id already exists."""
        cursor = await self.db.execute(
            "SELECT 1 FROM pending_claims_blocks WHERE block_id = ?", (block_id,)
        )
        return await cursor.fetchone() is not None

    async def delete_pending_block(self, block_id: str) -> bool:
        """Delete a pending block by block_id. Returns True if deleted."""
        cursor = await self.db.execute(
            "DELETE FROM pending_claims_blocks WHERE block_id = ?", (block_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def clear_pending_blocks(self, episode_key: str | None = None) -> int:
        """Delete all pending blocks, optionally filtered by episode_key. Returns count deleted."""
        if episode_key:
            cursor = await self.db.execute(
                "DELETE FROM pending_claims_blocks WHERE episode_key = ?",
                (episode_key,),
            )
        else:
            cursor = await self.db.execute("DELETE FROM pending_claims_blocks")
        await self.db.commit()
        return cursor.rowcount

    async def count_pending_blocks(self) -> int:
        """Return the total number of pending blocks."""
        cursor = await self.db.execute("SELECT COUNT(*) FROM pending_claims_blocks")
        row = await cursor.fetchone()
        return row[0]

    def _row_to_pending_block(self, row: aiosqlite.Row) -> dict:
        """Convert a database row to a pending block dict with parsed JSON."""
        return {
            "block_id": row["block_id"],
            "timestamp": row["timestamp"],
            "claims_count": row["claims_count"],
            "claims": json.loads(row["claims"]),
            "status": row["status"],
            "episode_key": row["episode_key"],
            "source_id": row["source_id"],
            "headline": row["headline"],
            "text_preview": row["text_preview"],
            "info": row["info"],
        }
