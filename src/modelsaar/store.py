"""Lightweight local persistence (SQLite, stdlib only).

Stores probe evidence and measurements keyed by deployment fingerprint, and a
bounded decision log containing *metadata only* (never prompts).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

# Evidence scheme. Bump when the fingerprint inputs or the evaluator/scorer semantics change so
# that rows written under the old scheme can no longer be trusted. Old rows are kept (for audit)
# but never loaded; `modelsaar doctor` reports them.
#   1: 0.1.0 (fingerprint without endpoint/identity; evaluator with lenient scorers)
#   2: hardening 2026-10-11 (endpoint + identity in fingerprint; strict scorers; conditions column)
EVIDENCE_SCHEME = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS probes (
  deployment_id TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  capability TEXT NOT NULL,
  value TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  checked_at REAL NOT NULL,
  scheme INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (deployment_id, fingerprint, capability)
);
CREATE TABLE IF NOT EXISTS measurements (
  deployment_id TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  task TEXT NOT NULL,
  quality REAL,
  samples INTEGER NOT NULL DEFAULT 0,
  p50_ms REAL, p95_ms REAL, ttft_ms REAL, load_ms REAL,
  source TEXT NOT NULL DEFAULT 'eval',
  measured_at REAL NOT NULL,
  scheme INTEGER NOT NULL DEFAULT 1,
  conditions TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (deployment_id, fingerprint, task, source)
);
CREATE TABLE IF NOT EXISTS decisions (
  request_id TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decisions_created ON decisions(created_at);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._migrate()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.chmod(str(self.path) + suffix, 0o600)
            except OSError:
                pass

    def _migrate(self) -> None:
        """Add columns introduced after 0.1.0 and record the evidence scheme. Rows that predate the
        current scheme keep scheme=<old> and are excluded from every load."""
        with self._lock:
            for table, col, ddl in (
                ("probes", "scheme", "ALTER TABLE probes ADD COLUMN scheme INTEGER NOT NULL DEFAULT 1"),
                ("measurements", "scheme", "ALTER TABLE measurements ADD COLUMN scheme INTEGER NOT NULL DEFAULT 1"),
                ("measurements", "conditions", "ALTER TABLE measurements ADD COLUMN conditions TEXT NOT NULL DEFAULT '{}'"),
            ):
                cols = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
                if col not in cols:
                    self._conn.execute(ddl)
            row = self._conn.execute("SELECT value FROM meta WHERE key='evidence_scheme'").fetchone()
            previous = int(row[0]) if row else 1
            if previous < EVIDENCE_SCHEME:
                self._conn.execute(
                    "INSERT OR REPLACE INTO meta VALUES ('evidence_scheme_migrated_at', ?)", (f"{time.time():.0f}:from {previous}",)
                )
            self._conn.execute("INSERT OR REPLACE INTO meta VALUES ('evidence_scheme', ?)", (str(EVIDENCE_SCHEME),))
            self._conn.commit()

    def invalidated_counts(self) -> dict[str, int]:
        """Rows written under an older evidence scheme (kept for audit, never loaded)."""
        with self._lock:
            p = self._conn.execute("SELECT COUNT(*) FROM probes WHERE scheme<>?", (EVIDENCE_SCHEME,)).fetchone()[0]
            m = self._conn.execute("SELECT COUNT(*) FROM measurements WHERE scheme<>?", (EVIDENCE_SCHEME,)).fetchone()[0]
        return {"probes": int(p), "measurements": int(m), "scheme": EVIDENCE_SCHEME}

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # probes ---------------------------------------------------------------
    def save_probe(self, deployment_id: str, fingerprint: str, capability: str, value: str, note: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO probes (deployment_id, fingerprint, capability, value, note, checked_at, scheme) "
                "VALUES (?,?,?,?,?,?,?)",
                (deployment_id, fingerprint, capability, value, note, time.time(), EVIDENCE_SCHEME),
            )
            self._conn.commit()

    def load_probes(self, deployment_id: str, fingerprint: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT capability, value, note, checked_at FROM probes WHERE deployment_id=? AND fingerprint=? AND scheme=?",
                (deployment_id, fingerprint, EVIDENCE_SCHEME),
            ).fetchall()
        return {r[0]: {"value": r[1], "note": r[2], "checked_at": r[3]} for r in rows}

    def stale_probe_fingerprints(self, deployment_id: str, current_fp: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT fingerprint FROM probes WHERE deployment_id=? AND fingerprint<>? AND scheme=?",
                (deployment_id, current_fp, EVIDENCE_SCHEME),
            ).fetchall()
        return [r[0] for r in rows]

    # measurements ---------------------------------------------------------
    def save_measurement(self, deployment_id: str, fingerprint: str, m: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO measurements (deployment_id, fingerprint, task, quality, samples, p50_ms, p95_ms, "
                "ttft_ms, load_ms, source, measured_at, scheme, conditions) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    deployment_id,
                    fingerprint,
                    m["task"],
                    m.get("quality"),
                    int(m.get("samples", 0)),
                    m.get("p50_ms"),
                    m.get("p95_ms"),
                    m.get("ttft_ms"),
                    m.get("load_ms"),
                    m.get("source", "eval"),
                    m.get("measured_at") or time.time(),
                    EVIDENCE_SCHEME,
                    json.dumps(m.get("conditions") or {}, sort_keys=True, separators=(",", ":")),
                ),
            )
            self._conn.commit()

    def load_measurements(self, deployment_id: str, fingerprint: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT task, quality, samples, p50_ms, p95_ms, ttft_ms, load_ms, source, measured_at, conditions "
                "FROM measurements WHERE deployment_id=? AND fingerprint=? AND scheme=?",
                (deployment_id, fingerprint, EVIDENCE_SCHEME),
            ).fetchall()
        keys = ["task", "quality", "samples", "p50_ms", "p95_ms", "ttft_ms", "load_ms", "source", "measured_at", "conditions"]
        out = []
        for r in rows:
            d = dict(zip(keys, r, strict=True))
            try:
                d["conditions"] = json.loads(d["conditions"] or "{}")
            except ValueError:
                d["conditions"] = {}
            out.append(d)
        return out

    # decisions ------------------------------------------------------------
    def save_decision(self, request_id: str, record: dict[str, Any], retention_days: int = 7) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO decisions VALUES (?,?,?)",
                (request_id, time.time(), json.dumps(record, separators=(",", ":"))),
            )
            cutoff = time.time() - retention_days * 86400
            self._conn.execute("DELETE FROM decisions WHERE created_at < ?", (cutoff,))
            self._conn.commit()

    def get_decision(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT record FROM decisions WHERE request_id=?", (request_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def recent_decisions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT record FROM decisions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    # meta -----------------------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
            self._conn.commit()

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
