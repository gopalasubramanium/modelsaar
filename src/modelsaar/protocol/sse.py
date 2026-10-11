"""Incremental Server-Sent-Events parsing and relay helpers.

The relay forwards upstream SSE frames to the client one *complete* event at
a time, tolerating partial network frames and multi-byte UTF-8 boundaries. It
never re-chunks or concatenates streams from different deployments.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SSEEvent:
    raw: bytes  # the complete frame including trailing blank line
    data: str | None = None  # joined data lines (without "data:" prefix)
    event: str | None = None

    def json(self) -> dict[str, Any] | None:
        if self.data is None or self.data.strip() == "[DONE]":
            return None
        try:
            v = json.loads(self.data)
            return v if isinstance(v, dict) else None
        except json.JSONDecodeError:
            return None

    @property
    def is_done(self) -> bool:
        return self.data is not None and self.data.strip() == "[DONE]"


@dataclass
class SSEParser:
    """Feed bytes, get complete events. Keeps partial frames buffered."""

    _buf: bytes = b""
    events_seen: int = 0

    def feed(self, chunk: bytes) -> Iterator[SSEEvent]:
        self._buf += chunk
        while True:
            # A frame ends at a blank line: \n\n or \r\n\r\n
            idx_n = self._buf.find(b"\n\n")
            idx_rn = self._buf.find(b"\r\n\r\n")
            candidates = [i for i in (idx_n, idx_rn) if i != -1]
            if not candidates:
                return
            if idx_rn != -1 and (idx_n == -1 or idx_rn < idx_n):
                end = idx_rn + 4
            else:
                end = idx_n + 2
            frame = self._buf[:end]
            self._buf = self._buf[end:]
            self.events_seen += 1
            yield self._parse(frame)

    def flush(self) -> Iterator[SSEEvent]:
        """Emit whatever is buffered as a final (possibly incomplete) frame."""
        if self._buf.strip():
            frame = self._buf
            self._buf = b""
            frame = frame.rstrip(b"\r\n") + b"\n\n"
            yield self._parse(frame)

    @staticmethod
    def _parse(frame: bytes) -> SSEEvent:
        data_lines: list[str] = []
        event: str | None = None
        text = frame.decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
            elif line.startswith("event:"):
                event = line[6:].strip()
        data = "\n".join(data_lines) if data_lines else None
        return SSEEvent(raw=frame, data=data, event=event)


def rewrite_model_field(ev: SSEEvent, model_name: str) -> bytes:
    """Return the frame bytes with chunk['model'] replaced, or the raw frame if not JSON."""
    obj = ev.json()
    if obj is None or "model" not in obj:
        return ev.raw
    obj["model"] = model_name
    return b"data: " + json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n\n"


@dataclass
class StreamObserver:
    """Tracks what the relay has seen for diagnostics and admission accounting."""

    first_byte_at: float | None = None
    events: int = 0
    content_chunks: int = 0
    reasoning_chunks: int = 0
    tool_call_deltas: int = 0
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    saw_done: bool = False
    error: str | None = None
    tool_call_indexes: set[int] = field(default_factory=set)

    def observe(self, ev: SSEEvent) -> None:
        self.events += 1
        if ev.is_done:
            self.saw_done = True
            return
        obj = ev.json()
        if not obj:
            return
        if "error" in obj:
            self.error = str(obj["error"])
        if obj.get("usage"):
            self.usage = obj["usage"]
        for ch in obj.get("choices") or []:
            if ch.get("finish_reason"):
                self.finish_reason = ch["finish_reason"]
            delta = ch.get("delta") or {}
            if delta.get("content"):
                self.content_chunks += 1
            if delta.get("reasoning_content") or delta.get("reasoning"):
                self.reasoning_chunks += 1
            for tc in delta.get("tool_calls") or []:
                self.tool_call_deltas += 1
                if isinstance(tc.get("index"), int):
                    self.tool_call_indexes.add(tc["index"])
