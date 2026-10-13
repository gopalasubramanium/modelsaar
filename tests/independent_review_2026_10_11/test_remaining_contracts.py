"""Independent desired-contract checks for ModelSaar 80276bb.

All inference endpoints are loopback Starlette fixtures. Workers only sleep;
memory values are metadata, not actual allocations. Failing assertions describe
desired corrected behavior, not a test of a known defect being present.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import time

import pytest

from conftest import build_gateway, chat, make_models
from starlette.responses import JSONResponse, StreamingResponse

from modelsaar.config import (
    AdmissionConfig, BackendConfig, Capabilities, DeclaredModel, DeploymentOverride,
    EmbeddingContract, ResourcePool, ServerConfig,
)
from modelsaar.testing.fakebackend import FakeBackend


OBSERVATIONS = []


def observe(name, **details):
    data = {"case": name, **details}
    OBSERVATIONS.append(data)
    print("OBSERVATION " + json.dumps(data, sort_keys=True))


class ContinuingBackend(FakeBackend):
    """A real HTTP backend whose already-started compute survives HTTP close."""
    def __init__(self, models, duration=0.55):
        self.duration = duration
        self.jobs = set()
        super().__init__(models)

    def start_job(self, name):
        async def compute():
            with self._lock:
                self.active += 1
                self.max_active = max(self.active, self.max_active)
            try:
                await asyncio.sleep(self.duration)
            finally:
                with self._lock:
                    self.active -= 1
        task = asyncio.create_task(compute())
        self.jobs.add(task)
        task.add_done_callback(self.jobs.discard)
        return task

    async def v1_chat(self, request):
        body = await request.json()
        name = body["model"]
        self.requests.append({"model": name, "stream": bool(body.get("stream"))})
        task = self.start_job(name)
        payload = {"id": "chatcmpl-independent", "object": "chat.completion",
                   "created": int(time.time()), "model": name,
                   "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                                "finish_reason": "stop"}]}
        if not body.get("stream"):
            await asyncio.shield(task)
            return JSONResponse(payload)
        async def events():
            chunk = {**payload, "object": "chat.completion.chunk", "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": "started"}, "finish_reason": None}]}
            yield b"data: " + json.dumps(chunk).encode() + b"\n\n"
            await asyncio.shield(task)
            chunk["choices"][0] = {"index": 0, "delta": {}, "finish_reason": "stop"}
            yield b"data: " + json.dumps(chunk).encode() + b"\n\ndata: [DONE]\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")

    async def v1_embeddings(self, request):
        body = await request.json()
        name = body["model"]
        self.requests.append({"model": name, "embedding": True})
        # A responds late; B is fast, allowing an alias first-use race.
        if name != "embed-other:1b":
            await asyncio.shield(self.start_job(name))
        return await super().v1_embeddings(request)


def one_slot_gateway(fake, timeout=0.08):
    return build_gateway(
        f"http://127.0.0.1:{fake.port}",
        server=ServerConfig(request_timeout_s=timeout),
        admission=AdmissionConfig(uncertain_hold_s=2.0, max_queue=0),
        resource_pools=(ResourcePool(id="pool", max_concurrent=1, max_queue=0),),
    )


@pytest.mark.parametrize("stream", [True, False], ids=["streaming-regression", "nonstream-positive-control"])
def test_stream_read_timeout_holds_capacity_until_recovery(stream):
    fake = ContinuingBackend(make_models())
    fake.start()
    g = one_slot_gateway(fake)
    try:
        first = chat(g, "ollama/small:1b", "hello", stream=stream)
        status = g.admin.get("/admin/status").json()["admission"]
        active_after_timeout = fake.active
        second = chat(g, "ollama/small:1b", "hello", stream=stream)
        observe("stream_timeout", stream=stream, first_status=first.status_code,
                first_contains_gateway_error="upstream_stream_error" in first.text,
                backend_active_after_timeout=active_after_timeout, admission=status,
                second_status=second.status_code, backend_max_active=fake.max_active,
                backend_requests=len(fake.requests))
        assert active_after_timeout == 1, "fixture must establish computation survived HTTP timeout"
        assert status["pool:pool"]["uncertain"] == 1, "streaming read timeout released a still-computing backend"
        assert second.status_code != 200, "second request was dispatched while first was still computing"
    finally:
        time.sleep(0.6)
        g.gw.stop()
        fake.stop()


def test_probe_timeout_stops_later_probe_inference():
    fake = ContinuingBackend(make_models())
    fake.start()
    g = one_slot_gateway(fake)
    try:
        result = g.admin.post("/admin/probe", json={"deployment": "ollama/small:1b",
                                                   "which": ["tools", "json_object"], "timeout": 0.08})
        status = g.admin.get("/admin/status").json()["admission"]
        observe("probe_timeout", http_status=result.status_code, response=result.json(),
                admission=status, backend_active=fake.active, backend_max_active=fake.max_active,
                backend_requests=len(fake.requests))
        assert fake.max_active <= 1, "probe runner started a second inference while timed-out first inference still ran"
        assert status["pool:pool"]["uncertain"] == 1, "admin probe released uncertain occupancy"
    finally:
        time.sleep(0.6)
        g.gw.stop()
        fake.stop()


def test_embedding_backend_timeout_is_enforced():
    fake = ContinuingBackend(make_models(), duration=0.55)
    fake.start()
    g = build_gateway(
        f"http://127.0.0.1:{fake.port}", server=ServerConfig(request_timeout_s=0.08),
        backends=(BackendConfig(id="ollama", type="ollama", base_url=f"http://127.0.0.1:{fake.port}",
                                resource_pool="pool", timeout_s=0.08),),
    )
    try:
        start = time.monotonic()
        result = g.client.post("/v1/embeddings", json={"model": "ollama/embed:0.6b", "input": "hello"})
        elapsed = time.monotonic() - start
        observe("embedding_timeout", configured_server_timeout_s=0.08, configured_backend_timeout_s=0.08,
                elapsed_s=round(elapsed, 3), http_status=result.status_code)
        assert result.status_code == 504, "embedding call ignored both configured timeouts and waited for slow backend"
    finally:
        g.gw.stop()
        fake.stop()


@pytest.mark.parametrize("anchored", [False, True], ids=["unanchored-regression", "declared-anchor-positive-control"])
def test_unknown_first_embedding_member_cannot_allow_distinct_spaces(anchored):
    models = make_models()
    for m in models:
        if "embedding" in m.capabilities:
            m.embedding_dimensions = 8
    fake = ContinuingBackend(models, duration=0.4)
    fake.start()
    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        admission=AdmissionConfig(max_queue=0),
        backends=(
            BackendConfig(id="unknown", type="openai_compatible", base_url=f"http://127.0.0.1:{fake.port}",
                          discover=False, resource_pool="pool", max_concurrent=1,
                          models=(DeclaredModel(name="unknown-first", role="embedding", embedding_dimensions=8),)),
            BackendConfig(id="a", type="openai_compatible", base_url=f"http://127.0.0.1:{fake.port}",
                          discover=False, resource_pool="pool", max_concurrent=1,
                          models=(DeclaredModel(name="embed:0.6b", role="embedding", embedding_dimensions=8, identity="weights-A"),)),
            BackendConfig(id="b", type="openai_compatible", base_url=f"http://127.0.0.1:{fake.port}",
                          discover=False, resource_pool="pool", max_concurrent=1,
                          models=(DeclaredModel(name="embed-other:1b", role="embedding", embedding_dimensions=8, identity="weights-B"),)),
        ),
        embeddings=(EmbeddingContract(alias="embed-safe", dimensions=8, identity="weights-A" if anchored else None,
                                      deployments=("unknown/unknown-first", "a/embed:0.6b", "b/embed-other:1b")),),
        deployments=(),
    )
    try:
        body = {"model": "embed-safe", "input": "same input"}
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(g.client.post, "/v1/embeddings", json=body)
            deadline = time.monotonic() + 2
            while not fake.requests and time.monotonic() < deadline:
                time.sleep(0.005)
            assert fake.requests and fake.requests[0]["model"] == "embed:0.6b"
            # A's backend is now at its real configured admission limit. B remains available.
            second = g.client.post("/v1/embeddings", json=body)
            first = future.result()
        observe("embedding_identity_race", anchored=anchored, first_status=first.status_code, second_status=second.status_code,
                first_deployment=first.headers.get("x-modelsaar-deployment"),
                second_deployment=second.headers.get("x-modelsaar-deployment"),
                identities={"a/embed:0.6b": "weights-A", "b/embed-other:1b": "weights-B"},
                recorded_identity=g.router._recorded_embedding_identity("embed-safe"))
        accepted = [r.headers.get("x-modelsaar-deployment") for r in (first, second) if r.status_code == 200]
        assert len(set(accepted)) <= 1, "one embedding alias returned vectors from two distinct declared identities"
    finally:
        g.gw.stop()
        fake.stop()


class ResidencyBackend(FakeBackend):
    async def v1_chat(self, request):
        body = await request.json()
        self.models[body["model"]].loaded = True
        return await super().v1_chat(request)


@pytest.mark.parametrize("refresh_before_second", [False, True], ids=["between-polls-regression", "refresh-positive-control"])
def test_completed_dispatch_keeps_loaded_weights_in_memory_budget(refresh_before_second):
    models = make_models()
    for m in models:
        m.loaded = False
    fake = ResidencyBackend(models)
    fake.start()
    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        resource_pools=(ResourcePool(id="pool", max_concurrent=1, memory_gb=5.0),),
        deployments=(DeploymentOverride(backend="ollama", model="small:1b", memory_gb_estimate=3.0),
                     DeploymentOverride(backend="ollama", model="plain:3b", memory_gb_estimate=3.0)),
    )
    try:
        first = chat(g, "ollama/small:1b", "hello")
        if refresh_before_second:
            g.refresh()
        observed_by_router = g.router.registry.get("ollama/small:1b").loaded
        second = chat(g, "ollama/plain:3b", "hello")
        observe("post_completion_memory", refresh_before_second=refresh_before_second, first_status=first.status_code, second_status=second.status_code,
                first_model_router_loaded=observed_by_router,
                backend_resident_models=[m.name for m in fake.models.values() if m.loaded],
                backend_requests=len(fake.requests), budget_gb=5.0, per_model_estimate_gb=3.0)
        assert first.status_code == 200
        assert second.status_code != 200, "completed model's weights vanished from admission before the next residency refresh"
    finally:
        g.gw.stop()
        fake.stop()


def test_reject_unknown_memory_applies_to_existing_residents():
    from modelsaar.routing.admission import Admission
    from modelsaar.registry import Deployment
    pool = ResourcePool(id="pool", memory_gb=5.0, unknown_memory_policy="reject")
    adm = Admission(AdmissionConfig(), [pool], [BackendConfig(id="b", type="openai_compatible", base_url="http://127.0.0.1:1", resource_pool="pool")])
    resident = Deployment(id="b/unknown", backend_id="b", backend_type="openai_compatible", model="unknown", resource_pool="pool", loaded=True)
    candidate = Deployment(id="b/known", backend_id="b", backend_type="openai_compatible", model="known", resource_pool="pool", memory_gb_estimate=4.0)
    adm.pool_members = lambda _: [resident, candidate]
    view = adm.memory_view(candidate)
    blocker = adm.memory_blocker(candidate)
    observe("unknown_resident_memory", view=view, blocker=blocker)
    assert blocker is not None, "strict unknown-memory pool treats an already resident unknown model as zero memory"


class InvalidSSEBackend(FakeBackend):
    async def v1_chat(self, request):
        await request.json()
        async def events():
            yield b'data: not-json\n\ndata: [DONE]\n\n'
        return StreamingResponse(events(), media_type="text/event-stream")


def test_invalid_sse_is_not_validated_success_or_session_pin():
    fake = InvalidSSEBackend(make_models())
    fake.start()
    g = build_gateway(f"http://127.0.0.1:{fake.port}")
    try:
        response = g.client.post("/v1/chat/completions", headers={"X-ModelSaar-Session": "invalid-session"},
                                 json={"model": "ollama/small:1b", "messages": [{"role": "user", "content": "hello"}], "stream": True})
        dec = g.decision(response.headers["x-modelsaar-request-id"])
        observe("invalid_sse", status=response.status_code, body=response.text, outcome=dec["outcome"],
                affinity_stats=g.router.affinity.stats(), circuit_failures=g.router.admission.circuit("ollama").failures)
        assert dec["outcome"] != "ok", "malformed SSE plus DONE was marked a validated completion"
        assert g.router.affinity.stats()["sessions"] == 0, "malformed response pinned session"
    finally:
        g.gw.stop()
        fake.stop()
