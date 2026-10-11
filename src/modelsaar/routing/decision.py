"""Concise, inspectable routing decision records (metadata only, never prompts)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Decision:
    request_id: str = field(default_factory=lambda: "req_" + uuid.uuid4().hex[:16])
    created_at: float = field(default_factory=time.time)
    config_hash: str = ""
    registry_version: int = 0
    requested_model: str = ""
    alias: str | None = None
    explicit: bool = False
    profile: str = "quality"
    requirements: dict[str, Any] = field(default_factory=dict)
    exclusions: dict[str, list[str]] = field(default_factory=dict)
    remedies: list[str] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    chosen: str | None = None
    evidence: str = ""
    classifier: dict[str, Any] = field(default_factory=dict)
    affinity: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    overhead_ms: float = 0.0
    outcome: str = "pending"  # pending | ok | upstream_error | no_eligible | admission_rejected | ...
    outcome_detail: str = ""
    failover: list[dict[str, Any]] = field(default_factory=list)
    translation_notes: list[str] = field(default_factory=list)
    requirements_note: str = ""
    stream: bool = False
    endpoint: str = "chat"

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "created_at": self.created_at,
            "config_hash": self.config_hash,
            "registry_version": self.registry_version,
            "endpoint": self.endpoint,
            "requested_model": self.requested_model,
            "alias": self.alias,
            "explicit": self.explicit,
            "profile": self.profile,
            "stream": self.stream,
            "requirements": self.requirements,
            "exclusions": self.exclusions,
            "remedies": self.remedies,
            "candidates": self.candidates,
            "chosen": self.chosen,
            "evidence": self.evidence,
            "classifier": self.classifier,
            "affinity": self.affinity,
            "reasons": self.reasons,
            "overhead_ms": round(self.overhead_ms, 2),
            "outcome": self.outcome,
            "outcome_detail": self.outcome_detail,
            "failover": self.failover,
            "translation_notes": self.translation_notes,
            "requirements_note": self.requirements_note,
        }

    def summary_line(self) -> str:
        return f"{self.request_id} {self.requested_model} -> {self.chosen or 'NONE'} ({self.evidence}; {self.overhead_ms:.1f}ms)"
