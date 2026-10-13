"""Bounded closure checks for R2/R4 at hardening5cb7443.

Only real loopback HTTP fixtures; no real inference or large allocations.
Checks focus on correction interactions (observation failure, dispatch phase,
and terminal stream ordering), not unrelated features.
"""
from __future__ import annotations

import json

import pytest
from conftest import build_gateway, chat, make_models
from starlette.responses import JSONResponse, StreamingResponse

from modelsaar.config import BackendConfig, DeclaredModel, DeploymentOverride, ResourcePool
from modelsaar.testing.fakebackend import FakeBackend


def observe(case, **values):
    print("OBSERVATION " + json.dumps({"case": case, **values}, sort_keys=True))


class ResidencyBackend(FakeBackend):
    fail_ps = False

    async def api_ps(self, request):
        if self.fail_ps:
            return JSONResponse({"error": "synthetic residency query failure"}, status_code=500)
        return await super().api_ps(request)

    async def v1_chat(self, request):
        body = await request.json()
        self.models[body["model"]].loaded = True
        return await super().v1_chat(request)


@pytest.mark.parametrize("fail_ps", [True, False], ids=["failed-observation-regression", "successful-observation-control"])
def test_r2_failed_residency_query_cannot_erase_loaded_weights(fail_ps):
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
        assert first.status_code == 200
        before = g.admin.get("/admin/status").json()["admission"]["pool:pool"]
        assert before["memory_assumed_resident"] == ["ollama/small:1b"]
        fake.fail_ps = fail_ps
        refresh = g.admin.post("/admin/refresh")
        candidate = g.router.registry.get("ollama/plain:3b")
        view = g.router.admission.memory_view(candidate)
        second = chat(g, "ollama/plain:3b", "hello")
        observe("r2_failed_residency", fail_ps=fail_ps, refresh_status=refresh.status_code,
                refresh_body=refresh.json(), first_status=first.status_code, second_status=second.status_code,
                memory_before_second=view,
                router_first_loaded=g.router.registry.get("ollama/small:1b").loaded,
                backend_residents=[m.name for m in fake.models.values() if m.loaded],
                backend_dispatches=len(fake.requests), budget_gb=5, per_model_gb=3)
        assert second.status_code != 200, "failed /api/ps was treated as a verified empty resident set and over-budget dispatch proceeded"
        assert len(fake.requests) == 1
    finally:
        g.gw.stop()
        fake.stop()


@pytest.mark.parametrize("first_backend_online", [False, True], ids=["connect-failure-regression", "successful-dispatch-control"])
def test_r2_refused_connection_does_not_create_phantom_residency(first_backend_online):
    a = FakeBackend(make_models())
    b = FakeBackend(make_models())
    a.start()
    b.start()
    g = build_gateway(
        f"http://127.0.0.1:{a.port}",
        resource_pools=(ResourcePool(id="pool", max_concurrent=2, memory_gb=5.0),),
        backends=(
            BackendConfig(id="a", type="openai_compatible", base_url=f"http://127.0.0.1:{a.port}", discover=False,
                          resource_pool="pool", models=(DeclaredModel(name="small:1b", context_length=8192, memory_gb_estimate=3.0),)),
            BackendConfig(id="b", type="openai_compatible", base_url=f"http://127.0.0.1:{b.port}", discover=False,
                          resource_pool="pool", models=(DeclaredModel(name="small:1b", context_length=8192, memory_gb_estimate=3.0),)),
        ),
        deployments=(),
    )
    try:
        if not first_backend_online:
            a.stop()
        response = chat(g, "auto", "hello")
        admission = g.admin.get("/admin/status").json()["admission"]["pool:pool"]
        dec = g.decision(response.headers["x-modelsaar-request-id"])
        observe("r2_connect_failure", first_backend_online=first_backend_online, response_status=response.status_code,
                first_backend_dispatches=len(a.requests), second_backend_dispatches=len(b.requests),
                admission=admission, decision_outcome=dec["outcome"], failover=dec["failover"], chosen=dec["chosen"])
        assert response.status_code == 200, "a refused connection created phantom model weights and blocked otherwise feasible failover"
        if not first_backend_online:
            assert len(a.requests) == 0 and len(b.requests) == 1
            assert "a/small:1b" not in admission["memory_assumed_resident"]
    finally:
        g.gw.stop()
        if first_backend_online:
            a.stop()
        b.stop()


class StreamBackend(FakeBackend):
    malformed = True

    async def v1_chat(self, request):
        await request.json()

        async def events():
            yield b'data: {"id":"c","object":"chat.completion.chunk","model":"small:1b","choices":[{"index":0,"delta":{"role":"assistant","content":"partial"},"finish_reason":null}]}\n\n'
            if self.malformed:
                yield b'data: not-json\n\n'
            else:
                yield b'data: {"id":"c","object":"chat.completion.chunk","model":"small:1b","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            yield b'data: [DONE]\n\n'

        return StreamingResponse(events(), media_type="text/event-stream")


@pytest.mark.parametrize("malformed", [True, False], ids=["terminal-order-regression", "valid-stream-control"])
def test_r4_stream_error_reaches_client_before_terminal_done(malformed):
    fake = StreamBackend(make_models())
    fake.malformed = malformed
    fake.start()
    g = build_gateway(f"http://127.0.0.1:{fake.port}")
    try:
        response = chat(g, "ollama/small:1b", "hello", stream=True)
        frames = [s.strip() for s in response.text.split("\n\n") if s.strip()]
        first_done = frames.index("data: [DONE]")
        client_visible = frames[:first_done + 1]
        dec = g.decision(response.headers["x-modelsaar-request-id"])
        observe("r4_terminal_order", malformed=malformed, response_status=response.status_code,
                all_frames=frames, client_visible_until_done=client_visible,
                decision_outcome=dec["outcome"])
        has_visible_error = any("upstream_stream_error" in frame for frame in client_visible)
        assert has_visible_error is malformed, "malformed-stream error was emitted after [DONE], where a correctly terminating client never reads it"
        assert frames.count("data: [DONE]") == 1, "terminal sentinel must appear once after the final error/completion event"
    finally:
        g.gw.stop()
        fake.stop()
