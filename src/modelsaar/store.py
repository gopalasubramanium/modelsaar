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

SCHEMA = """
CREATE TABLE IF NOT EXISTS probes (
  deployment_id TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  capability TEXT NOT NULL,
  value TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  checked_at REAL NOT NULL,
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
        for suffix in ("", "-wal", "-shm"):
            try:
                os.chmod(str(self.path) + suffix, 0o600)
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # probes ---------------------------------------------------------------
    def save_probe(self, deployment_id: str, fingerprint: str, capability: str, value: str, note: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO probes VALUES (?,?,?,?,?,?)",
                (deployment_id, fingerprint, capability, value, note, time.time()),
            )
            self._conn.commit()

    def load_probes(self, deployment_id: str, fingerprint: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT capability, value, note, checked_at FROM probes WHERE deployment_id=? AND fingerprint=?",
                (deployment_id, fingerprint),
            ).fetchall()
        return {r[0]: {"value": r[1], "note": r[2], "checked_at": r[3]} for r in rows}

    def stale_probe_fingerprints(self, deployment_id: str, current_fp: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT fingerprint FROM probes WHERE deployment_id=? AND fingerprint<>?",
                (deployment_id, current_fp),
            ).fetchall()
        return [r[0] for r in rows]

    # measurements ---------------------------------------------------------
    def save_measurement(self, deployment_id: str, fingerprint: str, m: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO measurements VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
                ),
            )
            self._conn.commit()

    def load_measurements(self, deployment_id: str, fingerprint: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT task, quality, samples, p50_ms, p95_ms, ttft_ms, load_ms, source, measured_at "
                "FROM measurements WHERE deployment_id=? AND fingerprint=?",
                (deployment_id, fingerprint),
            ).fetchall()
        keys = ["task", "quality", "samples", "p50_ms", "p95_ms", "ttft_ms", "load_ms", "source", "measured_at"]
        return [dict(zip(keys, r, strict=True)) for r in rows]

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
