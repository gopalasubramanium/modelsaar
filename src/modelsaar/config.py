"""Versioned configuration: one YAML file, typed validation, immutable snapshots.

The configuration is loaded into an immutable ``Config`` object; a request
captures the router/config snapshot at entry. Configuration changes take effect
by restarting ``modelsaar serve`` (there is no hot reload in 0.1).
"""

from __future__ import annotations

import os
import secrets
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import CONFIG_VERSION

Tri = Literal["supported", "unsupported", "unknown"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- #
# Server / security
# --------------------------------------------------------------------------- #
class ServerConfig(StrictModel):
    host: str = "127.0.0.1"
    port: int = 8484
    # Paths are relative to the config directory unless absolute.
    api_keys_file: str = "keys/api_keys"
    admin_key_file: str = "keys/admin_key"
    state_db: str = "state/modelsaar.db"
    request_timeout_s: float = 600.0
    max_request_bytes: int = 32 * 1024 * 1024
    # What the `model` field of responses carries: the requested alias (safe
    # for clients that validate model ids) or the selected deployment id.
    # The selected deployment is always available in X-ModelSaar-Deployment.
    response_model_field: Literal["requested", "deployment"] = "requested"
    # Background refresh intervals.
    residency_refresh_s: float = 15.0
    discovery_refresh_s: float = 120.0

    @field_validator("port")
    @classmethod
    def _port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("port must be 1..65535")
        return v


class SecurityConfig(StrictModel):
    # LAN exposure is opt-in and must be paired with a non-loopback bind.
    allow_lan: bool = False
    # local_only: only deployments with locality=local are eligible.
    locality_mode: Literal["local_only", "allow_remote"] = "local_only"
    # Backends may only be contacted at these hosts (exact host or host:port).
    # Populated from backend base_urls at load time; extra entries allowed.
    allowed_backend_hosts: tuple[str, ...] = ()
    # Media handling: the gateway never fetches remote image URLs by default.
    fetch_remote_media: bool = False
    # Never log prompts/responses/tool args/reasoning by default.
    log_prompts: bool = False
    telemetry_opt_in: bool = False


# --------------------------------------------------------------------------- #
# Backends / pools / deployments
# --------------------------------------------------------------------------- #
class ResourcePool(StrictModel):
    id: str
    kind: Literal["unified", "gpu", "cpu", "remote"] = "unified"
    memory_gb: float | None = None
    max_concurrent: int = 1
    max_queue: int = 16
    queue_timeout_s: float = 30.0
    # Memory headroom kept free on the pool. A dispatch is admitted only when the resident
    # set (distinct loaded deployments, including the classifier) plus the candidate's
    # memory estimate plus this margin fits in memory_gb.
    memory_margin_gb: float = 0.0
    # What to do with a deployment whose memory estimate is unknown when memory_gb is set:
    # "allow" admits it (counted as 0, labelled unknown in the decision); "reject" treats
    # it as not fitting — and applies to every counted member (resident, reserved or assumed
    # resident), not only the candidate: one unknown model makes the budget unverifiable.
    unknown_memory_policy: Literal["allow", "reject"] = "allow"
    # After a dispatch completes its request slot is released but the weights stay loaded. The
    # pool keeps counting them ("assumed resident") until the runtime's residency observation
    # (Ollama /api/ps on refresh) reconciles the registry. Runtimes that cannot report residency
    # keep the assumption indefinitely unless this TTL (seconds) is set; this is the conservative
    # choice because the gateway cannot see when such a runtime evicts a model.
    assumed_residency_ttl_s: float | None = None


class BackendConfig(StrictModel):
    id: str
    type: Literal["ollama", "openai_compatible"]
    base_url: str
    api_key_env: str | None = None
    api_key: str | None = None
    # Declared execution locality. "local" is a trust declaration that is
    # cross-checked where the adapter has evidence (e.g. Ollama remote_model).
    locality: Literal["local", "remote"] = "local"
    resource_pool: str | None = None
    discover: bool = True
    # Models to register when discovery is unavailable or incomplete.
    models: tuple[DeclaredModel, ...] = ()
    timeout_s: float = 600.0
    connect_timeout_s: float = 5.0
    # Per-backend concurrency ceiling (in addition to pool limits).
    max_concurrent: int = 4
    circuit_failure_threshold: int = 3
    circuit_cooldown_s: float = 30.0

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v.rstrip("/")


class Capabilities(StrictModel):
    """Three-state capability declarations (operator overrides)."""

    tools: Tri = "unknown"
    tool_choice_required: Tri = "unknown"
    parallel_tools: Tri = "unknown"
    json_schema: Tri = "unknown"
    json_object: Tri = "unknown"
    streaming: Tri = "unknown"
    vision: Tri = "unknown"
    audio_in: Tri = "unknown"
    thinking: Tri = "unknown"
    continuation: Tri = "unknown"


class DeclaredModel(StrictModel):
    name: str
    role: Literal["generative", "embedding", "decision", "ocr", "rerank", "guardrail"] = "generative"
    context_length: int | None = None
    max_output_tokens: int | None = None
    capabilities: Capabilities = Capabilities()
    tags: tuple[str, ...] = ()
    enabled: bool = True
    # Catalogue entry id for prior quality hints (optional).
    catalogue_id: str | None = None
    memory_gb_estimate: float | None = None
    embedding_dimensions: int | None = None
    # Operator-declared model identity (e.g. a weights digest or an exact revision id) for
    # backends that expose none. Used to prove that two embedding deployments are the same
    # model; a bare name match never is.
    identity: str | None = None


class DeploymentOverride(StrictModel):
    """Operator override applied after discovery, keyed by backend + model name."""

    backend: str
    model: str
    enabled: bool | None = None
    role: Literal["generative", "embedding", "decision", "ocr", "rerank", "guardrail"] | None = None
    context_length: int | None = None
    max_output_tokens: int | None = None
    capabilities: Capabilities | None = None
    tags: tuple[str, ...] | None = None
    catalogue_id: str | None = None
    memory_gb_estimate: float | None = None
    quality_prior: dict[str, float] | None = None  # task -> 0..1, labelled "operator"
    intended_use_note: str | None = None


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
class ProfileWeights(StrictModel):
    quality: float = 1.0
    latency: float = 0.2
    residency: float = 0.15
    overhead: float = 0.05


class RoutingProfiles(StrictModel):
    quality: ProfileWeights = ProfileWeights(quality=1.0, latency=0.15, residency=0.1, overhead=0.05)
    balanced: ProfileWeights = ProfileWeights(quality=1.0, latency=0.45, residency=0.3, overhead=0.1)
    fast: ProfileWeights = ProfileWeights(quality=0.6, latency=1.0, residency=0.6, overhead=0.2)


class ClassifierConfig(StrictModel):
    enabled: bool = False
    backend: str | None = None
    model: str | None = None
    timeout_s: float = 2.0
    max_input_chars: int = 1500
    # Only consult the classifier when deterministic classification is unsure.
    only_when_ambiguous: bool = True
    max_output_tokens: int = 64
    # The classifier receives an excerpt of the user's message. It must be a local deployment
    # unless the operator explicitly allows a remote one here AND security.locality_mode permits it.
    allow_remote: bool = False


class TokenEstimateConfig(StrictModel):
    chars_per_token: float = 3.0  # conservative (most tokenizers ~3.5-4.5 chars/token for English)
    per_message_overhead: int = 8
    image_tokens: int = 1200
    tool_definition_overhead: int = 24
    default_max_output: int = 1024
    reasoning_budget: int = 2048
    safety_margin: float = 0.05
    # Total wall-clock budget for exact token counting across all candidate deployments.
    exact_count_deadline_s: float = 1.5


class RoutingConfig(StrictModel):
    default_profile: Literal["quality", "balanced", "fast"] = "quality"
    profiles: RoutingProfiles = RoutingProfiles()
    # Penalty subtracted from a non-resident deployment's score (hysteresis).
    switching_penalty: float = 0.08
    classifier: ClassifierConfig = ClassifierConfig()
    token_estimate: TokenEstimateConfig = TokenEstimateConfig()
    # Allow one bounded failover before response commitment on connection errors.
    pre_commit_failover: bool = True
    max_failover_attempts: int = 1
    # Conservative prior for deployments with no evidence (labelled uncalibrated).
    uncalibrated_prior: float = 0.5


class AliasConfig(StrictModel):
    profile: Literal["quality", "balanced", "fast"] = "quality"
    require_tags: tuple[str, ...] = ()
    require_vision: bool = False
    # Restrict to these deployment ids (optional).
    deployments: tuple[str, ...] = ()
    description: str = ""


class AffinityConfig(StrictModel):
    mode: Literal["session", "stateless"] = "session"
    ttl_s: float = 3600.0
    max_sessions: int = 10000
    session_headers: tuple[str, ...] = ("X-ModelSaar-Session", "X-OpenWebUI-Chat-Id")
    body_fields: tuple[str, ...] = ("prompt_cache_key",)
    # Keep the same deployment while a tool round trip is outstanding even
    # without a session id (uses the tool_call ids as the continuity key).
    tool_round_trip_affinity: bool = True


class EmbeddingContract(StrictModel):
    alias: str
    deployments: tuple[str, ...]  # all must be the same model identity; validated at refresh
    dimensions: int | None = None
    normalized: bool = True
    # Reserved: the gateway never rewrites embedding inputs, so any non-empty prefix would be
    # a silent contract change. Rejected at load.
    query_prefix: str = ""
    document_prefix: str = ""
    # Optional expected identity (digest / revision) every member must match.
    identity: str | None = None
    note: str = ""

    @model_validator(mode="after")
    def _check(self) -> EmbeddingContract:
        if not self.deployments:
            raise ValueError(f"embedding contract {self.alias!r} lists no deployments")
        if self.query_prefix or self.document_prefix:
            raise ValueError(
                f"embedding contract {self.alias!r}: query_prefix/document_prefix are not applied by"
                " the gateway (inputs are forwarded verbatim); remove them"
            )
        return self


class ObservabilityConfig(StrictModel):
    decision_log: bool = True
    retention_days: int = 7
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class AdmissionConfig(StrictModel):
    # Hold an "uncertain" reservation after a disconnect until the backend is
    # confirmed idle or this many seconds elapse.
    uncertain_hold_s: float = 20.0
    max_queue: int = 32
    queue_timeout_s: float = 30.0


class Config(StrictModel):
    version: int = CONFIG_VERSION
    server: ServerConfig = ServerConfig()
    security: SecurityConfig = SecurityConfig()
    resource_pools: tuple[ResourcePool, ...] = ()
    backends: tuple[BackendConfig, ...] = ()
    deployments: tuple[DeploymentOverride, ...] = ()
    aliases: dict[str, AliasConfig] = Field(
        default_factory=lambda: {
            "auto": AliasConfig(profile="quality", description="Best expected quality within limits"),
            "auto-quality": AliasConfig(profile="quality"),
            "auto-balanced": AliasConfig(profile="balanced"),
            "auto-fast": AliasConfig(profile="fast"),
            "auto-code": AliasConfig(profile="quality", require_tags=("code",)),
            "auto-vision": AliasConfig(profile="quality", require_vision=True),
        }
    )
    routing: RoutingConfig = RoutingConfig()
    affinity: AffinityConfig = AffinityConfig()
    embeddings: tuple[EmbeddingContract, ...] = ()
    admission: AdmissionConfig = AdmissionConfig()
    observability: ObservabilityConfig = ObservabilityConfig()

    # Set by the loader; not part of the file.
    config_path: str | None = Field(default=None, exclude=True)
    config_hash: str = Field(default="", exclude=True)

    @model_validator(mode="after")
    def _check(self) -> Config:
        if self.version != CONFIG_VERSION:
            raise ValueError(
                f"config version {self.version} is not supported by this build (expected {CONFIG_VERSION}); "
                "run `modelsaar config migrate`"
            )
        ids = [b.id for b in self.backends]
        if len(ids) != len(set(ids)):
            raise ValueError("backend ids must be unique")
        pools = {p.id for p in self.resource_pools}
        for b in self.backends:
            if b.resource_pool and b.resource_pool not in pools:
                raise ValueError(f"backend {b.id} references unknown resource_pool {b.resource_pool}")
        if self.security.allow_lan is False and self.server.host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(
                "server.host is not loopback but security.allow_lan is false; "
                "set security.allow_lan: true explicitly to expose the gateway on the LAN"
            )
        for a in self.aliases:
            if not a.startswith("auto"):
                raise ValueError(f"alias names must start with 'auto' (got {a!r})")
        cl = self.routing.classifier
        if cl.enabled and (not cl.backend or not cl.model):
            raise ValueError("routing.classifier.enabled requires backend and model")
        return self

    # Resolve a path relative to the config directory.
    def resolve(self, p: str) -> Path:
        path = Path(p).expanduser()
        if path.is_absolute():
            return path
        base = Path(self.config_path).parent if self.config_path else Path.cwd()
        return base / path

    @property
    def config_dir(self) -> Path:
        return Path(self.config_path).parent if self.config_path else Path.cwd()


def default_config_path() -> Path:
    env = os.environ.get("MODELSAAR_CONFIG")
    if env:
        return Path(env).expanduser()
    home = os.environ.get("MODELSAAR_HOME")
    base = Path(home).expanduser() if home else Path.home() / ".modelsaar"
    return base / "config.yaml"


def load_config(path: Path | None = None) -> Config:
    path = path or default_config_path()
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")
    cfg = Config.model_validate(data)
    import hashlib

    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return cfg.model_copy(update={"config_path": str(path), "config_hash": h})


def config_to_yaml(cfg: Config) -> str:
    data = cfg.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _write_private_atomic(path: Path, text: str) -> None:
    """Create with mode 0600 from the first byte (no world-readable window), fsync, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def write_config_atomic(cfg: Config, path: Path) -> None:
    _write_private_atomic(path, config_to_yaml(cfg))


def generate_key(prefix: str = "msk") -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def read_keys(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]


def write_key_file(path: Path, keys: list[str]) -> None:
    _write_private_atomic(path, "\n".join(keys) + "\n")


class ExampleKind(str, Enum):
    ollama = "ollama"


def example_config(backend_url: str = "http://127.0.0.1:11434", backend_type: str = "ollama") -> Config:
    return Config(
        resource_pools=(ResourcePool(id="local-machine", kind="unified", max_concurrent=1),),
        backends=(
            BackendConfig(
                id="ollama",
                type=backend_type,  # type: ignore[arg-type]
                base_url=backend_url,
                resource_pool="local-machine",
            ),
        ),
    )


def dump_any(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    return obj
