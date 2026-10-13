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


# --------------------------------------------------------------------------- #
# Finding 3: effective resource configuration
# --------------------------------------------------------------------------- #


def test_pool_memory_budget_is_enforced_before_dispatch(fake):
    """Finding 3a: memory_gb=1 admitted a deployment with a 20.7 GB estimate."""
    from modelsaar.config import ResourcePool

    g = build_gateway(f"http://127.0.0.1:{fake.port}", resource_pools=(ResourcePool(id="pool", max_concurrent=4, memory_gb=1.0),))
    try:
        n = len(fake.requests)
        r = chat(g, "ollama/big:27b", "hi")  # ~20.7 GB estimate from the fake's size_bytes
        assert r.status_code == 422, r.text
        blockers = r.json()["error"]["modelsaar"]["blockers"]["ollama/big:27b"]
        assert any("memory" in b for b in blockers), blockers
        assert _models_hit(fake, n) == []
        # A small model (0.8 GB) still fits.
        assert chat(g, "ollama/small:1b", "hi").status_code == 200
    finally:
        g.gw.stop()


def test_pool_memory_budget_counts_distinct_reservations_and_unknown_policy(fake):
    """Finding 3a: aggregate reservations stay within the budget; unknown estimates follow policy."""
    from modelsaar.config import ResourcePool

    fake.models["small:1b"].behaviour = "slow"
    g = build_gateway(f"http://127.0.0.1:{fake.port}", resource_pools=(ResourcePool(id="pool", max_concurrent=4, max_queue=0, memory_gb=4.0, memory_margin_gb=0.5),))
    try:
        import threading

        results: list[int] = []

        def one(model: str):
            results.append(chat(g, model, "hi").status_code)

        t = threading.Thread(target=one, args=("ollama/small:1b",))
        t.start()
        import time as _t

        _t.sleep(0.3)
        # small:1b (~0.8 GB) is reserved; plain:3b (~0.8 GB) fits (1.6 + 0.5 <= 4); big:27b does not.
        assert chat(g, "ollama/plain:3b", "hi").status_code == 200
        rb = chat(g, "ollama/big:27b", "hi")
        assert rb.status_code == 422
        t.join()
        assert results == [200]
        st = g.admin.get("/admin/status").json()["admission"]["pool:pool"]
        assert st["memory_gb"] == 4.0 and "memory_reserved_gb" in st
    finally:
        fake.models["small:1b"].behaviour = "ok"
        g.gw.stop()


def test_unknown_memory_estimate_policy(fake):
    from modelsaar.config import BackendConfig, DeclaredModel, ResourcePool

    def gw(policy: str):
        return build_gateway(
            f"http://127.0.0.1:{fake.port}",
            resource_pools=(ResourcePool(id="pool", max_concurrent=4, memory_gb=4.0, unknown_memory_policy=policy),),
            backends=(
                BackendConfig(
                    id="oai",
                    type="openai_compatible",
                    base_url=f"http://127.0.0.1:{fake.port}",
                    resource_pool="pool",
                    models=(DeclaredModel(name="small:1b", context_length=8192),),
                ),
            ),
            deployments=(),
        )

    g = gw("reject")
    try:
        r = chat(g, "oai/small:1b", "hi")
        assert r.status_code == 422
        assert any("unknown" in b and "memory" in b for b in r.json()["error"]["modelsaar"]["blockers"]["oai/small:1b"])
    finally:
        g.gw.stop()
    g = gw("allow")
    try:
        r = chat(g, "oai/small:1b", "hi")
        assert r.status_code == 200
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert any("memory estimate unknown" in n for c in dec["candidates"] for n in c.get("notes", []))
    finally:
        g.gw.stop()


def test_admin_probe_runs_under_gateway_admission(fake):
    """Finding 3b: probes launched while the gateway's one-slot pool is busy must wait, not overlap."""
    import threading
    import time as _t

    from modelsaar.config import ResourcePool

    g = build_gateway(f"http://127.0.0.1:{fake.port}", resource_pools=(ResourcePool(id="pool", max_concurrent=1, max_queue=4, queue_timeout_s=10.0),))
    fake.models["plain:3b"].behaviour = "slow"
    try:
        fake.max_active = 0
        t = threading.Thread(target=lambda: chat(g, "ollama/plain:3b", "occupy"))
        t.start()
        _t.sleep(0.2)
        r = g.admin.post("/admin/probe", json={"deployment": "ollama/small:1b", "which": ["streaming"]})
        t.join()
        assert r.status_code == 200, r.text
        assert r.json()["deployment_id"] == "ollama/small:1b"
        assert fake.max_active == 1, "probe ran concurrently with the occupied one-slot pool"
        # Evidence is visible to the running gateway without a restart.
        d = g.router.registry.get("ollama/small:1b")
        assert d.cap("streaming") == "supported"
    finally:
        fake.models["plain:3b"].behaviour = "ok"
        g.gw.stop()


def test_cli_probe_coordinates_through_running_gateway(fake, tmp_path, capsys):
    """Finding 3b: `modelsaar probe` used a separate Router (two jobs in a one-slot pool)."""
    import threading
    import time as _t

    from modelsaar.cli import main
    from modelsaar.config import ResourcePool, write_config_atomic

    g = build_gateway(f"http://127.0.0.1:{fake.port}", resource_pools=(ResourcePool(id="pool", max_concurrent=1, max_queue=4, queue_timeout_s=10.0),))
    cfg_path = g.tmp / "config.yaml"
    write_config_atomic(g.gw.cfg, cfg_path)
    fake.models["plain:3b"].behaviour = "slow"
    try:
        fake.max_active = 0
        t = threading.Thread(target=lambda: chat(g, "ollama/plain:3b", "occupy"))
        t.start()
        _t.sleep(0.2)
        main(["--config", str(cfg_path), "probe", "ollama/small:1b", "--which", "streaming"])
        t.join()
        out = capsys.readouterr().out
        assert "via gateway" in out
        assert fake.max_active == 1
        # Direct probing while a gateway is listening is refused unless explicitly allowed.
        import pytest

        with pytest.raises(SystemExit):
            main(["--config", str(cfg_path), "probe", "ollama/small:1b", "--which", "streaming", "--offline"])
    finally:
        fake.models["plain:3b"].behaviour = "ok"
        g.gw.stop()


# --------------------------------------------------------------------------- #
# Finding 4: immutable embedding spaces
# --------------------------------------------------------------------------- #


def _embed(g, model: str, inp, **extra):
    body = {"model": model, "input": inp}
    body.update(extra)
    return g.client.post("/v1/embeddings", json=body)


def test_alias_never_interchanges_distinct_models_with_equal_dimensions(fake):
    """Finding 4: two different models (same dims) under one alias switched with residency."""
    from modelsaar.config import EmbeddingContract
    from modelsaar.testing.fakebackend import FakeModel

    fake.models["embed-twin:0.6b"] = FakeModel("embed-twin:0.6b", ["embedding"], 2048, parameter_size="0.6B", embedding_dimensions=8, loaded=True)
    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        embeddings=(EmbeddingContract(alias="docs", deployments=("ollama/embed:0.6b", "ollama/embed-twin:0.6b"), dimensions=8),),
    )
    try:
        r = _embed(g, "docs", ["a"])
        assert r.status_code == 200
        assert r.headers["x-modelsaar-deployment"] == "ollama/embed:0.6b", "resident twin must not be preferred over the contract identity"
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert "identity" in " ".join(dec["exclusions"].get("ollama/embed-twin:0.6b", []))
        del fake.models["embed:0.6b"]
        g.refresh()
        r = _embed(g, "docs", ["a"])
        assert r.status_code == 422
        assert "re-index" in " ".join(r.json()["error"]["modelsaar"]["remedies"])
    finally:
        fake.models.pop("embed-twin:0.6b", None)
        g.gw.stop()


def test_known_identical_replicas_share_an_alias(fake):
    """Finding 4: same digest on two backends is a verified replica set."""
    from modelsaar.config import BackendConfig, EmbeddingContract

    twin = FakeBackend(make_models())
    twin.start()
    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        backends=(
            BackendConfig(id="ollama", type="ollama", base_url=f"http://127.0.0.1:{fake.port}", resource_pool="pool", max_concurrent=4),
            BackendConfig(id="second", type="ollama", base_url=f"http://127.0.0.1:{twin.port}", resource_pool="pool", max_concurrent=4),
        ),
        embeddings=(EmbeddingContract(alias="docs", deployments=("ollama/embed:0.6b", "second/embed:0.6b"), dimensions=8),),
    )
    try:
        r = _embed(g, "docs", "a")
        assert r.status_code == 200
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert dec["exclusions"] == {}
        del fake.models["embed:0.6b"]
        g.refresh()
        r = _embed(g, "docs", "a")
        assert r.status_code == 200 and r.headers["x-modelsaar-deployment"] == "second/embed:0.6b"
    finally:
        g.gw.stop()
        twin.stop()


def test_unknown_identity_is_not_a_verified_replica(fake):
    """Finding 4: a name match on a generic endpoint without a declared identity proves nothing."""
    from modelsaar.config import BackendConfig, DeclaredModel, EmbeddingContract

    def gw(identity):
        return build_gateway(
            f"http://127.0.0.1:{fake.port}",
            backends=(
                BackendConfig(id="ollama", type="ollama", base_url=f"http://127.0.0.1:{fake.port}", resource_pool="pool", max_concurrent=4),
                BackendConfig(
                    id="oai",
                    type="openai_compatible",
                    base_url=f"http://127.0.0.1:{fake.port}",
                    resource_pool="pool",
                    models=(DeclaredModel(name="embed:0.6b", role="embedding", embedding_dimensions=8, identity=identity),),
                ),
            ),
            embeddings=(EmbeddingContract(alias="docs", deployments=("ollama/embed:0.6b", "oai/embed:0.6b"), dimensions=8),),
        )

    g = gw(None)
    try:
        r = _embed(g, "docs", "a")
        assert r.status_code == 200
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert any("identity unknown" in x for x in dec["exclusions"].get("oai/embed:0.6b", []))
        digest = g.router.registry.get("ollama/embed:0.6b").identity
    finally:
        g.gw.stop()
    g = gw(digest)
    try:
        r = _embed(g, "docs", "a")
        assert r.status_code == 200
        assert g.decision(r.headers["x-modelsaar-request-id"])["exclusions"] == {}
    finally:
        g.gw.stop()


def test_wrong_output_shape_is_a_contract_error(fake):
    """Finding 4: an 8-d contract returned 200 when the backend produced 4-d vectors."""
    from modelsaar.config import EmbeddingContract

    g = build_gateway(f"http://127.0.0.1:{fake.port}", embeddings=(EmbeddingContract(alias="docs", deployments=("ollama/embed:0.6b",), dimensions=8),))
    try:
        assert _embed(g, "docs", ["a", "b"]).status_code == 200
        fake.models["embed:0.6b"].embedding_dimensions = 4
        r = _embed(g, "docs", ["a", "b"])
        assert r.status_code == 502, r.text
        assert r.json()["error"]["code"] == "embedding_contract_violation"
        fake.models["embed:0.6b"].embedding_dimensions = 8
        fake.models["embed:0.6b"].normalize_embeddings = False
        r = _embed(g, "docs", ["a"])
        assert r.status_code == 502 and "normal" in r.json()["error"]["message"]
    finally:
        fake.models["embed:0.6b"].embedding_dimensions = 8
        fake.models["embed:0.6b"].normalize_embeddings = True
        g.gw.stop()


def test_request_level_contract_changes_rejected(fake):
    from modelsaar.config import EmbeddingContract

    g = build_gateway(f"http://127.0.0.1:{fake.port}", embeddings=(EmbeddingContract(alias="docs", deployments=("ollama/embed:0.6b",), dimensions=8),))
    try:
        r = _embed(g, "docs", "a", dimensions=4)
        assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_contract_option"
        r = _embed(g, "docs", "a", encoding_format="base64")
        assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_contract_option"
        assert _embed(g, "docs", "a", dimensions=8, encoding_format="float").status_code == 200
    finally:
        g.gw.stop()


# --------------------------------------------------------------------------- #
# Finding 5: evidence identity and invalidation
# --------------------------------------------------------------------------- #


def test_endpoint_change_invalidates_stored_probe(fake):
    """Finding 5: a replacement endpoint under the same backend id/model name inherited a stored
    successful tools probe although the new server lacks tool support."""
    from modelsaar.config import BackendConfig, DeclaredModel
    from modelsaar.testing.fakebackend import FakeModel

    def gw(port: int):
        return build_gateway(
            f"http://127.0.0.1:{port}",
            backends=(
                BackendConfig(
                    id="oai",
                    type="openai_compatible",
                    base_url=f"http://127.0.0.1:{port}",
                    resource_pool="pool",
                    models=(DeclaredModel(name="small:1b", context_length=8192),),
                ),
            ),
            deployments=(),
        )

    g = gw(fake.port)
    try:
        r = g.admin.post("/admin/probe", json={"deployment": "oai/small:1b", "which": ["tools"]})
        assert r.status_code == 200 and any(x["capability"] == "tools" and x["value"] == "supported" for x in r.json()["results"])
        assert g.router.registry.get("oai/small:1b").cap("tools") == "supported"
        fp1 = g.router.registry.get("oai/small:1b").fingerprint
        state_dir = g.tmp
    finally:
        g.gw.stop()
    # Same backend id and model name, different endpoint without tool support.
    other = FakeBackend([FakeModel("small:1b", ["completion"], 8192, parameter_size="1.0B")])
    other.start()
    g2 = _gateway_with_state(state_dir, other.port)
    try:
        d = g2.router.registry.get("oai/small:1b")
        assert d.fingerprint != fp1, "fingerprint ignored the endpoint"
        assert d.cap("tools") != "supported", "stored probe from the old endpoint was inherited"
        assert fp1 in (d.raw_metadata.get("invalidated_probe_fingerprints") or [])
    finally:
        g2.gw.stop()
        other.stop()


def _gateway_with_state(state_dir, port: int):
    """A gateway reusing an existing state directory (keys + DB) with a replaced oai endpoint."""
    import httpx
    from conftest import Gateway

    from modelsaar.config import BackendConfig, Config, DeclaredModel, ResourcePool, read_keys
    from modelsaar.runtime import GatewayThread, free_port

    api = read_keys(state_dir / "keys/api_keys")[0]
    adm = read_keys(state_dir / "keys/admin_key")[0]
    cfg = Config(
        resource_pools=(ResourcePool(id="pool", max_concurrent=2, max_queue=2, queue_timeout_s=2.0),),
        backends=(
            BackendConfig(id="oai", type="openai_compatible", base_url=f"http://127.0.0.1:{port}", resource_pool="pool", models=(DeclaredModel(name="small:1b", context_length=8192),)),
        ),
        deployments=(),
    )
    cfg = cfg.model_copy(update={"server": cfg.server.model_copy(update={"port": free_port(), "residency_refresh_s": 0.5, "discovery_refresh_s": 3600}), "config_path": str(state_dir / "config.yaml"), "config_hash": "test2"})
    gw = GatewayThread(cfg)
    gw.start()
    g = Gateway(gw, api, adm, state_dir)
    g.client = httpx.Client(base_url=gw.url, headers={"Authorization": f"Bearer {api}"}, timeout=30)
    g.admin = httpx.Client(base_url=gw.url, headers={"Authorization": f"Bearer {adm}"}, timeout=30)
    return g


def test_load_unload_keeps_evidence(gateway, fake):
    """Finding 5 (preserved fix): residency and served context changes are not identity changes."""
    d = gateway.router.registry.get("ollama/big:27b")
    fp = d.fingerprint
    fake.models["big:27b"].loaded = not fake.models["big:27b"].loaded
    gateway.refresh()
    assert gateway.router.registry.get("ollama/big:27b").fingerprint == fp


def test_evidence_scheme_versioning_invalidates_old_rows(tmp_path):
    """Finding 5: evidence written by the previous scheme / defective evaluator is not loaded."""
    import sqlite3
    import time

    from modelsaar.store import EVIDENCE_SCHEME, Store

    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE probes (deployment_id TEXT NOT NULL, fingerprint TEXT NOT NULL, capability TEXT NOT NULL,
          value TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', checked_at REAL NOT NULL,
          PRIMARY KEY (deployment_id, fingerprint, capability));
        CREATE TABLE measurements (deployment_id TEXT NOT NULL, fingerprint TEXT NOT NULL, task TEXT NOT NULL,
          quality REAL, samples INTEGER NOT NULL DEFAULT 0, p50_ms REAL, p95_ms REAL, ttft_ms REAL, load_ms REAL,
          source TEXT NOT NULL DEFAULT 'eval', measured_at REAL NOT NULL,
          PRIMARY KEY (deployment_id, fingerprint, task, source));
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    conn.execute("INSERT INTO probes VALUES ('b/m','fp1','tools','supported','',?)", (time.time(),))
    conn.execute("INSERT INTO measurements VALUES ('b/m','fp1','coding',0.9,10,100,200,NULL,NULL,'eval',?)", (time.time(),))
    conn.commit()
    conn.close()
    s = Store(db)
    try:
        assert s.get_meta("evidence_scheme") == str(EVIDENCE_SCHEME)
        assert s.load_probes("b/m", "fp1") == {}
        assert s.load_measurements("b/m", "fp1") == []
        inv = s.invalidated_counts()
        assert inv["probes"] == 1 and inv["measurements"] == 1
        s.save_measurement("b/m", "fp1", {"task": "coding", "quality": 0.5, "samples": 4, "source": "eval", "conditions": {"max_tokens": 1024, "scorer_version": "x"}})
        rows = s.load_measurements("b/m", "fp1")
        assert rows and rows[0]["conditions"]["max_tokens"] == 1024
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# Finding 7: first-run and file handling
# --------------------------------------------------------------------------- #


def _cli(args: list[str], env: dict[str, str]):
    import os
    import subprocess
    import sys

    return subprocess.run([sys.executable, "-m", "modelsaar.cli", *args], capture_output=True, text=True, env={**os.environ, **env}, timeout=120)


def test_apply_patch_preserves_mode_private_tmp_unique_backups(tmp_path, monkeypatch):
    """Finding 7: applying a client config turned a 0600 secret-bearing YAML into 0644 under umask 022."""
    import os
    import stat

    from modelsaar.clientconfig import AliasInfo, ClientTarget, apply_patch

    monkeypatch.setattr(os, "umask", os.umask)  # no-op; documents the assumption
    old = os.umask(0o022)
    try:
        t = ClientTarget("http://127.0.0.1:8484", aliases=[AliasInfo("auto", 32768, True, False)])
        hz = tmp_path / "config.yaml"
        hz.write_text("model:\n  default: foo\napi_key: secret-value\n")
        os.chmod(hz, 0o600)
        res = apply_patch("hermes", t, hz, dry_run=False)
        assert res["applied"]
        assert stat.S_IMODE(hz.stat().st_mode) == 0o600, "mode weakened"
        assert stat.S_IMODE(os.stat(res["backup"]).st_mode) == 0o600, "backup weaker than the original"
        assert not list(tmp_path.glob("*.tmp"))
        # A second change in the same second must not overwrite the first backup.
        hz.write_text(hz.read_text().replace("127.0.0.1:8484", "127.0.0.1:9999"))  # drift that the patch repairs
        res2 = apply_patch("hermes", t, hz, dry_run=False)
        assert res2["applied"] and res2["backup"] != res["backup"]
        assert len(list(tmp_path.glob("config.yaml.bak-*"))) == 2
        # New files are created private (they carry the gateway API key).
        new = tmp_path / "new" / "config.yaml"
        res3 = apply_patch("hermes", t, new, dry_run=False)
        assert res3["applied"] and stat.S_IMODE(new.stat().st_mode) == 0o600
    finally:
        os.umask(old)


def test_uninstall_removes_only_owned_files_and_refuses_symlinks(tmp_path):
    """Finding 7: uninstall deleted arbitrary contents beneath keys/ and state/."""
    import os

    home = tmp_path / "home"
    (home / "keys").mkdir(parents=True)
    (home / "state").mkdir()
    (home / "config.yaml").write_text("version: 1\n")
    (home / "keys/api_keys").write_text("msk_x\n")
    (home / "keys/admin_key").write_text("msa_x\n")
    (home / "state/modelsaar.db").write_bytes(b"")
    (home / "state/modelsaar.db-wal").write_bytes(b"")
    (home / "keys/my-private-notes.txt").write_text("keep me")
    (home / "state/other.db").write_text("keep me too")
    r = _cli(["uninstall", "--yes"], {"MODELSAAR_HOME": str(home)})
    assert r.returncode == 0, r.stderr
    assert not (home / "config.yaml").exists() and not (home / "keys/api_keys").exists() and not (home / "state/modelsaar.db").exists()
    assert (home / "keys/my-private-notes.txt").exists() and (home / "state/other.db").exists()
    assert "left in place" in r.stdout
    # Symlinked boundaries are refused (nothing deleted through them).
    home2 = tmp_path / "home2"
    home2.mkdir()
    (home2 / "config.yaml").write_text("version: 1\n")
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "api_keys").write_text("msk_y\n")
    os.symlink(target, home2 / "keys")
    r = _cli(["uninstall", "--yes"], {"MODELSAAR_HOME": str(home2)})
    assert r.returncode != 0 and "symlink" in r.stderr
    assert (target / "api_keys").exists() and (home2 / "config.yaml").exists()


def test_keys_ensure_is_idempotent_and_serve_points_to_it(tmp_path, fake):
    """Finding 7: a fresh container exited for missing keys although docs promised first-start creation."""
    home = tmp_path / "home"
    env = {"MODELSAAR_HOME": str(home)}
    assert _cli(["init", "--endpoint", f"http://127.0.0.1:{fake.port}", "--type", "ollama"], env).returncode == 0
    (home / "keys/api_keys").unlink()
    (home / "keys/admin_key").unlink()
    r = _cli(["keys", "ensure"], env)
    assert r.returncode == 0 and "created" in r.stdout
    api = (home / "keys/api_keys").read_text()
    r = _cli(["keys", "ensure"], env)
    assert r.returncode == 0 and "unchanged" in r.stdout
    assert (home / "keys/api_keys").read_text() == api, "ensure must never rotate"
    import stat

    assert stat.S_IMODE((home / "keys/api_keys").stat().st_mode) == 0o600
    # Config may be a read-only mount: ensure writes only under keys/.
    import os

    os.chmod(home / "config.yaml", 0o444)
    assert _cli(["keys", "ensure"], env).returncode == 0


def test_init_profile_applies_to_auto_alias(tmp_path, fake):
    """Finding 7: `init --profile fast` set routing.default_profile only; `auto` kept quality."""
    import yaml

    home = tmp_path / "home"
    env = {"MODELSAAR_HOME": str(home)}
    r = _cli(["init", "--endpoint", f"http://127.0.0.1:{fake.port}", "--type", "ollama", "--profile", "fast"], env)
    assert r.returncode == 0, r.stderr
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert cfg["routing"]["default_profile"] == "fast"
    assert cfg["aliases"]["auto"]["profile"] == "fast"
    r = _cli(["explain", "--message", "hello", "--json"], env)
    assert r.returncode == 0, r.stderr
    import json

    assert json.loads(r.stdout)["profile"] == "fast"


def test_cli_test_explains_missing_gateway(tmp_path, fake):
    """First-run UX: `modelsaar test` without a running gateway must say so instead of a traceback."""
    home = tmp_path / "home"
    env = {"MODELSAAR_HOME": str(home)}
    assert _cli(["init", "--endpoint", f"http://127.0.0.1:{fake.port}", "--type", "ollama", "--port", "1"], env).returncode == 0
    r = _cli(["test"], env)
    assert r.returncode != 0
    assert "no gateway is listening" in r.stderr and "modelsaar serve" in r.stderr
    assert "Traceback" not in r.stderr
