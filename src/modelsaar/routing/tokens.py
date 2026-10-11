"""Token accounting.

Exact tokenization is used when the backend exposes it (vLLM ``/tokenize``).
Otherwise a *documented conservative estimate* is applied: ``chars/3`` plus
per-message, per-tool and per-image overheads, plus the requested output and
any applicable reasoning budget. The estimate is deliberately pessimistic so
that a deployment is never chosen whose context the real request would overflow.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from ..config import TokenEstimateConfig


@dataclass
class TokenBudget:
    input_estimate: int
    output_allowance: int
    reasoning_allowance: int
    images: int
    method: str  # "exact:<backend>" | "estimate:chars/3"

    @property
    def total(self) -> int:
        return self.input_estimate + self.output_allowance + self.reasoning_allowance


_WIDE = re.compile(r"[\u0400-\u04FF\u0590-\u08FF\u0900-\u0DFF\u0E00-\u0E7F\u1100-\u11FF\u3000-\u30FF\u3400-\u9FFF\uAC00-\uD7AF\uF900-\uFAFF\uFF00-\uFFEF]")


def _wide_count(text: str) -> int:
    """Characters from scripts where tokenizers spend ~1+ token per character."""
    return len(_WIDE.findall(text))


def _text_of(content: Any) -> tuple[str, int]:
    """Flatten message content to text; return (text, image_count)."""
    if content is None:
        return "", 0
    if isinstance(content, str):
        return content, 0
    images = 0
    parts: list[str] = []
    if isinstance(content, list):
        for p in content:
            if not isinstance(p, dict):
                parts.append(str(p))
                continue
            t = p.get("type")
            if t in ("text", "input_text"):
                parts.append(str(p.get("text", "")))
            elif t in ("image_url", "input_image", "image"):
                images += 1
            elif t in ("input_audio", "audio"):
                parts.append("")  # audio has its own requirement flag
            else:
                parts.append(json.dumps(p, ensure_ascii=False))
    return "\n".join(parts), images


def estimate_chat_tokens(body: dict[str, Any], cfg: TokenEstimateConfig, thinking_possible: bool) -> TokenBudget:
    chars = 0
    wide_chars = 0
    images = 0
    msgs = body.get("messages") or []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        t, im = _text_of(m.get("content"))
        w = _wide_count(t)
        wide_chars += w
        chars += len(t) - w
        images += im
        if m.get("tool_calls"):
            chars += len(json.dumps(m["tool_calls"], ensure_ascii=False))
        if m.get("reasoning_content"):
            chars += len(str(m["reasoning_content"]))
        if m.get("name"):
            chars += len(str(m["name"]))
    tools = body.get("tools") or []
    tool_overhead = 0
    for t in tools:
        chars += len(json.dumps(t, ensure_ascii=False))
        tool_overhead += cfg.tool_definition_overhead
    rf = body.get("response_format")
    if isinstance(rf, dict):
        chars += len(json.dumps(rf, ensure_ascii=False))
    latin_chars = chars
    text_tokens = math.ceil(latin_chars / cfg.chars_per_token) + wide_chars  # 1 token per non-Latin char (conservative)
    input_estimate = text_tokens + len(msgs) * cfg.per_message_overhead + tool_overhead + images * cfg.image_tokens
    input_estimate = math.ceil(input_estimate * (1 + cfg.safety_margin))
    out = body.get("max_completion_tokens") or body.get("max_tokens") or cfg.default_max_output
    if not isinstance(out, int) or out < 1:
        out = cfg.default_max_output
    reasoning = cfg.reasoning_budget if thinking_possible else 0
    return TokenBudget(
        input_estimate=input_estimate,
        output_allowance=int(out),
        reasoning_allowance=reasoning,
        images=images,
        method=f"estimate:chars/{cfg.chars_per_token:g}+overheads",
    )


def estimate_text_tokens(text: str, cfg: TokenEstimateConfig) -> int:
    w = _wide_count(text)
    return math.ceil(((len(text) - w) / cfg.chars_per_token + w) * (1 + cfg.safety_margin))
