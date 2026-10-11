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
