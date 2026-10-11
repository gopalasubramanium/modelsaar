"""Capability probes: cheap, bounded live checks that turn claims into evidence.

Probes are explicit (``modelsaar probe``) because they consume local compute.
Results are stored per deployment *fingerprint*; a changed model, template,
quantization or runtime invalidates them automatically.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from .adapters.base import AdapterError, BaseAdapter, UpstreamResponse, UpstreamStream
from .protocol.sse import SSEParser, StreamObserver
from .registry import Deployment, Measurement
from .store import Store

# A 1x1 red PNG (generated with Pillow once; embedded to avoid a dependency).
# Thinking models spend output tokens on reasoning before the answer; keep probe budgets generous.
PROBE_MAX_TOKENS = 1024
PROBE_NAMES = frozenset({"streaming", "tools", "parallel_tools", "json_object", "json_schema", "vision", "latency"})
STREAM_PROBE_MAX_TOKENS = 400

_RED_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


@dataclass
class ProbeResult:
    capability: str
    value: str  # supported | unsupported | unknown
    note: str = ""
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProbeReport:
    deployment_id: str
    fingerprint: str
    results: list[ProbeResult] = field(default_factory=list)
    measurements: list[Measurement] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "fingerprint": self.fingerprint,
            "results": [r.__dict__ for r in self.results],
            "measurements": [m.__dict__ for m in self.measurements],
            "errors": self.errors,
        }


_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": "Get the current time in a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    },
}
_TOOL2 = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather in a city.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    },
}
_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "population_millions": {"type": "number"}},
    "required": ["city", "population_millions"],
    "additionalProperties": False,
}


async def _chat(adapter: BaseAdapter, dep: Deployment, body: dict[str, Any], timeout: float) -> UpstreamResponse:
    body = dict(body)
    body.setdefault("temperature", 0)
    body.setdefault("max_tokens", PROBE_MAX_TOKENS)
    return await adapter.chat(dep, body, stream=False, timeout=timeout)


def _budget_exhausted(resp: UpstreamResponse) -> bool:
    """Empty content with finish_reason=length: the model (probably thinking) used the whole budget."""
    try:
        ch = resp.body["choices"][0]
        return ch.get("finish_reason") == "length" and not (ch.get("message") or {}).get("content")
    except (KeyError, IndexError, TypeError):
        return False


_EXHAUSTED_NOTE = "output budget exhausted before an answer (thinking model?); increase PROBE_MAX_TOKENS or disable thinking"


def _content(resp: UpstreamResponse) -> str:
    try:
        c = resp.body["choices"][0]["message"].get("content")
        if isinstance(c, list):
            return "".join(p.get("text", "") for p in c if isinstance(p, dict))
        return c or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _tool_calls(resp: UpstreamResponse) -> list[dict[str, Any]]:
    try:
        return resp.body["choices"][0]["message"].get("tool_calls") or []
    except (KeyError, IndexError, TypeError):
        return []


async def probe_tools(adapter: BaseAdapter, dep: Deployment, timeout: float) -> ProbeResult:
    t0 = time.monotonic()
    body = {
        "messages": [{"role": "user", "content": "What time is it in Paris right now? You must call the tool."}],
        "tools": [_TOOL],
    }
    try:
        r = await _chat(adapter, dep, body, timeout)
    except AdapterError as e:
        return ProbeResult("tools", "unknown", f"probe error: {e.message[:100]}")
    ms = (time.monotonic() - t0) * 1000
    if r.status >= 500:
        return ProbeResult("tools", "unknown", f"backend returned {r.status} (transient?) for a tools request", ms)
    if r.status != 200:
        return ProbeResult("tools", "unsupported", f"backend returned {r.status} for a tools request", ms)
    calls = _tool_calls(r)
    for c in calls:
        fn = c.get("function") or {}
        if fn.get("name") == "get_current_time" and c.get("id"):
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                return ProbeResult("tools", "unsupported", "tool call emitted with non-JSON arguments", ms)
            ok = isinstance(args, dict) and "city" in args
            return ProbeResult("tools", "supported" if ok else "unsupported", "tool call with id and JSON args" if ok else "arguments missing required key", ms)
    return ProbeResult("tools", "unsupported", "no tool_calls returned for an explicit tool request", ms)


async def probe_parallel_tools(adapter: BaseAdapter, dep: Deployment, timeout: float) -> ProbeResult:
    t0 = time.monotonic()
    body = {
        "messages": [
            {"role": "user", "content": "Call both tools: get the current time in Tokyo AND the weather in Tokyo, in one turn."}
        ],
        "tools": [_TOOL, _TOOL2],
    }
    try:
        r = await _chat(adapter, dep, body, timeout)
    except AdapterError as e:
        return ProbeResult("parallel_tools", "unknown", f"probe error: {e.message[:100]}")
    ms = (time.monotonic() - t0) * 1000
    names = {(c.get("function") or {}).get("name") for c in _tool_calls(r)}
    if {"get_current_time", "get_weather"} <= names:
        return ProbeResult("parallel_tools", "supported", "two distinct tool calls in one turn", ms)
    return ProbeResult("parallel_tools", "unsupported", f"got {sorted(n for n in names if n)}", ms)


async def probe_json_schema(adapter: BaseAdapter, dep: Deployment, timeout: float) -> ProbeResult:
    t0 = time.monotonic()
    body = {
        "messages": [{"role": "user", "content": "Give the city Paris and its population in millions."}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "city", "schema": _SCHEMA, "strict": True}},
    }
    try:
        r = await _chat(adapter, dep, body, timeout)
    except AdapterError as e:
        return ProbeResult("json_schema", "unknown", f"probe error: {e.message[:100]}")
    ms = (time.monotonic() - t0) * 1000
    if r.status >= 500:
        return ProbeResult("json_schema", "unknown", f"backend returned {r.status} (transient?)", ms)
    if r.status != 200:
        return ProbeResult("json_schema", "unsupported", f"backend returned {r.status} for response_format=json_schema", ms)
    if _budget_exhausted(r):
        return ProbeResult("json_schema", "unknown", _EXHAUSTED_NOTE, ms)
    txt = _content(r).strip()
    try:
        obj = json.loads(txt)
    except json.JSONDecodeError:
        return ProbeResult("json_schema", "unsupported", "content is not valid JSON", ms)
    ok = (
        isinstance(obj, dict)
        and isinstance(obj.get("city"), str)
        and isinstance(obj.get("population_millions"), (int, float))
        and set(obj.keys()) <= {"city", "population_millions"}
    )
    return ProbeResult("json_schema", "supported" if ok else "unsupported", "schema-conformant object" if ok else f"non-conformant: keys={sorted(obj) if isinstance(obj, dict) else type(obj).__name__}", ms)


async def probe_json_object(adapter: BaseAdapter, dep: Deployment, timeout: float) -> ProbeResult:
    t0 = time.monotonic()
    body = {
        "messages": [{"role": "user", "content": "Return a JSON object with a key 'answer' whose value is the number 42."}],
        "response_format": {"type": "json_object"},
    }
    try:
        r = await _chat(adapter, dep, body, timeout)
    except AdapterError as e:
        return ProbeResult("json_object", "unknown", f"probe error: {e.message[:100]}")
    ms = (time.monotonic() - t0) * 1000
    if _budget_exhausted(r):
        return ProbeResult("json_object", "unknown", _EXHAUSTED_NOTE, ms)
    try:
        obj = json.loads(_content(r).strip())
        return ProbeResult("json_object", "supported" if isinstance(obj, dict) else "unsupported", "", ms)
    except json.JSONDecodeError:
        return ProbeResult("json_object", "unsupported", "content is not valid JSON", ms)


async def probe_vision(adapter: BaseAdapter, dep: Deployment, timeout: float) -> ProbeResult:
    t0 = time.monotonic()
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What single colour is this image? Answer with one word."},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _RED_PNG_B64}},
                ],
            }
        ]
    }
    try:
        r = await _chat(adapter, dep, body, timeout)
    except AdapterError as e:
        return ProbeResult("vision", "unknown", f"probe error: {e.message[:100]}")
    ms = (time.monotonic() - t0) * 1000
    if r.status >= 500:
        return ProbeResult("vision", "unknown", f"backend returned {r.status} (transient?)", ms)
    if r.status != 200:
        return ProbeResult("vision", "unsupported", f"backend returned {r.status} for an image request", ms)
    if _budget_exhausted(r):
        return ProbeResult("vision", "unknown", _EXHAUSTED_NOTE, ms)
    txt = _content(r).lower()
    if "red" in txt:
        return ProbeResult("vision", "supported", "accepted a base64 image and identified its colour", ms)
    return ProbeResult("vision", "unsupported", f"image accepted but answer did not identify the colour ({txt[:40]!r})", ms)


async def probe_streaming(adapter: BaseAdapter, dep: Deployment, timeout: float) -> tuple[ProbeResult, float | None]:
    t0 = time.monotonic()
    body = {"messages": [{"role": "user", "content": "Count from 1 to 5, separated by spaces."}], "max_tokens": STREAM_PROBE_MAX_TOKENS, "temperature": 0}
    try:
        s: UpstreamStream = await adapter.chat(dep, body, stream=True, timeout=timeout)
    except AdapterError as e:
        return ProbeResult("streaming", "unknown", f"probe error: {e.message[:100]}"), None
    if s.status != 200:
        await s.close()
        return ProbeResult("streaming", "unknown" if s.status >= 500 else "unsupported", f"backend returned {s.status}"), None
    parser = SSEParser()
    obs = StreamObserver()
    ttft: float | None = None
    try:
        async for chunk in s.aiter_bytes():
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            for ev in parser.feed(chunk):
                obs.observe(ev)
    finally:
        await s.close()
    ms = (time.monotonic() - t0) * 1000
    delivered = obs.content_chunks >= 1 or obs.reasoning_chunks >= 1
    ok = obs.events >= 2 and delivered and obs.saw_done
    value = "supported" if ok else ("unknown" if (obs.events >= 2 and obs.saw_done and obs.finish_reason == "length") else "unsupported")
    note = (
        f"events={obs.events} content_chunks={obs.content_chunks} reasoning_chunks={obs.reasoning_chunks} "
        f"done={obs.saw_done} finish={obs.finish_reason} usage={'yes' if obs.usage else 'no'}"
    )
    if value == "unknown":
        note += "; " + _EXHAUSTED_NOTE
    return ProbeResult("streaming", value, note, ms), ttft


async def measure_latency(adapter: BaseAdapter, dep: Deployment, timeout: float) -> Measurement:
    """Two short requests: the first may include model loading, the second is warm."""
    body = {"messages": [{"role": "user", "content": "Reply with the single word: ready"}], "max_tokens": 256, "temperature": 0}
    times: list[float] = []
    for _ in range(2):
        t0 = time.monotonic()
        try:
            r = await _chat(adapter, dep, body, timeout)
        except AdapterError:
            break
        if r.status != 200:
            break
        times.append((time.monotonic() - t0) * 1000)
    m = Measurement(task="latency_probe", samples=len(times), source="probe", measured_at=time.time())
    if len(times) == 2:
        m.p50_ms = times[1]
        m.p95_ms = max(times)
        m.load_ms = max(0.0, times[0] - times[1]) if not dep.loaded else 0.0
    elif times:
        m.p50_ms = times[0]
    return m


async def run_probes(
    adapter: BaseAdapter,
    dep: Deployment,
    store: Store | None,
    which: list[str] | None = None,
    timeout: float = 120.0,
) -> ProbeReport:
    which = which or ["streaming", "tools", "parallel_tools", "json_object", "json_schema", "vision", "latency"]
    rep = ProbeReport(dep.id, dep.fingerprint)
    if dep.role != "generative":
        rep.errors.append(f"deployment role is {dep.role}; chat probes apply only to generative deployments")
        return rep

    async def _save(r: ProbeResult) -> None:
        rep.results.append(r)
        if r.value != "unknown":
            dep.set_cap(r.capability, r.value, "probe", r.note)  # type: ignore[arg-type]
            if store:
                store.save_probe(dep.id, dep.fingerprint, r.capability, r.value, r.note)

    ttft: float | None = None
    if "streaming" in which:
        r, ttft = await probe_streaming(adapter, dep, timeout)
        await _save(r)
    if "tools" in which:
        if dep.cap("tools") == "unsupported" and dep.capabilities["tools"].provenance == "source_claim":
            rep.results.append(ProbeResult("tools", "unsupported", "skipped: backend metadata says tools unsupported"))
        else:
            await _save(await probe_tools(adapter, dep, timeout))
    if "parallel_tools" in which and dep.cap("tools") == "supported":
        await _save(await probe_parallel_tools(adapter, dep, timeout))
    if "json_object" in which:
        await _save(await probe_json_object(adapter, dep, timeout))
    if "json_schema" in which:
        await _save(await probe_json_schema(adapter, dep, timeout))
    if "vision" in which:
        if dep.cap("vision") == "unsupported" and dep.capabilities["vision"].provenance == "source_claim":
            rep.results.append(ProbeResult("vision", "unsupported", "skipped: backend metadata says vision unsupported"))
        else:
            await _save(await probe_vision(adapter, dep, timeout))
    if "latency" in which:
        m = await measure_latency(adapter, dep, timeout)
        if ttft is not None:
            m.ttft_ms = ttft
        rep.measurements.append(m)
        dep.measurements[m.task] = m
        if store and m.samples:
            store.save_measurement(dep.id, dep.fingerprint, m.__dict__)
    return rep
