"""Evaluator hardening regressions: scorers, sandbox, skipped accounting, checkpoint/resume,
deployment-selector resolution. Each scorer has positive and negative controls."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from modelsaar.evaluation import sandbox
from modelsaar.evaluation.harness import (
    EvalRun,
    load_tasks,
    render_report,
    resolve_selectors,
    run_live,
    run_simulated,
    summarize,
)
from modelsaar.evaluation.scoring import SCORER_VERSION, extract_numbers, normalise_stdout, score
from modelsaar.testing.fakebackend import _GOLD, _gold_code

TASKS = {t["id"]: t for t in load_tasks()}
OK = sandbox.SENTINEL


def _resp(content=None, tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg}]}


def _record(harness_stdout: str, completed: bool = True, model_ran: bool = True, error=None, nonce: str = "") -> str:
    """A runner result record as the trusted runner frames it (see sandbox._program)."""
    rec = {"nonce": nonce, "model_ran": model_ran, "harness_completed": completed, "harness_stdout": harness_stdout, "error": error}
    return f"\n{sandbox.RESULT_BEGIN}\n{json.dumps(rec)}\n{sandbox.RESULT_END}\n"


def _runner_returning(stdout: str, stderr: str = "", rc: int = 0):
    """Fabricated runner output: ``stdout`` is what the process printed (model text, sentinel, and
    optionally a result record from :func:`_record`)."""
    def runner(code, harness, timeout_s):
        return stdout, stderr, rc, "fake"

    return runner


def _local_python_runner(code, harness, timeout_s):
    """Trusted test-only runner: executes the *same program the sandbox would* on the host, so
    the sentinel/exit-code composition is tested without an isolation backend."""
    p = subprocess.run([sys.executable, "-I", "-c", sandbox._program(code, harness)], capture_output=True, text=True, timeout=timeout_s)
    return p.stdout, p.stderr, p.returncode, "local-test"


# --------------------------------------------------------------------------- #
# 1a. code_exec whitespace rule (symmetric, explicit)


def test_normalise_stdout_rule():
    assert normalise_stdout("a3b1c2 ") == "a3b1c2"
    assert normalise_stdout("a3b1c2 \n\n") == "a3b1c2"
    assert normalise_stdout("x \r\ny  \r\n") == "x\ny"
    assert normalise_stdout("  lead") == "  lead"  # leading whitespace is significant
    assert normalise_stdout("a  b") == "a  b"  # internal spacing is significant


def test_code05_fixture_uses_explicit_rule():
    assert TASKS["code-05"]["expected"]["stdout"] == "a3b1c2"


def test_code05_gold_rle_passes_with_trailing_space_output():
    task = TASKS["code-05"]
    ok, detail = score(task, _resp(_gold_code(task["messages"][0]["content"])), runner=_local_python_runner)
    assert ok is True, detail


def test_code_exec_trailing_whitespace_on_expected_side_is_also_ignored():
    task = json.loads(json.dumps(TASKS["code-05"]))
    task["expected"]["stdout"] = "a3b1c2 \n"
    ok, _ = score(task, _resp(f"```python\n{_gold_code('rle')}\n```"), runner=_runner_returning(_record("a3b1c2\n") + f"{OK}\n"))
    assert ok is True


def test_code_exec_wrong_output_fails():
    ok, detail = score(TASKS["code-05"], _resp("```python\ndef rle(s): return 'nope'\n```"), runner=_runner_returning(_record("nope nope\n") + f"{OK}\n"))
    assert ok is False and "harness output" in detail


# 1b. completion evidence: the runner's result record (not stdout text) + exit code


def test_code_exec_requires_result_record():
    # Expected text and even the public sentinel in stdout are not evidence without the record.
    ok, detail = score(TASKS["code-01"], _resp("x"), runner=_runner_returning("True False\n", rc=0))
    assert ok is False and "no result record" in detail
    ok, detail = score(TASKS["code-01"], _resp("x"), runner=_runner_returning(f"True False\n{OK}\n", rc=0))
    assert ok is False and "no result record" in detail


def test_code_exec_requires_exit_code_zero():
    ok, detail = score(TASKS["code-01"], _resp("x"), runner=_runner_returning(_record("True False\n") + f"{OK}\n", rc=1))
    assert ok is False and "exit code 1" in detail


def test_code_exec_record_must_say_harness_completed():
    ok, detail = score(TASKS["code-01"], _resp("x"), runner=_runner_returning(_record("True False\n", completed=False, error="harness raised X")))
    assert ok is False and "harness raised X" in detail
    ok, detail = score(TASKS["code-01"], _resp("x"), runner=_runner_returning(_record("", model_ran=False, completed=False, error="model code raised SyntaxError")))
    assert ok is False and "model code raised" in detail


def test_code_exec_record_with_foreign_nonce_is_ignored():
    def runner(code, harness, timeout_s):
        return _record("True False\n", nonce="attacker") + f"{OK}\n", "", 0, "fake"

    runner.last_nonce = "real-nonce"
    ok, detail = score(TASKS["code-01"], _resp("x"), runner=runner)
    assert ok is False and "no result record" in detail


def test_code_exec_print_then_raise_fails():
    code = "```python\ndef is_palindrome(s):\n    print('True False')\n    raise RuntimeError('boom')\n```"
    ok, detail = score(TASKS["code-01"], _resp(code), runner=_local_python_runner)
    assert ok is False and "harness raised RuntimeError" in detail


def test_code_exec_print_then_exit_zero_fails():
    code = "```python\nimport sys\ndef is_palindrome(s):\n    sys.stdout.write('True False\\n'); sys.stdout.flush(); sys.exit(0)\n```"
    ok, detail = score(TASKS["code-01"], _resp(code), runner=_local_python_runner)
    assert ok is False and "harness raised SystemExit" in detail


def test_code_exec_flushed_expected_output_and_marker_then_os_exit_fails():
    """The independent review's forged-completion case: expected text + public marker, flushed,
    os._exit(0) before defining the function. No record is produced, so it cannot score."""
    code = "```python\nimport os, sys\nsys.stdout.write('True False\\n" + OK + "\\n')\nsys.stdout.flush()\nos._exit(0)\n```"
    ok, detail = score(TASKS["code-01"], _resp(code), runner=_local_python_runner)
    assert ok is False and "no result record" in detail


def test_code_exec_self_printed_sentinel_fails():
    code = f"```python\nimport os\ndef is_palindrome(s):\n    print('True False'); print({OK!r}); os._exit(0)\n```"
    ok, _ = score(TASKS["code-01"], _resp(code), runner=_local_python_runner)
    # The model's own sentinel is printed before the harness output, so it is not the last line.
    assert ok is False


def test_code_exec_gold_solutions_pass_locally():
    for tid in ("code-01", "code-02", "code-03", "code-04", "code-05"):
        task = TASKS[tid]
        ok, detail = score(task, _resp(_gold_code(task["messages"][0]["content"])), runner=_local_python_runner)
        assert ok is True, (tid, detail)


# --------------------------------------------------------------------------- #
# 2. strict tool_call scorer


def _call(name="bash", args='{"command": "ls -la"}', cid="call_1"):
    c = {"type": "function", "function": {"name": name, "arguments": args}}
    if cid is not None:
        c["id"] = cid
    return c


def test_tool_call_valid_passes():
    ok, detail = score(TASKS["agent-01"], _resp(tool_calls=[_call()]))
    assert ok is True, detail


def test_tool_call_without_id_fails():
    ok, detail = score(TASKS["agent-01"], _resp(tool_calls=[_call(cid=None)]))
    assert ok is False and "no id" in detail
    ok, _ = score(TASKS["agent-01"], _resp(tool_calls=[_call(cid="")]))
    assert ok is False


def test_tool_call_missing_required_argument_fails():
    ok, detail = score(TASKS["agent-01"], _resp(tool_calls=[_call(args="{}")]))
    assert ok is False and "missing required" in detail
    ok, detail = score(TASKS["agent-02"], _resp(tool_calls=[_call(name="read_file", args='{"command": "ls"}')]))
    assert ok is False and "missing required" in detail and "path" in detail


def test_tool_call_arguments_must_be_object():
    ok, detail = score(TASKS["agent-01"], _resp(tool_calls=[_call(args="[]")]))
    assert ok is False and "not an object" in detail
    ok, detail = score(TASKS["agent-01"], _resp(tool_calls=[_call(args="{not json")]))
    assert ok is False and "not JSON" in detail


def test_tool_call_args_contains_enforced():
    ok, detail = score(TASKS["agent-03"], _resp(tool_calls=[_call(args='{"command": "ls"}')]))
    assert ok is False and "pytest" in detail
    ok, _ = score(TASKS["agent-03"], _resp(tool_calls=[_call(args='{"command": "python -m pytest -q"}')]))
    assert ok is True
    ok, _ = score(TASKS["agent-04"], _resp(tool_calls=[_call(name="read_file", args='{"path": "README.md"}')]))
    assert ok is False
    ok, _ = score(TASKS["agent-04"], _resp(tool_calls=[_call(name="read_file", args='{"path": "./pyproject.toml"}')]))
    assert ok is True


def test_tool_call_wrong_name_or_none_fails():
    ok, _ = score(TASKS["agent-01"], _resp(tool_calls=[_call(name="read_file", args='{"path": "x"}')]))
    assert ok is False
    ok, _ = score(TASKS["agent-01"], _resp("I would run ls"))
    assert ok is False


def test_agent_fixtures_declare_args_contains():
    for tid in ("agent-01", "agent-02", "agent-03", "agent-04", "agent-05"):
        assert TASKS[tid]["expected"].get("args_contains"), tid


# --------------------------------------------------------------------------- #
# 3. number scorer


def test_extract_numbers():
    assert extract_numbers("x = 6") == [6.0]
    assert extract_numbers("1,234 and 2.5") == [1234.0, 2.5]
    assert extract_numbers("25-7=18, so 18/3 = 6") == [25.0, 7.0, 18.0, 18.0, 3.0, 6.0]
    assert extract_numbers("=-6") == [-6.0]
    assert extract_numbers("no digits") == []


def test_number_rejects_superstring_match():
    ok, detail = score(TASKS["math-03"], _resp("16"))
    assert ok is False and "16" in detail
    ok, _ = score(TASKS["math-03"], _resp("x = 6"))
    assert ok is True
    ok, _ = score(TASKS["math-03"], _resp("25 - 7 = 18, so x = 6."))
    assert ok is True
    ok, _ = score(TASKS["math-03"], _resp("6, or maybe 7"))  # last number wins
    assert ok is False


def test_number_tolerance_and_commas():
    task = {"expected": {"type": "number", "value": 1234}}
    assert score(task, _resp("1,234"))[0] is True
    assert score(task, _resp("1234.0000001"))[0] is True
    assert score(task, _resp("1235"))[0] is False
    task = {"expected": {"type": "number", "value": 3.1416, "tol": 1e-3}}
    assert score(task, _resp("pi is about 3.14159"))[0] is True
    assert score(task, _resp("pi is about 3.2"))[0] is False
    big = {"expected": {"type": "number", "value": 1_000_000}}
    assert score(big, _resp("1000000.5"))[0] is True  # relative 1e-6 for large values
    assert score(big, _resp("1000002"))[0] is False
    assert score(big, _resp("none"))[0] is False


def test_math_fixtures_are_number_typed_and_gold_passes():
    for tid in ("math-01", "math-02", "math-03", "math-04", "math-05", "multi-02"):
        task = TASKS[tid]
        assert task["expected"]["type"] == "number", tid
        gold = _GOLD["math"](task["messages"][0]["content"])
        ok, detail = score(task, _resp(gold))
        assert ok is True, (tid, gold, detail)
    assert TASKS["math-06"]["expected"]["type"] == "contains_any"
    assert score(TASKS["math-06"], _resp(_GOLD["math"](TASKS["math-06"]["messages"][0]["content"])))[0] is True


# --------------------------------------------------------------------------- #
# 4. sandbox: no backend -> skipped, never unsandboxed


def test_code_exec_skipped_without_backend(monkeypatch):
    monkeypatch.setattr(sandbox, "available", lambda: (None, sandbox.NO_BACKEND_REASON))

    def never(*a, **k):
        raise AssertionError("code must not run without an isolation backend")

    monkeypatch.setattr(sandbox, "run", never)
    ok, detail = score(TASKS["code-01"], _resp("```python\nimport os; os.system('true')\n```"))
    assert ok is None
    assert detail.startswith("skipped: no isolation backend (install bubblewrap on Linux; macOS sandbox-exec; or Docker)")


def test_sandbox_run_refuses_without_backend(monkeypatch):
    monkeypatch.setattr(sandbox, "available", lambda: (None, "nope"))
    with pytest.raises(RuntimeError):
        sandbox.run("print(1)", "", 2.0)


def test_sandbox_has_no_unsafe_opt_in():
    src = Path(sandbox.__file__).read_text(encoding="utf-8")
    assert "unsafe" not in src.lower() and "allow_unsandboxed" not in src


BACKEND, REASON = sandbox.available()
needs_sandbox = pytest.mark.skipif(BACKEND is None, reason=REASON)


@needs_sandbox
def test_sandbox_blocks_writes_outside_work(tmp_path):
    target = tmp_path / "escape.txt"
    code = f"open({str(target)!r}, 'w').write('escaped')\nprint('wrote')\n"
    out, err, rc, backend = sandbox.run(code, "print('after')", 10.0)
    assert backend == BACKEND
    assert not target.exists(), f"sandbox {backend} let generated code write to the host: {target}"


# The runner records the concrete exception class raised by the model code. A refused network attempt
# surfaces as an OSError-family exception whose name depends on the isolation layer: bwrap / Docker
# `--network none` give ``OSError: [Errno 101] Network is unreachable``; macOS ``sandbox-exec`` with
# ``(deny network*)`` gives ``PermissionError: [Errno 1] Operation not permitted``; a black-holed route
# gives ``TimeoutError``. All of them mean "blocked"; a completed connection means "not blocked".
# ``ConnectionRefusedError`` is deliberately NOT accepted: a refusal means a peer answered, i.e. the
# network was reachable — it is evidence against isolation, not for it.
_NETWORK_BLOCKED_EXCEPTIONS = ("OSError", "PermissionError", "TimeoutError")


def _network_attempt_blocked(rec: dict | None) -> bool:
    """True only when the model code's connection attempt failed inside the isolation layer: the model
    code did not run to completion, the harness therefore never ran, and the recorded error is an
    OSError-family exception, a 'network is unreachable' message or a timeout. A record showing the
    model code completed (``model_ran``) is never classified as blocked."""
    if rec is None or rec.get("model_ran") or rec.get("harness_completed") or not rec.get("error"):
        return False
    err = rec["error"]
    low = err.lower()
    return any(f"raised {name}:" in err for name in _NETWORK_BLOCKED_EXCEPTIONS) or "unreachable" in low or "timed out" in low


class _LoopbackListener:
    """A TCP listener on 127.0.0.1 with a dynamically allocated port that counts accepted connections.
    Used as the controlled target for both the unsandboxed and the sandboxed connection attempts, so the
    verdict never depends on external-network availability."""

    def __init__(self) -> None:
        import socket
        import threading

        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.accepted = 0
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:

        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self.accepted += 1
            conn.close()

    def close(self) -> None:
        self._stop = True
        self._thread.join(2)
        self.sock.close()

    def connect_code(self) -> str:
        return f"import socket\ns = socket.create_connection(('127.0.0.1', {self.port}), timeout=3)\ns.close()\nprint('connected')\n"


def _run_unsandboxed(code: str, harness: str, workdir: Path) -> dict | None:
    """Run the SAME runner program the sandbox executes (``sandbox._program``), but directly with this
    interpreter and no isolation. Used only by the tests as the control arm."""
    prog = workdir / "prog.py"
    prog.write_text(sandbox._program(code, harness), encoding="utf-8")
    nonce = "control-" + "0" * 24
    p = subprocess.run([sys.executable, "-I", str(prog)], input=nonce + "\n", capture_output=True, text=True, timeout=30, cwd=workdir)
    return sandbox.parse_result(p.stdout, nonce)


@needs_sandbox
def test_sandbox_blocks_network(tmp_path):
    """Controlled-listener proof of network isolation. One loopback listener on a dynamic port:
    (a) the runner program connects to it WITHOUT the sandbox (the listener counts the connection), so the
    program and the listener are known to work; (b) the identical program through ``sandbox.run()`` must
    NOT reach the listener, the model code must not complete, the harness must not run, and the recorded
    error must be a network-denial/isolation error. An unreachable external host cannot make this pass."""
    listener = _LoopbackListener()
    try:
        code = listener.connect_code()
        control = _run_unsandboxed(code, "print('harness ran')", tmp_path)
        assert listener.accepted == 1, f"control arm: the listener saw {listener.accepted} connection(s), expected exactly 1"
        assert control is not None and control["model_ran"] and control["harness_completed"] and not control["error"], control
        before = listener.accepted
        out, err, rc, backend = sandbox.run(code, "print('harness ran')", 15.0)
        rec = sandbox.parse_result(out, sandbox.run.last_nonce)
        assert backend == BACKEND
        assert listener.accepted == before, f"sandbox {backend} let model code reach the loopback listener ({listener.accepted - before} connection(s))"
        assert "connected" not in out, (out, err, rc)
        assert rec is not None, (out[-400:], err[-400:], rc)
        assert not rec["model_ran"] and not rec["harness_completed"], rec
        assert _network_attempt_blocked(rec), (backend, rec["error"])
    finally:
        listener.close()


def test_sandbox_negative_control_network_success_is_not_classified_as_blocked(tmp_path):
    """Negative control: the runner program executed WITHOUT the sandbox against a loopback listener this
    test owns completes its connection; the record then shows the model code ran and the harness
    completed, and the blocked-classification must reject it. Proves the positive test cannot pass merely
    because a record exists or because an error string looks vaguely network-like."""
    listener = _LoopbackListener()
    try:
        rec = _run_unsandboxed(listener.connect_code(), "print('harness ran')", tmp_path)
        assert listener.accepted == 1, "the loopback listener never saw the connection; the control did not exercise a real connect"
        assert rec is not None and rec["model_ran"] and rec["harness_completed"] and not rec["error"], rec
        assert not _network_attempt_blocked(rec), rec
    finally:
        listener.close()
    # the classifier's positive side only accepts failure records of the right shape
    assert _network_attempt_blocked({"model_ran": False, "harness_completed": False, "error": "model code raised PermissionError: [Errno 1] Operation not permitted"})
    assert _network_attempt_blocked({"model_ran": False, "harness_completed": False, "error": "model code raised OSError: [Errno 101] Network is unreachable"})
    assert not _network_attempt_blocked({"model_ran": True, "harness_completed": True, "error": None})
    assert not _network_attempt_blocked({"model_ran": False, "harness_completed": False, "error": "model code raised ValueError: nope"})
    # a refused connection proves a peer answered: reachable network, never isolation
    assert not _network_attempt_blocked({"model_ran": False, "harness_completed": False, "error": "model code raised ConnectionRefusedError: [Errno 61] Connection refused"})


@needs_sandbox
def test_sandbox_reference_solution_passes():
    for tid in ("code-01", "code-05"):
        task = TASKS[tid]
        ok, detail = score(task, _resp(_gold_code(task["messages"][0]["content"])))
        assert ok is True, (tid, detail)
        assert f"[{BACKEND}]" in detail


@needs_sandbox
def test_sandbox_timeout_fails_cleanly():
    out, err, rc, _ = sandbox.run("while True: pass", "", 2.0)
    assert rc == 124 and "timeout" in err


@needs_sandbox
def test_sandbox_cannot_read_a_synthetic_host_file_outside_the_work_directory():
    """Review R7: the sandbox must not grant ordinary host read authority. A harmless synthetic file
    is created outside the sandbox (in the home directory, which is not an allowlisted runtime root;
    /tmp is a private tmpfs inside the sandbox so it would not prove anything)."""
    import os
    import tempfile

    home = Path(os.path.expanduser("~"))
    base = home if os.access(home, os.W_OK) else Path(tempfile.gettempdir())
    with tempfile.NamedTemporaryFile("w", suffix=".txt", dir=base, delete=False, prefix="modelsaar-synthetic-") as f:
        f.write("synthetic-marker-7f3a")
        name = f.name
    try:
        code = (
            "def peek(p):\n"
            "    try:\n        return open(p).read()\n"
            "    except OSError as e:\n        return 'unreadable:' + e.__class__.__name__\n"
        )
        out, err, rc, backend = sandbox.run(code, f"print(peek({name!r}))\nprint(peek('/etc/passwd' if __import__('sys').platform != 'darwin' else {str(home)!r}))", 10.0)
        rec = sandbox.parse_result(out, sandbox.run.last_nonce)
        assert rec is not None and rec["harness_completed"], (out, err, rc)
        lines = rec["harness_stdout"].splitlines()
        assert lines and lines[0].startswith("unreadable:"), f"sandbox {backend} let generated code read a host file: {lines}"
        assert "synthetic-marker-7f3a" not in out
    finally:
        os.unlink(name)


@needs_sandbox
def test_sandbox_forged_completion_marker_does_not_score():
    code = f"import os, sys\nsys.stdout.write('True False\\n{OK}\\n')\nsys.stdout.flush()\nos._exit(0)\n"
    ok, detail = score(TASKS["code-01"], _resp(f"```python\n{code}```"))
    assert ok is False and "no result record" in detail


# --------------------------------------------------------------------------- #
# 4b/8. skipped accounting and report wording


def _tasks(n_code=1, n_other=2):
    ts = [{"id": f"c{i}", "category": "coding", "split": "test", "expected": {"type": "code_exec", "harness": "", "stdout": ""}} for i in range(n_code)]
    ts += [{"id": f"o{i}", "category": "conversation", "split": "test", "expected": {"type": "nonempty"}} for i in range(n_other)]
    return ts


def test_summarize_counts_skipped_separately():
    tasks = _tasks(1, 2)
    recs = {
        "c0": {"ok": None, "skipped": True, "detail": "skipped: no isolation backend", "status": 200, "latency_ms": 1.0},
        "o0": {"ok": True, "status": 200, "latency_ms": 1.0},
        "o1": {"ok": False, "status": 200, "latency_ms": 1.0},
    }
    s = summarize(recs, tasks)
    assert s["n"] == 3 and s["n_scored"] == 2 and s["skipped"] == 1
    assert s["success"] == 0.5  # over scored tasks only, never 1/3 or 2/3
    assert s["skip_reasons"] == {"skipped: no isolation backend": 1}
    assert s["per_category"]["coding"] == {"success": None, "n": 0, "skipped": 1, "ci95": [0.0, 0.0]}
    assert s["per_category"]["conversation"]["n"] == 2
    assert s["completion_rate"] == 1.0


def test_summarize_without_skips_unchanged():
    tasks = _tasks(0, 2)
    s = summarize({"o0": {"ok": True, "status": 200, "latency_ms": 1.0}, "o1": {"ok": True, "status": 200, "latency_ms": 2.0}}, tasks)
    assert s["n"] == s["n_scored"] == 2 and s["skipped"] == 0 and s["success"] == 1.0


def test_render_report_states_skips_and_backend():
    rep = {
        "mode": "simulated", "generated_at": "t", "deployments": [{"id": "sim/x", "parameter_size": "1B", "quantization": "Q4", "context_length": 8}],
        "calibration": {"fixed_strong": "sim/x", "fixed_fast": "sim/x"}, "n_calib": 1, "n_test": 3,
        "sandbox": {"backend": None, "reason": "no isolation backend (install bubblewrap on Linux; macOS sandbox-exec; or Docker)", "code_exec_tasks": 1},
        "conditions": {"max_tokens": 400, "temperature": 0, "seed": 7, "scorer_version": SCORER_VERSION, "git_commit": "abc", "tasks_file_sha256": "deadbeef"},
        "results": {"auto (live routing)": summarize({"c0": {"ok": None, "skipped": True, "detail": "skipped: no isolation backend", "status": 200, "latency_ms": 1.0}, "o0": {"ok": True, "status": 200, "latency_ms": 1.0}}, _tasks(1, 1))},
        "routing": {"overhead_ms_mean": 1, "overhead_ms_p95": 1, "task_label_accuracy": 1, "evidence_levels": {}, "routing_mistakes": [], "classifier": {}},
    }
    text = render_report(rep)
    assert "sandbox: NONE - 1 code_exec task(s) SKIPPED" in text and "install bubblewrap" in text
    assert "scored" in text and "skip" in text and "skipped (not counted as success or failure)" in text
    assert "--" in text  # coding column: all skipped
    assert f"scorer={SCORER_VERSION}" in text
    rep["sandbox"] = {"backend": "bwrap", "reason": "bubblewrap at /usr/bin/bwrap", "code_exec_tasks": 1}
    assert "sandbox: bwrap" in render_report(rep)


# --------------------------------------------------------------------------- #
# 5. deployment selectors


DEPS = [{"id": "ollama/qwen3.6:latest", "model": "qwen3.6:latest"}, {"id": "ollama/small:1b", "model": "small:1b"}, {"id": "vllm/small:1b", "model": "small:1b"}]


def test_resolve_selectors_bare_and_full():
    assert resolve_selectors(DEPS, ["qwen3.6:latest", "ollama/small:1b", "qwen3.6:latest"]) == ["ollama/qwen3.6:latest", "ollama/small:1b"]
    assert resolve_selectors(DEPS, None) == []


def test_resolve_selectors_unknown_and_ambiguous():
    with pytest.raises(ValueError, match="unknown deployment selector 'qwen9'"):
        resolve_selectors(DEPS, ["qwen9"])
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_selectors(DEPS, ["small:1b"])


def _live_config(tmp_path, fake_url):
    from modelsaar.config import (
        BackendConfig,
        Config,
        ResourcePool,
        generate_key,
        write_config_atomic,
        write_key_file,
    )

    api_key, admin_key = generate_key("msk"), generate_key("msa")
    write_key_file(tmp_path / "keys/api_keys", [api_key])
    write_key_file(tmp_path / "keys/admin_key", [admin_key])
    cfg = Config(resource_pools=(ResourcePool(id="p", max_concurrent=2),), backends=(BackendConfig(id="sim", type="ollama", base_url=fake_url, resource_pool="p"),), deployments=())
    write_config_atomic(cfg, tmp_path / "config.yaml")
    return tmp_path / "config.yaml"


def _live_args(config, **kw):
    base = dict(config=str(config), deployments=None, probe=False, save_measurements=False, seed=1, tasks=None, out=None, limit=0, mode="live")
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture
def sim_fake():
    from modelsaar.testing.fakebackend import FakeBackend, FakeModel

    f = FakeBackend(
        [
            FakeModel("sim-small:1b", ["completion", "tools"], 8192, parameter_size="1.0B", loaded=True, good_at=["conversation"]),
            FakeModel("sim-code:7b", ["completion", "tools"], 16384, parameter_size="7B", good_at=["coding", "agent", "conversation", "math"]),
        ]
    )
    url = f.start()
    yield f, url
    f.stop()


def test_run_live_resolves_bare_selector_everywhere(tmp_path, sim_fake):
    fake, url = sim_fake
    cfg_path = _live_config(tmp_path, url)
    tasks = [TASKS[i] for i in ("conv-01", "math-01", "conv-04", "math-03", "agent-03")]
    rep = run_live(_live_args(cfg_path, deployments=["sim-code:7b"]), tasks)
    assert rep["deployment_filter"] == {"selectors": ["sim-code:7b"], "resolved": ["sim/sim-code:7b"]}
    assert [d["id"] for d in rep["deployments"]] == ["sim/sim-code:7b"]
    # calibration + every sweep used only the canonical id ...
    assert set(rep["calibration"]["per_deployment"]) == {"sim/sim-code:7b"}
    assert {r["model"] for r in rep["records"] if r["policy"] != "auto"} == {"sim/sim-code:7b"}
    # ... and so did the restricted `auto` alias (previously bare names left auto unrestricted).
    assert set(rep["routing"]["choices"].values()) == {"sim/sim-code:7b"}
    assert all(req["model"] == "sim-code:7b" for req in fake.requests if req["has_tools"] or True)


def test_run_live_rejects_unknown_selector_early(tmp_path, sim_fake):
    _, url = sim_fake
    cfg_path = _live_config(tmp_path, url)
    with pytest.raises(SystemExit, match="unknown deployment selector 'nope:1b'"):
        run_live(_live_args(cfg_path, deployments=["nope:1b"]), [TASKS["conv-01"], TASKS["conv-04"]])


# --------------------------------------------------------------------------- #
# 7. checkpoint / resume and conditions


SMALL = [TASKS[i] for i in ("conv-01", "math-01", "agent-01", "conv-04", "math-03", "agent-03", "code-03")]


def test_checkpoint_written_and_resumed(tmp_path):
    ck = tmp_path / "run.records.jsonl"
    rep1 = run_simulated(SMALL, seed=3, checkpoint=ck)
    lines = [json.loads(ln) for ln in ck.read_text(encoding="utf-8").splitlines()]
    request_records = [r for r in rep1["records"]]
    assert len(lines) == len(request_records) > 0 and rep1["resumed_records"] == 0
    assert rep1["checkpoint"] == str(ck)
    for rec in lines:  # sanitized: ids, status, latency, scorer detail only
        assert not ({"messages", "content", "prompt"} & set(rec)), rec
        assert rec.get("fingerprint") or rec["status"] != 200
    text = ck.read_text(encoding="utf-8")
    assert "kitten" not in text and "17 * 23" not in text
    # auto records carry the decision fields in the checkpoint (enriched before being written)
    assert any(r["policy"] == "auto" and "overhead_ms" in r for r in lines)
    rep2 = run_simulated(SMALL, seed=3, checkpoint=ck, resume=True)
    assert rep2["resumed_records"] == len(lines)
    assert len(ck.read_text(encoding="utf-8").splitlines()) == len(lines)  # nothing re-run, nothing appended
    assert all(r.get("resumed") for r in rep2["records"])
    assert rep2["results"]["auto (live routing)"]["success"] == rep1["results"]["auto (live routing)"]["success"]


def test_resume_ignores_records_from_other_fingerprint(tmp_path):
    from modelsaar.evaluation.harness import CHECKPOINT_FORMAT, conditions_key

    ck = tmp_path / "ck.jsonl"
    rec = {"task": "t1", "policy": "calib:d", "deployment": "d", "fingerprint": "old", "ok": True, "status": 200, "latency_ms": 1,
           "checkpoint_format": CHECKPOINT_FORMAT, "task_sha256": "x" * 64, "conditions_key": conditions_key("calib:d")}
    ck.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    run = EvalRun("http://127.0.0.1:9", "k", "a", simulated=False, checkpoint=ck, resume=True)
    run.fingerprints = {"d": "new"}
    assert run._resumable("t1", "calib:d") is None
    assert run.resume_rejected == {"deployment_changed": 1}
    run.fingerprints = {"d": "old"}
    assert run._resumable("t1", "calib:d")["ok"] is True
    assert run._resumable("t1", "test:d") is None


def test_resume_requires_checkpoint():
    with pytest.raises(ValueError, match="resume"):
        EvalRun("http://127.0.0.1:9", "k", "a", simulated=True, resume=True)


def test_report_conditions(tmp_path):
    rep = run_simulated(SMALL[:2], seed=5)
    c = rep["conditions"]
    assert c["max_tokens"] == 400 and c["temperature"] == 0 and c["seed"] == 5
    assert c["scorer_version"] == SCORER_VERSION
    assert len(c["tasks_file_sha256"]) == 64 and len(c["tasks_run_sha256"]) == 64
    assert "git_commit" in c and "sandbox_backend" in c
    assert set(c["deployment_fingerprints"]) == {d["id"] for d in rep["deployments"]}
    assert all(c["deployment_fingerprints"][d["id"]] == d["fingerprint"] for d in rep["deployments"])


def test_simulated_report_accounts_for_code_exec(monkeypatch):
    """With no backend, code_exec tasks are skipped with the reason visible; with one, scored."""
    rep = run_simulated(SMALL, seed=2)
    res = rep["results"]["auto (live routing)"]
    assert rep["sandbox"]["code_exec_tasks"] == 1
    if rep["sandbox"]["backend"] is None:
        assert res["skipped"] == 1 and res["n_scored"] == res["n"] - 1
        assert any("no isolation backend" in r for r in res["skip_reasons"])
        assert "SKIPPED" in render_report(rep)
    else:
        assert res["skipped"] == 0 and res["n_scored"] == res["n"]
        assert rep["sandbox"]["backend"] in render_report(rep)
