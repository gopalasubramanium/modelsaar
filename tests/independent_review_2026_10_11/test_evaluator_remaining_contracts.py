"""Independent, harmless scorer/checkpoint contract tests against the review candidate.

Run with the candidate installed, with proxy environment variables removed for loopback tests.
The local runner executes only the two small, reviewer-authored strings below. It is a test
seam for scoring/completion, not a claim that an actual isolation backend worked here.
"""
from __future__ import annotations

import json
import subprocess
import sys

import httpx

from modelsaar.evaluation import sandbox
from modelsaar.evaluation.harness import EvalRun, load_tasks
from modelsaar.evaluation.scoring import score


TASKS = {task["id"]: task for task in load_tasks()}


def response(content=None, calls=None):
    msg = {"role": "assistant", "content": content}
    if calls is not None:
        msg["tool_calls"] = calls
    return {"choices": [{"message": msg}]}


def trusted_string_runner(code, harness, timeout):
    process = subprocess.run(
        [sys.executable, "-I", "-c", sandbox._program(code, harness)],
        capture_output=True, text=True, timeout=timeout,
    )
    return process.stdout, process.stderr, process.returncode, "reviewer-authored-test-string"


def test_flushed_marker_then_exit_does_not_count_as_executed_harness():
    # No function is defined and the task harness is never reached. Only harmless stdout/exit.
    code = ("import os, sys\n"
            "sys.stdout.write('True False\\n__MODELSAAR_HARNESS_OK__\\n')\n"
            "sys.stdout.flush()\n"
            "os._exit(0)\n")
    ok, detail = score(TASKS["code-01"], response(code), runner=trusted_string_runner)
    print(json.dumps({"case": "forged_completion", "scored_ok": ok, "detail": detail}))
    assert ok is False, "code never defines/calls is_palindrome, but a flushed marker earns success"


def test_correct_function_still_passes():
    code = "def is_palindrome(s):\n    s = ''.join(c.lower() for c in s if c.isalnum())\n    return s == s[::-1]\n"
    ok, detail = score(TASKS["code-01"], response(code), runner=trusted_string_runner)
    assert ok is True, detail


def tool_call(arguments):
    return {"id": "review_call_1", "type": "function", "function": {
        "name": "bash", "arguments": json.dumps(arguments),
    }}


def test_tool_argument_wrong_schema_type_does_not_pass():
    # The fixture requires a string command, but the scorer stringifies a list for substring checks.
    task = TASKS["agent-03"]
    definition = task["tools"][0]["function"]["parameters"]
    assert definition["properties"]["command"]["type"] == "string"
    ok, detail = score(task, response(calls=[tool_call({"command": ["pytest"]})]))
    print(json.dumps({"case": "tool_argument_wrong_type", "scored_ok": ok, "detail": detail}))
    assert ok is False, "command array violates declared tool schema but is scored successful"


def test_tool_argument_correct_type_still_passes():
    ok, detail = score(TASKS["agent-03"], response(calls=[tool_call({"command": "python -m pytest -q"})]))
    assert ok is True, detail


def saved_record():
    return {"task": "review-task", "category": "conversation", "split": "test", "policy": "auto",
            "model": "auto", "deployment": "local/a", "fingerprint": "same-weights",
            "status": 200, "ok": True, "latency_ms": 1.0, "detail": "contains 'old answer'"}


def test_changed_task_cannot_reuse_old_score(tmp_path):
    checkpoint = tmp_path / "changed-task.jsonl"
    checkpoint.write_text(json.dumps(saved_record()) + "\n")
    run = EvalRun("http://127.0.0.1:9", "review-only-fake-key", "review-only-fake-admin", False,
                  checkpoint=checkpoint, resume=True)
    run.fingerprints = {"local/a": "same-weights"}
    requests = []

    def mock(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response("new answer"), headers={"x-modelsaar-deployment": "local/a"})

    run.c.close()
    run.c = httpx.Client(base_url="http://127.0.0.1:9", transport=httpx.MockTransport(mock))
    try:
        changed = {"id": "review-task", "category": "conversation", "split": "test",
                   "messages": [{"role": "user", "content": "A different task requiring a new answer"}],
                   "expected": {"type": "contains", "value": "new answer"}}
        result = run.run_one(changed, "auto", "auto")
        print(json.dumps({"case": "changed_task_resume", "requests_sent": len(requests), "result": result}))
        assert len(requests) == 1 and not result.get("resumed"), "changed prompt/scorer reused an unbound old record"
    finally:
        run.c.close()
        run.admin.close()


def test_removed_deployment_cannot_resume(tmp_path):
    checkpoint = tmp_path / "removed-deployment.jsonl"
    checkpoint.write_text(json.dumps(saved_record()) + "\n")
    run = EvalRun("http://127.0.0.1:9", "review-only-fake-key", "review-only-fake-admin", False,
                  checkpoint=checkpoint, resume=True)
    try:
        run.fingerprints = {"local/b": "different-weights"}
        result = run._resumable("review-task", "auto")
        print(json.dumps({"case": "removed_deployment_resume", "resumed": result is not None}))
        assert result is None, "auto checkpoint reuses a deployment that is no longer in the eligible run"
    finally:
        run.c.close()
        run.admin.close()


def test_changed_fingerprint_is_rejected_positive_control(tmp_path):
    checkpoint = tmp_path / "changed-fingerprint.jsonl"
    checkpoint.write_text(json.dumps(saved_record()) + "\n")
    run = EvalRun("http://127.0.0.1:9", "review-only-fake-key", "review-only-fake-admin", False,
                  checkpoint=checkpoint, resume=True)
    try:
        run.fingerprints = {"local/a": "new-weights"}
        assert run._resumable("review-task", "auto") is None
    finally:
        run.c.close()
        run.admin.close()
