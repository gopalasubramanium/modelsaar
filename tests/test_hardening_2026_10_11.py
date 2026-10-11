"""Regression tests for the 2026-10-11 hardening review (findings 1-8).

Each test encodes the desired behaviour; it failed against commit 1122e1f for the
observed defect named in its docstring.
"""

from __future__ import annotations

from conftest import build_gateway, chat, make_models

from modelsaar.config import BackendConfig, Capabilities, DeclaredModel
from modelsaar.testing.fakebackend import FakeBackend

# --------------------------------------------------------------------------- #
# Finding 1: privacy before payload operations
# --------------------------------------------------------------------------- #


def _two_backends(fake, remote: FakeBackend, **cfg):
    """Local ollama fake + a second openai_compatible fake declared remote."""
    return build_gateway(
        f"http://127.0.0.1:{fake.port}",
        backends=(
            BackendConfig(id="ollama", type="ollama", base_url=f"http://127.0.0.1:{fake.port}", resource_pool="pool", max_concurrent=4),
            BackendConfig(
                id="cloud",
                type="openai_compatible",
                base_url=f"http://127.0.0.1:{remote.port}",
                resource_pool="pool",
                locality="remote",
                models=(DeclaredModel(name="small:1b", context_length=8192, capabilities=Capabilities(tools="supported")),),
            ),
        ),
        deployments=(),
        **cfg,
    )


def test_local_only_sends_no_message_text_to_remote_tokenizer(fake):
    """Finding 1a: at 1122e1f `_exact_counts` ran before policy filtering and posted the prompt to
    every deployment with a /tokenize endpoint, including remote ones under local_only."""
    remote = FakeBackend(make_models())
    remote.start()
    g = _two_backends(fake, remote)
    try:
        # Borderline length for an 8k context so exact counting is attempted at all.
        r = chat(g, "auto", "word " * 1400, max_tokens=6000)
        assert r.status_code in (200, 422)
        assert remote.tokenize_requests == [], "remote backend received message text under local_only"
        assert remote.requests == []
    finally:
        g.gw.stop()
        remote.stop()


def test_exact_counts_only_for_policy_allowed_and_labelled_as_estimate(fake):
    """Finding 1a: exact counts are taken only for deployments that passed every non-context
    filter, and the method label does not claim exactness for the template overhead."""
    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        backends=(
            BackendConfig(
                id="oai",
                type="openai_compatible",
                base_url=f"http://127.0.0.1:{fake.port}",
                resource_pool="pool",
                models=(
                    DeclaredModel(name="small:1b", context_length=8192, capabilities=Capabilities(tools="supported")),
                    # Disabled: must never be tokenized for.
                    DeclaredModel(name="plain:3b", context_length=8192, enabled=False),
                ),
            ),
        ),
        deployments=(),
    )
    try:
        fake.tokenize_requests.clear()
        r = chat(g, "auto", "word " * 1400, max_tokens=6000)
        assert r.status_code == 200
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert [t["model"] for t in fake.tokenize_requests] == ["small:1b"]
        note = dec.get("requirements_note", "")
        assert "tokenize:oai+template-estimate" in note
        assert "exact" not in note.lower()
    finally:
        g.gw.stop()


def test_unsupported_content_part_types_rejected_before_any_dispatch(gateway, fake):
    """Finding 1c: audio_url / video_url / file parts were silently flattened and forwarded."""
    before = len(fake.requests)
    for part in (
        {"type": "audio_url", "audio_url": {"url": "data:audio/wav;base64,AAAA"}},
        {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,AAAA"}},
        {"type": "file", "file": {"file_data": "AAAA"}},
    ):
        r = gateway.client.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}, part]}]},
        )
        assert r.status_code == 400, r.text
        assert r.json()["error"]["code"] == "unsupported_content_type"
    assert len(fake.requests) == before
    assert fake.tokenize_requests == []


def test_classifier_requires_local_deployment_under_local_only(fake):
    """Finding 1b: the classifier excerpt must not leave the host unless explicitly allowed twice."""
    from modelsaar.config import ClassifierConfig, RoutingConfig

    remote = FakeBackend(make_models())
    remote.start()
    g = _two_backends(
        fake,
        remote,
        routing=RoutingConfig(classifier=ClassifierConfig(enabled=True, backend="cloud", model="small:1b", only_when_ambiguous=False)),
    )
    try:
        r = chat(g, "auto", "please")
        assert r.status_code == 200
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert dec["classifier"]["used"] is False
        assert "local" in dec["classifier"]["note"]
        assert remote.requests == []
    finally:
        g.gw.stop()
        remote.stop()


# --------------------------------------------------------------------------- #
# Finding 2: dispatch, continuity and completion contract
# --------------------------------------------------------------------------- #

TOOLS = [{"type": "function", "function": {"name": "bash", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}}]


def _models_hit(fake, since: int) -> list[str]:
    return [r["model"] for r in fake.requests[since:]]


def test_no_failover_for_tool_result_turn(gateway, fake):
    """Finding 2a: a tool round trip started on one model must fail rather than be handed to another."""
    content = [{"type": "text", "text": "look and list"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    r1 = chat(gateway, "auto", content, tools=TOOLS)
    assert r1.headers["x-modelsaar-deployment"] == "ollama/big:27b"
    calls = r1.json()["choices"][0]["message"]["tool_calls"]
    msgs = [
        {"role": "user", "content": "list"},
        {"role": "assistant", "content": None, "tool_calls": calls},
        {"role": "tool", "tool_call_id": calls[0]["id"], "content": "ok"},
    ]
    fake.models["big:27b"].behaviour = "error_500"
    try:
        n = len(fake.requests)
        r = gateway.client.post("/v1/chat/completions", json={"model": "auto", "messages": msgs, "tools": TOOLS})
        assert r.status_code == 502, r.text
        assert _models_hit(fake, n) == ["big:27b"], "failover switched models inside a tool round trip"
        dec = gateway.decision(r.headers["x-modelsaar-request-id"])
        assert dec["failover_allowed"] is False
        assert "tool" in dec["failover_note"]
    finally:
        fake.models["big:27b"].behaviour = "ok"


def test_no_failover_for_pinned_session(gateway, fake):
    """Finding 2a: a session pinned to a deployment is not silently moved by failover."""
    h = {"X-ModelSaar-Session": "sess-1"}
    r = gateway.client.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]}, headers=h)
    assert r.status_code == 200
    pinned = r.headers["x-modelsaar-deployment"]
    name = pinned.split("/", 1)[1]
    fake.models[name].behaviour = "error_500"
    try:
        n = len(fake.requests)
        r = gateway.client.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "again"}]}, headers=h)
        assert r.status_code == 502, r.text
        assert _models_hit(fake, n) == [name]
        dec = gateway.decision(r.headers["x-modelsaar-request-id"])
        assert dec["failover_allowed"] is False
        assert "pinned" in dec["failover_note"]
    finally:
        fake.models[name].behaviour = "ok"


def test_timeout_holds_slot_uncertain_then_recovers(fake):
    """Finding 2b: a read timeout released the slot immediately although the backend may still be busy."""
    from modelsaar.config import AdmissionConfig, ResourcePool, ServerConfig

    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        resource_pools=(ResourcePool(id="pool", max_concurrent=1, max_queue=0, queue_timeout_s=0.2),),
        admission=AdmissionConfig(uncertain_hold_s=1.0),
        server=ServerConfig(request_timeout_s=0.3),
    )
    fake.models["small:1b"].behaviour = "stall"
    try:
        r = chat(g, "ollama/small:1b", "x")
        assert r.status_code == 504, r.text
        stats = g.admin.get("/admin/status").json()["admission"]
        assert stats["pool:pool"]["uncertain"] == 1
        fake.models["small:1b"].behaviour = "ok"
        r2 = chat(g, "ollama/small:1b", "y")
        assert r2.status_code in (429, 503), "slot was free although the backend may still be generating"
        import time as _t

        _t.sleep(1.6)
        r3 = chat(g, "ollama/small:1b", "z")
        assert r3.status_code == 200
    finally:
        fake.models["small:1b"].behaviour = "ok"
        g.gw.stop()


def test_circuit_opens_on_truncated_streams(fake):
    """Finding 2c: success was recorded at stream-header time, so truncations never opened the circuit."""
    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        backends=(BackendConfig(id="ollama", type="ollama", base_url=f"http://127.0.0.1:{fake.port}", resource_pool="pool", max_concurrent=4, circuit_failure_threshold=3),),
    )
    fake.models["small:1b"].behaviour = "truncate_stream"
    try:
        for _ in range(4):
            with g.client.stream("POST", "/v1/chat/completions", json={"model": "ollama/small:1b", "stream": True, "messages": [{"role": "user", "content": "hi"}]}) as r:
                if r.status_code == 200:
                    b"".join(r.iter_bytes())
        assert g.router.admission.circuit("ollama").is_open()
    finally:
        fake.models["small:1b"].behaviour = "ok"
        g.gw.stop()


def test_response_model_follows_failover_target(gateway, fake):
    """Finding 2d: with response_model_field=deployment the body named the first (failed) deployment."""
    from modelsaar.config import ServerConfig

    g = build_gateway(f"http://127.0.0.1:{fake.port}", server=ServerConfig(response_model_field="deployment"))
    fake.models["small:1b"].behaviour = "error_500"
    try:
        r = chat(g, "auto", "hello")
        assert r.status_code == 200
        assert r.json()["model"] == r.headers["x-modelsaar-deployment"] != "ollama/small:1b"
    finally:
        fake.models["small:1b"].behaviour = "ok"
        g.gw.stop()


def test_html_200_is_a_typed_502_and_never_pins(gateway, fake):
    """Finding 2e: a 200 with a non-OpenAI envelope was relayed as success with model rewritten."""
    fake.models["small:1b"].behaviour = "bad_json"
    h = {"X-ModelSaar-Session": "sess-html"}
    try:
        r = gateway.client.post("/v1/chat/completions", json={"model": "ollama/small:1b", "messages": [{"role": "user", "content": "hi"}]}, headers=h)
        assert r.status_code == 502, r.text
        assert r.json()["error"]["code"] == "upstream_bad_response"
        with gateway.client.stream("POST", "/v1/chat/completions", json={"model": "ollama/small:1b", "stream": True, "messages": [{"role": "user", "content": "hi"}]}, headers=h) as rs:
            assert rs.status_code == 502
        dec = gateway.decision(r.headers["x-modelsaar-request-id"])
        assert dec["outcome"] != "ok"
        assert dec["affinity"].get("status") != "found"
        # A later request in the same session must not have been pinned to the bad deployment.
        fake.models["small:1b"].behaviour = "ok"
        r2 = gateway.client.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]}, headers=h)
        dec2 = gateway.decision(r2.headers["x-modelsaar-request-id"])
        assert dec2["affinity"]["status"] == "new"
    finally:
        fake.models["small:1b"].behaviour = "ok"
