"""Continuation capability: the probe that checks a backend accepts an assistant history carrying
``reasoning_content`` (the follow-up shape agentic clients such as Odysseus send), and the 422 remedy
that must point only at probes that exist."""

from __future__ import annotations

from conftest import build_gateway

ODYSSEUS_HISTORY = [
    {"role": "user", "content": "Give me two short tips for keeping a desk tidy."},
    {
        "role": "assistant",
        "content": "1. Clear it at the end of each day. 2. Keep only today's papers on it.",
        "reasoning_content": "The user wants brief practical tips. Two is enough. Keep them concrete.",
    },
    {"role": "user", "content": "Thanks. Add one more tip about cables."},
]


def _run(gateway, dep_id: str, **kw):
    from modelsaar.probes import run_probes

    r = gateway.router
    dep = r.registry.get(dep_id)
    return gateway.gw.run(run_probes(r.adapters["ollama"], dep, gateway.gw.store, ["continuation"], **kw)), dep


def test_probeable_set_matches_probe_names():
    from modelsaar.probes import PROBE_NAMES
    from modelsaar.routing.eligibility import _PROBEABLE

    assert _PROBEABLE == PROBE_NAMES - {"latency"}
    assert "continuation" in PROBE_NAMES


def test_probe_sends_the_reasoning_history_shape(gateway, fake):
    """The probe's own request carries reasoning_content on an assistant message — success is about
    *that* request being accepted, not about any other chat request returning 200."""
    from modelsaar.probes import _CONTINUATION_HISTORY

    assistant = [m for m in _CONTINUATION_HISTORY if m["role"] == "assistant"]
    assert assistant and assistant[0]["reasoning_content"] and assistant[0]["content"]
    assert _CONTINUATION_HISTORY[-1]["role"] == "user"
    before = len(fake.requests)
    rep, dep = _run(gateway, "ollama/big:27b")
    sent = fake.requests[before:]
    assert len(sent) == 1 and sent[0]["model"] == "big:27b" and sent[0]["stream"] is False


def test_probe_continuation_supported_and_stored(gateway, fake):
    rep, dep = _run(gateway, "ollama/big:27b")
    res = {x.capability: x for x in rep.results}["continuation"]
    assert res.value == "supported", res.note
    assert "protocol acceptance" in res.note and not res.uncertain
    assert dep.cap("continuation") == "supported" and dep.capabilities["continuation"].provenance == "probe"
    gateway.refresh()
    assert gateway.router.registry.get("ollama/big:27b").capabilities["continuation"].provenance == "probe"


def test_probe_continuation_explicit_rejection_is_unsupported(gateway, fake):
    fake.models["plain:3b"].reject_reasoning_history = True
    try:
        rep, dep = _run(gateway, "ollama/plain:3b")
    finally:
        fake.models["plain:3b"].reject_reasoning_history = False
    res = {x.capability: x for x in rep.results}["continuation"]
    assert res.value == "unsupported" and "HTTP 400" in res.note and "reasoning_content" in res.note
    assert dep.cap("continuation") == "unsupported" and dep.capabilities["continuation"].provenance == "probe"


def test_probe_continuation_transient_error_stays_unknown(gateway, fake):
    fake.models["plain:3b"].behaviour = "error_500"
    try:
        rep, dep = _run(gateway, "ollama/plain:3b")
    finally:
        fake.models["plain:3b"].behaviour = "ok"
    res = {x.capability: x for x in rep.results}["continuation"]
    assert res.value == "unknown" and "500" in res.note and not res.uncertain
    assert dep.cap("continuation") == "unknown", "a transient failure must not become a false unsupported"
    assert not rep.uncertain and not rep.errors


def test_probe_continuation_timeout_is_uncertain(gateway, fake):
    fake.models["plain:3b"].behaviour = "hang"
    try:
        rep, dep = _run(gateway, "ollama/plain:3b", timeout=1.0)
    finally:
        fake.models["plain:3b"].behaviour = "ok"
    res = {x.capability: x for x in rep.results}["continuation"]
    assert res.value == "unknown" and res.uncertain and rep.uncertain
    assert dep.cap("continuation") == "unknown"


def test_odysseus_history_routes_only_after_probe_or_override(gateway, fake):
    """Unprobed: 422 with a remedy naming a probe that exists (and the separate context-length note).
    After the probe: the same request routes to the probed deployment with needs_continuation recorded."""
    body = {"model": "auto", "messages": ODYSSEUS_HISTORY, "max_tokens": 64}
    r = gateway.client.post("/v1/chat/completions", json=body)
    assert r.status_code == 422, r.text
    err = r.json()["error"]
    assert err["code"] == "no_eligible_deployment"
    dec = gateway.decision(err["modelsaar"]["request_id"])
    assert dec["requirements"]["needs_continuation"] is True
    assert all(any("continuation is unknown" in why for why in whys) for whys in dec["exclusions"].values())
    remedies = " || ".join(dec["remedies"])
    assert "--which continuation" in remedies
    assert "raising context_length/num_ctx does not establish continuation support" in remedies
    # The old wording pointed at a bare `modelsaar probe <dep>` as if it verified continuation; it must be gone.
    assert "to verify continuation, or declare it in config" not in remedies

    # Probe through the gateway's admin endpoint (admission-coordinated), as the CLI does.
    p = gateway.admin.post("/admin/probe", json={"deployment": "ollama/big:27b", "which": ["continuation"], "timeout": 30})
    assert p.status_code == 200, p.text
    assert {x["capability"]: x["value"] for x in p.json()["results"]}["continuation"] == "supported"
    gateway.refresh()

    r2 = gateway.client.post("/v1/chat/completions", json=body)
    assert r2.status_code == 200, r2.text
    assert r2.headers["x-modelsaar-deployment"] == "ollama/big:27b"
    dec2 = gateway.decision(r2.headers["x-modelsaar-request-id"])
    assert dec2["requirements"]["needs_continuation"] is True and dec2["chosen"] == "ollama/big:27b"
    assert dec2["failover_allowed"] is False and "continuation" in dec2["failover_note"]
    # Deployments that were not probed are still excluded (default behaviour preserved).
    assert "ollama/small:1b" in dec2["exclusions"]


def test_override_still_makes_continuation_eligible(fake):
    from modelsaar.config import Capabilities, DeploymentOverride

    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        deployments=(DeploymentOverride(backend="ollama", model="small:1b", capabilities=Capabilities(continuation="supported")),),
    )
    try:
        r = g.client.post("/v1/chat/completions", json={"model": "auto", "messages": ODYSSEUS_HISTORY, "max_tokens": 64})
        assert r.status_code == 200, r.text
        assert r.headers["x-modelsaar-deployment"] == "ollama/small:1b"
    finally:
        g.gw.stop()


def test_cli_probe_accepts_which_continuation():
    import subprocess
    import sys

    r = subprocess.run([sys.executable, "-m", "modelsaar.cli", "probe", "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "continuation" in r.stdout
