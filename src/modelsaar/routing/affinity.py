"""Session/run affinity, scoped to the authenticated caller.

A session key comes only from explicit, documented sources: a configured
request header (e.g. ``X-ModelSaar-Session``, ``X-OpenWebUI-Chat-Id``), a
configured body field (``prompt_cache_key``), or the request's
``modelsaar.session`` hint. API keys are never used as conversation ids and a
shared system prompt is never treated as a session.

Tool round trips are kept on the same deployment even without a session id by
remembering the tool_call ids issued in the previous assistant turn.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from ..config import AffinityConfig


@dataclass
class AffinityEntry:
    deployment_id: str
    expires_at: float
    source: str


class AffinityStore:
    def __init__(self, cfg: AffinityConfig) -> None:
        self.cfg = cfg
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, AffinityEntry] = OrderedDict()
        self._tool_rounds: OrderedDict[str, AffinityEntry] = OrderedDict()

    @staticmethod
    def _scope(caller_id: str, key: str) -> str:
        return hashlib.sha256(f"{caller_id}\x00{key}".encode()).hexdigest()[:32]

    def extract_session_key(self, headers: dict[str, str], body: dict[str, Any]) -> tuple[str | None, str]:
        hint = body.get("modelsaar") or {}
        if isinstance(hint, dict) and hint.get("session"):
            return str(hint["session"])[:256], "body:modelsaar.session"
        lower = {k.lower(): v for k, v in headers.items()}
        for h in self.cfg.session_headers:
            v = lower.get(h.lower())
            if v:
                return str(v)[:256], f"header:{h}"
        for f in self.cfg.body_fields:
            v = body.get(f)
            if isinstance(v, str) and v:
                return v[:256], f"body:{f}"
        return None, "none"

    def get(self, caller_id: str, session_key: str) -> AffinityEntry | None:
        k = self._scope(caller_id, session_key)
        with self._lock:
            e = self._sessions.get(k)
            if e and e.expires_at > time.time():
                self._sessions.move_to_end(k)
                return e
            if e:
                self._sessions.pop(k, None)
        return None

    def set(self, caller_id: str, session_key: str, deployment_id: str, source: str) -> None:
        k = self._scope(caller_id, session_key)
        with self._lock:
            self._sessions[k] = AffinityEntry(deployment_id, time.time() + self.cfg.ttl_s, source)
            self._sessions.move_to_end(k)
            while len(self._sessions) > self.cfg.max_sessions:
                self._sessions.popitem(last=False)

    # Tool round trips ------------------------------------------------------
    @staticmethod
    def _round_key(caller_id: str, tool_call_ids: list[str]) -> str:
        return hashlib.sha256(("\x00".join([caller_id, *sorted(tool_call_ids)])).encode()).hexdigest()[:32]

    def remember_tool_calls(self, caller_id: str, tool_call_ids: list[str], deployment_id: str) -> None:
        if not tool_call_ids:
            return
        k = self._round_key(caller_id, tool_call_ids)
        with self._lock:
            self._tool_rounds[k] = AffinityEntry(deployment_id, time.time() + min(self.cfg.ttl_s, 1800), "tool_round_trip")
            while len(self._tool_rounds) > self.cfg.max_sessions:
                self._tool_rounds.popitem(last=False)

    def lookup_tool_round(self, caller_id: str, tool_call_ids: list[str]) -> AffinityEntry | None:
        if not tool_call_ids:
            return None
        # Try the exact set first, then any single id (parallel calls answered one at a time).
        keys = [self._round_key(caller_id, tool_call_ids)] + [self._round_key(caller_id, [i]) for i in tool_call_ids]
        with self._lock:
            for k in keys:
                e = self._tool_rounds.get(k)
                if e and e.expires_at > time.time():
                    return e
        return None

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"sessions": len(self._sessions), "tool_rounds": len(self._tool_rounds)}
