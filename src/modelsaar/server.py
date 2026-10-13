"""HTTP gateway (Starlette). Implements the OpenAI-compatible surface, the
protected inspection API and the response-commitment rules:

* Bounded failover is allowed only *before* any response header/byte is
  committed, only on connection-level failures or upstream 5xx with no body
  streamed, and only to another deployment that passed the same hard filters.
* After commitment, failures terminate the stream with an SSE error frame;
  the gateway never switches deployments or splices a replacement answer.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from . import __version__
from .adapters.base import AdapterError, UpstreamResponse, UpstreamStream
from .config import Config
from .protocol.openai import (
    ProtocolError,
    error_body,
    parse_chat_request,
    parse_embeddings_request,
    sse_error_frame,
)
from .protocol.sse import SSEParser, StreamObserver, rewrite_model_field
from .routing.admission import AdmissionRejected
from .routing.decision import Decision
from .routing.router import NoEligibleDeployment, Router
from .security import Auth, redact
from .store import Store

log = logging.getLogger("modelsaar.server")


class GatewayState:
    def __init__(self, cfg: Config, router: Router, auth: Auth, store: Store | None) -> None:
        self.cfg = cfg
        self.router = router
        self.auth = auth
        self.store = store
        self.started_at = time.time()
        self.ready = False
        self.requests_total = 0
        self.requests_failed = 0
        self._bg: list[asyncio.Task] = []
        self.loop: asyncio.AbstractEventLoop | None = None


def _json(status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=headers)


def _no_eligible_response(dec: Decision) -> JSONResponse:
    status = 404 if dec.outcome == "unknown_model" else 503 if dec.outcome == "admission_rejected" else 422
    body = error_body(
        "; ".join(dec.reasons) or "no eligible deployment",
        code="no_eligible_deployment" if dec.outcome != "unknown_model" else "model_not_found",
        param="model",
        modelsaar={
            "request_id": dec.request_id,
            "blockers": dec.exclusions,
            "remedies": dec.remedies,
            "requirements": dec.requirements,
        },
    )
    headers = {"X-ModelSaar-Request-Id": dec.request_id}
    if status == 503:
        headers["Retry-After"] = "2"
        body["error"]["code"] = "admission_rejected"
    return _json(status, body, headers)


async def _read_json(request: Request, limit: int) -> dict[str, Any]:
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > limit:
        raise ProtocolError("request body too large", status=413)
    raw = await request.body()
    if len(raw) > limit:
        raise ProtocolError("request body too large", status=413)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"invalid JSON body: {e.msg}") from e
    if not isinstance(data, dict):
        raise ProtocolError("request body must be a JSON object")
    return data


def _require_caller(state: GatewayState, request: Request) -> str:
    caller = state.auth.caller(dict(request.headers))
    if not caller:
        raise ProtocolError("missing or invalid API key", status=401, code="authentication_error")
    return caller


def _require_admin(state: GatewayState, request: Request) -> None:
    if not state.auth.is_admin(dict(request.headers)):
        raise ProtocolError("admin key required", status=403, code="permission_error")


# --------------------------------------------------------------------------- #
# Chat completions
# --------------------------------------------------------------------------- #
async def chat_completions(request: Request) -> Response:
    state: GatewayState = request.app.state.gw
    router = state.router  # snapshot for this request
    state.requests_total += 1
    try:
        caller = _require_caller(state, request)
        body = await _read_json(request, state.cfg.server.max_request_bytes)
        req = parse_chat_request(body)
    except ProtocolError as e:
        state.requests_failed += 1
        return _json(e.status, e.body())

    try:
        dec = await router.route_chat(body, dict(request.headers), caller)
    except NoEligibleDeployment as e:
        state.requests_failed += 1
        return _no_eligible_response(e.decision)

    base_headers = {"X-ModelSaar-Request-Id": dec.request_id}
    attempts = 0
    max_attempts = 1 + (state.cfg.routing.max_failover_attempts if state.cfg.routing.pre_commit_failover else 0)
    tried: list[str] = []
    candidate_ids = [c["deployment"] for c in dec.candidates]

    while True:
        dep_id = dec.chosen
        dep = router.registry.get(dep_id)
        if dep is None:
            state.requests_failed += 1
            dec.outcome = "internal_error"
            router.record(dec)
            return _json(500, error_body("selected deployment vanished", code="internal_error"), base_headers)
        adapter = router.adapters[dep.backend_id]
        attempts += 1
        tried.append(dep_id)
        # Client-compatibility hint `cache_prompt`: decided per backend path BEFORE anything is sent. `true` is
        # advisory (recorded, not forwarded); `false` is refused unless this path can guarantee a cache bypass.
        if req.cache_prompt is not None:
            accepted, note = adapter.cache_prompt_policy(req.cache_prompt)
            dec.compat["cache_prompt"] = f"{dep_id}: {note}"
            if not accepted:
                state.requests_failed += 1
                dec.outcome = "unsupported_capability"
                dec.outcome_detail = note
                router.record(dec)
                return _json(
                    400,
                    error_body(note, code="unsupported_capability", param="cache_prompt", modelsaar={"request_id": dec.request_id, "deployment": dep_id}),
                    base_headers,
                )
        # Attribution follows the deployment actually dispatched to (per attempt, not once).
        response_model = dec.requested_model if state.cfg.server.response_model_field == "requested" else dep_id
        try:
            reservation = await router.admission.acquire(dep, timeout=None)
        except AdmissionRejected as e:
            state.requests_failed += 1
            dec.outcome = "admission_rejected"
            dec.outcome_detail = e.message
            router.record(dec)
            return _json(
                e.status,
                error_body(e.message, code="admission_rejected", modelsaar={"request_id": dec.request_id, "deployment": dep_id}),
                {**base_headers, "Retry-After": "2"},
            )
        headers = {**base_headers, "X-ModelSaar-Deployment": dep_id, "X-ModelSaar-Profile": dec.profile}
        circuit = router.admission.circuit(dep.backend_id)
        try:
            # Record what the adapter path changes (typed, allow-listed translations only).
            translate = getattr(adapter, "translate_chat_body", None)
            if translate:
                _, notes = translate(body)
                if notes:
                    dec.translation_notes = [f"{dep_id}: {n}" for n in notes]
            if req.stream:
                upstream: UpstreamStream = await adapter.chat(dep, body, stream=True, timeout=state.cfg.server.request_timeout_s)
                if upstream.status >= 500 or upstream.status in (502, 503, 504):
                    # Nothing has been committed to the client yet: safe, bounded failover.
                    text = (await upstream.aread())[:300]
                    await upstream.close()
                    raise AdapterError(f"upstream {upstream.status}: {redact(text.decode('utf-8', 'replace'))}", status=502, retryable=True)
                if upstream.status != 200:
                    text = await upstream.aread()
                    await upstream.close()
                    await reservation.release()
                    dec.outcome = "upstream_error"
                    dec.outcome_detail = f"upstream {upstream.status}"
                    router.record(dec)
                    try:
                        payload = json.loads(text)
                    except Exception:
                        payload = error_body(redact(text.decode("utf-8", "replace")[:500]), code="upstream_error")
                    return _json(upstream.status, payload, headers)
                ctype = (upstream.headers.get("content-type") or "").lower()
                if "text/event-stream" not in ctype:
                    # A 200 that is not an SSE stream (proxy HTML page, JSON error with 200) is not a
                    # completion. Nothing has been sent to the client: typed error, no pin, no success.
                    text = (await upstream.aread())[:300]
                    await upstream.close()
                    raise AdapterError(
                        f"upstream returned 200 with content-type {ctype or 'missing'!r} instead of text/event-stream",
                        status=502,
                        retryable=False,
                        kind="bad_envelope",
                    )
                # Circuit success and session pinning are recorded once the stream completes (see _relay).
                return StreamingResponse(
                    _relay(state, router, dec, dep_id, upstream, reservation, response_model, caller),
                    status_code=200,
                    media_type="text/event-stream",
                    headers={**headers, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            else:
                resp: UpstreamResponse = await adapter.chat(dep, body, stream=False, timeout=state.cfg.server.request_timeout_s)
                await reservation.release()
                if resp.status >= 500:
                    raise AdapterError(f"upstream {resp.status}", status=502, retryable=True)
                if resp.status != 200:
                    dec.outcome = "upstream_error"
                    dec.outcome_detail = f"upstream {resp.status}"
                    router.record(dec)
                    return _json(resp.status, resp.body, headers)
                why = _envelope_problem(resp.body)
                if why:
                    raise AdapterError(f"upstream returned 200 but {why}", status=502, retryable=False, kind="bad_envelope")
                if circuit:
                    circuit.record_success()
                out = dict(resp.body)
                out["model"] = response_model
                router.pin_session(dec, caller, dep_id)
                _remember_tool_calls(router, caller, dep_id, out)
                dec.outcome = "ok"
                dec.outcome_detail = f"{resp.elapsed_ms:.0f}ms"
                router.record(dec)
                return _json(200, out, headers)
        except Exception as e:  # noqa: BLE001 - every failure path must release the slot
            if isinstance(e, AdapterError) and e.kind == "timeout":
                # The backend did not answer in time but may still be generating: hold the slot.
                await reservation.mark_uncertain()
            elif isinstance(e, AdapterError) and e.kind == "connect":
                # Proven pre-dispatch failure: nothing reached the runtime, so no weights were loaded.
                await reservation.release(submitted=False)
            else:
                await reservation.release()
            if not isinstance(e, AdapterError):
                state.requests_failed += 1
                dec.outcome = "internal_error"
                dec.outcome_detail = redact(f"{e.__class__.__name__}: {e}")[:200]
                router.record(dec)
                log.exception("unexpected error dispatching to %s", dep_id)
                return _json(500, error_body("internal gateway error", code="internal_error", modelsaar={"request_id": dec.request_id}), headers)
            if circuit:
                circuit.record_failure()
            dec.failover.append({"deployment": dep_id, "error": redact(e.message)[:200], "retryable": e.retryable})
            if e.kind == "unsupported_semantics":
                dec.outcome = "unsupported_semantics"
                router.record(dec)
                return _json(400, error_body(e.message, code="unsupported_semantics", modelsaar={"request_id": dec.request_id}), headers)
            next_id = next((c for c in candidate_ids if c not in tried), None)
            if e.retryable and attempts < max_attempts and next_id and dec.failover_allowed:
                dec.reasons.append(f"failover: {dep_id} failed before response commitment ({e.kind}); trying {next_id}")
                dec.chosen = next_id
                continue
            if e.retryable and next_id and not dec.failover_allowed:
                dec.reasons.append(f"failover refused: {dec.failover_note}")
            state.requests_failed += 1
            dec.outcome = "upstream_bad_response" if e.kind == "bad_envelope" else "upstream_error"
            dec.outcome_detail = redact(e.message)[:200]
            router.record(dec)
            return _json(
                e.status,
                error_body(
                    f"backend failed before a response was committed: {redact(e.message)}",
                    code="upstream_bad_response" if e.kind == "bad_envelope" else "upstream_error",
                    modelsaar={
                        "request_id": dec.request_id,
                        "deployment": dep_id,
                        "failover": dec.failover,
                        "failover_allowed": dec.failover_allowed,
                        "failover_note": dec.failover_note,
                    },
                ),
                headers,
            )


class _UpstreamStreamError(Exception):
    """The upstream stream ended abnormally after the response was committed."""


def _envelope_problem(body: Any) -> str | None:
    """Return why ``body`` is not a chat completion envelope, or None if it is one."""
    if not isinstance(body, dict):
        return "body is not a JSON object"
    if "error" in body and "choices" not in body:
        return "body is an error object"
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return "choices is missing or empty"
    first = choices[0]
    if not isinstance(first, dict) or not isinstance(first.get("message"), dict):
        return "choices[0].message is missing"
    return None


def _remember_tool_calls(router: Router, caller: str, dep_id: str, resp: dict[str, Any]) -> None:
    ids: list[str] = []
    for ch in resp.get("choices") or []:
        msg = ch.get("message") or {}
        for tc in msg.get("tool_calls") or []:
            if isinstance(tc, dict) and tc.get("id"):
                ids.append(str(tc["id"]))
    if ids:
        router.affinity.remember_tool_calls(caller, ids, dep_id)
        for i in ids:
            router.affinity.remember_tool_calls(caller, [i], dep_id)


async def _relay(
    state: GatewayState,
    router: Router,
    dec: Decision,
    dep_id: str,
    upstream: UpstreamStream,
    reservation,
    response_model: str,
    caller: str,
) -> AsyncIterator[bytes]:
    """Relay upstream SSE to the client. After the first byte the response is committed.

    Occupancy: the reservation is released only on confirmed completion or a confirmed upstream
    failure (the backend ended the stream). A read timeout or client disconnect leaves the backend
    possibly still generating, so the slot and the pool memory are held as *uncertain* until the
    configured hold expires (admission.uncertain_hold_s) — the same rule as non-streaming timeouts."""
    parser = SSEParser()
    obs = StreamObserver()
    tool_ids: list[str] = []
    completed = False
    uncertain = False
    try:
        async for chunk in upstream.aiter_bytes():
            if obs.first_byte_at is None:
                obs.first_byte_at = time.monotonic()
            for ev in parser.feed(chunk):
                obs.observe(ev)
                if ev.kind == "malformed":
                    # Not forwarded: it is not a completion structure. The stream is invalidated below.
                    continue
                if ev.kind == "done":
                    # The upstream terminal marker is held back: the downstream [DONE] is emitted
                    # exactly once, after validation, so any error frame precedes it.
                    continue
                obj = ev.json()
                if obj:
                    for ch in obj.get("choices") or []:
                        for tc in (ch.get("delta") or {}).get("tool_calls") or []:
                            if isinstance(tc, dict) and tc.get("id"):
                                tool_ids.append(str(tc["id"]))
                yield rewrite_model_field(ev, response_model)
        for ev in parser.flush():
            obs.observe(ev)
            if ev.kind not in ("malformed", "done"):
                yield rewrite_model_field(ev, response_model)
        problem = obs.completion_problem()
        if problem:
            raise _UpstreamStreamError(problem)
        completed = True
        # Exactly one terminal marker, after every validated event.
        yield b"data: [DONE]\n\n"
    except (asyncio.CancelledError, GeneratorExit):
        # Client went away. The backend may still be generating: hold the slot as uncertain.
        dec.outcome = "client_disconnected"
        dec.outcome_detail = f"after {obs.events} events"
        await reservation.mark_uncertain()
        await upstream.close()
        router.record(dec)
        raise
    except Exception as e:  # upstream failure mid-stream: terminate, never switch.
        if isinstance(e, AdapterError) and e.kind == "timeout":
            # The gateway stopped waiting; the backend did not end the stream and may still compute.
            uncertain = True
            dec.outcome = "stream_timeout_after_commit"
        elif isinstance(e, _UpstreamStreamError):
            dec.outcome = "stream_invalid_after_commit" if obs.malformed or not obs.valid_chunks else "stream_truncated_after_commit"
        else:
            dec.outcome = "stream_failed_after_commit"
        dec.outcome_detail = redact(str(e))[:200]
        c = router.admission.circuit(router.registry.get(dep_id).backend_id) if router.registry.get(dep_id) else None
        if c:
            c.record_failure()
        yield sse_error_frame(
            "upstream stream failed after the response was committed; the gateway does not switch models "
            f"mid-response ({redact(str(e))[:160]})",
            code="upstream_stream_error",
            modelsaar={"request_id": dec.request_id, "deployment": dep_id, "events_delivered": obs.events, "outcome": dec.outcome},
        )
        yield b"data: [DONE]\n\n"
    finally:
        if completed:
            dec.outcome = "ok"
            dec.outcome_detail = (
                f"events={obs.events} chunks={obs.valid_chunks} finish={obs.finish_reason} tool_deltas={obs.tool_call_deltas} "
                f"usage={'yes' if obs.usage else 'no'}"
            )
            await reservation.release()
            await upstream.close()
            # Only a validated, complete stream counts as a success for the circuit and for pinning.
            d = router.registry.get(dep_id)
            c = router.admission.circuit(d.backend_id) if d else None
            if c:
                c.record_success()
            router.pin_session(dec, caller, dep_id)
            if tool_ids:
                router.affinity.remember_tool_calls(caller, tool_ids, dep_id)
                for i in tool_ids:
                    router.affinity.remember_tool_calls(caller, [i], dep_id)
            router.record(dec)
        elif uncertain:
            await reservation.mark_uncertain()
            await upstream.close()
            router.record(dec)
        elif dec.outcome in ("stream_failed_after_commit", "stream_truncated_after_commit", "stream_invalid_after_commit"):
            await reservation.release()
            await upstream.close()
            router.record(dec)


# --------------------------------------------------------------------------- #
# Embeddings
# --------------------------------------------------------------------------- #
async def embeddings(request: Request) -> Response:
    state: GatewayState = request.app.state.gw
    router = state.router
    state.requests_total += 1
    try:
        caller = _require_caller(state, request)
        body = await _read_json(request, state.cfg.server.max_request_bytes)
        parse_embeddings_request(body)
    except ProtocolError as e:
        state.requests_failed += 1
        return _json(e.status, e.body())
    try:
        dec = await router.route_embeddings(body, caller)
    except NoEligibleDeployment as e:
        state.requests_failed += 1
        return _no_eligible_response(e.decision)
    dep = router.registry.get(dec.chosen)  # type: ignore[arg-type]
    adapter = router.adapters[dep.backend_id]
    headers = {"X-ModelSaar-Request-Id": dec.request_id, "X-ModelSaar-Deployment": dep.id}
    contract = next((c for c in state.cfg.embeddings if c.alias == dec.alias), None) if dec.alias else None
    problem = router.embedding_request_problem(body, contract, dep)
    if problem:
        state.requests_failed += 1
        dec.outcome = "unsupported_contract_option"
        dec.outcome_detail = problem
        router.record(dec)
        return _json(400, error_body(problem, code="unsupported_contract_option", modelsaar={"request_id": dec.request_id}), headers)
    try:
        reservation = await router.admission.acquire(dep)
    except AdmissionRejected as e:
        dec.outcome = "admission_rejected"
        router.record(dec)
        return _json(e.status, error_body(e.message, code="admission_rejected"), headers)
    try:
        # Same deadline rule as chat: the server request timeout or the backend timeout, whichever is tighter.
        resp = await adapter.embeddings(dep, body, timeout=state.cfg.server.request_timeout_s)
    except AdapterError as e:
        if e.kind == "timeout":
            # The backend may still be computing: hold the slot/memory as uncertain, do not release.
            await reservation.mark_uncertain()
        else:
            await reservation.release(submitted=e.kind != "connect")
        state.requests_failed += 1
        dec.outcome = "upstream_timeout" if e.kind == "timeout" else "upstream_error"
        dec.outcome_detail = redact(e.message)[:200]
        router.record(dec)
        return _json(e.status, error_body(redact(e.message), code="upstream_timeout" if e.kind == "timeout" else "upstream_error", modelsaar={"request_id": dec.request_id, "deployment": dep.id}), headers)
    except Exception as e:  # noqa: BLE001 - every failure path must account for the slot
        await reservation.release()
        state.requests_failed += 1
        dec.outcome = "internal_error"
        dec.outcome_detail = redact(f"{e.__class__.__name__}: {e}")[:200]
        router.record(dec)
        log.exception("unexpected error in embeddings dispatch to %s", dep.id)
        return _json(500, error_body("internal gateway error", code="internal_error", modelsaar={"request_id": dec.request_id}), headers)
    await reservation.release()
    if resp.status != 200:
        dec.outcome = "upstream_error"
        router.record(dec)
        return _json(resp.status, resp.body, headers)
    expected_dims = (contract.dimensions if contract else None) or dep.embedding_dimensions
    violation = _embedding_problem(resp.body, _embedding_input_count(body.get("input")), expected_dims, contract.normalized if contract else None)
    if violation:
        state.requests_failed += 1
        dec.outcome = "embedding_contract_violation"
        dec.outcome_detail = violation
        router.record(dec)
        return _json(
            502,
            error_body(
                f"backend output violates the embedding contract: {violation}",
                code="embedding_contract_violation",
                modelsaar={"request_id": dec.request_id, "deployment": dep.id},
            ),
            headers,
        )
    out = dict(resp.body)
    out["model"] = dec.requested_model if state.cfg.server.response_model_field == "requested" else dep.id
    if contract:
        router.record_embedding_identity(contract.alias, dep)
    dec.outcome = "ok"
    router.record(dec)
    return _json(200, out, headers)


def _embedding_input_count(inp: Any) -> int:
    if isinstance(inp, str):
        return 1
    if isinstance(inp, list):
        if inp and all(isinstance(x, int) for x in inp):
            return 1  # one token array
        return len(inp)
    return 1


def _embedding_problem(body: Any, n_inputs: int, dims: int | None, normalized: bool | None) -> str | None:
    """Validate count, indices, dimensions, finiteness and (when the contract says so) unit norm."""
    import math

    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        return "response has no data list"
    data = body["data"]
    if len(data) != n_inputs:
        return f"{len(data)} vectors returned for {n_inputs} inputs"
    seen_dims: int | None = None
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return f"data[{i}] is not an object"
        if item.get("index") != i:
            return f"data[{i}].index is {item.get('index')!r}"
        vec = item.get("embedding")
        if not isinstance(vec, list) or not vec:
            return f"data[{i}].embedding is not a non-empty list (base64 encodings are not supported)"
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in vec):
            return f"data[{i}].embedding contains non-finite or non-numeric values"
        if seen_dims is None:
            seen_dims = len(vec)
        elif len(vec) != seen_dims:
            return f"data[{i}].embedding has {len(vec)} dimensions, data[0] has {seen_dims}"
        if dims and len(vec) != dims:
            return f"data[{i}].embedding has {len(vec)} dimensions; contract requires {dims}"
        if normalized:
            norm = math.sqrt(sum(v * v for v in vec))
            if abs(norm - 1.0) > 1e-2:
                return f"data[{i}].embedding has L2 norm {norm:.3f}; contract declares normalized vectors (set normalized: false if the model does not normalize)"
    return None


# --------------------------------------------------------------------------- #
# Models, health, unsupported protocols
# --------------------------------------------------------------------------- #
async def list_models(request: Request) -> Response:
    state: GatewayState = request.app.state.gw
    try:
        _require_caller(state, request)
    except ProtocolError as e:
        return _json(e.status, e.body())
    return _json(200, {"object": "list", "data": state.router.models_listing()})


async def healthz(request: Request) -> Response:
    # Unauthenticated identification contract used by `modelsaar test` and the installer to tell a
    # ModelSaar gateway from another service on the same port before any key is sent. It is a
    # collision check, not authentication: anything can imitate it.
    return _json(200, {"status": "ok", "service": "modelsaar", "version": __version__, "api": "openai-compatible"})


async def readyz(request: Request) -> Response:
    state: GatewayState = request.app.state.gw
    healthy = [d for d in state.router.registry.all() if d.healthy and d.enabled]
    ok = state.ready and bool(healthy)
    return _json(
        200 if ok else 503,
        {
            "status": "ready" if ok else "not_ready",
            "registry_version": state.router.registry.version,
            "healthy_deployments": len(healthy),
            "last_refresh_error": state.router.last_refresh_error,
        },
    )


async def unsupported_protocol(request: Request) -> Response:
    return _json(
        501,
        error_body(
            f"{request.url.path} is not implemented by ModelSaar 0.1 (Responses and Anthropic Messages are separate "
            "protocol work). Use /v1/chat/completions. The gateway does not emulate stateful protocols.",
            code="unsupported_protocol",
        ),
    )


# --------------------------------------------------------------------------- #
# Admin / inspection
# --------------------------------------------------------------------------- #
async def admin_status(request: Request) -> Response:
    state: GatewayState = request.app.state.gw
    try:
        _require_admin(state, request)
    except ProtocolError as e:
        return _json(e.status, e.body())
    r = state.router
    return _json(
        200,
        {
            "version": __version__,
            "uptime_s": round(time.time() - state.started_at, 1),
            "config_path": state.cfg.config_path,
            "config_hash": state.cfg.config_hash,
            "ready": state.ready,
            "requests_total": state.requests_total,
            "requests_failed": state.requests_failed,
            "registry_version": r.registry.version,
            "last_refresh_error": r.last_refresh_error,
            "aliases": {a: r.alias_contract(a) for a in state.cfg.aliases},
            "deployments": r.registry.snapshot(),
            "admission": r.admission.stats(),
            "affinity": r.affinity.stats(),
            "classifier": r.classifier.stats(),
            "security": {
                "host": state.cfg.server.host,
                "allow_lan": state.cfg.security.allow_lan,
                "locality_mode": state.cfg.security.locality_mode,
                "log_prompts": state.cfg.security.log_prompts,
                "telemetry_opt_in": state.cfg.security.telemetry_opt_in,
            },
        },
    )


async def admin_decisions(request: Request) -> Response:
    state: GatewayState = request.app.state.gw
    try:
        _require_admin(state, request)
    except ProtocolError as e:
        return _json(e.status, e.body())
    if not state.store:
        return _json(200, {"decisions": []})
    rid = request.path_params.get("request_id")
    if rid:
        d = state.store.get_decision(rid)
        return _json(200 if d else 404, d or error_body("decision not found", code="not_found"))
    try:
        limit = int(request.query_params.get("limit", "50"))
    except ValueError:
        return _json(400, error_body("limit must be an integer"))
    limit = max(1, min(limit, 500))
    return _json(200, {"decisions": state.store.recent_decisions(limit)})


async def admin_explain(request: Request) -> Response:
    """Dry-run routing for a request body without dispatching it."""
    state: GatewayState = request.app.state.gw
    try:
        _require_admin(state, request)
        body = await _read_json(request, state.cfg.server.max_request_bytes)
        parse_chat_request(body)
    except ProtocolError as e:
        return _json(e.status, e.body())
    try:
        dec = await state.router.route_chat(body, dict(request.headers), "explain")
        dec.outcome = "explain_only"
        return _json(200, dec.as_dict())
    except NoEligibleDeployment as e:
        return _json(200, e.decision.as_dict())


async def admin_refresh(request: Request) -> Response:
    state: GatewayState = request.app.state.gw
    try:
        _require_admin(state, request)
    except ProtocolError as e:
        return _json(e.status, e.body())
    await state.router.refresh()
    return _json(200, {"registry_version": state.router.registry.version, "error": state.router.last_refresh_error})


async def admin_probe(request: Request) -> Response:
    """Run capability probes for one deployment under the gateway's own admission (slots, memory
    budget, queue). This is the coordinated path `modelsaar probe` uses while a gateway is running,
    so probe inference never overlaps with serving beyond the configured limits."""
    state: GatewayState = request.app.state.gw
    try:
        _require_admin(state, request)
        body = await _read_json(request, state.cfg.server.max_request_bytes)
    except ProtocolError as e:
        return _json(e.status, e.body())
    from .probes import PROBE_NAMES, run_probes

    router = state.router
    dep_id = str(body.get("deployment", ""))
    dep = router.registry.get(dep_id)
    if dep is None:
        return _json(404, error_body(f"deployment {dep_id!r} not found", code="unknown_deployment"))
    if dep.role != "generative" or not dep.healthy:
        return _json(422, error_body(f"{dep_id} is not a healthy generative deployment", code="not_probeable"))
    if state.cfg.security.locality_mode == "local_only" and dep.locality != "local":
        return _json(422, error_body(f"{dep_id} is not local; probes send prompts and are refused under local_only", code="locality"))
    which = body.get("which") or None
    if which is not None and (not isinstance(which, list) or any(w not in PROBE_NAMES for w in which)):
        return _json(400, error_body(f"which must be a subset of {sorted(PROBE_NAMES)}", code="invalid_request_error"))
    timeout = float(body.get("timeout") or 120.0)
    try:
        reservation = await router.admission.acquire(dep, timeout=None)
    except AdmissionRejected as e:
        return _json(e.status, error_body(e.message, code="admission_rejected"), {"Retry-After": "2"})
    try:
        rep = await run_probes(router.adapters[dep.backend_id], dep, state.store, which, timeout=timeout)
    except BaseException:
        await reservation.release()
        raise
    if rep.uncertain:
        # A probe inference timed out: the runner stopped and the backend may still be computing.
        # Hold the slot and the pool memory as uncertain (same rule as serving timeouts).
        await reservation.mark_uncertain()
    else:
        await reservation.release()
    await router.refresh()
    return _json(200, rep.as_dict())


async def admin_ui(request: Request) -> Response:
    page = Path(__file__).parent / "static" / "status.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
def build_app(cfg: Config, router: Router, auth: Auth, store: Store | None) -> Starlette:
    state = GatewayState(cfg, router, auth, store)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        state.loop = asyncio.get_running_loop()
        await router.refresh()
        state.ready = True
        state._bg.append(asyncio.create_task(_background(state)))
        try:
            yield
        finally:
            for t in state._bg:
                t.cancel()
            await router.aclose()

    app = Starlette(
        routes=[
            Route("/v1/chat/completions", chat_completions, methods=["POST"]),
            Route("/v1/embeddings", embeddings, methods=["POST"]),
            Route("/v1/models", list_models, methods=["GET"]),
            Route("/v1/responses", unsupported_protocol, methods=["POST"]),
            Route("/v1/messages", unsupported_protocol, methods=["POST"]),
            Route("/v1/completions", unsupported_protocol, methods=["POST"]),
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
            Route("/admin/status", admin_status, methods=["GET"]),
            Route("/admin/decisions", admin_decisions, methods=["GET"]),
            Route("/admin/decisions/{request_id}", admin_decisions, methods=["GET"]),
            Route("/admin/explain", admin_explain, methods=["POST"]),
            Route("/admin/refresh", admin_refresh, methods=["POST"]),
            Route("/admin/probe", admin_probe, methods=["POST"]),
            Route("/admin/ui", admin_ui, methods=["GET"]),
        ],
        lifespan=lifespan,
    )
    app.state.gw = state
    return app


async def _background(state: GatewayState) -> None:
    last_full = time.monotonic()
    while True:
        try:
            await asyncio.sleep(state.cfg.server.residency_refresh_s)
            if time.monotonic() - last_full >= state.cfg.server.discovery_refresh_s:
                await state.router.refresh()
                last_full = time.monotonic()
            else:
                await state.router.refresh_residency()
        except asyncio.CancelledError:
            return
        except Exception as e:  # pragma: no cover
            log.warning("background refresh failed: %s", redact(str(e)))
