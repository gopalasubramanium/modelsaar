"""Generic OpenAI-compatible adapter (vLLM, llama.cpp server, LM Studio, SGLang, ...).

Discovery via ``GET /models`` yields names only; capabilities stay ``unknown``
until declared by the operator (``backends[].models``) or verified by probes.
vLLM's ``/tokenize`` endpoint is used for tokenizer-based text counts when present (template overhead stays estimated).
"""

from __future__ import annotations

import time
from typing import Any

from ..config import DeclaredModel
from ..registry import Deployment, merge_capabilities
from .base import AdapterError, BaseAdapter, UpstreamResponse


class OpenAICompatAdapter(BaseAdapter):
    type_name = "openai_compatible"
    adapter_capabilities = {"streaming": "supported"}

    def __init__(self, cfg, allowed_hosts):  # type: ignore[no-untyped-def]
        super().__init__(cfg, allowed_hosts)
        self._tokenize_supported: bool | None = None

    async def health(self) -> tuple[bool, str]:
        try:
            await self._get_json("/models")
            return True, "openai-compatible endpoint reachable"
        except AdapterError as e:
            return False, e.message

    async def discover(self) -> list[Deployment]:
        declared: dict[str, DeclaredModel] = {m.name: m for m in self.cfg.models}
        names: list[str] = []
        ok, _ = await self.health()
        if self.cfg.discover and ok:
            try:
                data = await self._get_json("/models")
                for m in data.get("data", []) or []:
                    if isinstance(m, dict) and m.get("id"):
                        names.append(str(m["id"]))
            except AdapterError:
                pass
        for n in declared:
            if n not in names:
                names.append(n)
        deps: list[Deployment] = []
        for name in names:
            dep = Deployment(
                id=f"{self.cfg.id}/{name}",
                backend_id=self.cfg.id,
                backend_type="openai_compatible",
                model=name,
                runtime="openai_compatible",
                endpoint=self.endpoint,
                resource_pool=self.cfg.resource_pool,
                discovered=name in names,
                available_on_disk=ok,
                discovered_at=time.time(),
                healthy=ok,
                health_checked_at=time.time(),
                locality=self.cfg.locality,
                locality_evidence=(
                    f"operator declared backend locality={self.cfg.locality} (trust assumption: a generic endpoint "
                    "exposes no execution-location evidence)"
                ),
            )
            merge_capabilities(dep, dict(self.adapter_capabilities), "adapter")  # type: ignore[arg-type]
            d = declared.get(name)
            if d:
                dep.configured = True
                dep.role = d.role
                dep.context_length = d.context_length
                dep.max_output_tokens = d.max_output_tokens
                dep.tags = list(d.tags)
                dep.enabled = d.enabled
                dep.catalogue_id = d.catalogue_id
                dep.memory_gb_estimate = d.memory_gb_estimate
                dep.embedding_dimensions = d.embedding_dimensions
                if d.identity:
                    dep.identity = d.identity
                    dep.identity_source = "operator declaration"
                if d.memory_gb_estimate:
                    dep.memory_estimate_provenance = "operator declaration"
                merge_capabilities(
                    dep,
                    {k: v for k, v in d.capabilities.model_dump().items() if v != "unknown"},
                    "operator",
                    note="backends[].models declaration",
                )
            dep.compute_fingerprint()
            deps.append(dep)
        return deps

    async def tokenize(self, dep: Deployment, text: str) -> int | None:
        if self._tokenize_supported is False:
            return None
        try:
            r = await self._client.post(self._url("/tokenize"), json={"model": dep.model, "prompt": text}, timeout=5.0)
        except Exception:
            self._tokenize_supported = False
            return None
        if r.status_code != 200:
            self._tokenize_supported = False
            return None
        try:
            data = r.json()
        except ValueError:
            self._tokenize_supported = False
            return None
        self._tokenize_supported = True
        if isinstance(data.get("count"), int):
            return data["count"]
        toks = data.get("tokens")
        return len(toks) if isinstance(toks, list) else None

    def translate_chat_body(self, body: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        out = dict(body)
        notes: list[str] = []
        for k in ("modelsaar",):
            out.pop(k, None)
        # llama.cpp-style hints are consumed by the gateway; a private address does not mean the server
        # implements llama.cpp's extensions, so they are not forwarded to any OpenAI-compatible backend.
        for k in ("session_id", "cache_prompt"):
            if k in out:
                out.pop(k)
                notes.append(f"client-compatibility field {k} consumed by the gateway; not forwarded")
        return out, notes

    async def chat(self, dep: Deployment, body: dict[str, Any], stream: bool, timeout: float | None = None):
        fwd, _ = self.translate_chat_body(body)
        fwd["model"] = dep.model
        fwd["stream"] = stream
        if stream:
            so = dict(fwd.get("stream_options") or {})
            so.setdefault("include_usage", True)
            fwd["stream_options"] = so
            return await self._post_stream("/chat/completions", fwd, timeout=timeout)
        return await self._post_json("/chat/completions", fwd, timeout=timeout)

    async def embeddings(self, dep: Deployment, body: dict[str, Any], timeout: float | None = None) -> UpstreamResponse:
        fwd = {k: v for k, v in body.items() if k in ("input", "encoding_format", "dimensions", "user")}
        fwd["model"] = dep.model
        return await self._post_json("/embeddings", fwd, timeout=timeout)
