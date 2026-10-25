"""Adapter base: a backend is contacted only at its configured host (allow-list)."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..config import BackendConfig
from ..registry import Deployment


class AdapterError(Exception):
    """Transport-level or backend-level failure. ``retryable`` is only True when
    the failure happened before any response bytes were received and the
    operation is safe to repeat."""

    def __init__(self, message: str, status: int = 502, retryable: bool = False, kind: str = "upstream_error"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.retryable = retryable
        self.kind = kind


@dataclass
class UpstreamResponse:
    status: int
    body: dict[str, Any]
    headers: dict[str, str]
    elapsed_ms: float


@dataclass
class UpstreamStream:
    """An open streaming response. ``aiter_bytes`` yields raw bytes; ``close``
    must be awaited exactly once."""

    status: int
    headers: dict[str, str]
    _response: httpx.Response
    _stream_ctx: Any
    started_at: float = field(default_factory=time.monotonic)

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        """Yield raw bytes. A read timeout while the stream is open is typed as an
        ``AdapterError(kind="timeout")`` so callers can hold occupancy as uncertain: the backend may
        still be generating after the gateway stops waiting."""
        try:
            async for chunk in self._response.aiter_bytes():
                yield chunk
        except httpx.ReadTimeout as e:
            raise AdapterError("read timeout while streaming", status=504, retryable=False, kind="timeout") from e
        except httpx.HTTPError as e:
            raise AdapterError(f"{e.__class__.__name__}: {e}", status=502, retryable=False, kind="transport") from e

    async def aread(self) -> bytes:
        return await self._response.aread()

    async def close(self) -> None:
        try:
            await self._stream_ctx.__aexit__(None, None, None)
        except Exception:  # pragma: no cover - best effort
            pass


class BaseAdapter:
    type_name = "base"
    # Capabilities the *adapter path* itself cannot provide regardless of model.
    adapter_capabilities: dict[str, str] = {}

    def __init__(self, cfg: BackendConfig, allowed_hosts: set[str]) -> None:
        self.cfg = cfg
        self.base_url = cfg.base_url
        parts = urlsplit(self.base_url)
        self.host = parts.netloc
        if self.host not in allowed_hosts and parts.hostname not in allowed_hosts:
            raise ValueError(f"backend {cfg.id}: host {self.host} is not in security.allowed_backend_hosts")
        api_key = cfg.api_key or (os.environ.get(cfg.api_key_env) if cfg.api_key_env else None)
        headers = {"User-Agent": "modelsaar/0.1"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(cfg.timeout_s, connect=cfg.connect_timeout_s),
            follow_redirects=False,  # never follow redirects to other hosts
            limits=httpx.Limits(max_connections=cfg.max_concurrent + 4),
        )
        self.runtime_version: str = ""
        # Execution endpoint identity used in deployment fingerprints (no credentials).
        self.endpoint = f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"

    async def aclose(self) -> None:
        await self._client.aclose()

    # ----------------------------------------------------------------- #
    def _url(self, path: str) -> str:
        # Defensive: a path must be relative; it can never change the host.
        if "://" in path or path.startswith("//"):
            raise AdapterError("adapter paths must be relative", status=500, kind="internal")
        return path

    async def _get_json(self, path: str, **kw: Any) -> dict[str, Any]:
        try:
            r = await self._client.get(self._url(path), **kw)
        except httpx.HTTPError as e:
            raise AdapterError(f"{self.cfg.id}: {e.__class__.__name__}: {e}", retryable=True, kind="connect") from e
        if r.status_code >= 400:
            raise AdapterError(f"{self.cfg.id}: GET {path} -> {r.status_code}", status=502)
        try:
            return r.json()
        except ValueError as e:
            raise AdapterError(f"{self.cfg.id}: non-JSON response from {path}", status=502) from e

    def _deadline(self, timeout: float | None) -> httpx.Timeout:
        """The effective deadline for one upstream call: the backend's configured ``timeout_s`` or the
        caller's (server) deadline, whichever is tighter. A caller passing ``None`` gets the backend
        deadline, never "no timeout" (an explicit ``None`` would disable the client timeout in httpx)."""
        read = self.cfg.timeout_s if timeout is None else min(float(timeout), self.cfg.timeout_s)
        return httpx.Timeout(read, connect=min(self.cfg.connect_timeout_s, read))

    async def _post_json(self, path: str, body: dict[str, Any], timeout: float | None = None) -> UpstreamResponse:
        t0 = time.monotonic()
        try:
            r = await self._client.post(self._url(path), json=body, timeout=self._deadline(timeout))
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise AdapterError(f"{self.cfg.id}: connection failed: {e}", retryable=True, kind="connect") from e
        except httpx.ReadTimeout as e:
            raise AdapterError(f"{self.cfg.id}: read timeout", status=504, retryable=False, kind="timeout") from e
        except httpx.HTTPError as e:
            raise AdapterError(f"{self.cfg.id}: {e.__class__.__name__}: {e}", retryable=False, kind="transport") from e
        elapsed = (time.monotonic() - t0) * 1000
        try:
            data = r.json()
        except ValueError:
            data = {"error": {"message": r.text[:500], "type": "upstream_non_json"}}
        return UpstreamResponse(status=r.status_code, body=data, headers=dict(r.headers), elapsed_ms=elapsed)

    async def _post_stream(self, path: str, body: dict[str, Any], timeout: float | None = None) -> UpstreamStream:
        req = self._client.build_request("POST", self._url(path), json=body, timeout=self._deadline(timeout))
        try:
            resp = await self._client.send(req, stream=True)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise AdapterError(f"{self.cfg.id}: connection failed: {e}", retryable=True, kind="connect") from e
        except httpx.ReadTimeout as e:
            raise AdapterError(f"{self.cfg.id}: read timeout", status=504, retryable=False, kind="timeout") from e
        except httpx.HTTPError as e:
            raise AdapterError(f"{self.cfg.id}: {e.__class__.__name__}: {e}", retryable=False, kind="transport") from e

        class _Ctx:
            async def __aexit__(self_inner, *a: object) -> None:
                await resp.aclose()

        return UpstreamStream(status=resp.status_code, headers=dict(resp.headers), _response=resp, _stream_ctx=_Ctx())

    # ----------------------------------------------------------------- #
    # Interface
    async def health(self) -> tuple[bool, str]:
        raise NotImplementedError

    async def discover(self) -> list[Deployment]:
        raise NotImplementedError

    # True when ``loaded_models`` is a real observation of the runtime (e.g. Ollama /api/ps). Pools
    # keep assumed residency for deployments of a backend that cannot report it.
    reports_residency: bool = False
    # Outcome of the most recent residency query: True = observed, False = the query failed (the
    # runtime is up but did not answer /api/ps), None = never asked / not a reporting runtime.
    # A failed query is NOT an empty resident set; callers keep known/assumed occupancy.
    last_residency_observation_ok: bool | None = None

    async def loaded_models(self) -> dict[str, dict[str, Any]] | None:
        """Return {model_name: info} for models currently resident in memory when the runtime exposes
        it, ``{}`` when it does not report residency, and ``None`` when the query failed."""
        return {}

    async def chat(self, dep: Deployment, body: dict[str, Any], stream: bool, timeout: float | None = None):
        raise NotImplementedError

    async def embeddings(self, dep: Deployment, body: dict[str, Any], timeout: float | None = None) -> UpstreamResponse:
        raise NotImplementedError

    async def decide(
        self, dep: Deployment, state: str, questions: dict[str, Any], timeout: float | None = None
    ) -> UpstreamResponse:
        """Ask a decision model (``role == "decision"``) one or more typed questions about ``state`` and
        return its native answer (per-option probabilities, no generated text). Backends without a
        decision endpoint raise ``AdapterError(kind="unsupported")`` so callers fail closed."""
        raise AdapterError(
            f"{self.cfg.id}: backend type {getattr(self.cfg, 'type', 'backend')!r} has no decision-model endpoint",
            status=501,
            kind="unsupported",
        )

    async def tokenize(self, dep: Deployment, text: str) -> int | None:
        """Exact token count if the runtime supports it; None otherwise."""
        return None

    def forwardable_fields(self) -> frozenset[str]:
        from ..protocol.openai import FORWARDABLE_CHAT_FIELDS

        return FORWARDABLE_CHAT_FIELDS

    def unsupported_fields(self) -> frozenset[str]:
        """Fields that this backend path cannot honour; the router rejects requests using them."""
        return frozenset()

    def cache_prompt_policy(self, value: bool) -> tuple[bool, str]:
        """Disposition of the client-compatibility hint ``cache_prompt`` for this backend path.

        Returns (accepted, note). No shipped backend path offers per-request cache control through the
        OpenAI-compatible surface the gateway uses: the backend manages its own prompt cache. ``true`` is
        therefore an advisory no-op (nothing is forwarded, no cache hit is promised); ``false`` asks for a
        guaranteed bypass that cannot be honoured, so it is refused with a precise explanation rather than
        silently accepted."""
        kind = getattr(self.cfg, "type", "backend")
        if value:
            return True, f"advisory; prompt caching is managed by the {kind} backend itself (not forwarded, no cache hit promised)"
        return False, (
            f"cache_prompt=false asks for a guaranteed prompt-cache bypass, which the {kind} backend path cannot honour "
            "per request (its cache is backend-managed); omit the field or send cache_prompt=true"
        )
