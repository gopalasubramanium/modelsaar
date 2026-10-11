"""Unit tests: SSE parsing, requirements/tokens, config validation, affinity, client config, probes, CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from modelsaar.config import (
    AffinityConfig,
    BackendConfig,
    Config,
    SecurityConfig,
    ServerConfig,
    TokenEstimateConfig,
    load_config,
    write_config_atomic,
)
from modelsaar.protocol.openai import ProtocolError, parse_chat_request
from modelsaar.protocol.sse import SSEEvent, SSEParser, StreamObserver, rewrite_model_field
from modelsaar.routing.affinity import AffinityStore
from modelsaar.routing.requirements import analyze_chat


# --------------------------------------------------------------------------- #
def test_sse_parser_partial_frames_crlf_and_unicode_boundary():
    p = SSEParser()
    payload = json.dumps({"choices": [{"delta": {"content": "ünï ✓"}}], "model": "m"}, ensure_ascii=False).encode("utf-8")
    frame = b"data: " + payload + b"\n\n"
    cut = frame.index("ü".encode()) + 1  # split inside the 2-byte sequence
    events = list(p.feed(frame[:cut]))
    assert events == []
    events = list(p.feed(frame[cut:] + b"event: ping\r\ndata: {}\r\n\r\ndata: [DONE]\n\n"))
    assert len(events) == 3
    assert events[0].json()["choices"][0]["delta"]["content"] == "ünï ✓"
    assert events[1].event == "ping"
    assert events[2].is_done
    assert rewrite_model_field(events[0], "auto").startswith(b"data: ")
    assert json.loads(rewrite_model_field(events[0], "auto")[6:])["model"] == "auto"
    assert rewrite_model_field(events[2], "auto") == b"data: [DONE]\n\n"


def test_stream_observer_tracks_tool_indexes_and_usage():
    o = StreamObserver()
    o.observe(SSEEvent(raw=b"", data=json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "c"}]}, "finish_reason": None}]})))
    o.observe(SSEEvent(raw=b"", data=json.dumps({"choices": [], "usage": {"total_tokens": 3}})))
    o.observe(SSEEvent(raw=b"", data="[DONE]"))
    assert o.tool_call_indexes == {1} and o.usage == {"total_tokens": 3} and o.saw_done


# --------------------------------------------------------------------------- #
def test_requirements_structural_signals():
    cfg = TokenEstimateConfig()
    body = {
        "messages": [
            {"role": "system", "content": "You are a coding agent working in a repository."},
            {"role": "user", "content": "Fix the failing pytest in src/app.py"},
            {"role": "assistant", "content": None, "reasoning_content": "thinking...", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        ],
        "tools": [{"type": "function", "function": {"name": "bash"}}],
        "tool_choice": {"type": "function", "function": {"name": "bash"}},
        "response_format": {"type": "json_object"},
        "max_tokens": 500,
    }
    r = analyze_chat(body, cfg, thinking_possible=True)
    assert r.needs_tools and r.tool_choice_mode == "named"
    assert r.needs_json_object and not r.needs_json_schema
    assert r.needs_continuation
    assert r.is_tool_result_turn and r.outstanding_tool_call_ids == ["c1"]
    assert r.primary_task in ("agent", "coding") and r.tasks["agent"] >= 0.8
    assert r.tokens.output_allowance == 500 and r.tokens.input_estimate > 0


def test_short_hard_vs_long_easy_not_judged_by_length():
    cfg = TokenEstimateConfig()
    short = analyze_chat({"messages": [{"role": "user", "content": "Is 97 a prime number?"}]}, cfg)
    long = analyze_chat({"messages": [{"role": "user", "content": "Summarize: " + "the cat sat on the mat. " * 300}]}, cfg)
    assert short.primary_task == "math"
    assert long.primary_task == "summarization"
    assert long.tokens.input_estimate > short.tokens.input_estimate * 20


def test_request_validation_rejects_n_and_unknown_fields():
    with pytest.raises(ProtocolError):
        parse_chat_request({"model": "auto", "messages": [{"role": "user", "content": "x"}], "n": 2})
    with pytest.raises(ProtocolError):
        parse_chat_request({"model": "auto", "messages": []})
    with pytest.raises(ProtocolError) as e:
        parse_chat_request({"model": "auto", "messages": [{"role": "user", "content": "x"}], "mystery": 1})
    assert "mystery" in str(e.value)
    req = parse_chat_request({"model": "auto", "messages": [{"role": "user", "content": "x"}], "modelsaar": {"session": "s"}})
    assert req.modelsaar == {"session": "s"}


# --------------------------------------------------------------------------- #
def test_config_lan_guard_and_version(tmp_path: Path):
    with pytest.raises(ValueError):
        Config(server=ServerConfig(host="0.0.0.0"))
    Config(server=ServerConfig(host="0.0.0.0"), security=SecurityConfig(allow_lan=True))
    with pytest.raises(ValueError):
        Config(version=99)
    with pytest.raises(ValueError):
        Config(backends=(BackendConfig(id="a", type="ollama", base_url="http://x"), BackendConfig(id="a", type="ollama", base_url="http://y")))
    cfg = Config(backends=(BackendConfig(id="o", type="ollama", base_url="http://127.0.0.1:11434/"),))
    p = tmp_path / "c.yaml"
    write_config_atomic(cfg, p)
    loaded = load_config(p)
    assert loaded.backends[0].base_url == "http://127.0.0.1:11434"
    assert loaded.config_hash and loaded.config_path == str(p)
    if os.name != "nt":
        assert oct(p.stat().st_mode & 0o777) == "0o600"


def test_affinity_scoped_per_caller_and_sources():
    a = AffinityStore(AffinityConfig(ttl_s=60))
    key, src = a.extract_session_key({"x-openwebui-chat-id": "chat1"}, {})
    assert key == "chat1" and src == "header:X-OpenWebUI-Chat-Id"
    key, src = a.extract_session_key({}, {"prompt_cache_key": "pc"})
    assert key == "pc" and src == "body:prompt_cache_key"
    key, src = a.extract_session_key({}, {"modelsaar": {"session": "s"}})
    assert key == "s" and src == "body:modelsaar.session"
    assert a.extract_session_key({"authorization": "Bearer k"}, {})[0] is None, "API key is never a session"
    a.set("caller1", "s", "dep-a", "header")
    assert a.get("caller1", "s").deployment_id == "dep-a"
    assert a.get("caller2", "s") is None
    a.remember_tool_calls("caller1", ["c1", "c2"], "dep-b")
    assert a.lookup_tool_round("caller1", ["c2", "c1"]).deployment_id == "dep-b"
    assert a.lookup_tool_round("caller2", ["c1"]) is None


# --------------------------------------------------------------------------- #
def test_client_config_generation_and_idempotent_apply(tmp_path: Path):
    from modelsaar.clientconfig import AliasInfo, ClientTarget, apply_patch, render

    t = ClientTarget("http://127.0.0.1:8484", aliases=[AliasInfo("auto", 32768, True, False), AliasInfo("auto-vision", 32768, True, True)])
    assert "http://127.0.0.1:8484/v1" in render("open-webui", t)
    assert "host.docker.internal:8484/v1" in render("open-webui", ClientTarget("http://127.0.0.1:8484", in_docker=True))
    oc = tmp_path / "opencode.json"
    oc.write_text(json.dumps({"$schema": "https://opencode.ai/config.json", "theme": "dark", "provider": {"other": {"npm": "x"}}}))
    res = apply_patch("opencode", t, oc, dry_run=False)
    assert res["applied"] and res["backup"]
    data = json.loads(oc.read_text())
    assert data["theme"] == "dark" and "other" in data["provider"], "unrelated settings preserved"
    assert data["provider"]["modelsaar"]["npm"] == "@ai-sdk/openai-compatible"
    assert data["provider"]["modelsaar"]["models"]["auto-vision"]["attachment"] is True
    res2 = apply_patch("opencode", t, oc, dry_run=False)
    assert not res2["changed"], "idempotent"
    with pytest.raises(ValueError):
        apply_patch("opencode-v2", t, oc, dry_run=False)  # never mix V1/V2
    hz = tmp_path / "config.yaml"
    hz.write_text("model:\n  default: foo\nother: 1\n")
    res = apply_patch("hermes", t, hz, dry_run=False)
    import yaml

    data = yaml.safe_load(hz.read_text())
    assert data["other"] == 1 and data["providers"]["modelsaar"]["transport"] == "chat_completions"
    assert data["providers"]["modelsaar"]["session_affinity_header"] == "X-ModelSaar-Session"
    assert "opencode" in render("opencode-v2", t) and '"providers"' in render("opencode-v2", t)
    assert "supportsPromptCacheKey" in render("openclaw", t)


# --------------------------------------------------------------------------- #
def test_probes_against_fake_backend(gateway, fake):
    from modelsaar.probes import run_probes

    r = gateway.router
    big = r.registry.get("ollama/big:27b")
    rep = gateway.gw.run(run_probes(r.adapters["ollama"], big, gateway.gw.store))
    vals = {x.capability: x.value for x in rep.results}
    assert vals["tools"] == "supported" and vals["streaming"] == "supported" and vals["vision"] == "supported"
    assert vals["json_schema"] == "supported" and vals["parallel_tools"] == "supported"
    assert rep.measurements and rep.measurements[0].samples == 2
    plain = r.registry.get("ollama/plain:3b")
    rep = gateway.gw.run(run_probes(r.adapters["ollama"], plain, gateway.gw.store, ["tools", "vision"]))
    vals = {x.capability: x.value for x in rep.results}
    assert vals["tools"] == "unsupported" and vals["vision"] == "unsupported"
    gateway.refresh()
    assert r.registry.get("ollama/big:27b").capabilities["vision"].provenance == "probe"


# --------------------------------------------------------------------------- #
def _cli(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "modelsaar.cli", *args], capture_output=True, text=True, env={**os.environ, **env}, timeout=120)


def test_cli_init_discover_explain_doctor(fake, tmp_path: Path):
    env = {"MODELSAAR_HOME": str(tmp_path / "home")}
    r = _cli(["init", "--endpoint", f"http://127.0.0.1:{fake.port}", "--type", "ollama"], env)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "home/config.yaml").exists() and (tmp_path / "home/keys/api_keys").exists()
    assert "ollama/big:27b" in r.stdout
    r = _cli(["discover"], env)
    assert r.returncode == 0 and "auto" in r.stdout
    r = _cli(["explain", "--message", "write a python function", "--tools", "--json"], env)
    assert r.returncode == 0, r.stderr
    dec = json.loads(r.stdout)
    assert dec["chosen"] in ("ollama/small:1b", "ollama/big:27b") and dec["requirements"]["needs_tools"]
    r = _cli(["doctor"], env)
    assert "[OK  ] backend:ollama" in r.stdout
    assert "cloud" in r.stdout  # remote alias warning
    r = _cli(["config", "validate"], env)
    assert r.returncode == 0
    r = _cli(["client-config", "opencode", "--dry-run"], env)
    assert r.returncode == 0 and "@ai-sdk/openai-compatible" in r.stdout
    r = _cli(["init", "--endpoint", f"http://127.0.0.1:{fake.port}"], env)
    assert r.returncode != 0 and "already exists" in r.stderr


def test_cli_uninstall_removes_only_own_files(tmp_path: Path):
    home = tmp_path / "home"
    (home / "keys").mkdir(parents=True)
    (home / "config.yaml").write_text("version: 1\n")
    other = tmp_path / "models" / "weights.bin"
    other.parent.mkdir()
    other.write_text("x")
    r = _cli(["uninstall", "--yes"], {"MODELSAAR_HOME": str(home)})
    assert r.returncode == 0 and not home.exists() and other.exists()


def test_eval_simulated_small():
    from modelsaar.evaluation.harness import load_tasks, run_simulated

    tasks = [t for t in load_tasks() if t["id"] in ("conv-01", "code-01", "math-01", "conv-04", "code-03", "math-03", "agent-03", "extract-03")]
    rep = run_simulated(tasks, seed=1)
    assert "auto (live routing)" in rep["results"]
    assert rep["results"]["oracle (offline upper bound, not available at runtime)"]["success"] >= rep["results"]["auto (live routing)"]["success"]
    assert rep["routing"]["overhead_ms_mean"] is not None
    assert rep["note"].startswith("SIMULATED")
