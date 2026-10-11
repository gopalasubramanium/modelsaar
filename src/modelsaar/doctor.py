"""`modelsaar doctor`: practical diagnostics with actionable messages."""

from __future__ import annotations

import asyncio
import os
import socket
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .config import Config, read_keys
from .routing.router import Router


@dataclass
class Finding:
    level: str  # ok | warn | fail
    area: str
    message: str
    remedy: str = ""


@dataclass
class DoctorReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, area: str, message: str, remedy: str = "") -> None:
        self.findings.append(Finding(level, area, message, remedy))

    @property
    def failures(self) -> int:
        return sum(1 for f in self.findings if f.level == "fail")

    def as_dict(self) -> dict[str, Any]:
        return {"findings": [f.__dict__ for f in self.findings], "failures": self.failures}


def _in_container() -> bool:
    return Path("/.dockerenv").exists() or os.environ.get("MODELSAAR_IN_CONTAINER") == "1"


def _port_in_use(host: str, port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


async def run_doctor(cfg: Config | None, cfg_error: str | None, path: Path) -> DoctorReport:
    rep = DoctorReport()
    if cfg is None:
        rep.add("fail", "config", f"cannot load {path}: {cfg_error}", "run `modelsaar init` or fix the YAML")
        return rep
    rep.add("ok", "config", f"loaded {path} (version {cfg.version}, hash {cfg.config_hash})")

    # Keys & file permissions
    for label, p in (("api keys", cfg.resolve(cfg.server.api_keys_file)), ("admin key", cfg.resolve(cfg.server.admin_key_file))):
        if not p.exists() or not read_keys(p):
            rep.add("fail", "auth", f"{label} file missing or empty: {p}", "run `modelsaar keys rotate` or `modelsaar init`")
            continue
        mode = stat.S_IMODE(p.stat().st_mode)
        if mode & 0o077:
            rep.add("warn", "auth", f"{label} file {p} is readable by other users (mode {oct(mode)})", f"chmod 600 {p}")
        else:
            rep.add("ok", "auth", f"{label} present ({p})")

    # Bind / exposure
    if cfg.server.host not in ("127.0.0.1", "localhost", "::1"):
        rep.add(
            "warn",
            "network",
            f"gateway binds to {cfg.server.host} (LAN exposure enabled: allow_lan={cfg.security.allow_lan})",
            "ensure TLS termination or a trusted private tunnel; keys travel in cleartext over plain HTTP",
        )
    else:
        rep.add("ok", "network", f"gateway binds to loopback {cfg.server.host}:{cfg.server.port}")
    if _port_in_use(cfg.server.host if cfg.server.host != "0.0.0.0" else "127.0.0.1", cfg.server.port):
        rep.add(
            "warn",
            "network",
            f"port {cfg.server.port} is already accepting connections (a running gateway or another service)",
            "stop the other service or change server.port",
        )
    if cfg.security.log_prompts:
        rep.add("warn", "privacy", "security.log_prompts is enabled: raw prompts/responses will be logged", "disable unless debugging")
    if cfg.security.locality_mode == "allow_remote":
        rep.add("warn", "privacy", "locality_mode=allow_remote: remote/cloud-forwarded deployments are eligible")

    # Backends
    for b in cfg.backends:
        parts = urlsplit(b.base_url)
        host = parts.hostname or ""
        if _in_container() and host in ("127.0.0.1", "localhost"):
            rep.add(
                "fail",
                f"backend:{b.id}",
                f"base_url {b.base_url} points at the container's own loopback; the host's inference server is not reachable there",
                "use http://host.docker.internal:<port> (macOS/Windows; Linux needs --add-host=host.docker.internal:host-gateway)",
            )
        try:
            async with httpx.AsyncClient(timeout=b.connect_timeout_s, follow_redirects=False) as c:
                probe_path = "/api/version" if b.type == "ollama" else "/models"
                r = await c.get(b.base_url + probe_path, headers=_auth_headers(b))
            if r.status_code == 200:
                rep.add("ok", f"backend:{b.id}", f"{b.type} reachable at {b.base_url}")
            elif r.status_code in (401, 403):
                rep.add("fail", f"backend:{b.id}", f"{b.base_url} rejects the gateway's credentials ({r.status_code})", f"set api_key_env for backend {b.id}")
            else:
                rep.add("warn", f"backend:{b.id}", f"{b.base_url}{probe_path} returned {r.status_code}")
        except httpx.HTTPError as e:
            rep.add(
                "fail",
                f"backend:{b.id}",
                f"cannot reach {b.base_url}: {e.__class__.__name__}",
                "start the inference server (e.g. `ollama serve`) or fix base_url; from Docker use host.docker.internal",
            )

    # Deployments (discovery-level checks)
    try:
        router = Router(cfg, None)
        await router.refresh()
    except Exception as e:
        rep.add("fail", "discovery", f"discovery failed: {e}")
        return rep
    deps = router.registry.all()
    if not deps:
        rep.add("fail", "discovery", "no deployments discovered", "pull a model into your runtime (e.g. `ollama pull <model>`) or declare models in config")
    gen = [d for d in deps if d.role == "generative" and d.healthy and d.enabled]
    local_gen = [d for d in gen if d.locality == "local"]
    if gen and not local_gen and cfg.security.locality_mode == "local_only":
        rep.add(
            "fail",
            "locality",
            "all generative deployments are remote/cloud-forwarded; none is eligible under local_only",
            "pull a local model, or set security.locality_mode: allow_remote deliberately",
        )
    for d in deps:
        if d.locality == "remote" and cfg.security.locality_mode == "local_only":
            rep.add("warn", f"deployment:{d.id}", "cloud/remote alias discovered; excluded under local_only", "")
        if d.role == "generative":
            unknown = [k for k in ("tools", "vision", "json_schema") if d.cap(k) == "unknown"]
            if unknown:
                rep.add(
                    "warn",
                    f"deployment:{d.id}",
                    f"capabilities unknown: {unknown} (requests needing them will not route here)",
                    f"run `modelsaar probe {d.id}` to verify",
                )
            src = d.raw_metadata.get("num_ctx_source", "")
            if src.startswith("assumed"):
                rep.add(
                    "warn",
                    f"deployment:{d.id}",
                    f"served context length is assumed ({d.context_length}); trained max is {d.raw_metadata.get('trained_context_length')}",
                    "set num_ctx in the Modelfile or OLLAMA_CONTEXT_LENGTH, or add a deployments[] override with context_length",
                )
    cl = cfg.routing.classifier
    if cl.enabled:
        cd = router.registry.get(f"{cl.backend}/{cl.model}")
        if not cd:
            rep.add("fail", "classifier", f"configured classifier {cl.backend}/{cl.model} not discovered", "fix routing.classifier or disable it")
        elif cd.locality != "local" and cfg.security.locality_mode == "local_only":
            rep.add("fail", "classifier", "classifier deployment is remote under local_only", "choose a local classifier model")
        else:
            rep.add("ok", "classifier", f"classifier {cd.id} available")
    else:
        rep.add("ok", "classifier", "optional classifier disabled (deterministic routing only)")
    for a, _ in cfg.aliases.items():
        if router.alias_contract(a) is None:
            rep.add("warn", f"alias:{a}", "not advertised: no usable deployment satisfies this alias", "")
        else:
            rep.add("ok", f"alias:{a}", f"advertised with {len(router.alias_contract(a)['deployments'])} deployment(s)")
    await router.aclose()
    return rep


def _auth_headers(b) -> dict[str, str]:  # type: ignore[no-untyped-def]
    key = b.api_key or (os.environ.get(b.api_key_env) if b.api_key_env else None)
    return {"Authorization": f"Bearer {key}"} if key else {}


def run_doctor_sync(cfg: Config | None, cfg_error: str | None, path: Path) -> DoctorReport:
    return asyncio.run(run_doctor(cfg, cfg_error, path))
