"""Scorers for evaluation tasks. Executable where possible; never an LLM judge."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Any

_CODE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


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


def run_code_sandboxed(code: str, harness: str, timeout_s: float = 10.0) -> tuple[str, str]:
    """Run model-written code + harness in a disposable subprocess. Basic sandbox only."""
    src = code + "\n\n" + harness + "\n"
    with tempfile.TemporaryDirectory(prefix="modelsaar-eval-") as d:
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "HOME": d, "TMPDIR": d}
        preexec = None
        if sys.platform != "win32":
            import resource

            def _limits() -> None:
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
                    resource.setrlimit(resource.RLIMIT_CPU, (int(timeout_s) + 1, int(timeout_s) + 1))
                    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
                except Exception:
                    pass

            preexec = _limits
        try:
            p = subprocess.run(
                [sys.executable, "-I", "-"],
                input=src,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=d,
                env=env,
                preexec_fn=preexec,
            )
            return p.stdout.strip(), p.stderr.strip()[-300:]
        except subprocess.TimeoutExpired:
            return "", "timeout"


def score(task: dict[str, Any], response: dict[str, Any]) -> tuple[bool, str]:
    """Return (success, detail) for a successful HTTP response body."""
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
    if kind == "tool_call":
        calls = msg.get("tool_calls") or []
        for c in calls:
            fn = c.get("function") or {}
            if fn.get("name") == exp["name"]:
                try:
                    json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    return False, "tool call arguments not JSON"
                return True, f"called {exp['name']} with valid JSON"
        return False, f"expected tool call {exp['name']}, got {[ (c.get('function') or {}).get('name') for c in calls]} / content"
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
        m = _CODE_BLOCK.search(text)
        code = m.group(1) if m else text
        out, err = run_code_sandboxed(code, exp["harness"])
        ok = out == exp["stdout"]
        return ok, f"stdout={out!r}" + (f" err={err!r}" if err and not ok else "")
    return False, f"unknown scorer {kind}"
