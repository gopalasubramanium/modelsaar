"""`POST /v1/decisions`: typed questions about a state answered by a decision model (Ollama System One)
through the gateway — authentication, strict request validation, decision-role model resolution
(explicit id or `auto`), admission, answer validation and decision records. Nothing here touches chat
routing; the endpoint is only reachable when a decision-role deployment is discovered."""

from __future__ import annotations

import base64

import httpx
import pytest
from conftest import build_gateway, make_models

from modelsaar.config import BackendConfig, ResourcePool, ServerConfig
from modelsaar.protocol.decisions import decision_answers_problem, parse_decisions_request
from modelsaar.protocol.openai import ProtocolError
from modelsaar.testing.fakebackend import FakeBackend, FakeModel

CHOICE = {"type": "choice", "instructions": "Which label fits this ticket?", "criteria": {"bug": "Software errors", "billing": "Payments and refunds", "account": None}}
NOUL = {"type": "noul", "instructions": "Is the customer angry?"}
SCORE = {"type": "score", "instructions": "How urgent is it?", "criteria": ["not urgent", "soon", "today", "now"]}
STATE = "Our checkout has returned 500 errors since 9am."
PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()


def _models():
    ms = make_models()
    ms.append(FakeModel("decider:9b", ["decision"], 8192, parameter_size="9B", loaded=True, decides="bug"))
    ms.append(FakeModel("decider-cold:9b", ["decision"], 8192, parameter_size="9B", loaded=False, decides="bug"))
    ms.append(FakeModel("seer:27b", ["decision", "vision"], 65536, parameter_size="27B", loaded=False, decides="billing"))
    return ms


@pytest.fixture
def fake():
    f = FakeBackend(_models())
    f.start()
    yield f
    f.stop()


@pytest.fixture
def g(fake):
    gw = build_gateway(f"http://127.0.0.1:{fake.port}", server=ServerConfig(request_timeout_s=1.5))
    yield gw
    gw.gw.stop()


def decide(g, **body) -> httpx.Response:
    payload = {"model": "ollama/decider:9b", "state": STATE, "questions": {"label": CHOICE}}
    payload.update(body)
    return g.client.post("/v1/decisions", json=payload)


def systemone_calls(fake):
    return [q for q in fake.requests if q.get("path") == "/v1/systemone"]


# --------------------------------------------------------------------------- #
# Success
# --------------------------------------------------------------------------- #
def test_choice_question_answered_by_explicit_decision_model(fake, g):
    r = decide(g)
    assert r.status_code == 200, r.text
    out = r.json()
    assert set(out) == {"model", "answers", "usage"} and out["model"] == "ollama/decider:9b"
    a = out["answers"]["label"]
    assert a["type"] == "choice" and a["choice"] == "bug" and set(a["probabilities"]) == set(CHOICE["criteria"])
    assert 0 <= a["confidence"] <= 1 and out["usage"]["output_tokens"] == 1
    assert r.headers["X-ModelSaar-Deployment"] == "ollama/decider:9b"
    dec = g.decision(r.headers["x-modelsaar-request-id"])
    assert dec["endpoint"] == "decisions" and dec["chosen"] == "ollama/decider:9b" and dec["outcome"] == "ok" and dec["explicit"] is True
    assert dec["requirements"]["role"] == "decision"
    calls = systemone_calls(fake)
    assert len(calls) == 1 and calls[0]["model"] == "decider:9b" and calls[0]["fields"] == ["model", "questions", "state"] and calls[0]["questions"] == ["label"]


def test_all_question_types_and_object_state(fake, g):
    r = decide(g, state={"ticket": {"text": STATE, "channel": "email"}}, questions={"label": CHOICE, "angry": NOUL, "urgency": SCORE})
    assert r.status_code == 200, r.text
    ans = r.json()["answers"]
    assert set(ans) == {"label", "angry", "urgency"}
    assert ans["angry"]["type"] == "noul" and 0 <= ans["angry"]["noul"] <= 1
    assert ans["urgency"]["type"] == "score" and set(ans["urgency"]["probabilities"]) == {"0", "1", "2", "3"} and set(ans["urgency"]["legend"]) == {"0", "1", "2", "3"}


def test_auto_selects_a_resident_decision_model_and_records_why(fake, g):
    r = decide(g, model="auto")
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "auto"  # response_model_field=requested (default)
    dec = g.decision(r.headers["x-modelsaar-request-id"])
    assert dec["chosen"] == "ollama/decider:9b" and dec["explicit"] is False and dec["evidence"] == "deterministic"
    assert any("resident" in x for x in dec["reasons"])
    assert "ollama/big:27b" not in dec["exclusions"]  # generative models are never candidates for `auto` here


def test_images_route_to_a_vision_capable_decision_model(fake, g):
    r = decide(g, model="auto", images=[PNG_B64])
    assert r.status_code == 200, r.text
    assert r.headers["X-ModelSaar-Deployment"] == "ollama/seer:27b"
    dec = g.decision(r.headers["x-modelsaar-request-id"])
    assert "vision" in " ".join(dec["exclusions"]["ollama/decider:9b"])
    assert systemone_calls(fake)[-1]["fields"] == ["images", "model", "questions", "state"]


# --------------------------------------------------------------------------- #
# Authentication and request validation (nothing reaches the backend)
# --------------------------------------------------------------------------- #
def test_requires_api_key(fake, g):
    r = httpx.post(f"{g.url}/v1/decisions", json={"model": "auto", "state": STATE, "questions": {"label": CHOICE}})
    assert r.status_code == 401 and r.json()["error"]["code"] == "authentication_error"
    assert not systemone_calls(fake)


@pytest.mark.parametrize(
    "body,param",
    [
        ({"questions": {}}, "questions"),
        ({"questions": {f"q{i}": CHOICE for i in range(65)}}, "questions"),
        ({"questions": {"label": {"type": "choice", "instructions": "x", "criteria": {"only": None}}}}, "questions"),
        ({"questions": {"label": {"type": "rank", "instructions": "x", "criteria": {"a": None, "b": None}}}}, "questions"),
        ({"questions": {"label": {"type": "choice", "criteria": {"a": None, "b": None}}}}, "questions"),  # instructions required
        ({"questions": {"urgency": {"type": "score", "instructions": "x", "criteria": ["one"]}}}, "questions"),
        ({"questions": {"bad name!": CHOICE}}, "questions"),
        ({"state": "   "}, "state"),
        ({"state": 42}, "state"),
        ({"model": ""}, "model"),
        ({"keep_alive": "5m"}, "keep_alive"),  # lifecycle is the gateway's, not per request
        ({"stream": True}, "stream"),
        ({"images": ["data:image/png;base64,AAAA"]}, "images"),
        ({"images": ["https://example.com/a.png"]}, "images"),
        ({"images": ["not base64!!"]}, "images"),
        ({"images": []}, "images"),
    ],
)
def test_invalid_requests_are_refused_with_the_field_named(fake, g, body, param):
    r = decide(g, **body)
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "invalid_request_error" and err["param"] == param and err["message"].startswith("invalid decisions request")
    assert not systemone_calls(fake)


def test_text_size_limit_and_non_json(fake, g):
    r = decide(g, state="x" * (64 * 1024 + 1))
    assert r.status_code == 400 and "64 KiB" in r.json()["error"]["message"]
    r = g.client.post("/v1/decisions", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
    r = g.client.post("/v1/decisions", json=[1, 2])
    assert r.status_code == 400
    assert not systemone_calls(fake)


def test_parse_helpers_directly():
    with pytest.raises(ProtocolError):
        parse_decisions_request({"model": "auto", "state": STATE})
    req = parse_decisions_request({"model": "auto", "state": STATE, "questions": {"label": CHOICE}})
    assert req.upstream_questions() == {"label": CHOICE}
    good = {"answers": {"label": {"type": "choice", "choice": "bug", "probabilities": {"bug": 0.9, "billing": 0.05, "account": 0.05}, "confidence": 0.8}}}
    assert decision_answers_problem(req, good) is None
    bad = [
        ("not a JSON object", "x"),
        ("no 'answers'", {"model": "x"}),
        ("no answer for", {"answers": {}}),
        ("unknown question", {"answers": {**good["answers"], "extra": good["answers"]["label"]}}),
        ("has type", {"answers": {"label": {"type": "noul", "noul": 0.5}}}),
        ("not one of the options", {"answers": {"label": {**good["answers"]["label"], "choice": "spam"}}}),
        ("exactly the 3 options", {"answers": {"label": {**good["answers"]["label"], "probabilities": {"bug": 1.0}}}}),
        ("highest-probability", {"answers": {"label": {**good["answers"]["label"], "choice": "billing"}}}),
        ("finite number in [0, 1]", {"answers": {"label": {**good["answers"]["label"], "confidence": 1.5}}}),
        ("finite number in [0, 1]", {"answers": {"label": {**good["answers"]["label"], "probabilities": {"bug": 2, "billing": 0, "account": 0}}}}),
    ]
    for fragment, body in bad:
        problem = decision_answers_problem(req, body)
        assert problem and fragment in problem, (fragment, problem)


# --------------------------------------------------------------------------- #
# Unsupported models and backends
# --------------------------------------------------------------------------- #
def test_generative_model_is_refused_as_role_mismatch(fake, g):
    r = decide(g, model="ollama/plain:3b")
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "no_eligible_deployment" and "role mismatch" in " ".join(err["modelsaar"]["blockers"]["ollama/plain:3b"])
    assert not systemone_calls(fake) and not any(q["model"] == "plain:3b" for q in fake.requests)


def test_unknown_model_and_chat_alias_are_404(fake, g):
    r = decide(g, model="ollama/nothing:1b")
    assert r.status_code == 404 and r.json()["error"]["code"] == "model_not_found"
    r = decide(g, model="auto-fast")  # a chat alias, not a decision deployment
    assert r.status_code == 404 and "auto" in r.json()["error"]["message"]
    assert not systemone_calls(fake)


def test_images_on_a_text_only_decision_model_are_refused_before_the_call(fake, g):
    r = decide(g, model="ollama/decider:9b", images=[PNG_B64])
    assert r.status_code == 422
    assert "vision" in " ".join(r.json()["error"]["modelsaar"]["blockers"]["ollama/decider:9b"])
    assert not systemone_calls(fake)


def test_no_decision_model_discovered(fake):
    f2 = FakeBackend(make_models())  # no decision-capable model at all
    f2.start()
    gw = build_gateway(f"http://127.0.0.1:{f2.port}")
    try:
        r = gw.client.post("/v1/decisions", json={"model": "auto", "state": STATE, "questions": {"label": CHOICE}})
        assert r.status_code == 422 and "no decision-model deployment" in r.json()["error"]["message"]
    finally:
        gw.gw.stop()
        f2.stop()


def test_backend_without_a_decision_endpoint_is_refused_cleanly(fake):
    """An openai_compatible backend has no documented decision endpoint. Its models are discovered as
    generative, so an explicit request is a role mismatch (422); if a deployment were forced to role
    decision the adapter itself would answer `unsupported_backend` (501). Either way nothing is invented
    on the wire."""
    url = f"http://127.0.0.1:{fake.port}"
    gw = build_gateway(
        url,
        resource_pools=(ResourcePool(id="pool", max_concurrent=2, max_queue=2, queue_timeout_s=2.0),),
        backends=(
            BackendConfig(id="ollama", type="ollama", base_url=url, resource_pool="pool", max_concurrent=4),
            BackendConfig(id="compat", type="openai_compatible", base_url=url + "/v1", resource_pool="pool", max_concurrent=4),
        ),
    )
    try:
        r = gw.client.post("/v1/decisions", json={"model": "compat/decider:9b", "state": STATE, "questions": {"label": CHOICE}})
        assert r.status_code in (422, 501), r.text
        if r.status_code == 501:
            assert r.json()["error"]["code"] == "unsupported_backend"
        d = gw.router.registry.get("compat/decider:9b")
        if d is not None:
            d.role = "decision"  # force the role to exercise the adapter's refusal
            r = gw.client.post("/v1/decisions", json={"model": "compat/decider:9b", "state": STATE, "questions": {"label": CHOICE}})
            assert r.status_code == 501 and r.json()["error"]["code"] == "unsupported_backend"
            dec = gw.decision(r.headers["x-modelsaar-request-id"])
            assert dec["outcome"] == "unsupported_backend"
        assert not systemone_calls(fake)
    finally:
        gw.gw.stop()


# --------------------------------------------------------------------------- #
# Backend failures and malformed answers
# --------------------------------------------------------------------------- #
def test_upstream_error_is_reported_not_passed_through_raw(fake, g):
    fake.models["decider:9b"].behaviour = "error_500"
    r = decide(g)
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "upstream_error" and "simulated scoring failure" in err["message"]
    assert g.decision(r.headers["x-modelsaar-request-id"])["outcome"] == "upstream_error"


def test_upstream_timeout_holds_the_slot_and_returns_504(fake, g):
    fake.models["decider:9b"].behaviour = "hang"
    r = decide(g)
    assert r.status_code == 504
    assert r.json()["error"]["code"] == "upstream_timeout"
    assert g.decision(r.headers["x-modelsaar-request-id"])["outcome"] == "upstream_timeout"


@pytest.mark.parametrize("behaviour", ["malformed_decision", "bad_json"])
def test_malformed_answers_are_a_contract_violation(fake, g, behaviour):
    fake.models["decider:9b"].behaviour = behaviour
    r = decide(g)
    assert r.status_code == 502, r.text
    err = r.json()["error"]
    assert err["code"] == "decision_contract_violation" and err["modelsaar"]["deployment"] == "ollama/decider:9b"
    assert g.decision(r.headers["x-modelsaar-request-id"])["outcome"] == "decision_contract_violation"


def test_chat_routing_is_unchanged_by_the_endpoint(fake, g):
    from conftest import chat

    r = chat(g, "auto", "Translate to French: good morning")
    assert r.status_code == 200
    dec = g.decision(r.headers["x-modelsaar-request-id"])
    assert dec["endpoint"] == "chat" and not dec["chosen"].startswith(("ollama/decider", "ollama/seer"))
    assert not systemone_calls(fake)


# --------------------------------------------------------------------------- #
# Request-size limits: bounded body read (declared and chunked) + the backend's whole-request limit
# --------------------------------------------------------------------------- #
LIMIT = 64 * 1024  # a small server.max_request_bytes for these tests


@pytest.fixture
def small_limit_gateway(fake):
    gw = build_gateway(f"http://127.0.0.1:{fake.port}", server=ServerConfig(request_timeout_s=1.5, max_request_bytes=LIMIT))
    yield gw
    gw.gw.stop()


def _big_payload(total_bytes: int) -> bytes:
    """A syntactically valid decisions body of about ``total_bytes`` (images are base64 of zero bytes)."""
    import json as _json

    skeleton = {"model": "ollama/decider:9b", "state": STATE, "questions": {"label": CHOICE}, "images": [""]}
    overhead = len(_json.dumps(skeleton).encode())
    n = max(total_bytes - overhead, 0) // 4 * 3  # base64 expands 3 -> 4
    skeleton["images"] = [base64.b64encode(b"\x00" * n).decode()]
    return _json.dumps(skeleton).encode()


def test_declared_content_length_over_the_limit_is_refused_before_reading(fake, small_limit_gateway):
    g = small_limit_gateway
    body = _big_payload(LIMIT + 4096)
    assert len(body) > LIMIT
    r = g.client.post("/v1/decisions", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 413 and "too large" in r.json()["error"]["message"]
    assert not systemone_calls(fake)
    # the declared length alone is enough: the gateway answers 413 without waiting for the body (raw socket,
    # because HTTP clients refuse to send a Content-Length they cannot honour)
    import socket
    from urllib.parse import urlsplit

    u = urlsplit(g.url)
    with socket.create_connection((u.hostname, u.port), timeout=5) as s:
        s.sendall(
            (
                f"POST /v1/decisions HTTP/1.1\r\nHost: {u.hostname}\r\nAuthorization: Bearer {g.api_key}\r\n"
                f"Content-Type: application/json\r\nContent-Length: {LIMIT + 1}\r\n\r\n{{"
            ).encode()
        )
        head = s.recv(4096).decode(errors="replace")
    assert head.startswith("HTTP/1.1 413"), head[:80]


def test_chunked_body_over_the_limit_is_cut_off_at_the_limit(fake, small_limit_gateway):
    g = small_limit_gateway
    body = _big_payload(LIMIT * 4)
    sent = {"bytes": 0}

    def chunks():
        for i in range(0, len(body), 8192):
            sent["bytes"] += len(body[i : i + 8192])
            yield body[i : i + 8192]

    # a generator body is sent with Transfer-Encoding: chunked and no Content-Length
    r = g.client.post("/v1/decisions", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413 and "too large" in r.json()["error"]["message"]
    assert not systemone_calls(fake)
    assert "content-length" not in {k.lower() for k in r.request.headers} and r.request.headers.get("transfer-encoding") == "chunked"


def test_body_within_the_limit_is_served(fake, small_limit_gateway):
    g = small_limit_gateway
    # vision model so that the image is accepted; the image keeps the body just under the limit
    body = _big_payload(LIMIT - 512).replace(b"ollama/decider:9b", b"ollama/seer:27b")
    assert len(body) <= LIMIT
    r = g.client.post("/v1/decisions", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 200, r.text
    assert systemone_calls(fake)[-1]["model"] == "seer:27b"


def test_upstream_whole_request_limit_is_checked_before_dispatch(fake, g, monkeypatch):
    """The backend's documented whole-request limit (32 MiB locally) is checked on the re-serialised
    upstream body before any call; lowered here so the test does not need a 32 MiB payload."""
    import modelsaar.protocol.decisions as dmod

    monkeypatch.setattr(dmod, "MAX_REQUEST_BYTES", 16 * 1024)
    r = decide(g, model="ollama/seer:27b", images=[base64.b64encode(b"\x00" * 15 * 1024).decode()])
    assert r.status_code == 413, r.text
    err = r.json()["error"]
    assert err["param"] == "images" and "exceed" in err["message"] and "MiB limit of the decision backend" in err["message"]
    assert not systemone_calls(fake)
    r = decide(g, model="ollama/seer:27b", images=[base64.b64encode(b"\x00" * 1024).decode()])
    assert r.status_code == 200  # under the (lowered) limit: served
