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

    @field_validator("n")
    @classmethod
    def _n(cls, v: int | None) -> int | None:
        if v is not None and v != 1:
            raise ValueError("n > 1 is not supported by the gateway")
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
    unknown = set(body.keys()) - FORWARDABLE_CHAT_FIELDS - MODELSAAR_FIELDS
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
