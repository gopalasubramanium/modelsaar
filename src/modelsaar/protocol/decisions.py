"""`POST /v1/decisions` — the gateway's decision-model endpoint.

The wire contract is Ollama's System One request and answer (docs.ollama.com/api/systemone), carried
through the gateway with its usual authentication, model resolution, admission, locality policy and
decision records:

request  ``{"model": <deployment id | "auto">, "state": <non-empty string | object | array>,
            "questions": {<name>: {"type": "choice"|"noul"|"score", "instructions": ..., "criteria": ...}},
            "images": [<base64>, ...]  (optional; needs a vision-capable decision model)}``
response ``{"model": ..., "answers": {<name>: <answer>}, "usage": {"input_tokens": n, "output_tokens": n}}``

Question limits are the documented ones (1..64 questions; ``choice`` 2..255 options; ``score`` 2..10
levels; text and schema at most 64 KiB; the whole request the backend receives — JSON including base64
images — at most 32 MiB, checked before dispatch). Before any of that, the gateway reads at most
``server.max_request_bytes`` (default 32 MiB) of the client's body — a larger declared ``Content-Length``
is refused before reading and a streamed body is cut off at the limit — so no request is buffered beyond
that bound. ``keep_alive`` and any other field are refused: model lifecycle
is managed by the gateway, not per request. Answers are validated against the questions before they are
returned (type match, options from the criteria, probabilities and confidence in [0, 1]); a backend answer
that violates the contract is reported as ``decision_contract_violation`` instead of being passed on.
"""

from __future__ import annotations

import base64
import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .openai import ProtocolError

MAX_QUESTIONS = 64
MAX_TEXT_BYTES = 64 * 1024  # documented local limit for state + questions (excluding images)
MAX_REQUEST_BYTES = 32 * 1024 * 1024  # documented local limit for the whole request Ollama receives (JSON incl. base64 images)
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
Instructions = str | dict[str, Any] | list[Any]


def _non_empty_text(v: Any, what: str) -> Any:
    if isinstance(v, str):
        if not v.strip():
            raise ValueError(f"{what} must contain a non-whitespace character")
        return v
    if isinstance(v, (dict, list)):
        return v
    raise ValueError(f"{what} must be a non-empty string, an object or an array")


class ChoiceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["choice"]
    instructions: Instructions
    criteria: dict[str, str | None] = Field(min_length=2, max_length=255)

    @field_validator("instructions")
    @classmethod
    def _instr(cls, v: Any) -> Any:
        return _non_empty_text(v, "instructions")


class NoulQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["noul"]
    instructions: Instructions
    criteria: dict[Literal["true", "false"], str] | None = None

    @field_validator("instructions")
    @classmethod
    def _instr(cls, v: Any) -> Any:
        return _non_empty_text(v, "instructions")


class ScoreQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["score"]
    instructions: Instructions
    criteria: list[str] = Field(min_length=2, max_length=10)

    @field_validator("instructions")
    @classmethod
    def _instr(cls, v: Any) -> Any:
        return _non_empty_text(v, "instructions")


Question = ChoiceQuestion | NoulQuestion | ScoreQuestion


class DecisionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1)
    state: Any
    questions: dict[str, Question] = Field(min_length=1, max_length=MAX_QUESTIONS)
    images: list[str] | None = None

    @field_validator("state")
    @classmethod
    def _state(cls, v: Any) -> Any:
        return _non_empty_text(v, "state")

    @field_validator("questions")
    @classmethod
    def _names(cls, v: dict[str, Question]) -> dict[str, Question]:
        for name in v:
            if not _NAME_RE.match(name):
                raise ValueError(f"question name {name!r} must be 1-100 characters of letters, digits, '_', '.' or '-'")
        return v

    @field_validator("images")
    @classmethod
    def _images(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("images must not be empty when present")
        for i, img in enumerate(v):
            if not isinstance(img, str) or not img:
                raise ValueError(f"images[{i}] must be a base64 string")
            if img.startswith(("data:", "http://", "https://")):
                raise ValueError(f"images[{i}]: URLs and data URLs are not accepted; send raw base64")
            try:
                base64.b64decode(img, validate=True)
            except Exception as e:  # noqa: BLE001
                raise ValueError(f"images[{i}] is not valid base64") from e
        return v

    @model_validator(mode="after")
    def _size(self) -> DecisionsRequest:
        text = json.dumps({"state": self.state, "questions": {k: q.model_dump() for k, q in self.questions.items()}}, ensure_ascii=False)
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError(f"state and questions exceed {MAX_TEXT_BYTES // 1024} KiB")
        return self

    def upstream_questions(self) -> dict[str, Any]:
        return {k: q.model_dump(exclude_none=True) for k, q in self.questions.items()}

    def upstream_bytes(self) -> int:
        """Size of the JSON the backend will receive (model, state, questions, images), as the adapter
        serialises it; checked against the documented 32 MiB whole-request limit before dispatch."""
        body: dict[str, Any] = {"model": self.model, "state": self.state, "questions": self.upstream_questions()}
        if self.images:
            body["images"] = self.images
        return len(json.dumps(body).encode("utf-8"))


def parse_decisions_request(body: dict[str, Any]) -> DecisionsRequest:
    """Validate the body. Field errors are ``400`` naming the field; a request whose upstream form would
    exceed the documented whole-request limit is ``413`` (the gateway's own ``server.max_request_bytes``
    bounds the bytes read from the client before this point)."""
    try:
        req = DecisionsRequest.model_validate(body)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ()))
        msg = first.get("msg", "invalid request")
        raise ProtocolError(
            f"invalid decisions request: {loc + ': ' if loc else ''}{msg}", param=loc.split(".")[0] if loc else None
        ) from e
    size = req.upstream_bytes()
    if size > MAX_REQUEST_BYTES:
        raise ProtocolError(
            f"decisions request too large: {size} bytes including base64 images and JSON overhead exceed the "
            f"{MAX_REQUEST_BYTES // (1024 * 1024)} MiB limit of the decision backend",
            status=413,
            param="images" if req.images else "state",
        )
    return req


# --------------------------------------------------------------------------- #
# Answer validation (the backend's answer is untrusted data)
# --------------------------------------------------------------------------- #
def _unit(v: Any) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and 0.0 <= v <= 1.0


def decision_answers_problem(req: DecisionsRequest, body: Any) -> str | None:
    """Return a description of the first contract violation in an upstream answer body, or ``None``."""
    if not isinstance(body, dict):
        return "response is not a JSON object"
    answers = body.get("answers")
    if not isinstance(answers, dict):
        return "response has no 'answers' object"
    missing = sorted(set(req.questions) - set(answers))
    if missing:
        return f"no answer for question(s) {missing}"
    extra = sorted(set(answers) - set(req.questions))
    if extra:
        return f"answers for unknown question(s) {extra}"
    for name, q in req.questions.items():
        a = answers[name]
        if not isinstance(a, dict):
            return f"answer {name!r} is not an object"
        if a.get("type") != q.type:
            return f"answer {name!r} has type {a.get('type')!r}, question type is {q.type!r}"
        if q.type == "choice":
            probs = a.get("probabilities")
            if not isinstance(probs, dict) or set(probs) != set(q.criteria):
                return f"answer {name!r}: probabilities do not cover exactly the {len(q.criteria)} options"
            if not all(_unit(p) for p in probs.values()):
                return f"answer {name!r}: a probability is not a finite number in [0, 1]"
            choice = a.get("choice")
            if not isinstance(choice, str) or choice not in q.criteria:
                return f"answer {name!r}: choice is not one of the options"
            if any(p > probs[choice] for p in probs.values()):
                return f"answer {name!r}: choice is not the highest-probability option"
            if not _unit(a.get("confidence")):
                return f"answer {name!r}: confidence is not a finite number in [0, 1]"
        elif q.type == "noul":
            if not _unit(a.get("noul")):
                return f"answer {name!r}: noul is not a finite number in [0, 1]"
        else:  # score
            n = len(q.criteria)
            score = a.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= n - 1:
                return f"answer {name!r}: score is not a finite number in [0, {n - 1}]"
            probs = a.get("probabilities")
            if not isinstance(probs, dict) or set(probs) != {str(i) for i in range(n)}:
                return f"answer {name!r}: probabilities do not cover exactly the {n} levels"
            if not all(_unit(p) for p in probs.values()):
                return f"answer {name!r}: a probability is not a finite number in [0, 1]"
            if not _unit(a.get("confidence")):
                return f"answer {name!r}: confidence is not a finite number in [0, 1]"
    usage = body.get("usage")
    if usage is not None and not isinstance(usage, dict):
        return "usage is not an object"
    return None
