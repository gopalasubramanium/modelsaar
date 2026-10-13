"""Typed, allow-listed view of the OpenAI Chat Completions / Embeddings requests.

We validate the structure we rely on (messages, tools, response_format,
tool_choice, token limits) and carry the original body through for
forwarding. Unknown top-level fields are preserved for forwarding only when
allow-listed by the adapter; otherwise they are rejected with a clear error.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# Fields we understand and forward unchanged (per adapter allow-list).
FORWARDABLE_CHAT_FIELDS = frozenset(
    {
        "model",
        "messages",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "response_format",
        "stream",
        "stream_options",
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "stop",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "n",
        "logprobs",
        "top_logprobs",
        "logit_bias",
        "user",
        "reasoning_effort",
        "metadata",
        "store",
        "prompt_cache_key",
        "service_tier",
        "modalities",
        "prediction",
        "audio",
        "web_search_options",
    }
)

# Fields that are ModelSaar-specific and must never be forwarded.
MODELSAAR_FIELDS = frozenset({"modelsaar"})

# Client-compatibility fields the gateway CONSUMES and never forwards. Some clients that know they talk to a
# self-hosted OpenAI-compatible server add llama.cpp-style hints (Odysseus's ``_apply_local_cache_affinity``
# sends ``session_id`` and ``cache_prompt=true``). The gateway gives them a defined meaning instead of either
# rejecting the request or passing them to a backend that may not implement them:
#   session_id   -> caller-scoped conversation affinity (same semantics as ``modelsaar.session``)
#   cache_prompt -> advisory performance hint; the backend manages its own prompt cache, nothing is promised
CLIENT_COMPAT_FIELDS = frozenset({"session_id", "cache_prompt"})
SESSION_ID_MAX_LEN = 256


class ProtocolError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "invalid_request_error", param: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.param = param

    def body(self) -> dict[str, Any]:
        return {"error": {"message": self.message, "type": self.code, "param": self.param, "code": self.code}}


class ToolFunction(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None
    strict: bool | None = None


class ToolDef(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str = "function"
    function: ToolFunction


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    type: str = "function"
    function: dict[str, Any]


# Content part types the gateway understands. Everything else (audio_url, video_url, input_video,
# file, input_file, refusal, ...) is rejected before any backend is contacted: a part the gateway
# cannot classify could carry media or fetch instructions for a backend that is not allowed to
# receive them.
SUPPORTED_PART_TYPES = frozenset({"text", "image_url", "input_audio"})
_PART_KEYS = {
    "text": {"type", "text"},
    "image_url": {"type", "image_url"},
    "input_audio": {"type", "input_audio"},
}


def validate_content_parts(content: Any, where: str) -> None:
    """Typed validation of multipart message content. Raises ProtocolError (400) on anything unknown."""
    if content is None or isinstance(content, str):
        return
    if not isinstance(content, list):
        raise ProtocolError(f"{where}: content must be a string or a list of content parts", param=where)
    for i, part in enumerate(content):
        loc = f"{where}.content[{i}]"
        if not isinstance(part, dict):
            raise ProtocolError(f"{loc}: content part must be an object", param=loc)
        t = part.get("type")
        if t not in SUPPORTED_PART_TYPES:
            raise ProtocolError(
                f"{loc}: unsupported content part type {t!r}; ModelSaar 0.1 accepts "
                f"{sorted(SUPPORTED_PART_TYPES)} only (audio/video/file parts are not forwarded to any backend)",
                param=loc,
                code="unsupported_content_type",
            )
        extra = set(part.keys()) - _PART_KEYS[t]
        if extra:
            raise ProtocolError(f"{loc}: unexpected keys {sorted(extra)} in a {t} part", param=loc)
        if t == "text" and not isinstance(part.get("text"), str):
            raise ProtocolError(f"{loc}: text part requires a string 'text'", param=loc)
        if t == "image_url":
            iu = part.get("image_url")
            url = iu.get("url") if isinstance(iu, dict) else iu
            if not isinstance(url, str) or not url:
                raise ProtocolError(f"{loc}: image_url part requires image_url.url (string)", param=loc)
            if isinstance(iu, dict) and set(iu.keys()) - {"url", "detail"}:
                raise ProtocolError(f"{loc}: unexpected keys in image_url", param=loc)
        if t == "input_audio":
            ia = part.get("input_audio")
            if not isinstance(ia, dict) or not isinstance(ia.get("data"), str) or not isinstance(ia.get("format"), str):
                raise ProtocolError(f"{loc}: input_audio part requires inline input_audio.data and .format", param=loc)
            if set(ia.keys()) - {"data", "format"}:
                raise ProtocolError(f"{loc}: unexpected keys in input_audio (remote audio is not fetched)", param=loc)


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: Any = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    reasoning_content: str | None = None

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ("system", "developer", "user", "assistant", "tool", "function"):
            raise ValueError(f"unsupported role {v!r}")
        return v


class ChatRequest(BaseModel):
    """Validated view. The raw body is kept separately for forwarding."""

    model_config = ConfigDict(extra="allow")
    model: str
    messages: list[Message] = Field(min_length=1)
    tools: list[ToolDef] | None = None
    tool_choice: Any = None
    parallel_tool_calls: bool | None = None
    response_format: dict[str, Any] | None = None
    stream: bool = False
    stream_options: dict[str, Any] | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=10_000_000)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=10_000_000)
    reasoning_effort: str | None = None
    n: int | None = None
    user: str | None = None
    prompt_cache_key: str | None = None
    modelsaar: dict[str, Any] | None = None  # per-request routing hints (session, profile)
    session_id: Any = None  # client-compat conversation id (validated below; consumed, never forwarded)
    cache_prompt: Any = None  # client-compat advisory cache hint (validated below; consumed, never forwarded)

    @field_validator("n")
    @classmethod
    def _n(cls, v: int | None) -> int | None:
        if v is not None and v != 1:
            raise ValueError("n > 1 is not supported by the gateway")
        return v

    @field_validator("session_id")
    @classmethod
    def _session_id(cls, v: Any) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str) or not v.strip() or len(v) > SESSION_ID_MAX_LEN or any(ord(ch) < 32 or ch == "\x7f" for ch in v):
            raise ValueError(
                f"session_id must be a non-empty printable string of at most {SESSION_ID_MAX_LEN} characters "
                "(a client conversation id; the gateway uses it as caller-scoped conversation affinity)"
            )
        return v

    @field_validator("cache_prompt")
    @classmethod
    def _cache_prompt(cls, v: Any) -> bool | None:
        if v is None:
            return None
        if not isinstance(v, bool):
            raise ValueError("cache_prompt must be a JSON boolean (an advisory prompt-cache hint; the gateway does not coerce strings or numbers)")
        return v


class EmbeddingsRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str
    input: Any
    encoding_format: str | None = None
    dimensions: int | None = None
    user: str | None = None


def parse_chat_request(body: dict[str, Any]) -> ChatRequest:
    try:
        req = ChatRequest.model_validate(body)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", ()))
        raise ProtocolError(f"invalid chat request: {first.get('msg')} at {loc}", param=loc or None) from e
    for i, m in enumerate(body.get("messages") or []):
        if isinstance(m, dict):
            validate_content_parts(m.get("content"), f"messages[{i}]")
    unknown = set(body.keys()) - FORWARDABLE_CHAT_FIELDS - MODELSAAR_FIELDS - CLIENT_COMPAT_FIELDS
    if unknown:
        raise ProtocolError(
            f"unsupported request field(s): {sorted(unknown)}; the gateway forwards only allow-listed fields "
            "and does not silently drop unknown semantics",
            param=sorted(unknown)[0],
        )
    return req


def parse_embeddings_request(body: dict[str, Any]) -> EmbeddingsRequest:
    try:
        return EmbeddingsRequest.model_validate(body)
    except ValidationError as e:
        first = e.errors()[0]
        raise ProtocolError(f"invalid embeddings request: {first.get('msg')}") from e


def error_body(message: str, code: str = "invalid_request_error", param: str | None = None, **extra: Any) -> dict:
    err: dict[str, Any] = {"message": message, "type": code, "param": param, "code": code}
    err.update(extra)
    return {"error": err}


def sse_error_frame(message: str, code: str = "upstream_error", **extra: Any) -> bytes:
    return b"data: " + json.dumps(error_body(message, code, **extra), separators=(",", ":")).encode() + b"\n\n"
