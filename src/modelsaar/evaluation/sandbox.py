"""Isolation backends for executing model-written code during evaluation.

The evaluator never runs generated code with ordinary host authority. Exactly one of these
backends is used, detected in this order:

1. ``bwrap`` (bubblewrap, Linux): new user/pid/net/ipc/uts namespaces, the host filesystem
   bound read-only, a private tmpfs ``/tmp``, the work directory bound at ``/tmp/work`` (a
   mount point under the private tmpfs: with ``--ro-bind / /`` bwrap cannot create a new
   top-level ``/work`` on the read-only root).
2. ``sandbox-exec`` (macOS): profile that denies all network access and allows writes only
   under the work directory (and ``/dev``).
3. Docker: ``--network none --read-only --tmpfs /tmp -m 512m --pids-limit 64`` with the
   work directory mounted read-only at ``/work`` (image ``python:3.12-slim``).

In all cases: wall-clock timeout, CPU/address-space/file-size rlimits (host side for bwrap and
sandbox-exec, ``--ulimit``/``-m`` for Docker) and a hard cap on captured output.

When no backend is available ``code_exec`` tasks are *skipped* (reported with their own
denominator); there is deliberately no unsandboxed fallback and no opt-in flag for one.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

SENTINEL = "__MODELSAAR_HARNESS_OK__"
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
            ok, why = _probe([bw, "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--tmpfs", "/tmp", "--", true])
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


def _program(code: str, harness: str) -> str:
    """Model code, then the harness, then the completion sentinel.

    The sentinel is printed *last*: if the model code or the harness raises, calls ``sys.exit``
    or ``os._exit`` before the checks finish, it is missing and the scorer fails the task.
    """
    return code + "\n\n" + harness + "\n" + f"print({SENTINEL!r})\n"


def _macos_profile(workdir: str) -> str:
    return (
        "(version 1)\n"
        "(allow default)\n"
        "(deny network*)\n"
        "(deny file-write*)\n"
        f'(allow file-write* (subpath "{workdir}") (subpath "/dev"))\n'
    )


def _command(backend: str, workdir: str, capdir: str, name: str, timeout_s: float) -> list[str]:
    py = sys.executable
    if backend == "bwrap":
        return [
            "bwrap", "--unshare-all", "--die-with-parent",
            "--ro-bind", "/", "/",
            "--tmpfs", "/tmp",
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
            "docker", "run", "--rm", "--name", name,
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

    Returns ``(stdout, stderr, returncode, backend)``. Raises ``RuntimeError`` when no backend is
    available (callers must check :func:`available` and skip; there is no unsandboxed path).
    ``returncode`` is 124 on wall-clock timeout.
    """
    backend, reason = available()
    if backend is None:
        raise RuntimeError(reason)
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
                    cmd, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, timeout=timeout_s, cwd=cap, env=env,
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
