"""Ollama adapter.

Discovery uses Ollama's native API for truthful metadata (``/api/tags``,
``/api/show``, ``/api/ps``, ``/api/version``); inference is forwarded through
Ollama's OpenAI-compatible endpoints so tool semantics are preserved exactly
as Ollama implements them.

Documented limits of Ollama's OpenAI layer that this adapter enforces
(source: https://docs.ollama.com/api/openai-compatibility, checked 2026-10-11):
``tool_choice``, ``logit_bias``, ``n``, ``logprobs`` are not supported, and
image inputs must be base64 data URLs (remote image URLs are not fetched).
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from ..registry import CAPABILITY_KEYS, Deployment, merge_capabilities
from .base import AdapterError, BaseAdapter, UpstreamResponse

_CLOUD_NAME = re.compile(r"(:cloud$|-cloud$|-cloud:)")

# Ollama does not expose the server's default context length through the
# API for unloaded models. This is Ollama's documented default when neither
# the Modelfile nor OLLAMA_CONTEXT_LENGTH sets one (assumption; see docs/).
OLLAMA_ASSUMED_DEFAULT_NUM_CTX = 4096


class OllamaAdapter(BaseAdapter):
    type_name = "ollama"
    adapter_capabilities = {
        "tool_choice_required": "unsupported",  # OpenAI layer ignores tool_choice
        "json_object": "supported",
        "streaming": "supported",
    }

    async def health(self) -> tuple[bool, str]:
        try:
            v = await self._get_json("/api/version")
            self.runtime_version = str(v.get("version", ""))
            return True, f"ollama {self.runtime_version}"
        except AdapterError as e:
            return False, e.message

    async def loaded_models(self) -> dict[str, dict[str, Any]]:
        try:
            ps = await self._get_json("/api/ps")
        except AdapterError:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for m in ps.get("models", []) or []:
            name = m.get("name") or m.get("model")
            if name:
                out[name] = {
                    "size_vram": m.get("size_vram"),
                    "size": m.get("size"),
                    "expires_at": m.get("expires_at"),
                    "context_length": m.get("context_length"),
                }
        return out

    async def discover(self) -> list[Deployment]:
        tags = await self._get_json("/api/tags")
        ok, _ = await self.health()
        loaded = await self.loaded_models() if ok else {}
        deps: list[Deployment] = []
        for m in tags.get("models", []) or []:
            name = m.get("name") or m.get("model")
            if not name:
                continue
            details = m.get("details") or {}
            dep = Deployment(
                id=f"{self.cfg.id}/{name}",
                backend_id=self.cfg.id,
                backend_type="ollama",
                model=name,
                family=str(details.get("family", "")),
                parameter_size=str(details.get("parameter_size", "")),
                quantization=str(details.get("quantization_level", "")),
                digest=str(m.get("digest", "")),
                identity=str(m.get("digest", "")),
                identity_source="ollama digest" if m.get("digest") else "",
                runtime="ollama",
                runtime_version=self.runtime_version,
                endpoint=self.endpoint,
                resource_pool=self.cfg.resource_pool,
                discovered=True,
                available_on_disk=True,
                discovered_at=time.time(),
            )
            # Locality: a locally addressed Ollama can forward to Ollama Cloud.
            remote = bool(m.get("remote_model") or m.get("remote_host")) or bool(_CLOUD_NAME.search(name))
            if remote:
                dep.locality = "remote"
                dep.locality_evidence = (
                    f"ollama /api/tags reports remote_model/remote_host or cloud-suffixed name "
                    f"({m.get('remote_host') or 'cloud'}): inference does not run on this host"
                )
            else:
                dep.locality = self.cfg.locality
                dep.locality_evidence = (
                    f"operator declared backend locality={self.cfg.locality}; /api/tags shows no remote_model "
                    "(trust assumption: the gateway cannot inspect the runtime's internals)"
                )
            size = m.get("size")
            if isinstance(size, (int, float)) and size > 0:
                dep.memory_gb_estimate = round(size / 1e9 * 1.15, 2)
                dep.memory_estimate_provenance = (
                    "weights file size x1.15 runtime overhead; KV cache for the served context is NOT included"
                )
            await self._enrich(dep)
            if name in loaded:
                dep.loaded = True
                dep.loaded_observed_at = time.time()
                lc = loaded[name].get("context_length")
                if isinstance(lc, int) and lc > 0 and dep.raw_metadata.get("num_ctx_source") != "modelfile":
                    dep.context_length = lc
                    dep.raw_metadata["num_ctx_source"] = "ollama /api/ps (currently loaded)"
            dep.healthy = ok
            dep.health_checked_at = time.time()
            dep.compute_fingerprint()
            deps.append(dep)
        return deps

    async def _enrich(self, dep: Deployment) -> None:
        try:
            show = await self._client.post(self._url("/api/show"), json={"model": dep.model})
            info = show.json() if show.status_code == 200 else {}
        except Exception:
            info = {}
        caps_list = info.get("capabilities") or []
        model_info = info.get("model_info") or {}
        details = info.get("details") or {}
        arch = str(model_info.get("general.architecture", "")) or str(details.get("family", ""))
        dep.family = dep.family or arch
        if not dep.publisher:
            dep.publisher = str(model_info.get("general.basename", "")) or ""
        # Trained context length (model-card value) vs served context (num_ctx).
        trained_ctx = None
        for k, v in model_info.items():
            if k.endswith(".context_length") and isinstance(v, int):
                trained_ctx = v
                break
        dep.raw_metadata["trained_context_length"] = trained_ctx
        params_text = str(info.get("parameters", "") or "")
        m = re.search(r"num_ctx\s+(\d+)", params_text)
        if m:
            dep.context_length = int(m.group(1))
            dep.raw_metadata["num_ctx_source"] = "modelfile"
        else:
            dep.context_length = min(trained_ctx, OLLAMA_ASSUMED_DEFAULT_NUM_CTX) if trained_ctx else OLLAMA_ASSUMED_DEFAULT_NUM_CTX
            dep.raw_metadata["num_ctx_source"] = (
                f"assumed Ollama default ({OLLAMA_ASSUMED_DEFAULT_NUM_CTX}); set num_ctx in the Modelfile, "
                "OLLAMA_CONTEXT_LENGTH, or an operator override to change"
            )
        for k, v in model_info.items():
            if k.endswith(".embedding_length") and isinstance(v, int) and "embedding" in caps_list:
                dep.embedding_dimensions = v
        template = str(info.get("template", "") or "")
        dep.template_hash = hashlib.sha256(template.encode()).hexdigest()[:12] if template else ""
        dep.raw_metadata["license_excerpt"] = str(info.get("license", "") or "")[:200]
        # Role from capabilities.
        if "embedding" in caps_list and "completion" not in caps_list:
            dep.role = "embedding"
        else:
            dep.role = "generative"
        claims: dict[str, str] = {}
        claims["tools"] = "supported" if "tools" in caps_list else ("unsupported" if caps_list else "unknown")
        claims["vision"] = "supported" if ("vision" in caps_list or "image" in caps_list) else (
            "unsupported" if caps_list else "unknown"
        )
        claims["audio_in"] = "supported" if "audio" in caps_list else ("unsupported" if caps_list else "unknown")
        claims["thinking"] = "supported" if "thinking" in caps_list else ("unsupported" if caps_list else "unknown")
        merge_capabilities(dep, claims, "source_claim", note="ollama /api/show capabilities")  # type: ignore[arg-type]
        merge_capabilities(dep, dict(self.adapter_capabilities), "adapter", note="ollama OpenAI-compatible layer")  # type: ignore[arg-type]
        # Parallel tools / json_schema / continuation remain unknown until probed.
        for k in CAPABILITY_KEYS:
            dep.capabilities.setdefault(k, dep.capabilities.get(k))  # keep unknowns explicit
        dep.raw_metadata["capabilities_list"] = caps_list

    # --------------------------------------------------------------- #
    def unsupported_fields(self) -> frozenset[str]:
        return frozenset({"logit_bias", "logprobs", "top_logprobs", "n"})

    def translate_chat_body(self, body: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Typed, allow-listed translation. Returns (body, notes)."""
        out = dict(body)
        notes: list[str] = []
        tc = out.get("tool_choice")
        if tc is not None:
            if tc == "auto":
                out.pop("tool_choice")
                notes.append("tool_choice=auto is Ollama's default; field omitted")
            elif tc == "none":
                out.pop("tool_choice")
                if out.get("tools"):
                    out.pop("tools")
                    notes.append("tool_choice=none translated by omitting tool definitions (faithful semantics)")
            else:
                raise AdapterError(
                    "Ollama's OpenAI-compatible layer does not support tool_choice=required/named",
                    status=400,
                    kind="unsupported_semantics",
                )
        for k in ("user", "metadata", "store", "prompt_cache_key", "service_tier", "modelsaar"):
            if k in out:
                out.pop(k)
                notes.append(f"non-semantic field {k} not forwarded")
        return out, notes

    async def chat(self, dep: Deployment, body: dict[str, Any], stream: bool, timeout: float | None = None):
        fwd, _ = self.translate_chat_body(body)
        fwd["model"] = dep.model
        fwd["stream"] = stream
        if stream:
            so = dict(fwd.get("stream_options") or {})
            so.setdefault("include_usage", True)
            fwd["stream_options"] = so
            return await self._post_stream("/v1/chat/completions", fwd, timeout=timeout)
        return await self._post_json("/v1/chat/completions", fwd, timeout=timeout)

    async def embeddings(self, dep: Deployment, body: dict[str, Any]) -> UpstreamResponse:
        fwd = {k: v for k, v in body.items() if k in ("input", "encoding_format", "dimensions")}
        fwd["model"] = dep.model
        return await self._post_json("/v1/embeddings", fwd)
