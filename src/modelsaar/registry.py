"""Deployment registry.

The routing unit is an exact *deployment*: a model served by a specific
backend with a specific runtime, template, quantization, context and
resource pool. The registry keeps distinct states (configured, discovered,
available, loaded, healthy) and three-state capabilities with provenance.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Tri = Literal["supported", "unsupported", "unknown"]
Role = Literal["generative", "embedding", "decision", "ocr", "rerank", "guardrail"]

CAPABILITY_KEYS = (
    "tools",
    "tool_choice_required",
    "parallel_tools",
    "json_schema",
    "json_object",
    "streaming",
    "vision",
    "audio_in",
    "thinking",
    "continuation",
)


@dataclass
class CapValue:
    value: Tri = "unknown"
    # "source_claim" (backend metadata / model card), "probe", "operator", "adapter"
    provenance: str = "none"
    checked_at: float | None = None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Measurement:
    """Measured latency/quality evidence for a deployment (per fingerprint)."""

    task: str
    quality: float | None = None  # 0..1 measured success rate
    samples: int = 0
    p50_ms: float | None = None
    p95_ms: float | None = None
    ttft_ms: float | None = None
    load_ms: float | None = None
    source: str = "eval"  # eval | probe | live
    measured_at: float | None = None
    # Measurement conditions (hardware/context/generation settings/workload) so a number is never
    # read outside the conditions it was taken under.
    conditions: dict[str, Any] = field(default_factory=dict)


@dataclass
class Deployment:
    id: str  # "<backend_id>/<model_name>"
    backend_id: str
    backend_type: str
    model: str
    role: Role = "generative"
    publisher: str = ""
    family: str = ""
    parameter_size: str = ""
    quantization: str = ""
    digest: str = ""
    # Checkpoint identity: a weights digest from the runtime or an operator declaration. Empty
    # means unknown; a bare model-name match is never an identity.
    identity: str = ""
    identity_source: str = ""
    # Execution endpoint (scheme://host:port/path of the backend base URL). Part of the
    # fingerprint: the same backend id and model name on another server is other evidence.
    endpoint: str = ""
    runtime: str = ""
    runtime_version: str = ""
    template_hash: str = ""
    context_length: int | None = None
    max_output_tokens: int | None = None
    embedding_dimensions: int | None = None
    resource_pool: str | None = None
    locality: Literal["local", "remote", "unknown"] = "unknown"
    locality_evidence: str = ""
    capabilities: dict[str, CapValue] = field(default_factory=lambda: {k: CapValue() for k in CAPABILITY_KEYS})
    tags: list[str] = field(default_factory=list)
    catalogue_id: str | None = None
    memory_gb_estimate: float | None = None
    memory_estimate_provenance: str = ""
    intended_use_note: str = ""
    enabled: bool = True
    # Observed state
    configured: bool = False
    discovered: bool = False
    available_on_disk: bool = False
    loaded: bool = False
    loaded_observed_at: float | None = None
    healthy: bool = False
    health_checked_at: float | None = None
    last_error: str = ""
    # Evidence
    quality_prior: dict[str, float] = field(default_factory=dict)
    quality_prior_provenance: str = "uncalibrated"
    measurements: dict[str, Measurement] = field(default_factory=dict)
    fingerprint: str = ""
    discovered_at: float | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    def compute_fingerprint(self) -> str:
        # Intrinsic identity only. The *served* context length and residency change whenever a
        # runtime loads/unloads a model (Ollama reports it only while loaded); they affect eligibility
        # per request but do not change what the checkpoint can do, so they must not invalidate evidence.
        parts = self.fingerprint_inputs()
        s = json.dumps(parts, sort_keys=True)
        self.fingerprint = hashlib.sha256(s.encode()).hexdigest()[:16]
        return self.fingerprint

    def cap(self, key: str) -> Tri:
        cv = self.capabilities.get(key)
        return cv.value if cv else "unknown"

    def set_cap(self, key: str, value: Tri, provenance: str, note: str = "") -> None:
        self.capabilities[key] = CapValue(value=value, provenance=provenance, checked_at=time.time(), note=note)

    def is_eligible_base(self) -> bool:
        return self.enabled and self.healthy

    def fingerprint_inputs(self) -> dict[str, Any]:
        """Checkpoint identity + serving configuration that affects capabilities. Empty values are
        unknown and are shown as such in `modelsaar discover` / the admin status."""
        return {
            "backend": self.backend_id,
            "endpoint": self.endpoint,
            "model": self.model,
            "digest": self.digest,
            "identity": self.identity,
            "runtime": self.runtime,
            "runtime_version": self.runtime_version,
            "template": self.template_hash,
            "quant": self.quantization,
            "pool": self.resource_pool,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "backend": self.backend_id,
            "backend_type": self.backend_type,
            "model": self.model,
            "role": self.role,
            "family": self.family,
            "parameter_size": self.parameter_size,
            "quantization": self.quantization,
            "identity": self.identity,
            "identity_source": self.identity_source,
            "endpoint": self.endpoint,
            "fingerprint_inputs": {k: (v if v not in ("", None) else "unknown") for k, v in self.fingerprint_inputs().items()},
            "context_length": self.context_length,
            "max_output_tokens": self.max_output_tokens,
            "locality": self.locality,
            "locality_evidence": self.locality_evidence,
            "resource_pool": self.resource_pool,
            "capabilities": {k: v.as_dict() for k, v in self.capabilities.items()},
            "tags": self.tags,
            "catalogue_id": self.catalogue_id,
            "memory_gb_estimate": self.memory_gb_estimate,
            "memory_estimate_provenance": self.memory_estimate_provenance,
            "enabled": self.enabled,
            "state": {
                "configured": self.configured,
                "discovered": self.discovered,
                "available_on_disk": self.available_on_disk,
                "loaded": self.loaded,
                "healthy": self.healthy,
                "last_error": self.last_error,
            },
            "quality_prior": self.quality_prior,
            "quality_prior_provenance": self.quality_prior_provenance,
            "measurements": {k: asdict(v) for k, v in self.measurements.items()},
            "fingerprint": self.fingerprint,
            "intended_use_note": self.intended_use_note,
        }


class Registry:
    """In-memory registry of deployments keyed by id. Replaced atomically on refresh."""

    def __init__(self) -> None:
        self._deployments: dict[str, Deployment] = {}
        self.version: int = 0
        self.refreshed_at: float | None = None

    def replace(self, deployments: list[Deployment]) -> None:
        self._deployments = {d.id: d for d in deployments}
        self.version += 1
        self.refreshed_at = time.time()

    def get(self, dep_id: str) -> Deployment | None:
        return self._deployments.get(dep_id)

    def all(self) -> list[Deployment]:
        return list(self._deployments.values())

    def by_backend(self, backend_id: str) -> list[Deployment]:
        return [d for d in self._deployments.values() if d.backend_id == backend_id]

    def snapshot(self) -> list[dict[str, Any]]:
        return [d.summary() for d in self._deployments.values()]


def merge_capabilities(dep: Deployment, caps: dict[str, Tri], provenance: str, note: str = "") -> None:
    """Merge capability values respecting provenance priority: operator > probe > adapter > source_claim."""
    priority = {"none": 0, "source_claim": 1, "adapter": 2, "probe": 3, "operator": 4}
    for k, v in caps.items():
        if k not in CAPABILITY_KEYS:
            continue
        cur = dep.capabilities.get(k, CapValue())
        if priority.get(provenance, 0) >= priority.get(cur.provenance, 0):
            dep.set_cap(k, v, provenance, note)
