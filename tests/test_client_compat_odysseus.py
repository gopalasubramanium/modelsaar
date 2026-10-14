"""Client-compatibility contract for llama.cpp-style hints (Odysseus, 2026-10-13).

Odysseus's ``_apply_local_cache_affinity`` adds ``session_id`` and ``cache_prompt=true`` to every request it sends to
a self-hosted OpenAI-compatible endpoint. Before this contract the gateway answered
``HTTP 400: unsupported request field(s): ['cache_prompt', 'session_id']``. Now: ``session_id`` is validated and
consumed as caller-scoped conversation affinity; ``cache_prompt=true`` is an advisory hint recorded in the decision;
``cache_prompt=false`` is refused with a precise explanation when the backend path cannot guarantee a bypass;
neither field reaches the backend; every other unknown field is still rejected.

All text is synthetic; keys come from the test fixtures only.
"""

from __future__ import annotations

import json

import httpx
from conftest import chat, stream_events

from modelsaar.config import AffinityConfig, generate_key
from modelsaar.protocol.openai import ProtocolError, parse_chat_request
from modelsaar.routing.affinity import AffinityStore

ODYSSEUS_SESSION = "odysseus-conv-7f3a"


def odysseus_body(content: str = "Hello", session: str = ODYSSEUS_SESSION, stream: bool = False, **extra) -> dict:
    """The request shape Odysseus sends to a local endpoint: ordinary chat fields PLUS session_id and cache_prompt=true."""
    body = {
        "model": "auto",
        "messages": [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": content}],
        "temperature": 0.7,
        "stream": stream,
        "session_id": session,
        "cache_prompt": True,
    }
    body.update(extra)
    return body


# --------------------------------------------------------------------------- #
# 1. the Odysseus-shaped request returns a valid completion; the backend never sees the two fields
# --------------------------------------------------------------------------- #
def test_odysseus_request_completes_and_backend_receives_only_supported_fields(gateway, fake):
    r = gateway.client.post("/v1/chat/completions", json=odysseus_body("Hello"))
    assert r.status_code == 200, r.text
    msg = r.json()["choices"][0]["message"]
    assert msg["role"] == "assistant" and msg["content"]
    assert r.headers["x-modelsaar-request-id"].startswith("req_") and r.headers["x-modelsaar-deployment"].startswith("ollama/")
    sent = fake.requests[-1]["fields"]
    assert "session_id" not in sent and "cache_prompt" not in sent, f"compat fields must not reach Ollama: {sent}"
    assert set(sent) <= {"model", "messages", "temperature", "stream"}, sent
    dec = gateway.decision(r.headers["x-modelsaar-request-id"])
    assert dec["affinity"]["session_source"] == "body:session_id"
    assert dec["compat"]["session_id"].startswith("consumed as caller-scoped conversation affinity")
    assert "advisory" in dec["compat"]["cache_prompt"] and "not forwarded" in dec["compat"]["cache_prompt"]
    assert any("session_id consumed by the gateway" in n for n in dec["translation_notes"])
    assert any("cache_prompt consumed by the gateway" in n for n in dec["translation_notes"])


# --------------------------------------------------------------------------- #
# 2. streamed responses work with the same shape
# --------------------------------------------------------------------------- #
def test_odysseus_streamed_request(gateway, fake):
    with gateway.client.stream("POST", "/v1/chat/completions", json=odysseus_body("Hello", stream=True)) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        frames = stream_events(r)
    assert frames[-1].strip() == "data: [DONE]"
    deltas = [json.loads(f[len("data: "):]) for f in frames[:-1] if f.startswith("data: ")]
    text = "".join((d["choices"][0].get("delta") or {}).get("content") or "" for d in deltas if d.get("choices"))
    assert text, "streamed content arrived"
    sent = fake.requests[-1]
    assert sent["stream"] is True and "session_id" not in sent["fields"] and "cache_prompt" not in sent["fields"]


# --------------------------------------------------------------------------- #
# 3. follow-up turns with the same session_id keep the deployment; a different caller does not inherit it
# --------------------------------------------------------------------------- #
def test_session_id_pins_follow_up_turns_per_caller(gateway, fake):
    # Turn 1 needs vision -> big:27b. Turn 2 is plain text (small:1b would win stateless) but carries the same session_id.
    content = [{"type": "text", "text": "describe"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    r1 = gateway.client.post("/v1/chat/completions", json=odysseus_body(content))
    assert r1.status_code == 200 and r1.headers["x-modelsaar-deployment"] == "ollama/big:27b"
    r2 = gateway.client.post("/v1/chat/completions", json=odysseus_body("and now a plain follow-up"))
    assert r2.status_code == 200
    assert r2.headers["x-modelsaar-deployment"] == "ollama/big:27b", "same session_id -> same deployment"
    dec = gateway.decision(r2.headers["x-modelsaar-request-id"])
    assert dec["affinity"] == {"session_source": "body:session_id", "pinned": "ollama/big:27b", "status": "found"}
    # Without the id the plain turn is request-routed (stateless policy unchanged).
    r3 = chat(gateway, "auto", "plain")
    assert r3.headers["x-modelsaar-deployment"] == "ollama/small:1b"
    # A second authenticated caller sending the SAME session_id does not inherit the pin.
    k2 = generate_key("msk")
    keys_file = gateway.tmp / "keys/api_keys"
    keys_file.write_text(keys_file.read_text() + k2 + "\n")
    gateway.gw.auth.api_keys.append(k2)
    c2 = httpx.Client(base_url=gateway.url, headers={"Authorization": f"Bearer {k2}"}, timeout=30)
    r4 = c2.post("/v1/chat/completions", json=odysseus_body("plain from another caller"))
    assert r4.status_code == 200 and r4.headers["x-modelsaar-deployment"] == "ollama/small:1b", "affinity is scoped per caller"


# --------------------------------------------------------------------------- #
# 3b. tool-result continuity still holds with session_id present
# --------------------------------------------------------------------------- #
def test_tool_round_trip_with_session_id(gateway, fake):
    tools = [{"type": "function", "function": {"name": "bash", "parameters": {"type": "object"}}}]
    content = [{"type": "text", "text": "look and list"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    r1 = gateway.client.post("/v1/chat/completions", json=odysseus_body(content, tools=tools))
    assert r1.status_code == 200 and r1.headers["x-modelsaar-deployment"] == "ollama/big:27b"
    calls = r1.json()["choices"][0]["message"]["tool_calls"]
    body = odysseus_body("list", tools=tools)
    body["messages"] = [
        {"role": "user", "content": "list files"},
        {"role": "assistant", "content": None, "tool_calls": calls},
        {"role": "tool", "tool_call_id": calls[0]["id"], "content": "a.py"},
    ]
    r2 = gateway.client.post("/v1/chat/completions", json=body)
    assert r2.status_code == 200 and r2.headers["x-modelsaar-deployment"] == "ollama/big:27b"
    dec = gateway.decision(r2.headers["x-modelsaar-request-id"])
    assert dec["affinity"]["tool_round_trip"] == "ollama/big:27b" and dec["affinity"]["session_source"] == "body:session_id"


# --------------------------------------------------------------------------- #
# 4. invalid types, conflicting identifiers, unrelated unknown fields
# --------------------------------------------------------------------------- #
def test_invalid_compat_values_are_rejected_with_the_field_named(gateway, fake):
    before = len(fake.requests)
    for bad, param in (
        ({"session_id": ""}, "session_id"),
        ({"session_id": "   "}, "session_id"),
        ({"session_id": "x" * 257}, "session_id"),
        ({"session_id": 123}, "session_id"),
        ({"session_id": "a\nb"}, "session_id"),
        ({"cache_prompt": "true"}, "cache_prompt"),
        ({"cache_prompt": 1}, "cache_prompt"),
        ({"cache_prompt": None, "session_id": None}, None),  # JSON null = absent, accepted
    ):
        body = odysseus_body("Hello")
        body.update(bad)
        r = gateway.client.post("/v1/chat/completions", json=body)
        if param is None:
            assert r.status_code == 200, r.text
            continue
        assert r.status_code == 400, (bad, r.text)
        err = r.json()["error"]
        assert err["param"] == param and param in err["message"], err
    assert len(fake.requests) == before + 1, "invalid requests never reached the backend"


def test_session_hint_precedence_is_fixed_and_conflicts_are_reported(gateway):
    # body:modelsaar.session > body:session_id > configured headers > configured body fields
    r = gateway.client.post(
        "/v1/chat/completions",
        json=odysseus_body("Hello", session="from-session-id", prompt_cache_key="from-pck", modelsaar={"session": "from-modelsaar"}),
        headers={"X-ModelSaar-Session": "from-header"},
    )
    assert r.status_code == 200
    dec = gateway.decision(r.headers["x-modelsaar-request-id"])
    assert dec["affinity"]["session_source"] == "body:modelsaar.session"
    assert dec["affinity"]["ignored_hints"] == ["body:session_id", "header:X-ModelSaar-Session", "body:prompt_cache_key"]
    assert dec["compat"]["session_id"].startswith("present but superseded by body:modelsaar.session")
    r = gateway.client.post("/v1/chat/completions", json=odysseus_body("Hello", session="s-a"), headers={"X-ModelSaar-Session": "s-b"})
    dec = gateway.decision(r.headers["x-modelsaar-request-id"])
    assert dec["affinity"]["session_source"] == "body:session_id" and dec["affinity"]["ignored_hints"] == ["header:X-ModelSaar-Session"]
    # identical values are not a conflict
    r = gateway.client.post("/v1/chat/completions", json=odysseus_body("Hello", session="same"), headers={"X-ModelSaar-Session": "same"})
    dec = gateway.decision(r.headers["x-modelsaar-request-id"])
    assert "ignored_hints" not in dec["affinity"]


def test_affinity_store_precedence_unit():
    a = AffinityStore(AffinityConfig(ttl_s=60))
    key, src, ignored = a.extract_session({"x-openwebui-chat-id": "h"}, {"session_id": "b", "prompt_cache_key": "p"})
    assert (key, src, ignored) == ("b", "body:session_id", ["header:X-OpenWebUI-Chat-Id", "body:prompt_cache_key"])
    key, src, ignored = a.extract_session({}, {"session_id": "b", "modelsaar": {"session": "m"}})
    assert (key, src, ignored) == ("m", "body:modelsaar.session", ["body:session_id"])
    assert a.extract_session({}, {"session_id": "   "})[0] is None, "blank ids are not sessions"
    assert a.extract_session_key({}, {"session_id": "b"}) == ("b", "body:session_id"), "legacy accessor unchanged"


def test_unrelated_unknown_fields_still_rejected(gateway, fake):
    before = len(fake.requests)
    r = gateway.client.post("/v1/chat/completions", json=odysseus_body("Hello", id_slot=3))
    assert r.status_code == 400
    err = r.json()["error"]
    assert "unsupported request field(s): ['id_slot']" in err["message"] and err["param"] == "id_slot"
    assert "session_id" not in err["message"] and "cache_prompt" not in err["message"]
    with_parse = {"model": "auto", "messages": [{"role": "user", "content": "x"}], "mystery": 1, "session_id": "s"}
    try:
        parse_chat_request(with_parse)
        raise AssertionError("mystery must be rejected")
    except ProtocolError as e:
        assert "['mystery']" in e.message
    assert len(fake.requests) == before


# --------------------------------------------------------------------------- #
# 5. cache_prompt=false is not silently accepted as a guaranteed bypass
# --------------------------------------------------------------------------- #
def test_cache_prompt_false_is_refused_precisely_for_backend_managed_caches(gateway, fake):
    before = len(fake.requests)
    r = gateway.client.post("/v1/chat/completions", json=odysseus_body("Hello", cache_prompt=False))
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "unsupported_capability" and err["param"] == "cache_prompt"
    assert "guaranteed prompt-cache bypass" in err["message"] and "ollama" in err["message"]
    assert err["modelsaar"]["request_id"].startswith("req_") and err["modelsaar"]["deployment"].startswith("ollama/")
    assert len(fake.requests) == before, "nothing was sent to the backend"
    dec = gateway.decision(err["modelsaar"]["request_id"])
    assert dec["outcome"] == "unsupported_capability" and "cache_prompt" in dec["compat"]
    # explain (dry run) accepts the Odysseus shape too
    r = gateway.client.post("/v1/chat/completions", json=odysseus_body("Hello", cache_prompt=True))
    assert r.status_code == 200
