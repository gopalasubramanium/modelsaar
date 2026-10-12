"""Isolation backends for executing model-written code during evaluation.

The evaluator never runs generated code with ordinary host authority. Exactly one of these
backends is used, detected in this order:

1. ``bwrap`` (bubblewrap, Linux): new user/pid/net/ipc/uts namespaces; **only** the Python
   runtime and the system library directories are bound read-only (input allowlist, see
   ``_bwrap_read_roots``), a private tmpfs ``/tmp``, the work directory bound at ``/tmp/work``.
   The rest of the host filesystem does not exist inside the sandbox.
2. ``sandbox-exec`` (macOS): deny-by-default profile; reads allowed for the Python runtime, system
   libraries/frameworks and the work directory; writes only under the work directory (and
   ``/dev``); no network. Host files outside those roots are not readable.
3. Docker: ``--network none --read-only --tmpfs /tmp -m 512m --pids-limit 64`` with the
   work directory mounted read-only at ``/work`` (image ``python:3.12-slim``); the container
   sees no host path other than that directory.

In all cases: wall-clock timeout, CPU/address-space/file-size rlimits (host side for bwrap and
sandbox-exec, ``--ulimit``/``-m`` for Docker) and a hard cap on captured output. Completion is
evidenced by the trusted runner's nonce-keyed result record (``_program``), not by text the model
code prints. What the sandbox does NOT provide: protection against model code that targets the
evaluator process itself (same interpreter), or against resource use below the rlimits.

When no backend is available ``code_exec`` tasks are *skipped* (reported with their own
denominator); there is deliberately no unsandboxed fallback and no opt-in flag for one.
"""

from __future__ import annotations

import functools
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

SENTINEL = "__MODELSAAR_HARNESS_OK__"  # former public completion marker; printing it proves nothing (see _program)
DOCKER_IMAGE = "python:3.12-slim"
BWRAP_WORK = "/tmp/work"  # inside the sandbox; everything else is read-only or a private tmpfs
NO_BACKEND_REASON = "no isolation backend (install bubblewrap on Linux; macOS sandbox-exec; or Docker)"

MEMORY_BYTES = 512 * 1024 * 1024
OUTPUT_CAP_BYTES = 1024 * 1024  # kernel-enforced via RLIMIT_FSIZE on the capture files
STDOUT_KEEP = 64 * 1024  # bytes of stdout handed back to the scorer
STDERR_KEEP = 1000  # trailing characters of stderr handed back
PIDS_LIMIT = 64


def _probe(cmd: list[str], timeout: float = 10.0) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)[:120]
    if p.returncode != 0:
        return False, (p.stderr or p.stdout).strip()[-120:]
    return True, ""


@functools.lru_cache(maxsize=1)
def available() -> tuple[str | None, str]:
    """Return ``(backend_name, reason)``; ``backend_name`` is None when nothing usable exists.

    The result is cached for the process (``available.cache_clear()`` resets it).
    """
    notes: list[str] = []
    if sys.platform.startswith("linux"):
        bw = shutil.which("bwrap")
        if bw:
            true = shutil.which("true") or "/bin/true"
            ok, why = _probe([bw, "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr", "--ro-bind-try", "/lib", "/lib", "--ro-bind-try", "/lib64", "/lib64", "--ro-bind-try", "/bin", "/bin", "--tmpfs", "/tmp", "--", true])
            if ok:
                return "bwrap", f"bubblewrap at {bw}"
            notes.append(f"bwrap present but unusable: {why}")
        else:
            notes.append("bwrap not installed")
    if sys.platform == "darwin":
        se = shutil.which("sandbox-exec")
        if se:
            return "sandbox-exec", f"macOS sandbox-exec at {se}"
        notes.append("sandbox-exec not found")
    dk = shutil.which("docker")
    if dk:
        ok, why = _probe([dk, "info"], timeout=15.0)
        if ok:
            ok2, why2 = _probe([dk, "image", "inspect", DOCKER_IMAGE], timeout=15.0)
            if ok2:
                return "docker", f"docker at {dk} (image {DOCKER_IMAGE})"
            notes.append(f"docker daemon reachable but image {DOCKER_IMAGE} is not pulled (run: docker pull {DOCKER_IMAGE})")
        else:
            notes.append(f"docker present but daemon not reachable: {why}")
    else:
        notes.append("docker not installed")
    return None, NO_BACKEND_REASON + ("; " + "; ".join(notes) if notes else "")


def _rlimits(timeout_s: float):  # type: ignore[no-untyped-def]
    """preexec_fn applying host-side resource limits (inherited by the sandboxed process)."""
    import resource

    cpu = int(timeout_s) + 1

    def _apply() -> None:
        for res, val in (
            (resource.RLIMIT_CPU, cpu),
            (resource.RLIMIT_FSIZE, OUTPUT_CAP_BYTES),
            (resource.RLIMIT_AS, MEMORY_BYTES),
            (resource.RLIMIT_CORE, 0),
        ):
            try:
                resource.setrlimit(res, (val, val))
            except Exception:
                pass

    return _apply


RESULT_BEGIN = "__MODELSAAR_RESULT_BEGIN__"
RESULT_END = "__MODELSAAR_RESULT_END__"

_RUNNER = r'''
import io as __ms_io, json as __ms_json, sys as __ms_sys
# The nonce arrives on stdin from the evaluator and is never written to disk or the environment;
# stdin is closed before any model code runs.
try:
    __ms_nonce = "" if (__ms_sys.stdin is None or __ms_sys.stdin.isatty()) else __ms_sys.stdin.readline().strip()
except Exception:
    __ms_nonce = ""
try:
    __ms_sys.stdin.close()
except Exception:
    pass
__ms_real_stdout = __ms_sys.stdout
__ms_record = {"nonce": __ms_nonce, "model_ran": False, "harness_completed": False, "harness_stdout": "", "error": None}
__ms_model_out = __ms_io.StringIO()
__ms_sys.stdout = __ms_model_out  # model-controlled output is captured, never counted as harness output
try:
    exec(compile(__MS_MODEL_CODE__, "model.py", "exec"), globals())
    __ms_record["model_ran"] = True
except BaseException as __ms_e:  # noqa: BLE001 - the record must say why the harness never ran
    __ms_record["error"] = "model code raised " + __ms_e.__class__.__name__ + ": " + str(__ms_e)[:200]
__ms_sys.stdout = __ms_real_stdout
__ms_record["model_stdout_chars"] = len(__ms_model_out.getvalue())
if __ms_record["model_ran"]:
    __ms_harness_out = __ms_io.StringIO()
    __ms_sys.stdout = __ms_harness_out
    try:
        exec(compile(__MS_HARNESS_CODE__, "harness.py", "exec"), globals())
        __ms_record["harness_completed"] = True
    except BaseException as __ms_e:  # noqa: BLE001
        __ms_record["error"] = "harness raised " + __ms_e.__class__.__name__ + ": " + str(__ms_e)[:200]
    __ms_sys.stdout = __ms_real_stdout
    __ms_record["harness_stdout"] = __ms_harness_out.getvalue()[:65536]
__ms_real_stdout.write("\n" + __MS_BEGIN__ + "\n" + __ms_json.dumps(__ms_record) + "\n" + __MS_END__ + "\n")
__ms_real_stdout.flush()
'''


def _program(code: str, harness: str) -> str:
    """The trusted runner: it reads a per-run nonce from stdin, executes the model code with its
    stdout captured, then executes the task harness (trusted, task-authored) with *its* stdout
    captured separately, and finally writes a result record framed by RESULT_BEGIN/RESULT_END and
    keyed with the nonce. The scorer accepts a task only from that record: the harness's own output
    (the externally checked behaviour) must match the expectation and ``harness_completed`` must be
    true. Model code that prints the expected text or the public sentinel, exits early (``sys.exit``,
    ``os._exit``) or raises therefore never scores: there is no record, or the record says the
    harness did not complete.

    Limit (documented): everything runs in one interpreter, so model code that deliberately
    inspects the runner's frames could recover the nonce; the protocol defeats marker echo and
    early exit, not an adversary targeting the evaluator itself."""
    return (
        _RUNNER.replace("__MS_MODEL_CODE__", repr(code))
        .replace("__MS_HARNESS_CODE__", repr(harness))
        .replace("__MS_BEGIN__", repr(RESULT_BEGIN))
        .replace("__MS_END__", repr(RESULT_END))
    )


def parse_result(stdout: str, nonce: str) -> dict | None:
    """Return the runner's result record when the framed record carries ``nonce``; else None."""
    start = stdout.rfind(RESULT_BEGIN)
    if start == -1:
        return None
    end = stdout.find(RESULT_END, start)
    if end == -1:
        return None
    body = stdout[start + len(RESULT_BEGIN):end].strip()
    try:
        rec = json.loads(body)
    except ValueError:
        return None
    if not isinstance(rec, dict) or rec.get("nonce") != nonce:
        return None
    return rec


def _runtime_read_roots() -> list[str]:
    """Paths the interpreter needs readable: the Python installation (prefix/base_prefix, the
    executable's real location) and the system libraries. The user's files are not among them."""
    roots = {os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix), os.path.realpath(sys.exec_prefix)}
    exe = os.path.realpath(sys.executable)
    roots.add(os.path.dirname(os.path.dirname(exe)))
    return sorted(roots)


def _macos_profile(workdir: str) -> str:
    """Deny by default. Allowed: process basics, reads of the Python runtime, system libraries and
    frameworks, the work directory; writes only under the work directory and /dev; no network.
    Host files outside those roots (the user's home, other projects) are not readable."""
    reads = "".join(f'  (subpath "{r}")\n' for r in _runtime_read_roots())
    return (
        "(version 1)\n"
        "(deny default)\n"
        "(allow process*)\n"
        "(allow sysctl-read)\n"
        "(allow mach-lookup)\n"
        "(allow signal (target self))\n"
        '(allow file-read* (literal "/") (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random") (literal "/dev/zero") (literal "/dev/tty"))\n'
        '(allow file-read-metadata)\n'
        '(allow file-read* (subpath "/usr/lib") (subpath "/usr/share") (subpath "/System") (subpath "/Library/Frameworks")\n'
        '  (subpath "/opt/homebrew") (subpath "/usr/local") (subpath "/private/etc") (subpath "/etc") (subpath "/private/var/db")\n'
        '  (subpath "/var/db") (subpath "/Library/Preferences") (subpath "/private/var/select") (subpath "/usr/bin") (subpath "/bin"))\n'
        f"(allow file-read* (subpath \"{workdir}\")\n{reads})\n"
        f'(allow file-write* (subpath "{workdir}") (subpath "/dev"))\n'
        "(allow file-ioctl (subpath \"/dev\"))\n"
        "(deny network*)\n"
    )


def _bwrap_read_roots() -> list[str]:
    """Directories bound read-only into the bubblewrap sandbox: shared libraries, the Python
    installation (and the venv's base) and the directories ``sys.executable`` lives in."""
    roots = {"/usr/lib", "/usr/lib64", "/lib", "/lib64", "/usr/local/lib", "/etc/ld.so.cache", "/etc/alternatives"}
    roots |= set(_runtime_read_roots())
    exe = os.path.realpath(sys.executable)
    roots.add(os.path.dirname(exe))
    return sorted(roots)


def _command(backend: str, workdir: str, capdir: str, name: str, timeout_s: float) -> list[str]:
    py = sys.executable
    if backend == "bwrap":
        # Input allowlist: only the Python runtime and the system library directories are bound
        # (read-only). The rest of the host filesystem does not exist inside the sandbox.
        # Order matters: the private /tmp first, then the read-only runtime roots (so a Python
        # installation that itself lives under /tmp is still visible), then the work directory.
        binds: list[str] = []
        for r in _bwrap_read_roots():
            binds += ["--ro-bind-try", r, r]
        return [
            "bwrap", "--unshare-all", "--die-with-parent",
            "--tmpfs", "/tmp",
            *binds,
            "--bind", workdir, BWRAP_WORK,
            "--chdir", BWRAP_WORK,
            "--dev", "/dev", "--proc", "/proc",
            "--new-session",
            "--", py, "-I", "-B", f"{BWRAP_WORK}/prog.py",
        ]
    if backend == "sandbox-exec":
        prof = Path(capdir) / "profile.sb"
        prof.write_text(_macos_profile(workdir), encoding="utf-8")
        return ["sandbox-exec", "-f", str(prof), py, "-I", "-B", os.path.join(workdir, "prog.py")]
    if backend == "docker":
        return [
            "docker", "run", "--rm", "-i", "--name", name,
            "--network", "none", "--read-only", "--tmpfs", "/tmp",
            "-m", "512m", "--pids-limit", str(PIDS_LIMIT),
            "--ulimit", f"cpu={int(timeout_s) + 1}", "--ulimit", f"fsize={OUTPUT_CAP_BYTES}",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "-v", f"{workdir}:/work:ro", "-w", "/work",
            "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp", "-e", "TMPDIR=/tmp",
            DOCKER_IMAGE, "python", "-I", "-B", "/work/prog.py",
        ]
    raise ValueError(f"unknown sandbox backend {backend!r}")


def run(code: str, harness: str, timeout_s: float = 10.0) -> tuple[str, str, int, str]:
    """Execute ``code`` + ``harness`` in the detected sandbox.

    Returns ``(stdout, stderr, returncode, backend)``; ``stdout`` carries the runner's framed result
    record (see :func:`_program`), which the scorer extracts with :func:`parse_result` using the
    nonce stored in ``run.last_nonce``. Raises ``RuntimeError`` when no backend is available
    (callers must check :func:`available` and skip; there is no unsandboxed path).
    ``returncode`` is 124 on wall-clock timeout.
    """
    backend, reason = available()
    if backend is None:
        raise RuntimeError(reason)
    nonce = secrets.token_hex(16)
    run.last_nonce = nonce  # type: ignore[attr-defined]
    with tempfile.TemporaryDirectory(prefix="modelsaar-eval-work-") as work, tempfile.TemporaryDirectory(prefix="modelsaar-eval-cap-") as cap:
        workdir = os.path.realpath(work)  # macOS: /var -> /private/var for the sandbox profile
        Path(workdir, "prog.py").write_text(_program(code, harness), encoding="utf-8")
        if backend == "docker":
            os.chmod(workdir, 0o755)
            os.chmod(os.path.join(workdir, "prog.py"), 0o644)
        name = f"modelsaar-eval-{uuid.uuid4().hex[:12]}"
        cmd = _command(backend, workdir, cap, name, timeout_s)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "HOME": BWRAP_WORK if backend == "bwrap" else workdir,
            "TMPDIR": "/tmp" if backend == "bwrap" else workdir,
            "LANG": "C.UTF-8",
        }
        if backend == "docker":
            env = dict(os.environ)  # the docker CLI needs its own context/config; isolation is the container's job
        out_path, err_path = Path(cap, "stdout"), Path(cap, "stderr")
        rc = 124
        with open(out_path, "wb") as fo, open(err_path, "wb") as fe:
            try:
                p = subprocess.run(
                    cmd, input=(nonce + "\n").encode(), stdout=fo, stderr=fe, timeout=timeout_s, cwd=cap, env=env,
                    preexec_fn=_rlimits(timeout_s) if backend != "docker" and sys.platform != "win32" else None,
                )
                rc = p.returncode
            except subprocess.TimeoutExpired:
                if backend == "docker":
                    subprocess.run(["docker", "kill", name], capture_output=True, timeout=15)
                rc = 124
        stdout = out_path.read_bytes()[:STDOUT_KEEP].decode("utf-8", "replace")
        stderr = err_path.read_bytes()[-4096:].decode("utf-8", "replace")[-STDERR_KEEP:]
        if rc == 124:
            stderr = (stderr + "\ntimeout").strip()
        return stdout, stderr, rc, backend
