#!/usr/bin/env python3
"""Acceptance cases for the one-line installer on an OS whose Python is externally managed (PEP 668).

These run the REAL `site/static/install.sh` end to end with REAL package installations (pip/uv/pipx fetch
the package and its dependencies over the network) against a CONTROLLED HTTP BACKEND — the repository's
fake Ollama (`modelsaar.testing.fakebackend`), started by this harness on a loopback port. The routed
request therefore proves installer -> init -> temporary gateway -> `auto` routing through the installed
executable; it is not inference by a real model.

Every case runs in a fresh HOME with a controlled PATH: a directory of symlinks to the system's commands
from which `uv`, `pipx`, `git` (and, per case, `python3`) are REMOVED, so a case that claims "no uv/pipx"
really has none. Nothing is installed into the OS Python; the harness checks that before/after.

Cases (the numbers follow the acceptance list of the 2026-10-13 fix):
  1. old installer on externally-managed Python, no uv/pipx -> the original `externally-managed-environment` failure
  2. new installer, same environment -> persistent user-owned venv, routed `auto` request via the installed executable
  3. venv/ensurepip unavailable (a Python whose venv module cannot bootstrap pip) and no git -> pinned uv is downloaded,
     checksum-verified, used; the venv is built on the SYSTEM interpreter (no managed Python download)
  4. existing uv path and existing pipx path still work
  5. repeat run reuses the environment and keeps config/keys/state byte-identical; a failed attempt (bad commit)
     leaves the working installation and configuration untouched; a backend outage after installation exits 2;
     (5d) upgrading from an earlier commit switches envs/current atomically, keeps the previous environment,
     removes older ones
  6. (inside 2) `init` and one `auto` request through the exact installed executable
  7. optional: the package installed from the source archive is file-for-file identical to a git checkout install

Usage: python scripts/installer_fallback_tests.py --out DIR [--source ARCHIVE_PATH_OR_URL] [--ref SHA]
         [--user tester] [--no-ensurepip-python python3.11] [--uv-binary PATH] [--repo PATH] [--cases 1,2,...]
Run as an unprivileged user (CI runner) or as root with --user (the cases then run as that user).
Exit 0 when every executed case passes; the transcript and results.json are written to DIR.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from modelsaar.testing.fakebackend import FakeBackend, FakeModel  # noqa: E402

PASS_ENV = ("HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy", "SSL_CERT_FILE", "PIP_CERT", "CURL_CA_BUNDLE",
            "REQUESTS_CA_BUNDLE", "UV_NATIVE_TLS", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "UV_INDEX_URL", "PIP_CONFIG_FILE",
            "LANG", "LC_ALL", "TERM", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
REDACT = re.compile(r"msk_[A-Za-z0-9_-]+")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sha256_path(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree_digest(root: Path) -> str:
    """Digest of names+sizes+mtimes of a directory tree (cheap 'did anything change here' check)."""
    h = hashlib.sha256()
    if not root.exists():
        return "absent"
    for p in sorted(root.rglob("*")):
        try:
            st = p.lstat()
        except OSError:
            continue
        h.update(f"{p.relative_to(root)}|{st.st_size}|{int(st.st_mtime)}|{stat.S_IMODE(st.st_mode)}\n".encode())
    return h.hexdigest()


class Harness:
    def __init__(self, a: argparse.Namespace) -> None:
        self.a = a
        self.out = Path(a.out).resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.log = open(self.out / "transcript.txt", "w", encoding="utf-8")
        self.results: list[dict] = []
        self.ok_all = True
        self.user = a.user if os.geteuid() == 0 else None
        if os.geteuid() == 0 and not a.user:
            sys.exit("run as an unprivileged user, or as root with --user <unprivileged user>")
        self.work = Path(tempfile.mkdtemp(prefix="modelsaar-installer-tests-", dir=a.tmpdir))
        if self.user:
            pw = pwd.getpwnam(self.user)
            os.chown(self.work, pw.pw_uid, pw.pw_gid)
        self.install = Path(a.install).resolve()
        self.old_install = Path(a.old_install).resolve() if a.old_install else None
        self.ref = a.ref
        self.source = a.source
        self.os_dist = [Path(p) for p in ("/usr/lib/python3/dist-packages", "/usr/local/lib/python3.12/dist-packages")]
        self.os_before = {str(p): tree_digest(p) for p in self.os_dist}

    # ---- output ---------------------------------------------------------------------------------
    def say(self, *parts: object) -> None:
        line = REDACT.sub("msk_<redacted>", " ".join(str(p) for p in parts))
        print(line, flush=True)
        self.log.write(line + "\n")
        self.log.flush()

    def record(self, case: str, passed: bool | None, **d: object) -> None:
        if passed is None:
            self.say(f"== {case}: NOT EXECUTED ({d.get('why', '')})")
            self.results.append({"case": case, "result": "NOT EXECUTED", **d})
            return
        self.ok_all &= passed
        self.results.append({"case": case, "result": "PASS" if passed else "FAIL", **d})
        self.say(f"== {case}: {'PASS' if passed else 'FAIL'}")

    # ---- environments ---------------------------------------------------------------------------
    def mkhome(self, name: str) -> Path:
        home = self.work / f"home-{name}"
        home.mkdir()
        if self.user:
            pw = pwd.getpwnam(self.user)
            os.chown(home, pw.pw_uid, pw.pw_gid)
        return home

    def mkpath(self, name: str, *, python3: str | None, keep: set[str] = frozenset(), extra: dict[str, Path] | None = None,
               fail_shims: set[str] = frozenset()) -> Path:
        """A PATH directory of symlinks to the system commands, minus uv/pipx/git/python* unless kept."""
        d = self.work / f"path-{name}"
        d.mkdir()
        drop = {"uv", "uvx", "pipx", "git", "python3", "python", "python3.10", "python3.11", "python3.12", "python3.13", "python3.14", "modelsaar"} - keep
        seen: set[str] = set()
        for src in ("/usr/local/bin", "/usr/bin", "/bin"):
            sp = Path(src)
            if not sp.is_dir():
                continue
            for f in sp.iterdir():
                if f.name in seen or f.name in drop:
                    continue
                if f.name.startswith("python") and f.name not in keep:
                    continue
                seen.add(f.name)
                os.symlink(f, d / f.name)
        if python3:
            target = shutil.which(python3) or python3
            os.symlink(target, d / "python3")
            if Path(target).name != "python3" and not (d / Path(target).name).exists():
                os.symlink(target, d / Path(target).name)
        for name_, p in (extra or {}).items():
            os.symlink(p, d / name_)
        for name_ in fail_shims:
            s = d / name_
            s.write_text(f"#!/bin/sh\necho '{name_}: command not found (masked by the installer test)' >&2\nexit 127\n")
            s.chmod(0o755)
        return d

    def env(self, home: Path, path: Path, **extra: str) -> dict[str, str]:
        e = {"HOME": str(home), "PATH": str(path), "USER": self.user or os.environ.get("USER", "tester")}
        for k in PASS_ENV:
            if k in os.environ:
                e[k] = os.environ[k]
        e.update(extra)
        return e

    def run(self, cmd: str, env: dict[str, str], *, stdin_file: Path | None = None, timeout: int = 1500, cwd: Path | None = None) -> subprocess.CompletedProcess:
        """Run `cmd` as the test user with ONLY `env`; stdin_file is piped into it like `curl … | sh`."""
        envargs = [f"{k}={v}" for k, v in env.items()]
        base = ["env", "-i", *envargs, "sh", "-c", cmd]
        if self.user:
            base = ["runuser", "-u", self.user, "--", *base]
        shown = cmd if len(cmd) < 160 else cmd[:157] + "..."
        self.say(f"\n$ ({'as ' + self.user if self.user else 'as current user'}; HOME={env['HOME']}) {shown}" + (f"  < {stdin_file.name}" if stdin_file else ""))
        with open(stdin_file, "rb") if stdin_file else open(os.devnull, "rb") as fin:
            r = subprocess.run(base, stdin=fin, capture_output=True, text=True, timeout=timeout, cwd=cwd or self.work)
        for ln in (r.stdout or "").splitlines():
            self.say("  | " + ln)
        for ln in (r.stderr or "").splitlines():
            self.say("  ! " + ln)
        self.say(f"  [exit {r.returncode}]")
        return r

    def sh_pipe(self, script: Path, env: dict[str, str], extra_vars: str = "") -> subprocess.CompletedProcess:
        """The literal interface: the script arrives on stdin (`curl -fsSL … | sh`), not as a file argument."""
        return self.run(f"{extra_vars} sh".strip(), env, stdin_file=script)

    def os_python_unchanged(self) -> bool:
        after = {str(p): tree_digest(p) for p in self.os_dist}
        return after == self.os_before

    # ---- backend --------------------------------------------------------------------------------
    def backend(self) -> FakeBackend:
        fake = FakeBackend([FakeModel("small:1b", ["completion", "tools"], 8192, parameter_size="1.0B", loaded=True),
                            FakeModel("plain:3b", ["completion"], 4096, parameter_size="3B")])
        fake.start()
        self.say(f"[controlled HTTP backend: fake Ollama on 127.0.0.1:{fake.port} — not a real model]")
        return fake

    def install_env(self, home: Path, path: Path, fake: FakeBackend, port: int, public: bool = False, **extra: str) -> dict[str, str]:
        e = self.env(home, path, MODELSAAR_ENDPOINT=f"http://127.0.0.1:{fake.port}", MODELSAAR_TYPE="ollama", MODELSAAR_PORT=str(port))
        if not public:
            e["MODELSAAR_REF"] = self.ref
            # The installer's default source is GitHub's archive of the commit; when the test source IS that URL the
            # hook is not set at all, so the public code path is exercised exactly.
            if self.source != f"https://github.com/gopalasubramanium/modelsaar/archive/{self.ref}.tar.gz":
                e["MODELSAAR_SOURCE"] = self.source
        e.update(extra)
        return e

    def case_public_url(self) -> None:
        """The literal public command in a fresh HOME with no uv/pipx/git on PATH: `curl -fsSL URL | sh`.
        The served script's OWN pin is used (no MODELSAAR_REF/SOURCE); --ref says which pin to expect."""
        url = self.a.public_url
        home = self.mkhome("public")
        path = self.mkpath("public", python3=self.a.managed_python, fail_shims={"git"})
        fake = self.backend()
        port = free_port()
        try:
            served = subprocess.run(["curl", "-fsSL", url], capture_output=True, timeout=60)
            digest = hashlib.sha256(served.stdout).hexdigest() if served.returncode == 0 else None
            self.say(f"[served {url}: HTTP fetch {'ok' if served.returncode == 0 else 'FAILED'}; sha256 {digest}; expected {self.a.expect_sha256 or '(not given)'}]")
            e = self.install_env(home, path, fake, port, public=True)
            r = self.run(f"curl -fsSL {url} | sh", e)
            out = r.stdout + r.stderr
            envs = home / ".local/share/modelsaar/envs"
            checks = {
                "served_bytes_match": (self.a.expect_sha256 is None) or (digest == self.a.expect_sha256),
                "exit_0": r.returncode == 0,
                "pinned_commit_installed": f"commit {self.ref}" in out and (envs / self.ref / ".modelsaar-installed").exists(),
                "isolated_method": ("via venv" in out) or ("via bootstrap" in out),
                "verification_ok": "verification: OK" in out and "routed: 'auto' -> ollama/" in out,
                "no_user_site_install": not (home / ".local/lib").exists(),
                "os_python_unchanged": self.os_python_unchanged(),
            }
            self.record("P_public_url_curl_sh_fresh_environment", all(checks.values()), exit=r.returncode, url=url, served_sha256=digest, **checks)
            r2 = self.run(f"curl -fsSL {url} | sh", e)
            self.record("P2_public_url_repeat_run", r2.returncode == 0 and "existing installation of this commit reused" in r2.stdout and "existing configuration kept" in r2.stdout, exit=r2.returncode)
        finally:
            fake.stop()

    # ---- cases ----------------------------------------------------------------------------------
    def case1_old_installer(self) -> None:
        if not self.old_install:
            self.record("1_old_installer_externally_managed_failure", None, why="--old-install not given")
            return
        home = self.mkhome("c1")
        # The previous installer's package spec was a git+https URL, so pip needed git; the GX10 has git. Keep it
        # here so the failure reproduced is the externally-managed one, not a missing-git one.
        path = self.mkpath("c1", python3=self.a.managed_python, keep={"git"})
        fake = self.backend()
        try:
            e = self.install_env(home, path, fake, free_port())
            # Does this machine's pip honour the marker? (GitHub's runner images, for one, ship a pip.conf with
            # break-system-packages=true; a stock Debian/Ubuntu does not. PIP_CONFIG_FILE=/dev/null restores the OS default.)
            probe = self.run("python3 -m pip install --user --dry-run --no-index modelsaar-no-such-package-probe 2>&1 | head -3; true", e)
            if "externally-managed-environment" not in probe.stdout:
                self.record("1_old_installer_externally_managed_failure", None,
                            why="pip on this machine does not enforce PEP 668 (a pip.conf/env override?); set PIP_CONFIG_FILE=/dev/null to test the OS default")
                return
            r = self.sh_pipe(self.old_install, e)
            out = r.stdout + r.stderr
            self.record("1_old_installer_externally_managed_failure",
                        r.returncode != 0 and "externally-managed-environment" in out and "pip install failed" in out
                        and not (home / ".local/lib").exists() and self.os_python_unchanged(),
                        exit=r.returncode, python=self.a.managed_python, os_python_unchanged=self.os_python_unchanged())
        finally:
            fake.stop()

    def case2_venv_install(self) -> tuple[Path, Path, FakeBackend, int] | None:
        home = self.mkhome("c2")
        path = self.mkpath("c2", python3=self.a.managed_python, fail_shims={"git"})
        fake = self.backend()
        port = free_port()
        e = self.install_env(home, path, fake, port)
        r = self.sh_pipe(self.install, e)
        out = r.stdout + r.stderr
        envs = home / ".local/share/modelsaar/envs"
        cur = envs / "current"
        exe = cur / "bin/modelsaar"
        launcher = home / ".local/bin/modelsaar"
        checks = {
            "exit_0": r.returncode == 0,
            "method_venv": "via venv" in out,
            "verification_ok": "verification: OK" in out and "routed: 'auto' -> ollama/" in out and "request req_" in out,
            "summary_lines": "Installed revision:  " in out and "Configuration/keys:  created" in out and "Routing check:       passed" in out and "fresh complete" in out,
            "config_and_keys": (home / ".modelsaar/config.yaml").exists() and (home / ".modelsaar/keys/api_keys").exists(),
            "key_mode_600": (home / ".modelsaar/keys/api_keys").exists() and stat.S_IMODE((home / ".modelsaar/keys/api_keys").stat().st_mode) == 0o600,
            "env_dir_and_marker": (envs / self.ref / ".modelsaar-installed").exists() and exe.exists(),
            "current_symlink": cur.is_symlink() and os.readlink(cur) == self.ref,
            "launcher_symlink": launcher.is_symlink() and os.readlink(launcher) == str(exe),
            "venv_on_system_python": os.path.realpath(envs / self.ref / "bin/python") == os.path.realpath(shutil.which(self.a.managed_python) or self.a.managed_python),
            "no_user_site_install": not (home / ".local/lib").exists(),
            "no_uv_helper_downloaded": not (home / ".local/share/modelsaar/uv").exists(),
            "os_python_unchanged": self.os_python_unchanged(),
            "exact_executable_used": f"({exe})" in out,
            "no_profile_edits": not any((home / f).exists() for f in (".bashrc", ".profile", ".zshrc", ".zprofile", ".bash_profile")),
        }
        self.record("2_new_installer_venv_on_externally_managed_python", all(checks.values()), exit=r.returncode, **checks)
        if not checks["exit_0"]:
            fake.stop()
            return None
        # 6. init already ran inside the installer; now an ordinary request through the EXACT installed executable
        gw_port = free_port()
        r2 = self.run(
            f'set -e; MS="$HOME/.local/share/modelsaar/envs/current/bin/modelsaar"; "$MS" --version; '
            f'"$MS" config show | grep -q "port: {port}"; '
            f'(MODELSAAR_HOME="$HOME/.modelsaar" "$MS" serve >"$HOME/serve.log" 2>&1 & echo $! > "$HOME/gw.pid"); '
            f'i=0; until curl -fsS -m 2 http://127.0.0.1:{port}/healthz 2>/dev/null | grep -q modelsaar; do i=$((i+1)); [ $i -gt 60 ] && exit 9; sleep 0.5; done; '
            f'"$MS" test --model auto; rc=$?; kill $(cat "$HOME/gw.pid"); exit $rc',
            self.env(home, path, MODELSAAR_HOME=str(home / ".modelsaar")))
        self.record("6_init_then_auto_request_via_installed_executable", r2.returncode == 0 and "routed: 'auto' -> ollama/" in r2.stdout and "request req_" in r2.stdout,
                    exit=r2.returncode, backend="controlled fake Ollama (not real inference)")
        _ = gw_port
        return home, path, fake, port

    def case5_repeat_and_failure(self, ctx: tuple[Path, Path, FakeBackend, int] | None) -> None:
        if not ctx:
            self.record("5_repeat_run_preserves", None, why="case 2 did not complete")
            return
        home, path, fake, port = ctx
        cfg = home / ".modelsaar/config.yaml"
        keys = home / ".modelsaar/keys/api_keys"
        adm = home / ".modelsaar/keys/admin_key"
        before = {p: (sha256_path(p), stat.S_IMODE(p.stat().st_mode)) for p in (cfg, keys, adm)}
        state_before = tree_digest(home / ".modelsaar/state")
        e = self.install_env(home, path, fake, port)
        r = self.sh_pipe(self.install, e)
        out = r.stdout + r.stderr
        after = {p: (sha256_path(p), stat.S_IMODE(p.stat().st_mode)) for p in (cfg, keys, adm)}
        self.record("5a_repeat_run_reuses_env_and_keeps_config_keys", r.returncode == 0 and "existing installation of this commit reused" in out
                    and "existing configuration kept" in out and "verification: OK" in out and before == after,
                    exit=r.returncode, config_keys_byte_identical=before == after, state_db_present_before=state_before != "absent")
        # a failed attempt at another commit must not touch the working installation
        exe = home / ".local/share/modelsaar/envs/current/bin/modelsaar"
        bogus = "0" * 40
        e2 = self.install_env(home, path, fake, port, MODELSAAR_REF=bogus, MODELSAAR_SOURCE=str(self.work / "does-not-exist.tar.gz"))
        r2 = self.sh_pipe(self.install, e2)
        out2 = r2.stdout + r2.stderr
        still = subprocess.run([str(exe), "--version"], capture_output=True, text=True)
        after2 = {p: (sha256_path(p), stat.S_IMODE(p.stat().st_mode)) for p in (cfg, keys, adm)}
        self.record("5b_failed_attempt_keeps_working_install", r2.returncode == 1 and "failed" in out2 and still.returncode == 0
                    and os.readlink(home / ".local/share/modelsaar/envs/current") == self.ref and not (home / f".local/share/modelsaar/envs/{bogus}-custom").exists()
                    and before == after2 and "Installed revision:" not in out2,
                    exit=r2.returncode, working_executable_after=still.returncode == 0, config_untouched=before == after2)
        # backend outage after installation: package + config in place, routing check fails -> exit 2, no success wording
        fake.stop()
        r3 = self.sh_pipe(self.install, e)
        out3 = r3.stdout + r3.stderr
        self.record("5c_backend_unavailable_exits_2_not_success", r3.returncode == 2 and "Routing check:       FAILED" in out3 and "verification: FAILED" in out3
                    and "gateway is up" in out3 and "upgrade finished with issues (exit 2)" in out3
                    and "verification: OK" not in out3, exit=r3.returncode)

    def case5d_upgrade_from_prior_revision(self) -> None:
        """Installation A (prior commit) exists; installing B must switch envs/current to B atomically, B must run,
        and A must remain available (a running service and rollback use it); environments older than A go."""
        if not self.a.prior_ref:
            self.record("5d_upgrade_from_prior_revision", None, why="--prior-ref not given")
            return
        prior_src = self.a.prior_source or f"https://github.com/gopalasubramanium/modelsaar/archive/{self.a.prior_ref}.tar.gz"
        home = self.mkhome("c5d")
        path = self.mkpath("c5d", python3=self.a.managed_python, fail_shims={"git"})
        fake = self.backend()
        port = free_port()
        try:
            envs = home / ".local/share/modelsaar/envs"
            e_a = self.install_env(home, path, fake, port, MODELSAAR_REF=self.a.prior_ref)
            if prior_src != f"https://github.com/gopalasubramanium/modelsaar/archive/{self.a.prior_ref}.tar.gz":
                e_a["MODELSAAR_SOURCE"] = prior_src
            else:
                e_a.pop("MODELSAAR_SOURCE", None)
            r_a = self.sh_pipe(self.install, e_a)
            a_ok = r_a.returncode == 0 and envs.is_dir() and os.readlink(envs / "current") == self.a.prior_ref
            cfg = home / ".modelsaar/config.yaml"
            keys = home / ".modelsaar/keys/api_keys"
            before = (sha256_path(cfg), sha256_path(keys)) if a_ok else None
            # an even older complete environment that should be cleaned up (only A, the previous one, is retained)
            stale = envs / ("0" * 40)
            stale.mkdir()
            (stale / ".modelsaar-installed").write_text("stale\n")
            if self.user:
                pw = pwd.getpwnam(self.user)
                os.chown(stale, pw.pw_uid, pw.pw_gid)
                os.chown(stale / ".modelsaar-installed", pw.pw_uid, pw.pw_gid)
            e_b = self.install_env(home, path, fake, port)
            r_b = self.sh_pipe(self.install, e_b)
            out = r_b.stdout + r_b.stderr
            cur = envs / "current"
            b_exe = envs / self.ref / "bin/modelsaar"
            a_exe = envs / self.a.prior_ref / "bin/modelsaar"
            run_b = subprocess.run([str(b_exe), "--version"], capture_output=True, text=True) if b_exe.exists() else None
            run_a = subprocess.run([str(a_exe), "--version"], capture_output=True, text=True) if a_exe.exists() else None
            checks = {
                "a_installed_first": a_ok,
                "b_exit_0": r_b.returncode == 0,
                "current_is_symlink_to_b": cur.is_symlink() and os.readlink(cur) == self.ref,
                "no_stray_link_inside_a": not list((envs / self.a.prior_ref).glob("current.tmp.*")) if a_ok else False,
                "b_executes": bool(run_b) and run_b.returncode == 0,
                "a_remains_available": bool(run_a) and run_a.returncode == 0 and (envs / self.a.prior_ref / ".modelsaar-installed").exists(),
                "older_env_removed": not stale.exists(),
                "previous_kept_message": "previous environment kept" in out,
                "launcher_via_current": (home / ".local/bin/modelsaar").is_symlink() and os.readlink(home / ".local/bin/modelsaar") == str(cur / "bin/modelsaar"),
                "config_keys_unchanged": before is not None and (sha256_path(cfg), sha256_path(keys)) == before,
                "verification_ok": "verification: OK" in out,
            }
            self.record("5d_upgrade_from_prior_revision", all(checks.values()), prior=self.a.prior_ref[:12], new=self.ref[:12], **checks)
        finally:
            fake.stop()

    # ---- real systemd user-service cases (Linux with a reachable user manager; otherwise NOT EXECUTED) ----
    def _user_manager(self) -> bool:
        if self.user:
            return False  # the cases run as the current user against its own manager
        return subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True).returncode == 0

    def _unit_path(self) -> Path:
        return Path(os.path.expanduser("~")) / ".config/systemd/user/modelsaar.service"

    def _write_unit(self, exec_start: str, home_dir: Path | None) -> None:
        p = self._unit_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        env = f"Environment=MODELSAAR_HOME={home_dir}\n" if home_dir else ""
        p.write_text(f"[Unit]\nDescription=ModelSaar gateway (installer test)\n\n[Service]\n{env}ExecStart={exec_start}\nRestart=no\n\n[Install]\nWantedBy=default.target\n")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)

    def _svc(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)

    def _svc_prop(self, prop: str) -> str:
        return self._svc("show", "modelsaar.service", "-p", prop, "--value").stdout.strip()

    def _svc_cleanup(self) -> None:
        self._svc("stop", "modelsaar.service")
        self._svc("reset-failed", "modelsaar.service")
        p = self._unit_path()
        if p.exists():
            p.unlink()
        self._svc("daemon-reload")

    def _running_env(self, pid: str) -> str:
        try:
            m = re.findall(r"/\.local/share/modelsaar/envs/[0-9a-f]{40}", Path(f"/proc/{pid}/maps").read_text())
            return sorted(set(m))[0] if m else ""
        except OSError:
            return ""

    def _lan_ip(self) -> str | None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            s.close()
            return ip if not ip.startswith("127.") else None
        except OSError:
            return None

    def cases_service(self) -> None:
        tag = "S_user_service"
        if os.uname().sysname != "Linux" or not self._user_manager():
            self.record(f"{tag}_1_upgrade_active_matching_service", None, why="no reachable systemd user manager (Linux `systemctl --user`) for the current user")
            return
        if not self.a.prior_ref:
            self.record(f"{tag}_1_upgrade_active_matching_service", None, why="--prior-ref not given")
            return
        prior_src = self.a.prior_source or f"https://github.com/gopalasubramanium/modelsaar/archive/{self.a.prior_ref}.tar.gz"
        home = self.mkhome("svc")
        path = self.mkpath("svc", python3=self.a.managed_python, fail_shims={"git"})
        fake = self.backend()
        port = free_port()
        envs = home / ".local/share/modelsaar/envs"
        cur = envs / "current"
        home_dir = home / ".modelsaar"
        self._svc_cleanup()
        try:
            # --- installation A (prior revision), fresh, loopback ---
            e_a = self.install_env(home, path, fake, port, MODELSAAR_REF=self.a.prior_ref)
            if prior_src != f"https://github.com/gopalasubramanium/modelsaar/archive/{self.a.prior_ref}.tar.gz":
                e_a["MODELSAAR_SOURCE"] = prior_src
            else:
                e_a.pop("MODELSAAR_SOURCE", None)
            r_a = self.sh_pipe(self.install, e_a)
            assert r_a.returncode == 0 and os.readlink(cur) == self.a.prior_ref, "installation A failed"
            # --- non-loopback configuration (like the owner's GX10): bind to the machine's LAN address ---
            ip = self._lan_ip()
            cfg = home_dir / "config.yaml"
            text = cfg.read_text()
            if ip:
                text = re.sub(r"(?m)^(\s*host:\s*).*$", rf"\g<1>{ip}", text, count=1)
                text = re.sub(r"(?m)^(\s*allow_lan:\s*).*$", r"\g<1>true", text, count=1) if re.search(r"(?m)^\s*allow_lan:", text) else text.replace("\nsecurity:\n", "\nsecurity:\n  allow_lan: true\n", 1)
                cfg.write_text(text)
                if "allow_lan: true" not in cfg.read_text():
                    cfg.write_text(cfg.read_text() + "\nsecurity:\n  allow_lan: true\n")
            vr = subprocess.run([str(cur / "bin/modelsaar"), "config", "validate"], env={**os.environ, "MODELSAAR_HOME": str(home_dir)}, capture_output=True, text=True)
            self.say(f"[config: host={ip or '127.0.0.1'} validate rc={vr.returncode} {vr.stdout.strip() or vr.stderr.strip()[:120]}]")
            lan_ok = vr.returncode == 0
            before = {p_: sha256_path(p_) for p_ in (cfg, home_dir / "keys/api_keys", home_dir / "keys/admin_key")}
            # --- a user unit that belongs to this installation (ExecStart via envs/current, this MODELSAAR_HOME) ---
            self._write_unit(f"{cur}/bin/modelsaar serve", home_dir)
            self._svc("start", "modelsaar.service")
            deadline = 30
            while deadline and self._svc_prop("ActiveState") != "active":
                time.sleep(1)
                deadline -= 1
            pid_a = self._svc_prop("MainPID")
            time.sleep(2)
            running_a = self._running_env(pid_a)
            self.say(f"[service started: pid {pid_a}, runs {running_a[-12:] if running_a else '?'}]")
            # --- 1. upgrade to B with the plain command (no MODELSAAR_NO_CHECK) ---
            e_b = self.install_env(home, path, fake, port)
            r = self.sh_pipe(self.install, e_b)
            out = r.stdout + r.stderr
            pid_b = self._svc_prop("MainPID")
            running_b = self._running_env(pid_b)
            after = {p_: sha256_path(p_) for p_ in before}
            host_line = f"http://{ip}:" if ip else "http://127.0.0.1:"
            checks = {
                "exit_0": r.returncode == 0,
                "mode_upgrade_no_init": "mode: upgrade" in out and "wrote " not in out,
                "service_detected_and_restarted": "belongs to this installation; restarting" in out,
                "service_active_after": self._svc_prop("ActiveState") == "active",
                "service_pid_changed": pid_b not in ("", "0") and pid_b != pid_a,
                "running_revision_is_new": running_b.endswith(self.ref) and f"Running revision:    {self.ref}" in out,
                "current_is_new": os.readlink(cur) == self.ref,
                "previous_env_retained": (envs / self.a.prior_ref / ".modelsaar-installed").exists(),
                "no_temporary_gateway": "starting a temporary gateway" not in out,
                "checked_restarted_service": "checking the restarted service" in out,
                "routing_passed": "Routing check:       passed" in out,
                "endpoint_from_config": f"Endpoint:            {host_line}{port}/v1" in out and ("loopback only" not in out if ip else True),
                "lan_config_valid": lan_ok,
                "config_keys_preserved": before == after and "Configuration/keys:  preserved" in out,
                "no_serve_instruction": "run the gateway:" not in out and "running under modelsaar.service" in out,
                "summary_complete": "upgrade complete" in out,
            }
            self.record(f"{tag}_1_upgrade_active_matching_service", all(checks.values()), exit=r.returncode, lan_ip=ip, **checks)
            # --- 2. same revision again: no restart, no disruption ---
            r2 = self.sh_pipe(self.install, e_b)
            out2 = r2.stdout + r2.stderr
            pid_c = self._svc_prop("MainPID")
            self.record(f"{tag}_2_same_revision_repeat_no_restart", r2.returncode == 0 and "already runs this revision; not restarted" in out2
                        and pid_c == pid_b and "existing installation of this commit reused" in out2 and "upgrade complete" in out2, exit=r2.returncode, pid_same=pid_c == pid_b)
            # --- 3. intentionally stopped service stays stopped ---
            self._svc("stop", "modelsaar.service")
            time.sleep(1)
            r3 = self.sh_pipe(self.install, e_b)
            out3 = r3.stdout + r3.stderr
            self.record(f"{tag}_3_inactive_service_preserved", r3.returncode == 0 and "is inactive; left as it is (not started)" in out3
                        and self._svc_prop("ActiveState") == "inactive" and "starting a temporary gateway" in out3 and "temporary gateway stopped" in out3
                        and "systemctl --user start modelsaar.service" in out3, exit=r3.returncode, state=self._svc_prop("ActiveState"))
            # --- 4. failed replacement startup -> rollback to the previous environment and service ---
            self._svc("start", "modelsaar.service")
            time.sleep(3)
            pid_d = self._svc_prop("MainPID")
            broken = "f" * 40
            bdir = envs / broken
            (bdir / "bin").mkdir(parents=True)
            os.symlink(cur.resolve() / "bin/python", bdir / "bin/python")
            # passes every pre-activation check (runs, validates, shows the config, ensures keys) but cannot serve:
            # it lingers a few seconds first (like a gateway that dies during startup), so the bounded wait has to
            # report progress ("Waiting for service…") before systemd marks the unit failed and the installer gives up
            (bdir / "bin/modelsaar").write_text('#!/bin/sh\ncase "$1" in --version) echo "modelsaar 0.1.0-broken-test"; exit 0;; config) [ "$2" = show ] && cat "$MODELSAAR_HOME/config.yaml"; exit 0;; keys) exit 0;; esac\nsleep 7; echo "broken replacement: refusing to serve" >&2; exit 7\n')
            (bdir / "bin/modelsaar").chmod(0o755)
            # the marker must name the spec the installer itself derives for MODELSAAR_REF=<broken>, otherwise the
            # environment is treated as "installed from a different source" and reinstalled instead of reused
            if self.source.startswith("git+"):
                spec_b = f"{self.source}@{broken}"
            elif self.source == f"https://github.com/gopalasubramanium/modelsaar/archive/{self.ref}.tar.gz":
                spec_b = f"modelsaar @ https://github.com/gopalasubramanium/modelsaar/archive/{broken}.tar.gz"
            else:
                spec_b = f"modelsaar @ {self.source}"
            (bdir / ".modelsaar-installed").write_text(spec_b + "\n")
            e_bad = self.install_env(home, path, fake, port, MODELSAAR_REF=broken)
            r4 = self.sh_pipe(self.install, e_bad)
            out4 = r4.stdout + r4.stderr
            pid_e = self._svc_prop("MainPID")
            checks4 = {
                "exit_3": r4.returncode == 3,
                "not_started_cleanly": "replacement did not start cleanly" in out4,
                "rollback_line": "Rollback:            restored " + self.ref in out4,
                "current_restored": os.readlink(cur) == self.ref,
                "service_active_again": self._svc_prop("ActiveState") == "active",
                "running_previous_revision": self._running_env(pid_e).endswith(self.ref),
                "broken_env_marked_failed": (bdir / ".modelsaar-failed").exists() and not (bdir / ".modelsaar-installed").exists(),
                "waiting_progress_shown": "Waiting for service" in out4,
                "diagnostics_retained": "journal:" in out4 and "refusing to serve" in out4,
                "routing_check_skipped": "Routing check:       skipped (replacement rolled back)" in out4,
                "summary_issues_exit_3": "finished with issues (exit 3)" in out4,
            }
            self.record(f"{tag}_4_failed_replacement_rolls_back", all(checks4.values()), exit=r4.returncode, state=self._svc_prop("ActiveState"),
                        pid_before=pid_d, pid_after=pid_e, **checks4)
            # --- 5. unrelated unit of the same name is refused, not touched ---
            self._svc("stop", "modelsaar.service")
            self._write_unit("/bin/sleep 300", None)
            self._svc("start", "modelsaar.service")
            time.sleep(1)
            pid_f = self._svc_prop("MainPID")
            r5 = self.sh_pipe(self.install, e_b)
            out5 = r5.stdout + r5.stderr
            self.record(f"{tag}_5_unrelated_service_refused", r5.returncode == 0 and "not this installation; not touched" in out5 and self._svc_prop("MainPID") == pid_f
                        and "Still required:      restart your gateway yourself" in out5 and "starting a temporary gateway" in out5, exit=r5.returncode)
        finally:
            self._svc_cleanup()
            fake.stop()

    def case3_no_ensurepip_bootstrap(self) -> None:
        py = self.a.no_ensurepip_python
        if not py or not shutil.which(py):
            self.record("3_no_ensurepip_bootstraps_pinned_uv", None, why=f"--no-ensurepip-python not given or {py!r} not installed")
            return
        probe = subprocess.run([py, "-m", "venv", str(self.work / "probe-venv")], capture_output=True, text=True)
        if probe.returncode == 0:
            self.record("3_no_ensurepip_bootstraps_pinned_uv", None, why=f"{py} CAN create a venv here (ensurepip present); remove the OS venv package in the test VM to exercise this case")
            return
        self.say(f"[{py} -m venv fails as on Debian/Ubuntu without python3-venv: {(probe.stderr or probe.stdout).strip().splitlines()[-1][:160]}]")
        home = self.mkhome("c3")
        path = self.mkpath("c3", python3=py, fail_shims={"git"})
        fake = self.backend()
        port = free_port()
        try:
            e = self.install_env(home, path, fake, port)
            r = self.sh_pipe(self.install, e)
            out = r.stdout + r.stderr
            rt = home / ".local/share/modelsaar"
            uvbin = rt / "uv/uv"
            checks = {
                "exit_0": r.returncode == 0,
                "explains_missing_venv": "cannot create a usable virtual environment" in out,
                "announces_download": "downloading uv " in out and "/releases/download/" in out and "user-local helper" in out,
                "checksum_verified": "verified: sha256" in out,
                "method_bootstrap": "via bootstrap" in out,
                "uv_binary_present": uvbin.exists() and os.access(uvbin, os.X_OK),
                "uv_not_on_user_path": not (home / ".local/bin/uv").exists(),
                "venv_on_system_python_no_managed_download": os.path.realpath(rt / f"envs/{self.ref}/bin/python") == os.path.realpath(shutil.which(py)) and not (rt / "python").exists(),
                "verification_ok": "verification: OK" in out and "routed: 'auto' -> ollama/" in out,
                "no_git_needed": "git: command not found" not in out,
                "no_user_site_install": not (home / ".local/lib").exists(),
                "os_python_unchanged": self.os_python_unchanged(),
                "launcher_symlink": (home / ".local/bin/modelsaar").is_symlink(),
            }
            self.record("3_no_ensurepip_bootstraps_pinned_uv", all(checks.values()), exit=r.returncode, python=py, **checks)
            # tamper check: a wrong checksum must be refused and nothing installed
            home2 = self.mkhome("c3-tamper")
            tampered = self.work / "install-tampered.sh"
            t = self.install.read_text()
            t2 = re.sub(r"(x86_64-unknown-linux-gnu\)\s+echo )[0-9a-f]{64}", r"\g<1>" + "0" * 64, t)
            t2 = re.sub(r"(aarch64-unknown-linux-gnu\)\s+echo )[0-9a-f]{64}", r"\g<1>" + "0" * 64, t2)
            tampered.write_text(t2)
            tampered.chmod(0o644)
            r2 = self.sh_pipe(tampered, self.install_env(home2, path, fake, free_port()))
            out2 = r2.stdout + r2.stderr
            self.record("3b_checksum_mismatch_refused", r2.returncode == 1 and "checksum mismatch" in out2 and not (home2 / ".local/share/modelsaar/uv/uv").exists()
                        and not list((home2 / ".local/share/modelsaar").rglob("bin/modelsaar")) and not list((home2 / ".local/share/modelsaar/uv").glob("*"))
                        and "Installed revision" not in out2, exit=r2.returncode)
        finally:
            fake.stop()

    def case4_uv_and_pipx(self) -> None:
        # 4a: an existing uv on PATH
        if self.a.uv_binary and Path(self.a.uv_binary).exists():
            home = self.mkhome("c4uv")
            path = self.mkpath("c4uv", python3=self.a.managed_python, extra={"uv": Path(self.a.uv_binary).resolve()})
            fake = self.backend()
            try:
                r = self.sh_pipe(self.install, self.install_env(home, path, fake, free_port()))
                out = r.stdout + r.stderr
                self.record("4a_existing_uv_path", r.returncode == 0 and "via uv" in out and "verification: OK" in out
                            and (home / ".local/share/uv/tools/modelsaar").exists() and not (home / ".local/share/modelsaar").exists(), exit=r.returncode)
            finally:
                fake.stop()
        else:
            self.record("4a_existing_uv_path", None, why="--uv-binary not given")
        # 4b: an existing pipx on PATH
        if shutil.which("pipx"):
            home = self.mkhome("c4pipx")
            path = self.mkpath("c4pipx", python3=self.a.managed_python, keep={"pipx"})
            fake = self.backend()
            try:
                r = self.sh_pipe(self.install, self.install_env(home, path, fake, free_port()))
                out = r.stdout + r.stderr
                self.record("4b_existing_pipx_path", r.returncode == 0 and "via pipx" in out and "verification: OK" in out
                            and (home / ".local/bin/modelsaar").exists() and not (home / ".local/share/modelsaar").exists(), exit=r.returncode)
            finally:
                fake.stop()
        else:
            self.record("4b_existing_pipx_path", None, why="pipx not installed on this machine")

    def case7_archive_vs_git(self) -> None:
        if not self.a.repo or not shutil.which("git"):
            self.record("7_archive_install_matches_git_install", None, why="--repo not given or git absent")
            return
        repo = Path(self.a.repo).resolve()
        if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{self.ref}^{{commit}}"], capture_output=True).returncode != 0:
            self.record("7_archive_install_matches_git_install", None, why=f"{self.ref[:12]} is not present in {repo} (shallow clone?)")
            return
        py = shutil.which(self.a.managed_python) or sys.executable
        envs = {}
        try:
            for name, spec in (("git", f"git+file://{repo}@{self.ref}"), ("archive", f"modelsaar @ {self.source}")):
                v = self.work / f"cmp-{name}"
                subprocess.run([py, "-m", "venv", str(v)], check=True, capture_output=True, text=True)
                r = subprocess.run([str(v / "bin/python"), "-m", "pip", "install", "-q", "--disable-pip-version-check", spec], capture_output=True, text=True, env={**os.environ})
                if r.returncode != 0:
                    self.say("  ! " + (r.stderr or r.stdout).strip()[-600:])
                    raise RuntimeError(f"pip install of {name} source failed")
                site = next((v / "lib").glob("python3.*/site-packages/modelsaar"))
                envs[name] = {str(p.relative_to(site)): sha256_path(p) for p in site.rglob("*.py")}
        except (RuntimeError, subprocess.CalledProcessError, StopIteration) as exc:
            self.record("7_archive_install_matches_git_install", False, error=str(exc))
            return
        same = envs["git"] == envs["archive"]
        self.record("7_archive_install_matches_git_install", same and len(envs["git"]) > 10, files=len(envs["git"]), identical=same)

    # ---- driver ---------------------------------------------------------------------------------
    def main(self) -> int:
        want = set(self.a.cases.split(",")) if self.a.cases else ({"P"} if self.a.public_url else {"1", "2", "3", "4", "5", "7", "S"})
        self.say(f"installer: {self.install}  ref: {self.ref}  source: {self.source}  user: {self.user or os.environ.get('USER')}  "
                 f"platform: {os.uname().sysname} {os.uname().machine}  managed python: {self.a.managed_python} -> {shutil.which(self.a.managed_python)}")
        marker = Path(f"/usr/lib/python{'.'.join(map(str, sys.version_info[:2]))}/EXTERNALLY-MANAGED")
        mp = shutil.which(self.a.managed_python)
        if mp:
            v = subprocess.run([mp, "-c", "import sys,sysconfig; print(sysconfig.get_path('stdlib'))"], capture_output=True, text=True).stdout.strip()
            marker = Path(v) / "EXTERNALLY-MANAGED"
        self.say(f"EXTERNALLY-MANAGED marker for {self.a.managed_python}: {marker} -> {'present' if marker.exists() else 'ABSENT'}")
        try:
            if "1" in want:
                self.case1_old_installer()
            ctx = self.case2_venv_install() if "2" in want else None
            if "5" in want:
                self.case5_repeat_and_failure(ctx)
                self.case5d_upgrade_from_prior_revision()
            elif ctx:
                ctx[2].stop()
            if "3" in want:
                self.case3_no_ensurepip_bootstrap()
            if "4" in want:
                self.case4_uv_and_pipx()
            if "7" in want:
                self.case7_archive_vs_git()
            if "P" in want and self.a.public_url:
                self.case_public_url()
            if "S" in want:
                self.cases_service()
        finally:
            self.say(f"\nOS python packages unchanged: {self.os_python_unchanged()}; EXTERNALLY-MANAGED marker still present: {marker.exists()}")
            (self.out / "results.json").write_text(json.dumps({"platform": f"{os.uname().sysname} {os.uname().machine}", "ref": self.ref,
                                                                 "externally_managed_marker": marker.exists(), "results": self.results}, indent=2) + "\n")
            self.say(f"results: {self.out / 'results.json'}")
            self.log.close()
            if not self.a.keep:
                shutil.rmtree(self.work, ignore_errors=True)
        executed = [r for r in self.results if r["result"] != "NOT EXECUTED"]
        print(json.dumps(self.results, indent=2))
        return 0 if self.ok_all and executed else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--install", default=str(ROOT / "site/static/install.sh"), help="the installer under test (the __PINNED_SHA__ template is fine: --ref is passed as MODELSAAR_REF)")
    ap.add_argument("--old-install", default=None, help="the previous installer, for case 1")
    ap.add_argument("--ref", required=True, help="commit to install (the accepted pin)")
    ap.add_argument("--source", default=None, help="archive path or URL of that commit (default: GitHub's archive of --ref)")
    ap.add_argument("--user", default=None, help="unprivileged user to run the cases as (required when running as root)")
    ap.add_argument("--managed-python", default="python3.12", help="the externally managed interpreter to expose as python3 (default python3.12)")
    ap.add_argument("--no-ensurepip-python", default=None, help="an interpreter whose `-m venv` fails for lack of ensurepip (case 3)")
    ap.add_argument("--uv-binary", default=None, help="a real uv binary to expose for case 4a")
    ap.add_argument("--prior-ref", default=None, help="an earlier commit to install first for the different-revision upgrade case (5d)")
    ap.add_argument("--prior-source", default=None, help="archive path or URL of --prior-ref (default: GitHub's archive)")
    ap.add_argument("--repo", default=None, help="git checkout containing --ref, for case 7")
    ap.add_argument("--cases", default=None, help="comma-separated subset, e.g. 1,2,5 (P = the public URL case)")
    ap.add_argument("--public-url", default=None, help="run the literal `curl -fsSL URL | sh` case against this served installer")
    ap.add_argument("--expect-sha256", default=None, help="sha256 the served script must have (public URL case)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tmpdir", default=None)
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    if not a.source:
        a.source = f"https://github.com/gopalasubramanium/modelsaar/archive/{a.ref}.tar.gz"
    return Harness(a).main()


if __name__ == "__main__":
    sys.exit(main())
