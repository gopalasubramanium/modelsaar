"""Decision-model classifier (routing.classifier.mode: decision): the optional classifier asks a
decision model (role=decision, Ollama ``POST /v1/systemone``) one ``choice`` question over the closed
task-label set and uses the returned per-label probabilities. Everything stays opt-in: with the
classifier disabled or in the default ``chat`` mode nothing here is exercised."""

from __future__ import annotations

import pytest
from conftest import build_gateway, chat, make_models

from modelsaar.config import ClassifierConfig, RoutingConfig
from modelsaar.routing.classifier import DECISION_QUESTION, TASK_DESCRIPTIONS, parse_decision_answer
from modelsaar.routing.requirements import TASKS
from modelsaar.testing.fakebackend import FakeBackend, FakeModel

AMBIGUOUS = "thoughts?"  # short/vague: deterministic classification flags it ambiguous -> classifier consulted


def _answer(choice="coding", probs=None, confidence=0.8, qtype="choice", question=DECISION_QUESTION):
    probs = probs if probs is not None else {"coding": 0.9, "math": 0.1}
    return {"model": "decider", "answers": {question: {"type": qtype, "choice": choice, "probabilities": probs, "confidence": confidence}}, "usage": {"input_tokens": 1, "output_tokens": 1}}


# --------------------------------------------------------------------------- #
# Strict validation of the decision answer (untrusted data)
# --------------------------------------------------------------------------- #
def test_parse_decision_answer_accepts_documented_choice_answer():
    assert parse_decision_answer(_answer()) == ("coding", 0.9, 0.8)
    assert parse_decision_answer(_answer("math", {"math": 1, "coding": 0}, 1)) == ("math", 1.0, 1.0)


@pytest.mark.parametrize(
    "body",
    [
        None,
        "coding",
        {},
        {"answers": {}},
        {"answers": {"other": _answer()["answers"][DECISION_QUESTION]}},  # wrong question name
        _answer(qtype="noul"),  # not a choice answer
        _answer("hacking", {"hacking": 0.9, "coding": 0.1}),  # label outside the closed set
        _answer("coding", {"coding": 0.9, "hacking": 0.1}),  # unknown label in probabilities
        _answer("coding", {}),  # no probabilities
        _answer("coding", {"math": 0.9}),  # chosen label without a probability
        _answer("coding", {"coding": 0.2, "math": 0.8}),  # choice is not the arg-max
        _answer("coding", {"coding": 2.0, "math": 0.1}),  # probability out of range
        _answer("coding", {"coding": "0.9", "math": 0.1}),  # string probability
        _answer("coding", {"coding": True, "math": 0.1}),  # bool probability
        _answer(confidence=1.5),
        _answer(confidence="high"),
        _answer(confidence=None),
    ],
)
def test_parse_decision_answer_rejects_malformed(body):
    with pytest.raises(ValueError):
        parse_decision_answer(body)


def test_question_criteria_cover_exactly_the_closed_label_set():
    assert set(TASK_DESCRIPTIONS) == set(TASKS)
    assert all(isinstance(v, str) and v for v in TASK_DESCRIPTIONS.values())


# --------------------------------------------------------------------------- #
# Discovery: a model that declares "decision" (and no "completion") is a decision model, never chat
# --------------------------------------------------------------------------- #
def _models():
    ms = make_models()
    ms.append(FakeModel("decider:9b", ["decision"], 8192, parameter_size="9B", loaded=True, decides="coding"))
    return ms


@pytest.fixture
def fake_with_decider():
    f = FakeBackend(_models())
    f.start()
    yield f
    f.stop()


def test_decision_model_discovered_with_role_decision_and_excluded_from_chat(fake_with_decider):
    g = build_gateway(f"http://127.0.0.1:{fake_with_decider.port}")
    try:
        d = g.router.registry.get("ollama/decider:9b")
        assert d is not None and d.role == "decision"
        r = chat(g, "auto", "Translate to French: good morning")
        assert r.status_code == 200
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert dec["chosen"] != "ollama/decider:9b"
        r = chat(g, "ollama/decider:9b", "hello")  # explicit request for a decision model is refused, not forwarded
        assert r.status_code == 422
        assert not any(q["model"] == "decider:9b" and q.get("path") != "/v1/systemone" for q in fake_with_decider.requests)
    finally:
        g.gw.stop()


# --------------------------------------------------------------------------- #
# The classifier in decision mode, end to end through the gateway
# --------------------------------------------------------------------------- #
def _gateway(fake, **cls):
    base = dict(enabled=True, backend="ollama", model="decider:9b", mode="decision", timeout_s=1.0, only_when_ambiguous=True)
    base.update(cls)
    return build_gateway(f"http://127.0.0.1:{fake.port}", routing=RoutingConfig(classifier=ClassifierConfig(**base)))


def test_decision_mode_refines_the_task_label_from_probabilities(fake_with_decider):
    fake = fake_with_decider
    g = _gateway(fake)
    try:
        r = chat(g, "auto", AMBIGUOUS)
        assert r.status_code == 200
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        c = dec["classifier"]
        assert c["status"] == "ok" and c["used"] is True
        assert c["task"] == "coding" and c["confidence"] == pytest.approx(0.9)
        assert "decision model" in c["note"]
        # the label refined the requirements and is visible in the signals
        assert dec["requirements"]["primary_task"] == "coding"
        assert any(s.startswith("classifier:coding@0.90") for s in dec["requirements"]["signals"])
        # the request went to the native decision endpoint with exactly one choice question over the label set
        calls = [q for q in fake.requests if q.get("path") == "/v1/systemone"]
        assert len(calls) == 1 and calls[0]["model"] == "decider:9b"
        assert calls[0]["fields"] == ["model", "questions", "state"]  # nothing else is forwarded
        assert calls[0]["questions"] == [DECISION_QUESTION]
        # the decision model itself is never the chosen chat deployment
        assert dec["chosen"] and dec["chosen"] != "ollama/decider:9b"
        st = g.admin.get("/admin/status").json()
        assert st["classifier"]["mode"] == "decision" and st["classifier"]["calls"] == 1 and st["classifier"]["timeouts"] == 0
    finally:
        g.gw.stop()


def test_decision_mode_is_only_consulted_when_ambiguous(fake_with_decider):
    fake = fake_with_decider
    g = _gateway(fake)
    try:
        r = chat(g, "auto", "Translate to French: good morning")
        assert r.status_code == 200
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert dec["classifier"]["used"] is False and dec["classifier"]["status"] == "skipped"
        assert not [q for q in fake.requests if q.get("path") == "/v1/systemone"]
    finally:
        g.gw.stop()


def test_low_probability_answer_does_not_override_the_deterministic_label(fake_with_decider):
    fake = fake_with_decider
    fake.models["decider:9b"].decision_probability = 0.3  # arg-max but below the 0.5 acceptance bar
    g = _gateway(fake)
    try:
        r = chat(g, "auto", AMBIGUOUS)
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert dec["classifier"]["status"] == "ok" and dec["classifier"]["confidence"] == pytest.approx(0.3)
        assert dec["requirements"]["primary_task"] != "coding"
        assert not any(s.startswith("classifier:") for s in dec["requirements"]["signals"])
    finally:
        g.gw.stop()


@pytest.mark.parametrize(
    "behaviour,status",
    [("error_500", "error"), ("hang", "timeout"), ("bad_json", "malformed"), ("malformed_decision", "malformed")],
)
def test_decision_mode_failures_fall_back_deterministically(fake_with_decider, behaviour, status):
    fake = fake_with_decider
    fake.models["decider:9b"].behaviour = behaviour
    g = _gateway(fake)
    try:
        r = chat(g, "auto", AMBIGUOUS)
        assert r.status_code == 200  # routing continues on the deterministic label
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert dec["classifier"]["used"] is False and dec["classifier"]["status"] == status
        assert dec["chosen"] and dec["chosen"] != "ollama/decider:9b"
        if status == "timeout":
            assert g.admin.get("/admin/status").json()["classifier"]["timeouts"] == 1
    finally:
        g.gw.stop()


def test_role_mismatch_is_refused_before_any_call(fake_with_decider):
    fake = fake_with_decider
    # decision mode pointed at a generative model
    g = _gateway(fake, model="plain:3b")
    try:
        r = chat(g, "auto", AMBIGUOUS)
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert dec["classifier"]["status"] == "unavailable" and "role=decision" in dec["classifier"]["note"]
    finally:
        g.gw.stop()
    # chat mode (the default) pointed at a decision model
    g = _gateway(fake, mode="chat")
    try:
        r = chat(g, "auto", AMBIGUOUS)
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert dec["classifier"]["status"] == "unavailable" and "mode: decision" in dec["classifier"]["note"]
    finally:
        g.gw.stop()
    assert not [q for q in fake.requests if q.get("path") == "/v1/systemone"]
    assert not [q for q in fake.requests if q["model"] == "decider:9b"]


def test_backend_without_a_decision_endpoint_is_unavailable(fake_with_decider):
    """An openai_compatible backend has no documented decision endpoint: the classifier reports
    'unavailable' and routing continues; nothing is invented on the wire."""
    from modelsaar.config import BackendConfig, ResourcePool

    fake = fake_with_decider
    url = f"http://127.0.0.1:{fake.port}"
    g = build_gateway(
        url,
        resource_pools=(ResourcePool(id="pool", max_concurrent=2, max_queue=2, queue_timeout_s=2.0),),
        backends=(
            BackendConfig(id="ollama", type="ollama", base_url=url, resource_pool="pool", max_concurrent=4),
            BackendConfig(id="compat", type="openai_compatible", base_url=url + "/v1", resource_pool="pool", max_concurrent=4),
        ),
        routing=RoutingConfig(classifier=ClassifierConfig(enabled=True, backend="compat", model="decider:9b", mode="decision", timeout_s=1.0)),
    )
    try:
        d = g.router.registry.get("compat/decider:9b")
        if d is not None and d.role == "decision":
            r = chat(g, "auto", AMBIGUOUS)
            dec = g.decision(r.headers["x-modelsaar-request-id"])
            assert dec["classifier"]["used"] is False and dec["classifier"]["status"] in ("unavailable", "error")
        else:
            # the generic backend cannot even recognise a decision model: the role check refuses first
            r = chat(g, "auto", AMBIGUOUS)
            dec = g.decision(r.headers["x-modelsaar-request-id"])
            assert dec["classifier"]["used"] is False and dec["classifier"]["status"] == "unavailable"
        assert not [q for q in fake.requests if q.get("path") == "/v1/systemone"]
    finally:
        g.gw.stop()


def test_default_mode_is_chat_and_unchanged(fake_with_decider):
    cfg = ClassifierConfig()
    assert cfg.enabled is False and cfg.mode == "chat"
    g = build_gateway(f"http://127.0.0.1:{fake_with_decider.port}")
    try:
        r = chat(g, "auto", AMBIGUOUS)
        dec = g.decision(r.headers["x-modelsaar-request-id"])
        assert not dec.get("classifier")
        assert g.admin.get("/admin/status").json()["classifier"] == {"enabled": False, "mode": "chat", "calls": 0, "timeouts": 0, "failures": 0}
    finally:
        g.gw.stop()
