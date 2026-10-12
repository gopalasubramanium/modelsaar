"""Regression tests for the 2026-10-12 correction pass (independent review findings R1–R4).

The reviewer's own assertions are executed verbatim from ``tests/independent_review_2026_10_11/``.
These tests add the parts the correction must also preserve: recovery after an uncertain hold,
reconciliation of assumed residency by a real observation, legitimate SSE comments/keepalive/usage
frames, legitimate same-identity replicas, and the admin status fields that make the holds visible.
All endpoints are loopback fixtures; "memory" is metadata, never allocated.
"""

from __future__ import annotations

import asyncio
import json
import time

from conftest import build_gateway, chat, make_models
from starlette.responses import JSONResponse, StreamingResponse

from modelsaar.config import (
    AdmissionConfig,
    BackendConfig,
    DeclaredModel,
    DeploymentOverride,
    EmbeddingContract,
    ResourcePool,
    ServerConfig,
)
from modelsaar.testing.fakebackend import FakeBackend


class ContinuingBackend(FakeBackend):
    """Compute that survives the HTTP close (a valid first chunk, then a long job)."""

    def __init__(self, models, duration=0.5):
        self.duration = duration
        super().__init__(models)

    def _job(self):
        async def compute():
            with self._lock:
                self.active += 1
                self.max_active = max(self.active, self.max_active)
            try:
                await asyncio.sleep(self.duration)
            finally:
                with self._lock:
                    self.active -= 1

        return asyncio.create_task(compute())

    async def v1_chat(self, request):
        body = await request.json()
        name = body["model"]
        self.requests.append({"model": name, "stream": bool(body.get("stream"))})
        task = self._job()
        payload = {"id": "c", "object": "chat.completion", "created": int(time.time()), "model": name,
                   "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}
        if not body.get("stream"):
            await asyncio.shield(task)
            return JSONResponse(payload)

        async def events():
            chunk = {**payload, "object": "chat.completion.chunk",
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": "started"}, "finish_reason": None}]}
            yield b"data: " + json.dumps(chunk).encode() + b"\n\n"
            await asyncio.shield(task)
            chunk["choices"][0] = {"index": 0, "delta": {}, "finish_reason": "stop"}
            yield b"data: " + json.dumps(chunk).encode() + b"\n\ndata: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    async def v1_embeddings(self, request):
        body = await request.json()
        self.requests.append({"model": body["model"], "embedding": True})
        await asyncio.shield(self._job())
        return await super().v1_embeddings(request)


def _one_slot(fake, timeout=0.08, hold=0.4):
    return build_gateway(
        f"http://127.0.0.1:{fake.port}",
        server=ServerConfig(request_timeout_s=timeout),
        admission=AdmissionConfig(uncertain_hold_s=hold, max_queue=0),
        resource_pools=(ResourcePool(id="pool", max_concurrent=1, max_queue=0),),
    )


def test_r1_stream_timeout_holds_then_recovers():
    """R1: a streaming read timeout holds the slot as uncertain, the response says so, and the slot
    comes back after the hold (no permanent capacity loss)."""
    fake = ContinuingBackend(make_models(), duration=0.3)
    fake.start()
    g = _one_slot(fake, hold=0.5)
    try:
        first = chat(g, "ollama/small:1b", "hello", stream=True)
        assert first.status_code == 200 and "upstream_stream_error" in first.text
        dec = g.decision(first.headers["x-modelsaar-request-id"])
        assert dec["outcome"] == "stream_timeout_after_commit"
        st = g.admin.get("/admin/status").json()["admission"]["pool:pool"]
        assert st["uncertain"] == 1 and st["active"] == 0
        assert chat(g, "ollama/small:1b", "hello").status_code != 200  # slot held
        time.sleep(0.9)  # hold expires and the fixture's job is long over
        fake.duration = 0.01  # the backend answers within the deadline again
        assert chat(g, "ollama/small:1b", "hello").status_code == 200  # recovered
        assert fake.max_active == 1
    finally:
        g.gw.stop()
        fake.stop()


def test_r1_probe_timeout_reports_skipped_probes_and_holds():
    fake = ContinuingBackend(make_models(), duration=0.3)
    fake.start()
    g = _one_slot(fake, hold=0.5)
    try:
        rep = g.admin.post("/admin/probe", json={"deployment": "ollama/small:1b", "which": ["tools", "json_object", "latency"], "timeout": 0.08}).json()
        assert rep["uncertain"] is True
        assert rep["skipped"] == ["json_object", "latency"]
        assert rep["results"][0]["uncertain"] is True and rep["results"][0]["value"] == "unknown"
        assert any("remaining probes were not run" in e for e in rep["errors"])
        assert g.admin.get("/admin/status").json()["admission"]["pool:pool"]["uncertain"] == 1
        assert fake.max_active == 1 and len(fake.requests) == 1
    finally:
        time.sleep(0.4)
        g.gw.stop()
        fake.stop()


def test_r4_embedding_timeout_is_uncertain_and_bounded():
    fake = ContinuingBackend(make_models(), duration=0.4)
    fake.start()
    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        server=ServerConfig(request_timeout_s=0.08),
        admission=AdmissionConfig(uncertain_hold_s=0.5, max_queue=0),
        resource_pools=(ResourcePool(id="pool", max_concurrent=1, max_queue=0),),
    )
    try:
        t0 = time.monotonic()
        r = g.client.post("/v1/embeddings", json={"model": "ollama/embed:0.6b", "input": "hello"})
        assert r.status_code == 504 and r.json()["error"]["code"] == "upstream_timeout"
        assert time.monotonic() - t0 < 0.35
        assert g.admin.get("/admin/status").json()["admission"]["pool:pool"]["uncertain"] == 1
    finally:
        time.sleep(0.5)
        g.gw.stop()
        fake.stop()


class CommentedStreamBackend(FakeBackend):
    """A legitimate stream: SSE comment, keepalive, content chunk, usage-only frame, [DONE]."""

    async def v1_chat(self, request):
        await request.json()

        async def events():
            yield b": keepalive\n\n"
            yield b'data: {"id":"c","object":"chat.completion.chunk","model":"small:1b","choices":[{"index":0,"delta":{"role":"assistant","content":"hi"},"finish_reason":null}]}\n\n'
            yield b": another comment\n\n"
            yield b'data: {"id":"c","object":"chat.completion.chunk","model":"small:1b","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            yield b'data: {"id":"c","object":"chat.completion.chunk","model":"small:1b","choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n'
            yield b"data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")


def test_r4_comments_keepalives_and_usage_frames_are_a_valid_completion():
    fake = CommentedStreamBackend(make_models())
    fake.start()
    g = build_gateway(f"http://127.0.0.1:{fake.port}")
    try:
        r = g.client.post("/v1/chat/completions", headers={"X-ModelSaar-Session": "s1"},
                          json={"model": "ollama/small:1b", "messages": [{"role": "user", "content": "hi"}], "stream": True})
        assert r.status_code == 200 and "upstream_stream_error" not in r.text
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert dec["outcome"] == "ok" and "chunks=3" in dec["outcome_detail"]
        assert g.router.affinity.stats()["sessions"] == 1
        assert g.router.admission.circuit("ollama").failures == 0
    finally:
        g.gw.stop()
        fake.stop()


class MalformedThenValidBackend(FakeBackend):
    async def v1_chat(self, request):
        await request.json()

        async def events():
            yield b'data: {"id":"c","object":"chat.completion.chunk","model":"small:1b","choices":[{"index":0,"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\n'
            yield b"data: <html>oops</html>\n\n"
            yield b"data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")


def test_r4_malformed_frame_amid_valid_chunks_invalidates_and_is_not_forwarded():
    fake = MalformedThenValidBackend(make_models())
    fake.start()
    g = build_gateway(f"http://127.0.0.1:{fake.port}")
    try:
        r = g.client.post("/v1/chat/completions", headers={"X-ModelSaar-Session": "s2"},
                          json={"model": "ollama/small:1b", "messages": [{"role": "user", "content": "hi"}], "stream": True})
        assert "data: <html>oops</html>" not in r.text  # the malformed frame itself is not relayed
        assert "upstream_stream_error" in r.text
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert dec["outcome"] == "stream_invalid_after_commit"
        assert g.router.affinity.stats()["sessions"] == 0
        assert g.router.admission.circuit("ollama").failures == 1
    finally:
        g.gw.stop()
        fake.stop()


class ResidencyBackend(FakeBackend):
    """Loading a model on first use, like a real runtime; /api/ps (FakeBackend) reports it."""

    async def v1_chat(self, request):
        body = await request.json()
        self.models[body["model"]].loaded = True
        return await super().v1_chat(request)


def _budget_gateway(fake):
    return build_gateway(
        f"http://127.0.0.1:{fake.port}",
        resource_pools=(ResourcePool(id="pool", max_concurrent=1, memory_gb=5.0),),
        deployments=(DeploymentOverride(backend="ollama", model="small:1b", memory_gb_estimate=3.0),
                     DeploymentOverride(backend="ollama", model="plain:3b", memory_gb_estimate=3.0)),
    )


def test_r2_assumed_residency_is_counted_then_reconciled_by_observation():
    """R2: after A completes its weights stay counted (B rejected). When the runtime later reports A
    unloaded and the gateway observes it, the assumption is dropped and B is admitted."""
    models = make_models()
    for m in models:
        m.loaded = False
    fake = ResidencyBackend(models)
    fake.start()
    g = _budget_gateway(fake)
    try:
        assert chat(g, "ollama/small:1b", "hello").status_code == 200
        st = g.admin.get("/admin/status").json()["admission"]["pool:pool"]
        assert st["memory_assumed_resident"] == ["ollama/small:1b"] and st["memory_holders"] == []
        rb = chat(g, "ollama/plain:3b", "hello")
        assert rb.status_code != 200
        assert any("memory" in b for b in rb.json()["error"]["modelsaar"]["blockers"]["ollama/plain:3b"])
        # The runtime evicts A (observable through /api/ps); a refresh reconciles the assumption.
        fake.models["small:1b"].loaded = False
        g.refresh()
        st = g.admin.get("/admin/status").json()["admission"]["pool:pool"]
        assert st["memory_assumed_resident"] == []
        assert chat(g, "ollama/plain:3b", "hello").status_code == 200
    finally:
        g.gw.stop()
        fake.stop()


def test_r2_same_deployment_is_counted_once_and_keeps_serving():
    models = make_models()
    for m in models:
        m.loaded = False
    fake = ResidencyBackend(models)
    fake.start()
    g = _budget_gateway(fake)
    try:
        for _ in range(3):
            assert chat(g, "ollama/small:1b", "hello").status_code == 200
        v = g.router.admission.memory_view(g.router.registry.get("ollama/small:1b"))
        assert v["counted"] == ["ollama/small:1b"] and v["estimated_gb"] == 3.0
    finally:
        g.gw.stop()
        fake.stop()


def test_r2_unknown_resident_blocks_under_reject_but_not_under_allow():
    from modelsaar.registry import Deployment
    from modelsaar.routing.admission import Admission

    for policy, blocked in (("reject", True), ("allow", False)):
        pool = ResourcePool(id="pool", memory_gb=5.0, unknown_memory_policy=policy)
        adm = Admission(AdmissionConfig(), [pool], [BackendConfig(id="b", type="openai_compatible", base_url="http://127.0.0.1:1", resource_pool="pool")])
        resident = Deployment(id="b/unknown", backend_id="b", backend_type="openai_compatible", model="unknown", resource_pool="pool", loaded=True)
        cand = Deployment(id="b/known", backend_id="b", backend_type="openai_compatible", model="known", resource_pool="pool", memory_gb_estimate=4.0)
        members = [resident, cand]
        adm.pool_members = lambda _, members=members: members
        why = adm.memory_blocker(cand)
        assert (why is not None) is blocked, (policy, why)
        if blocked:
            assert "b/unknown" in why and "reject" in why


def test_r3_same_identity_replicas_share_an_alias_and_anchor_is_persisted_before_dispatch():
    fake = FakeBackend(make_models())
    fake.start()
    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        backends=(
            BackendConfig(id="a", type="openai_compatible", base_url=f"http://127.0.0.1:{fake.port}", discover=False, resource_pool="pool",
                          models=(DeclaredModel(name="embed:0.6b", role="embedding", embedding_dimensions=8, identity="weights-A"),)),
            BackendConfig(id="b", type="openai_compatible", base_url=f"http://127.0.0.1:{fake.port}", discover=False, resource_pool="pool",
                          models=(DeclaredModel(name="embed:0.6b", role="embedding", embedding_dimensions=8, identity="weights-A"),)),
            BackendConfig(id="c", type="openai_compatible", base_url=f"http://127.0.0.1:{fake.port}", discover=False, resource_pool="pool",
                          models=(DeclaredModel(name="embed-other:1b", role="embedding", embedding_dimensions=16, identity="weights-C"),)),
        ),
        embeddings=(EmbeddingContract(alias="embed-safe", dimensions=8, deployments=("a/embed:0.6b", "b/embed:0.6b", "c/embed-other:1b")),),
        deployments=(),
    )
    try:
        assert g.router._recorded_embedding_identity("embed-safe") == ""
        r = g.client.post("/v1/embeddings", json={"model": "embed-safe", "input": "x"})
        assert r.status_code == 200
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        # Anchored before dispatch to the first member's verified identity; the replica stays eligible,
        # the differing identity is excluded even though it would have been excluded by dimensions too.
        assert g.router._recorded_embedding_identity("embed-safe") == "weights-A"
        assert "c/embed-other:1b" in dec["exclusions"]
        assert any(c in dec["chosen"] for c in ("a/embed:0.6b", "b/embed:0.6b"))
    finally:
        g.gw.stop()
        fake.stop()
