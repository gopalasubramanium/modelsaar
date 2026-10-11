"""Authentication, caller scoping and log redaction."""

from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path

from .config import Config, read_keys

_SECRET_RX = re.compile(
    r"(?i)(bearer\s+[a-z0-9_\-\.]{8,}|msk_[A-Za-z0-9_\-]{16,}|msa_[A-Za-z0-9_\-]{16,}|sk-[A-Za-z0-9]{8,}|"
    r"(api[_-]?key|authorization|token)\s*[=:]\s*['\"]?[A-Za-z0-9_\-\.]{8,})"
)


def redact(text: str) -> str:
    return _SECRET_RX.sub("[REDACTED]", text)


class Auth:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.api_keys = read_keys(cfg.resolve(cfg.server.api_keys_file))
        self.admin_keys = read_keys(cfg.resolve(cfg.server.admin_key_file))

    @staticmethod
    def _bearer(headers: dict[str, str]) -> str | None:
        h = headers.get("authorization") or headers.get("Authorization")
        if not h:
            # Some clients send x-api-key.
            return headers.get("x-api-key")
        parts = h.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return None

    @staticmethod
    def _match(token: str, keys: list[str]) -> bool:
        t = token.encode("utf-8", "surrogateescape")
        return any(hmac.compare_digest(t, k.encode("utf-8")) for k in keys)

    def caller(self, headers: dict[str, str]) -> str | None:
        """Return a stable caller id (hash of the key) or None if unauthenticated."""
        tok = self._bearer(headers)
        if not tok:
            return None
        if self._match(tok, self.api_keys) or self._match(tok, self.admin_keys):
            return hashlib.sha256(tok.encode()).hexdigest()[:12]
        return None

    def is_admin(self, headers: dict[str, str]) -> bool:
        tok = self._bearer(headers)
        return bool(tok) and self._match(tok, self.admin_keys)

    @property
    def configured(self) -> bool:
        return bool(self.api_keys) and bool(self.admin_keys)


def key_paths(cfg: Config) -> tuple[Path, Path]:
    return cfg.resolve(cfg.server.api_keys_file), cfg.resolve(cfg.server.admin_key_file)
