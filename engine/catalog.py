"""
catalog.py — SQLite generation catalog (spec Section 17.1).

This is MEMORY + a reusable library, NOT an anti-repetition rule engine.
It stores descriptive, readable metadata about each generated session so the
intelligence layer can later READ its own history and reason about variety and
natural progression (spec 17.2). There is deliberately NO mechanical
"signature comparison" here — querying returns recent entries as context;
the engine reasons over them, it does not compute equality.
"""

from __future__ import annotations
import sqlite3
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog (
    id              TEXT PRIMARY KEY,
    generated_at    TEXT NOT NULL,
    mode            TEXT NOT NULL,
    dominant_zone   TEXT NOT NULL,
    structural_pattern TEXT,
    complementary   TEXT,           -- JSON array of zone names
    duration_seconds INTEGER,
    estimated_tss   REAL,
    estimated_if    REAL,
    progression_id  TEXT,           -- nullable; links one multi-week request
    summary         TEXT,           -- human/engine-readable one-liner
    markdown        TEXT NOT NULL   -- full rendered .md (reusable library)
);
CREATE INDEX IF NOT EXISTS idx_catalog_generated_at ON catalog(generated_at);
CREATE INDEX IF NOT EXISTS idx_catalog_mode_zone ON catalog(mode, dominant_zone);
CREATE INDEX IF NOT EXISTS idx_catalog_progression ON catalog(progression_id);
"""


@dataclass
class CatalogEntry:
    id: str
    generated_at: str
    mode: str
    dominant_zone: str
    structural_pattern: Optional[str]
    complementary: list[str]
    duration_seconds: Optional[int]
    estimated_tss: Optional[float]
    estimated_if: Optional[float]
    progression_id: Optional[str]
    summary: Optional[str]
    markdown: str

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


class Catalog:
    def __init__(self, db_path: str | Path = "workout_catalog.sqlite"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add(self, entry: CatalogEntry) -> None:
        self._conn.execute(
            """INSERT INTO catalog
               (id, generated_at, mode, dominant_zone, structural_pattern,
                complementary, duration_seconds, estimated_tss, estimated_if,
                progression_id, summary, markdown)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.id, entry.generated_at, entry.mode, entry.dominant_zone,
                entry.structural_pattern, json.dumps(entry.complementary),
                entry.duration_seconds, entry.estimated_tss, entry.estimated_if,
                entry.progression_id, entry.summary, entry.markdown,
            ),
        )
        self._conn.commit()

    def recent(self, *, mode: Optional[str] = None,
               dominant_zone: Optional[str] = None,
               within_days: Optional[int] = 21,
               limit: int = 50) -> list[CatalogEntry]:
        """Return recent entries as CONTEXT for the reasoning layer.
        Filters by recency window (default 21 days, spec 17.2) and optionally
        by mode/zone. This is context retrieval, not an equality gate."""
        clauses, params = [], []
        if mode:
            clauses.append("mode = ?"); params.append(mode)
        if dominant_zone:
            clauses.append("dominant_zone = ?"); params.append(dominant_zone)
        if within_days is not None:
            cutoff = datetime.now(timezone.utc).timestamp() - within_days * 86400
            cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
            clauses.append("generated_at >= ?"); params.append(cutoff_iso)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM catalog{where} ORDER BY generated_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def by_progression(self, progression_id: str) -> list[CatalogEntry]:
        rows = self._conn.execute(
            "SELECT * FROM catalog WHERE progression_id = ? ORDER BY generated_at ASC",
            (progression_id,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]

    @staticmethod
    def _row_to_entry(r: sqlite3.Row) -> CatalogEntry:
        return CatalogEntry(
            id=r["id"], generated_at=r["generated_at"], mode=r["mode"],
            dominant_zone=r["dominant_zone"],
            structural_pattern=r["structural_pattern"],
            complementary=json.loads(r["complementary"]) if r["complementary"] else [],
            duration_seconds=r["duration_seconds"],
            estimated_tss=r["estimated_tss"], estimated_if=r["estimated_if"],
            progression_id=r["progression_id"], summary=r["summary"],
            markdown=r["markdown"],
        )

    def close(self) -> None:
        self._conn.close()
