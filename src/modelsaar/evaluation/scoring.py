"""Scorers for evaluation tasks. Executable where possible; never an LLM judge.

``score(task, response)`` returns ``(ok, detail)``. ``ok`` is ``True``/``False``, or ``None`` when
the task could not be scored at all (currently only ``code_exec`` without an isolation
backend); the harness counts ``None`` as *skipped* with its own denominator, never as a failure
and never as a success.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from . import sandbox

# Bump whenever a scorer's acceptance rule changes so reports are not compared across rules.
SCORER_VERSION = "2026.10.12-3"

_CODE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)
# Standalone numeric tokens: optional sign (not glued to a preceding word/number, so "25-7"
# yields 25 and 7), digits with optional thousands commas, optional decimal part.
_NUMBER = re.compile(r"(?<![\w.])(-?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\w])")

Runner = Callable[[str, str, float], tuple[str, str, int, str]]


def _basic_schema_check(obj: Any, schema: dict[str, Any]) -> bool:
    """Minimal JSON-schema conformance (type/required/additionalProperties/properties types)."""
    t = schema.get("type")
    if t == "object":
        if not isinstance(obj, dict):
            return False
        props = schema.get("properties", {})
        for r in schema.get("required", []):
            if r not in obj:
                return False
        if schema.get("additionalProperties") is False and set(obj) - set(props):
            return False
        return all(_basic_schema_check(obj[k], props[k]) for k in obj if k in props)
    if t == "array":
        return isinstance(obj, list) and all(_basic_schema_check(x, schema.get("items", {})) for x in obj)
    if t == "string":
        return isinstance(obj, str)
    if t == "integer":
        return isinstance(obj, int) and not isinstance(obj, bool)
    if t == "number":
        return isinstance(obj, (int, float)) and not isinstance(obj, bool)
    if t == "boolean":
        return isinstance(obj, bool)
    return True


def normalise_stdout(s: str) -> str:
    """Whitespace rule for ``code_exec`` (applied to BOTH expected and actual output).

    Trailing whitespace on every line and trailing blank lines are ignored; leading whitespace
    and internal spacing are significant; ``\\r\\n`` is treated as ``\\n``.
    """
    lines = [ln.rstrip() for ln in s.replace("\r\n", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def extract_numbers(text: str) -> list[float]:
    out = []
    for sign, intpart, frac in _NUMBER.findall(text):
        try:
            out.append(float(sign + intpart.replace(",", "") + (frac or "")))
        except ValueError:
            continue
    return out


def _number_matches(got: float, want: float, tol: float) -> bool:
    return abs(got - want) <= max(tol, tol * abs(want))


def _tool_definition(task: dict[str, Any], name: str) -> dict[str, Any] | None:
    for t in task.get("tools") or []:
        fn = t.get("function") or {}
        if fn.get("name") == name:
            return fn
    return None


def _score_tool_call(task: dict[str, Any], msg: dict[str, Any], exp: dict[str, Any]) -> tuple[bool, str]:
    """Strict: the call must be well-formed AND carry the arguments the task needs.

    (Whether the *agent task* was completed is a separate question; this scorer only says the
    tool was invoked correctly.)
    """
    name = exp["name"]
    calls = msg.get("tool_calls") or []
    if not isinstance(calls, list):
        return False, "tool_calls is not a list"
    tool_def = _tool_definition(task, name) or {}
    required = list(((tool_def.get("parameters") or {}).get("required")) or [])
    args_contains: dict[str, str] = exp.get("args_contains") or {}
    names = []
    reasons = []
    for c in calls:
        if not isinstance(c, dict):
            reasons.append("tool call is not an object")
            continue
        fn = c.get("function") or {}
        names.append(fn.get("name"))
        if fn.get("name") != name:
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid.strip():
            reasons.append("tool call has no id")
            continue
        raw = fn.get("arguments")
        if raw is None or raw == "":
            raw = "{}"
        if isinstance(raw, dict):
            args: Any = raw
        else:
            try:
                args = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                reasons.append("tool call arguments not JSON")
                continue
        if not isinstance(args, dict):
            reasons.append("tool call arguments are not an object")
            continue
        missing = [k for k in required if k not in args]
        if missing:
            reasons.append(f"missing required argument(s) {missing}")
            continue
        params = tool_def.get("parameters")
        if isinstance(params, dict) and not _basic_schema_check(args, params):
            # Declared schema is the contract: a list where a string is required is a wrong call
            # even if its text representation contains the expected substring.
            reasons.append("arguments do not conform to the tool's declared parameter schema")
            continue
        bad = [k for k, sub in args_contains.items() if not isinstance(args.get(k), (str, int, float)) or str(sub) not in str(args.get(k, ""))]
        if bad:
            reasons.append(f"argument(s) {bad} do not contain expected substring(s) {[args_contains[k] for k in bad]}")
            continue
        return True, f"called {name} with id, valid JSON object args {sorted(args)}" + (f", {args_contains}" if args_contains else "")
    if reasons:
        return False, f"tool call {name} rejected: " + "; ".join(reasons)
    return False, f"expected tool call {name}, got {names} / content"


def _score_code_exec(task: dict[str, Any], text: str, exp: dict[str, Any], runner: Runner | None) -> tuple[bool | None, str]:
    """Scored from the trusted runner's result record (see ``sandbox._program``): the harness must
    have completed and *its* captured output must equal the expectation. Text the model code
    prints, including the public sentinel, is never evidence; a missing or foreign record fails."""
    m = _CODE_BLOCK.search(text)
    code = m.group(1) if m else text
    if runner is None:
        backend, reason = sandbox.available()
        if backend is None:
            return None, f"skipped: {reason}"
        runner = sandbox.run
    out, err, rc, backend = runner(code, exp["harness"], float(exp.get("timeout_s", 10.0)))
    rec = sandbox.parse_result(out, getattr(runner, "last_nonce", ""))
    want = normalise_stdout(str(exp["stdout"]))
    problems = []
    if rc != 0:
        problems.append(f"exit code {rc}")
    if rec is None:
        problems.append("no result record from the runner (model code exited or crashed before the harness ran)")
        body = ""
    else:
        if not rec.get("model_ran"):
            problems.append(rec.get("error") or "model code did not run")
        elif not rec.get("harness_completed"):
            problems.append(rec.get("error") or "harness did not complete")
        body = normalise_stdout(str(rec.get("harness_stdout", "")))
        if body != want:
            problems.append(f"harness output {body[:200]!r} != expected {want[:200]!r}")
    if problems:
        return False, f"[{backend}] " + "; ".join(problems) + (f" err={err[-300:]!r}" if err else "")
    return True, f"[{backend}] harness completed with expected output, exit 0"


def score(task: dict[str, Any], response: dict[str, Any], runner: Runner | None = None) -> tuple[bool | None, str]:
    """Return (success, detail) for a successful HTTP response body.

    ``runner`` (tests only) replaces the sandbox for ``code_exec``; it must have the signature of
    :func:`modelsaar.evaluation.sandbox.run`.
    """
    exp = task["expected"]
    kind = exp["type"]
    try:
        msg = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return False, "malformed response"
    content = msg.get("content")
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    text = (content or "").strip()
    low = text.lower()
    if kind == "nonempty":
        return bool(text), "nonempty" if text else "empty"
    if kind == "contains":
        ok = str(exp["value"]).lower() in low
        return ok, f"contains {exp['value']!r}" if ok else f"missing {exp['value']!r}"
    if kind == "contains_any":
        hit = next((v for v in exp["value"] if str(v).lower() in low), None)
        return hit is not None, f"contains {hit!r}" if hit else f"none of {exp['value']}"
    if kind == "number":
        nums = extract_numbers(text)
        if not nums:
            return False, "no numeric token in content"
        want = float(exp["value"])
        tol = float(exp.get("tol", 1e-6))
        got = nums[-1]
        ok = _number_matches(got, want, tol)
        return ok, f"last number {got:g} {'==' if ok else '!='} {want:g} (tol {tol:g}, {len(nums)} numeric token(s))"
    if kind == "tool_call":
        return _score_tool_call(task, msg, exp)
    if kind == "json_schema":
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return False, "content is not JSON"
        if not _basic_schema_check(obj, exp["schema"]):
            return False, "JSON does not conform to schema"
        for k, v in (exp.get("checks") or {}).items():
            if obj.get(k) != v:
                return False, f"field {k}={obj.get(k)!r} != {v!r}"
        return True, "schema-conformant with correct fields"
    if kind == "code_exec":
        return _score_code_exec(task, text, exp, runner)
    return False, f"unknown scorer {kind}"

