"""A controllable fake inference backend that speaks Ollama's native metadata
API and the OpenAI-compatible chat/embeddings API.

It is used by the contract/fault-injection test suite and by ``modelsaar demo``
(clearly labelled SIMULATED). Behaviours are deterministic and can be changed
per model at runtime:

  ok | error_500 | fail_mid_stream | truncate_stream | slow | hang | bad_json | unsupported_tools

Responses are synthetic: a model "answers" by echoing structural facts, calls
a tool when one is offered, emits schema-conformant JSON when asked, and
reports "red" for the embedded 1x1 probe image if it has the vision capability.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route


@dataclass
class FakeModel:
    name: str
    capabilities: list[str] = field(default_factory=lambda: ["completion"])
    context_length: int = 8192
    family: str = "fake"
    parameter_size: str = "1.0B"
    quantization: str = "Q4_K_M"
    size_bytes: int = 700_000_000
    behaviour: str = "ok"
    # Simulated per-token delay in seconds (for latency/perf tests).
    token_delay_s: float = 0.0
    remote: bool = False
    loaded: bool = False
    # Simulated "skill": which tasks this model answers correctly in the eval harness.
    good_at: list[str] = field(default_factory=list)
    json_schema_ok: bool = True
    embedding_dimensions: int = 8
    template: str = "{{ .Prompt }}"
    # Simulated thinking model: spends this many output tokens on reasoning before answering.
    thinking_tokens: int = 0


def _expected_json(text: str) -> dict[str, Any]:
    em = re.search(r"[\w.]+@[\w.]+", text)
    am = re.search(r"\b(\d{2})\b", text)
    return {"name": "Person", "email": em.group(0).rstrip(".;") if em else "", "age": int(am.group(1)) if am else 0}


_GOLD = {
    "math": lambda t: "391" if "17 * 23" in t else "72" if "180 km" in t else "6" if "3x + 7" in t else "55" if "first 10" in t else "50" if "perimeter 30" in t else "144" if "12 × 12" in t else "yes",
    "translation": lambda t: "La bibliothèque ouvre à neuf heures demain." if "library" in t else "¿Dónde está la estación de tren más cercana?" if "train station" in t else "The train is twenty minutes late.",
    "rag": lambda t: "2019" if "repainted" in t.split("Question:")[-1] else "410 metres" if "long" in t.split("Question:")[-1] else "harbour blue",
    "decision": lambda t: "negative" if "sentiment" in t else "account" if "password" in t else "sports",
    "summarization": lambda t: "LINE 0: THE QUICK BROWN FOX" if "uppercase" in t else "The council approved a six-month bicycle lane trial with a parking review.",
    "conversation": lambda t: "pineapple" if "pineapple" in t else "They weigh the same - both are one kilogram." if "feathers" in t else "La fotosíntesis es el proceso por el que las plantas usan la luz del sol para producir energía." if "fotosíntesis" in t else "Here is a friendly answer.",
    "coding": lambda t: _gold_code(t),
    "document_vision": lambda t: "red",
}


def _gold_code(t: str) -> str:
    if "is_palindrome" in t:
        return "```python\nimport re\ndef is_palindrome(s):\n    s = re.sub(r'[^a-z0-9]', '', s.lower())\n    return s == s[::-1]\n```"
    if "fizzbuzz" in t:
        return "```python\ndef fizzbuzz(n):\n    return ['FizzBuzz' if i%15==0 else 'Fizz' if i%3==0 else 'Buzz' if i%5==0 else str(i) for i in range(1,n+1)]\n```"
    if "word_freq" in t:
        return "```python\ndef word_freq(text):\n    d={}\n    for w in text.split():\n        w=w.strip('.,!?').lower()\n        d[w]=d.get(w,0)+1\n    return d\n```"
    if "def mean" in t:
        return "```python\ndef mean(xs):\n    return sum(xs) / len(xs)\n```"
    if "rle" in t:
        return "```python\ndef rle(s):\n    out=''\n    i=0\n    while i<len(s):\n        j=i\n        while j<len(s) and s[j]==s[i]: j+=1\n        out+=s[i]+str(j-i); i=j\n    return out\n```"
    return "It matches three digits, a hyphen, then four digits (undefined is not a function is a JavaScript error)."


def _expected_text(task: str, text: str, ok: bool, name: str) -> str:
    if not ok:
        return f"I am not sure about that. ({name})"
    fn = _GOLD.get(task)
    return fn(text) if fn else f"Answer from {name}."


class FakeBackend:
    def __init__(self, models: list[FakeModel], version: str = "0.0.0-fake") -> None:
        self.models: dict[str, FakeModel] = {m.name: m for m in models}
        self.version = version
        self.active = 0
        self.max_active = 0
        self.requests: list[dict[str, Any]] = []  # metadata only (model, stream, has_tools)
        self._lock = threading.Lock()
        self.app = self._build()
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0

    # ---------------------------------------------------------------- #
    def _build(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/api/version", self.api_version, methods=["GET"]),
                Route("/api/tags", self.api_tags, methods=["GET"]),
                Route("/api/show", self.api_show, methods=["POST"]),
                Route("/api/ps", self.api_ps, methods=["GET"]),
                Route("/v1/models", self.v1_models, methods=["GET"]),
                Route("/models", self.v1_models, methods=["GET"]),
                Route("/v1/chat/completions", self.v1_chat, methods=["POST"]),
                Route("/chat/completions", self.v1_chat, methods=["POST"]),
                Route("/v1/embeddings", self.v1_embeddings, methods=["POST"]),
                Route("/embeddings", self.v1_embeddings, methods=["POST"]),
                Route("/tokenize", self.tokenize, methods=["POST"]),
            ]
        )

    async def api_version(self, request: Request) -> Response:
        return JSONResponse({"version": self.version})

    async def api_tags(self, request: Request) -> Response:
        out = []
        for m in self.models.values():
            d: dict[str, Any] = {
                "name": m.name,
                "model": m.name,
                "size": m.size_bytes,
                "digest": f"sha256:{abs(hash((m.name, m.template, m.quantization))) % (10**12):012d}",
                "details": {
                    "family": m.family,
                    "parameter_size": m.parameter_size,
                    "quantization_level": m.quantization,
                },
            }
            if m.remote:
                d["remote_model"] = m.name
                d["remote_host"] = "https://ollama.com"
            out.append(d)
        return JSONResponse({"models": out})

    async def api_show(self, request: Request) -> Response:
        body = await request.json()
        m = self.models.get(body.get("model") or body.get("name"))
        if not m:
            return JSONResponse({"error": "model not found"}, status_code=404)
        return JSONResponse(
            {
                "capabilities": m.capabilities,
                "details": {"family": m.family, "parameter_size": m.parameter_size, "quantization_level": m.quantization},
                "model_info": {
                    "general.architecture": m.family,
                    f"{m.family}.context_length": m.context_length,
                    f"{m.family}.embedding_length": m.embedding_dimensions,
                },
                "template": m.template,
                "parameters": f"num_ctx {m.context_length}",
                "license": "fake-licence",
            }
        )

    async def api_ps(self, request: Request) -> Response:
        return JSONResponse(
            {
                "models": [
                    {"name": m.name, "model": m.name, "size": m.size_bytes, "size_vram": m.size_bytes, "context_length": m.context_length}
                    for m in self.models.values()
                    if m.loaded
                ]
            }
        )

    async def v1_models(self, request: Request) -> Response:
        return JSONResponse({"object": "list", "data": [{"id": m.name, "object": "model"} for m in self.models.values()]})

    # ---------------------------------------------------------------- #
    def _answer(self, m: FakeModel, body: dict[str, Any]) -> dict[str, Any]:
        """Return {'content': str} or {'tool_calls': [...]}."""
        msgs = body.get("messages") or []
        last = msgs[-1] if msgs else {}
        text = ""
        has_image = False
        if isinstance(last.get("content"), str):
            text = last["content"]
        elif isinstance(last.get("content"), list):
            for p in last["content"]:
                if p.get("type") == "text":
                    text += p.get("text", "")
                if p.get("type") == "image_url":
                    has_image = True
        tools = body.get("tools") or []
        if last.get("role") == "tool":
            n = len(str(last.get("content") or "").splitlines())
            return {"content": f"Tool result received ({last.get('tool_call_id')}). There are {n} entries. Final answer from {m.name}."}
        # Eval harness marker (simulation artefact): a model answers "correctly" when the task is in good_at.
        mk = re.search(r"<!-- eval:(\w+) -->", text)
        if mk:
            task = mk.group(1)
            ok = task in m.good_at
            if tools and "tools" in m.capabilities:
                if ok:
                    fn = tools[0].get("function", {})
                    return {"tool_calls": [{"id": f"call_{m.name.replace(':', '_')}_0", "type": "function", "function": {"name": fn.get("name", "fn"), "arguments": json.dumps({"command": "ls"})}}]}
                return {"content": f"I would list the files but I cannot. ({m.name})"}
            rf = body.get("response_format") or {}
            if rf.get("type") == "json_schema":
                return {"content": json.dumps({"name": "X", "email": "x@example.org", "age": 1}) if not ok else json.dumps(_expected_json(text))}
            return {"content": _expected_text(task, text, ok, m.name)}
        if tools and "tools" in m.capabilities and m.behaviour != "unsupported_tools":
            calls = []
            want_all = "both" in text.lower() or "one turn" in text.lower()
            for i, t in enumerate(tools[: 2 if want_all else 1]):
                fn = t.get("function", {})
                calls.append(
                    {
                        "id": f"call_{m.name.replace(':', '_')}_{i}",
                        "type": "function",
                        "function": {"name": fn.get("name", "fn"), "arguments": json.dumps({"city": "Paris"})},
                    }
                )
            return {"tool_calls": calls}
        rf = body.get("response_format") or {}
        if rf.get("type") == "json_schema":
            if m.json_schema_ok:
                return {"content": json.dumps({"city": "Paris", "population_millions": 2.1})}
            return {"content": "Paris has about 2.1 million people."}
        if rf.get("type") == "json_object":
            return {"content": json.dumps({"answer": 42})}
        if has_image:
            return {"content": "red" if "vision" in m.capabilities else "I cannot see images."}
        if "count from 1 to 5" in text.lower():
            return {"content": "1 2 3 4 5"}
        if "single word: ready" in text.lower():
            return {"content": "ready"}
        # Eval harness: a model answers "correctly" when the task is in its good_at list.
        task = (body.get("metadata") or {}).get("eval_task") if isinstance(body.get("metadata"), dict) else None
        if task:
            ok = task in m.good_at
            return {"content": f"[{'CORRECT' if ok else 'WRONG'}] answer from {m.name} for {task}"}
        return {"content": f"Hello from {m.name}: you said {text[:60]!r} — ünïcødé ✓"}

    async def v1_chat(self, request: Request) -> Response:
        body = await request.json()
        name = body.get("model")
        m = self.models.get(name)
        with self._lock:
            self.requests.append({"model": name, "stream": bool(body.get("stream")), "has_tools": bool(body.get("tools")), "fields": sorted(body.keys())})
        if not m:
            return JSONResponse({"error": {"message": f"model '{name}' not found", "type": "not_found"}}, status_code=404)
        if m.behaviour == "error_500":
            return JSONResponse({"error": {"message": "simulated internal error", "type": "server_error"}}, status_code=500)
        if m.behaviour == "hang":
            await asyncio.sleep(3600)
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if m.behaviour == "slow":
                await asyncio.sleep(1.0)
            ans = self._answer(m, body)
            rid = f"chatcmpl-fake-{int(time.time()*1000)}"
            budget = body.get("max_tokens") or 4096
            if m.thinking_tokens and not body.get("stream") and budget <= m.thinking_tokens:
                return JSONResponse(
                    {
                        "id": rid, "object": "chat.completion", "created": int(time.time()), "model": name,
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "", "reasoning_content": "thinking..."}, "finish_reason": "length"}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": budget, "total_tokens": 10 + budget},
                    }
                )
            if not body.get("stream"):
                if m.behaviour == "bad_json":
                    return Response(b"<html>not json</html>", status_code=200, media_type="text/html")
                msg: dict[str, Any] = {"role": "assistant", "content": ans.get("content")}
                finish = "stop"
                if ans.get("tool_calls"):
                    msg["tool_calls"] = ans["tool_calls"]
                    msg["content"] = None
                    finish = "tool_calls"
                return JSONResponse(
                    {
                        "id": rid,
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": name,
                        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    }
                )
            return StreamingResponse(self._stream(m, name, rid, ans, body), media_type="text/event-stream")
        finally:
            with self._lock:
                self.active -= 1

    async def _stream(self, m: FakeModel, name: str, rid: str, ans: dict[str, Any], body: dict[str, Any]) -> AsyncIterator[bytes]:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            def frame(delta: dict[str, Any], finish: str | None = None, usage: Any = None) -> bytes:
                obj: dict[str, Any] = {
                    "id": rid,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": name,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                if usage is not None:
                    obj["usage"] = usage
                return b"data: " + json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n\n"

            yield frame({"role": "assistant", "content": ""})
            if m.thinking_tokens:
                budget = body.get("max_tokens") or 4096
                for _ in range(3):
                    yield frame({"reasoning_content": "hmm "})
                if budget <= m.thinking_tokens:
                    yield frame({}, finish="length")
                    if (body.get("stream_options") or {}).get("include_usage"):
                        yield frame({}, usage={"prompt_tokens": 10, "completion_tokens": budget, "total_tokens": 10 + budget})
                    yield b"data: [DONE]\n\n"
                    return
            if m.behaviour == "truncate_stream":
                yield frame({"content": "half"})
                return  # ends cleanly without finish_reason or [DONE]
            if ans.get("tool_calls"):
                # Indexed, interleaved tool-call deltas: id+name first, then argument fragments.
                calls = ans["tool_calls"]
                for i, c in enumerate(calls):
                    yield frame({"tool_calls": [{"index": i, "id": c["id"], "type": "function", "function": {"name": c["function"]["name"], "arguments": ""}}]})
                args = [c["function"]["arguments"] for c in calls]
                pos = 0
                while any(pos < len(a) for a in args):
                    for i, a in enumerate(args):
                        if pos < len(a):
                            yield frame({"tool_calls": [{"index": i, "function": {"arguments": a[pos : pos + 4]}}]})
                    pos += 4
                if m.behaviour == "fail_mid_stream":
                    raise RuntimeError("simulated backend crash during tool streaming")
                yield frame({}, finish="tool_calls")
            else:
                content = ans.get("content") or ""
                words = content.split(" ")
                for i, w in enumerate(words):
                    piece = w + (" " if i < len(words) - 1 else "")
                    if m.behaviour == "fail_mid_stream" and i == max(1, len(words) // 2):
                        raise RuntimeError("simulated backend crash mid-stream")
                    if m.token_delay_s:
                        await asyncio.sleep(m.token_delay_s)
                    # Split the frame bytes into two partial writes to exercise partial-frame parsing,
                    # deliberately cutting inside multi-byte UTF-8 sequences when present.
                    data = frame({"content": piece})
                    cut = len(data) // 2
                    yield data[:cut]
                    await asyncio.sleep(0)
                    yield data[cut:]
                yield frame({}, finish="stop")
            if (body.get("stream_options") or {}).get("include_usage"):
                yield frame({}, usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
            yield b"data: [DONE]\n\n"
        finally:
            with self._lock:
                self.active -= 1

    async def tokenize(self, request: Request) -> Response:
        """vLLM-style /tokenize: here 1 token per 4 characters (deterministic fake tokenizer)."""
        body = await request.json()
        n = len(str(body.get("prompt", ""))) // 4
        return JSONResponse({"count": n, "max_model_len": 32768, "tokens": list(range(n))})

    async def v1_embeddings(self, request: Request) -> Response:
        body = await request.json()
        m = self.models.get(body.get("model"))
        if not m or "embedding" not in m.capabilities:
            return JSONResponse({"error": {"message": "not an embedding model", "type": "invalid_request_error"}}, status_code=400)
        inputs = body.get("input")
        if isinstance(inputs, str):
            inputs = [inputs]
        data = []
        for i, text in enumerate(inputs or []):
            vec = [((hash((m.name, str(text), j)) % 1000) / 1000.0) for j in range(m.embedding_dimensions)]
            data.append({"object": "embedding", "index": i, "embedding": vec})
        return JSONResponse({"object": "list", "data": data, "model": m.name, "usage": {"prompt_tokens": 3, "total_tokens": 3}})

    # ---------------------------------------------------------------- #
    def start(self, host: str = "127.0.0.1", port: int = 0) -> str:
        import socket

        if port == 0:
            s = socket.socket()
            s.bind((host, 0))
            port = s.getsockname()[1]
            s.close()
        self.port = port
        config = uvicorn.Config(self.app, host=host, port=port, log_level="error", lifespan="off")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.time() + 10
        while not self._server.started and time.time() < deadline:
            time.sleep(0.02)
        return f"http://{host}:{port}"

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
