"""Regression tests for findings of the independent adversarial review (2026-10-11)."""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

from conftest import build_gateway, chat, stream_events

from modelsaar.config import BackendConfig, Capabilities, DeclaredModel, TokenEstimateConfig
from modelsaar.routing.requirements import analyze_chat


def test_unknown_context_length_is_a_hard_exclusion(fake):
    """Finding 1: undeclared models on a generic endpoint must not accept unbounded requests."""
    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        backends=(BackendConfig(id="oai", type="openai_compatible", base_url=f"http://127.0.0.1:{fake.port}", resource_pool="pool"),),
        deployments=(),
    )
    try:
        r = chat(g, "oai/small:1b", "hello")
        assert r.status_code == 422
        assert any("context length unknown" in b for why in r.json()["error"]["modelsaar"]["blockers"].values() for b in why)
    finally:
        g.gw.stop()


def test_declared_models_keep_adapter_capabilities_and_exact_tokenize(fake):
    """Findings 6 and 11: declared models keep adapter-level streaming; /tokenize refines borderline counts."""
    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        backends=(
            BackendConfig(
                id="oai",
                type="openai_compatible",
                base_url=f"http://127.0.0.1:{fake.port}",
                resource_pool="pool",
                models=(DeclaredModel(name="small:1b", context_length=8192, capabilities=Capabilities(tools="supported")),),
            ),
        ),
        deployments=(),
    )
    try:
        with g.client.stream("POST", "/v1/chat/completions", json={"model": "oai/small:1b", "stream": True, "messages": [{"role": "user", "content": "hi"}]}) as r:
            assert r.status_code == 200
            frames = stream_events(r)
        assert frames[-1].strip() == "data: [DONE]"
        # ~7000 chars: estimate ~2450 tokens, exact (1 per 4 chars) ~1750 -> borderline for 8192 ctx with max_tokens 6000
        r = chat(g, "oai/small:1b", "word " * 1400, max_tokens=6000)
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert "exact token counts used" in dec.get("requirements_note", "")
        assert r.status_code == 200
    finally:
        g.gw.stop()


def test_negative_or_zero_max_tokens_rejected(gateway):
    """Finding 2."""
    assert chat(gateway, "auto", "hi", max_tokens=-100000).status_code == 400
    assert chat(gateway, "auto", "hi", max_tokens=0).status_code == 400
    assert chat(gateway, "auto", "hi", max_completion_tokens=-1).status_code == 400


def test_tool_round_trip_pins_to_latest_issuer(gateway):
    """Finding 3: an older answered tool call must not pin a later round trip."""
    tools = [{"type": "function", "function": {"name": "bash", "parameters": {"type": "object"}}}]
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_old_big", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_old_big", "content": "done"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_new_small", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_new_small", "content": "x"},
    ]
    gateway.router.affinity.remember_tool_calls("x", ["call_old_big"], "ollama/big:27b")
    req = analyze_chat({"messages": msgs, "tools": tools}, TokenEstimateConfig())
    assert req.outstanding_tool_call_ids == ["call_new_small"]
    # Live: the old id was issued by big; the new round trip (small) must not be pulled to big.
    caller = gateway.router.affinity  # use real caller path through HTTP
    r1 = chat(gateway, "ollama/small:1b", "list", tools=tools)
    new_id = r1.json()["choices"][0]["message"]["tool_calls"][0]["id"]
    msgs2 = msgs[:5] + [{"role": "assistant", "content": None, "tool_calls": [{"id": new_id, "type": "function", "function": {"name": "bash", "arguments": "{}"}}]}, {"role": "tool", "tool_call_id": new_id, "content": "x"}]
    r2 = gateway.client.post("/v1/chat/completions", json={"model": "auto", "messages": msgs2, "tools": tools})
    assert r2.status_code == 200
    assert r2.headers["x-modelsaar-deployment"] == "ollama/small:1b"
    assert caller is gateway.router.affinity


def test_truncated_stream_is_reported_not_completed(gateway, fake):
    """Finding 4: a stream that ends without finish_reason/[DONE] must end with an error frame."""
    fake.models["small:1b"].behaviour = "truncate_stream"
    try:
        with gateway.client.stream("POST", "/v1/chat/completions", json={"model": "ollama/small:1b", "stream": True, "messages": [{"role": "user", "content": "hi"}]}) as r:
            frames = stream_events(r)
        assert any("upstream_stream_error" in f and "truncated" in f for f in frames)
        assert frames[-1].strip() == "data: [DONE]"
        dec = gateway.decision(r.headers["x-modelsaar-request-id"])
        assert dec["outcome"] == "stream_truncated_after_commit"
    finally:
        fake.models["small:1b"].behaviour = "ok"


def test_cjk_token_estimate_is_conservative():
    """Finding 5."""
    cfg = TokenEstimateConfig()
    zh = analyze_chat({"messages": [{"role": "user", "content": "你" * 6400}]}, cfg)
    assert zh.tokens.input_estimate >= 6400


def test_any_non_data_image_url_is_external(gateway):
    """Finding 7."""
    for url in ("HTTP://x/y.png", "Https://x/y.png", "//x/y.png", "ftp://x/y", "file:///etc/passwd", "data:text/plain,abc"):
        content = [{"type": "text", "text": "c"}, {"type": "image_url", "image_url": {"url": url}}]
        r = chat(gateway, "auto", content)
        assert r.status_code == 422, url
        assert any("remote image URL" in b for why in r.json()["error"]["modelsaar"]["blockers"].values() for b in why), url


def test_uninstall_refuses_foreign_files(tmp_path: Path):
    """Finding 8."""
    home = tmp_path / "shared"
    (home / "keys").mkdir(parents=True)
    (home / "config.yaml").write_text("version: 1\n")
    (home / "notes.txt").write_text("mine")
    r = subprocess.run([sys.executable, "-m", "modelsaar.cli", "--config", str(home / "config.yaml"), "uninstall", "--yes"], capture_output=True, text=True, check=False)
    assert r.returncode != 0 and (home / "notes.txt").exists() and (home / "config.yaml").exists()


def test_key_files_created_private(tmp_path: Path):
    """Finding 9."""
    import os
    import stat

    from modelsaar.config import write_key_file

    p = tmp_path / "k" / "api_keys"
    write_key_file(p, ["msk_x"])
    if os.name != "nt":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700


def test_non_ascii_bearer_is_401_not_500(gateway):
    """Finding 10."""
    host, port = gateway.url.replace("http://", "").split(":")
    s = socket.create_connection((host, int(port)), timeout=5)
    s.sendall(b"GET /v1/models HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer msk_\xc3\xa9\xc3\xa9\xc3\xa9\r\nConnection: close\r\n\r\n")
    data = s.recv(4096)
    s.close()
    assert data.startswith(b"HTTP/1.1 401")


def test_translation_notes_recorded(gateway):
    """Finding 20: adapter translations are visible in the decision."""
    tools = [{"type": "function", "function": {"name": "f"}}]
    r = chat(gateway, "ollama/small:1b", "x", tools=tools, tool_choice="none", user="u1")
    assert r.status_code == 200
    dec = gateway.decision(r.headers["x-modelsaar-request-id"])
    notes = " ".join(dec["translation_notes"])
    assert "tool_choice=none" in notes and "user" in notes


def test_admin_decisions_limit_validation(gateway):
    """Finding 18."""
    assert gateway.admin.get("/admin/decisions?limit=abc").status_code == 400
    assert gateway.admin.get("/admin/decisions?limit=-5").status_code == 200


def test_failover_pins_session_to_answering_deployment(gateway, fake):
    """Finding 21."""
    fake.models["small:1b"].behaviour = "error_500"
    try:
        r = gateway.client.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]}, headers={"X-ModelSaar-Session": "s-fo"})
        answered = r.headers["x-modelsaar-deployment"]
        assert answered != "ollama/small:1b"
        fake.models["small:1b"].behaviour = "ok"
        r2 = gateway.client.post("/v1/chat/completions", json={"model": "auto", "messages": [{"role": "user", "content": "again"}]}, headers={"X-ModelSaar-Session": "s-fo"})
        assert r2.headers["x-modelsaar-deployment"] == answered
    finally:
        fake.models["small:1b"].behaviour = "ok"
