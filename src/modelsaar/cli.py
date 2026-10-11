"""`modelsaar` command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .config import (
    BackendConfig,
    Config,
    ResourcePool,
    config_to_yaml,
    default_config_path,
    generate_key,
    load_config,
    read_keys,
    write_config_atomic,
    write_key_file,
)


def _out(obj: Any, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, default=str))
    else:
        print(obj if isinstance(obj, str) else json.dumps(obj, indent=2, default=str))


def _load(args: argparse.Namespace) -> Config:
    path = Path(args.config) if getattr(args, "config", None) else default_config_path()
    try:
        return load_config(path)
    except FileNotFoundError:
        sys.exit(f"config not found at {path}; run `modelsaar init` first (or pass --config)")
    except Exception as e:
        sys.exit(f"invalid config {path}: {e}")


def _router_with_evidence(cfg: Config):  # type: ignore[no-untyped-def]
    """Router that sees stored probe/measurement evidence when a state DB exists (never creates one)."""
    from .routing.router import Router
    from .store import Store

    db = cfg.resolve(cfg.server.state_db)
    return Router(cfg, Store(db) if db.exists() else None)


def _admin_client(cfg: Config) -> httpx.Client:
    keys = read_keys(cfg.resolve(cfg.server.admin_key_file))
    if not keys:
        sys.exit("admin key file missing; run `modelsaar keys rotate --admin`")
    return httpx.Client(base_url=f"http://{cfg.server.host}:{cfg.server.port}", headers={"Authorization": f"Bearer {keys[0]}"}, timeout=30)


def _api_client(cfg: Config) -> httpx.Client:
    keys = read_keys(cfg.resolve(cfg.server.api_keys_file))
    if not keys:
        sys.exit("api key file missing; run `modelsaar keys rotate`")
    return httpx.Client(base_url=f"http://{cfg.server.host}:{cfg.server.port}", headers={"Authorization": f"Bearer {keys[0]}"}, timeout=120)


# --------------------------------------------------------------------------- #
def cmd_init(args: argparse.Namespace) -> None:
    path = Path(args.config) if args.config else default_config_path()
    if path.exists() and not args.force:
        sys.exit(f"{path} already exists; use --force to overwrite (keys and state are preserved)")
    endpoint = args.endpoint
    btype = args.type
    if not endpoint:
        # Probe documented loopback defaults only (never scans networks).
        candidates = [("http://127.0.0.1:11434", "ollama"), ("http://127.0.0.1:1234/v1", "openai_compatible"), ("http://127.0.0.1:8080/v1", "openai_compatible"), ("http://127.0.0.1:8000/v1", "openai_compatible")]
        for url, t in candidates:
            try:
                r = httpx.get(url + ("/api/version" if t == "ollama" else "/models"), timeout=1.5)
                if r.status_code == 200:
                    endpoint, btype = url, t
                    print(f"discovered {t} at {url}")
                    break
            except httpx.HTTPError:
                continue
        if not endpoint:
            sys.exit("no inference endpoint found on documented loopback defaults; pass --endpoint URL --type ollama|openai_compatible")
    cfg = Config(
        resource_pools=(ResourcePool(id="local-machine", kind="unified", max_concurrent=args.max_concurrent),),
        backends=(BackendConfig(id=args.backend_id, type=btype, base_url=endpoint, resource_pool="local-machine"),),
    )
    cfg = cfg.model_copy(update={"server": cfg.server.model_copy(update={"port": args.port})})
    cfg = cfg.model_copy(update={"routing": cfg.routing.model_copy(update={"default_profile": args.profile})})
    cfg = cfg.model_copy(update={"config_path": str(path)})
    write_config_atomic(cfg, path)
    api_p, adm_p = cfg.resolve(cfg.server.api_keys_file), cfg.resolve(cfg.server.admin_key_file)
    if not read_keys(api_p):
        write_key_file(api_p, [generate_key("msk")])
    if not read_keys(adm_p):
        write_key_file(adm_p, [generate_key("msa")])
    print(f"wrote {path}")
    print(f"API key:   {api_p}")
    print(f"admin key: {adm_p}")
    # One-shot discovery so the user sees what will be routable.
    cfg = load_config(path)

    async def _disc() -> list[dict[str, Any]]:
        r = _router_with_evidence(cfg)
        await r.refresh()
        out = r.registry.snapshot()
        err = r.last_refresh_error
        await r.aclose()
        if err:
            print(f"warning: discovery error: {err}")
        return out

    deps = asyncio.run(_disc())
    print(f"discovered {len(deps)} deployment(s):")
    for d in deps:
        print(f"  {d['id']:40s} role={d['role']:10s} ctx={d['context_length']} tools={d['capabilities']['tools']['value']} vision={d['capabilities']['vision']['value']} locality={d['locality']}")
    print("\nnext steps:")
    print("  modelsaar doctor            # check reachability, context assumptions, unknown capabilities")
    print("  modelsaar probe --all       # verify tools/json/vision/streaming on each model (uses local compute)")
    print("  modelsaar serve             # start the gateway")
    print("  modelsaar client-config open-webui|openclaw|opencode|opencode-v2|hermes")


def cmd_discover(args: argparse.Namespace) -> None:
    cfg = _load(args)

    async def _run() -> dict[str, Any]:
        r = _router_with_evidence(cfg)
        await r.refresh()
        out = {"error": r.last_refresh_error, "deployments": r.registry.snapshot(), "aliases": {a: r.alias_contract(a) for a in cfg.aliases}}
        await r.aclose()
        return out

    res = asyncio.run(_run())
    if args.json:
        _out(res, True)
        return
    if res["error"]:
        print(f"error: {res['error']}")
    for d in res["deployments"]:
        st = d["state"]
        print(
            f"{d['id']:40s} {d['role']:10s} ctx={d['context_length']!s:7s} "
            f"tools={d['capabilities']['tools']['value']:11s} vision={d['capabilities']['vision']['value']:11s} "
            f"json_schema={d['capabilities']['json_schema']['value']:11s} loaded={st['loaded']} healthy={st['healthy']} locality={d['locality']}"
        )
    print("aliases:")
    for a, c in res["aliases"].items():
        print(f"  {a:14s} " + (f"-> {c['deployments']} ctx>={c['context_length_min']} tools={c['tools']} vision={c['vision']}" if c else "(not advertised: no usable deployment)"))


def cmd_probe(args: argparse.Namespace) -> None:
    cfg = _load(args)
    from .probes import run_probes
    from .routing.router import Router
    from .store import Store

    async def _run() -> list[dict[str, Any]]:
        store = Store(cfg.resolve(cfg.server.state_db))
        r = Router(cfg, store)
        await r.refresh()
        targets = [d for d in r.registry.all() if d.role == "generative" and d.healthy and (args.all or d.id in args.deployment)]
        if cfg.security.locality_mode == "local_only":
            targets = [d for d in targets if d.locality == "local"]
        if not targets:
            print("no matching generative deployments (check `modelsaar discover`)")
        reports = []
        for d in targets:
            print(f"probing {d.id} (fingerprint {d.fingerprint}) ...")
            rep = await run_probes(r.adapters[d.backend_id], d, store, args.which or None, timeout=args.timeout)
            for res in rep.results:
                print(f"  {res.capability:16s} {res.value:12s} {res.latency_ms:7.0f}ms  {res.note}")
            for m in rep.measurements:
                print(f"  latency           p50={m.p50_ms and round(m.p50_ms)}ms ttft={m.ttft_ms and round(m.ttft_ms)}ms load~{m.load_ms and round(m.load_ms)}ms (samples={m.samples})")
            reports.append(rep.as_dict())
        await r.aclose()
        store.close()
        return reports

    reps = asyncio.run(_run())
    if args.json:
        _out(reps, True)


def cmd_serve(args: argparse.Namespace) -> None:
    cfg = _load(args)
    import uvicorn

    from .runtime import build, configure_logging

    configure_logging(cfg.observability.log_level)
    app, router, auth, store = build(cfg)
    if not auth.configured:
        sys.exit("API/admin key files are missing; run `modelsaar keys rotate` (or `modelsaar init`)")
    url = f"http://{cfg.server.host}:{cfg.server.port}"
    print(f"ModelSaar {__version__} on {url}/v1  (config {cfg.config_path}, hash {cfg.config_hash})")
    print(f"API key file:   {cfg.resolve(cfg.server.api_keys_file)}")
    print(f"admin key file: {cfg.resolve(cfg.server.admin_key_file)}")
    print(f"status page:    {url}/admin/ui   (enter the admin key)")
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level="warning")


def cmd_status(args: argparse.Namespace) -> None:
    cfg = _load(args)
    try:
        with _admin_client(cfg) as c:
            s = c.get("/admin/status").json()
    except httpx.HTTPError as e:
        sys.exit(f"gateway not reachable at {cfg.server.host}:{cfg.server.port}: {e}")
    if args.json:
        _out(s, True)
        return
    print(f"ModelSaar {s['version']} up {s['uptime_s']}s  requests={s['requests_total']} failed={s['requests_failed']} ready={s['ready']}")
    if s.get("last_refresh_error"):
        print(f"refresh error: {s['last_refresh_error']}")
    print("aliases:")
    for a, c in s["aliases"].items():
        print(f"  {a:14s} " + (f"{c['deployments']} ctx>={c['context_length_min']} tools={c['tools']} vision={c['vision']}" if c else "(not advertised)"))
    print("deployments:")
    for d in s["deployments"]:
        st = d["state"]
        print(f"  {d['id']:40s} {d['role']:10s} healthy={st['healthy']} loaded={st['loaded']} ctx={d['context_length']} tools={d['capabilities']['tools']['value']}")
    print(f"admission: {s['admission']}")


def cmd_doctor(args: argparse.Namespace) -> None:
    path = Path(args.config) if args.config else default_config_path()
    cfg: Config | None = None
    err: str | None = None
    try:
        cfg = load_config(path)
    except Exception as e:
        err = str(e)
    from .doctor import run_doctor_sync

    rep = run_doctor_sync(cfg, err, path)
    if args.json:
        _out(rep.as_dict(), True)
    else:
        for f in rep.findings:
            mark = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}[f.level]
            print(f"[{mark}] {f.area}: {f.message}" + (f"\n       -> {f.remedy}" if f.remedy else ""))
        print(f"\n{rep.failures} failure(s)")
    sys.exit(1 if rep.failures else 0)


def _explain_body(args: argparse.Namespace) -> dict[str, Any]:
    if args.file:
        return json.loads(Path(args.file).read_text(encoding="utf-8"))
    body: dict[str, Any] = {"model": args.model, "messages": [{"role": "user", "content": args.message or "Hello"}]}
    if args.tools:
        body["tools"] = [{"type": "function", "function": {"name": "bash", "description": "Run a shell command", "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}}]
    if args.image:
        body["messages"][0]["content"] = [{"type": "text", "text": args.message or "Describe"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    if args.json_schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "x", "schema": {"type": "object"}}}
    return body


def cmd_explain(args: argparse.Namespace) -> None:
    cfg = _load(args)
    body = _explain_body(args)
    if args.live:
        with _admin_client(cfg) as c:
            dec = c.post("/admin/explain", json=body).json()
    else:
        from .routing.router import NoEligibleDeployment, Router
        from .store import Store

        async def _run() -> dict[str, Any]:
            store = Store(cfg.resolve(cfg.server.state_db))
            r = Router(cfg, store)
            await r.refresh()
            try:
                d = await r.route_chat(body, {}, "explain")
                d.outcome = "explain_only"
                res = d.as_dict()
            except NoEligibleDeployment as e:
                res = e.decision.as_dict()
            await r.aclose()
            store.close()
            return res

        dec = asyncio.run(_run())
    if args.json:
        _out(dec, True)
        return
    print(f"request {dec['request_id']}: {dec['requested_model']} -> {dec.get('chosen') or 'NO ELIGIBLE DEPLOYMENT'}  (profile {dec['profile']}, {dec['overhead_ms']} ms)")
    req = dec.get("requirements", {})
    print(f"task: {req.get('primary_task')} {req.get('tasks')} ambiguous={req.get('ambiguous')}  tokens~{(req.get('tokens') or {}).get('total')}")
    for r in dec.get("reasons", []):
        print(f"  - {r}")
    if dec.get("classifier"):
        print(f"classifier: {dec['classifier']}")
    if dec.get("candidates"):
        print("candidates:")
        for c in dec["candidates"]:
            print(f"  {c['deployment']:40s} score={c['score']:+.3f} quality={c['quality']:.2f}±{c['uncertainty']:.2f} [{c['evidence']}] latency={c['latency_cost']:.2f} residency={c['residency_cost']:.2f} {c['notes']}")
    if dec.get("exclusions"):
        print("excluded:")
        for d, why in dec["exclusions"].items():
            print(f"  {d}: {'; '.join(why)}")
    if dec.get("remedies"):
        print("remedies: " + " | ".join(dec["remedies"]))


def cmd_decisions(args: argparse.Namespace) -> None:
    cfg = _load(args)
    with _admin_client(cfg) as c:
        if args.request_id:
            _out(c.get(f"/admin/decisions/{args.request_id}").json(), True)
        else:
            for d in c.get(f"/admin/decisions?limit={args.limit}").json()["decisions"]:
                print(f"{d['request_id']} {d['requested_model']:14s} -> {d.get('chosen')!s:40s} {d.get('outcome'):14s} {d['overhead_ms']:6.1f}ms {(d.get('requirements') or {}).get('primary_task')}")


def cmd_test(args: argparse.Namespace) -> None:
    cfg = _load(args)
    with _api_client(cfg) as c:
        r = c.get("/v1/models")
        print(f"GET /v1/models -> {r.status_code}: {[m['id'] for m in r.json().get('data', [])]}")
        body = {"model": args.model, "messages": [{"role": "user", "content": args.message}], "max_tokens": 64}
        t0 = time.monotonic()
        r = c.post("/v1/chat/completions", json=body)
        ms = (time.monotonic() - t0) * 1000
        print(f"POST /v1/chat/completions -> {r.status_code} in {ms:.0f}ms; deployment={r.headers.get('x-modelsaar-deployment')} request={r.headers.get('x-modelsaar-request-id')}")
        if r.status_code == 200:
            print("content:", (r.json()["choices"][0]["message"].get("content") or "")[:300])
        else:
            _out(r.json(), True)
            sys.exit(1)


def cmd_client_config(args: argparse.Namespace) -> None:
    cfg = _load(args)
    from .clientconfig import CLIENTS, AliasInfo, ClientTarget, apply_patch, render

    aliases: list[AliasInfo] = []
    try:
        with _admin_client(cfg) as c:
            s = c.get("/admin/status").json()
        for a, con in s["aliases"].items():
            if con:
                aliases.append(AliasInfo(a, con["context_length_min"] or 4096, con["tools"] == "supported", con["vision"] == "supported", con.get("description", "")))
    except Exception:

        async def _run() -> list[AliasInfo]:
            r = _router_with_evidence(cfg)
            await r.refresh()
            out = []
            for a in cfg.aliases:
                con = r.alias_contract(a)
                if con:
                    out.append(AliasInfo(a, con["context_length_min"] or 4096, con["tools"] == "supported", con["vision"] == "supported", con.get("description", "")))
            await r.aclose()
            return out

        aliases = asyncio.run(_run())
    if not aliases:
        print("warning: no alias currently has a usable deployment; generating config with `auto` placeholders")
    t = ClientTarget(gateway_url=f"http://{cfg.server.host}:{cfg.server.port}", aliases=aliases or None, in_docker=args.docker)
    if args.client not in CLIENTS:
        sys.exit(f"unknown client; choose one of {CLIENTS}")
    print(render(args.client, t))
    if args.apply or args.dry_run:
        try:
            res = apply_patch(args.client, t, Path(args.path) if args.path else None, dry_run=not args.apply)
        except ValueError as e:
            sys.exit(str(e))
        if not res["changed"]:
            print(f"{res['path']}: already up to date (idempotent)")
        elif res["applied"]:
            print(f"applied to {res['path']}" + (f" (backup: {res['backup']})" if res["backup"] else " (new file)"))
        else:
            print(f"--- proposed content for {res['path']} (not written; add --apply) ---\n{res['after']}")


def cmd_keys(args: argparse.Namespace) -> None:
    cfg = _load(args)
    api_p, adm_p = cfg.resolve(cfg.server.api_keys_file), cfg.resolve(cfg.server.admin_key_file)
    if args.keys_cmd == "show":
        print(f"API keys ({api_p}): {len(read_keys(api_p))} key(s)")
        print(f"admin keys ({adm_p}): {len(read_keys(adm_p))} key(s)")
        if args.reveal:
            print("api:", *read_keys(api_p))
            print("admin:", *read_keys(adm_p))
    elif args.keys_cmd == "rotate":
        if args.admin:
            write_key_file(adm_p, [generate_key("msa")])
            print(f"rotated admin key -> {adm_p}")
        else:
            write_key_file(api_p, [generate_key("msk")])
            print(f"rotated API key -> {api_p} (restart the gateway and update clients)")


def cmd_config(args: argparse.Namespace) -> None:
    path = Path(args.config) if args.config else default_config_path()
    if args.config_cmd == "validate":
        cfg = load_config(path)
        print(f"ok: {path} (version {cfg.version}, {len(cfg.backends)} backend(s))")
    elif args.config_cmd == "show":
        print(config_to_yaml(load_config(path)))
    elif args.config_cmd == "example":
        from .config import example_config

        print(config_to_yaml(example_config()))
    elif args.config_cmd == "migrate":
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        v = int(raw.get("version", 0))
        from . import CONFIG_VERSION

        if v == CONFIG_VERSION:
            print("config already at the current version; nothing to do")
            return
        sys.exit(f"no migration path from version {v} to {CONFIG_VERSION} in this build")


def cmd_eval(args: argparse.Namespace) -> None:
    from .evaluation.harness import run_eval_cli

    run_eval_cli(args)


def cmd_demo(args: argparse.Namespace) -> None:
    """Start a SIMULATED backend plus a gateway so the UX can be tried without models."""
    import tempfile

    from .runtime import GatewayThread, free_port
    from .testing.fakebackend import FakeBackend, FakeModel

    fake = FakeBackend(
        [
            FakeModel("sim-small:1b", ["completion", "tools"], 8192, parameter_size="1.0B", loaded=True, good_at=["conversation", "summarization"]),
            FakeModel("sim-large:27b", ["completion", "tools", "vision", "thinking"], 32768, parameter_size="27B", size_bytes=18_000_000_000, good_at=["coding", "math", "agent", "extraction", "document_vision"]),
            FakeModel("sim-embed:0.6b", ["embedding"], 2048, parameter_size="0.6B"),
        ]
    )
    burl = fake.start()
    tmp = Path(tempfile.mkdtemp(prefix="modelsaar-demo-"))
    api_key, admin_key = generate_key("msk"), generate_key("msa")
    write_key_file(tmp / "keys/api_keys", [api_key])
    write_key_file(tmp / "keys/admin_key", [admin_key])
    cfg = Config(
        resource_pools=(ResourcePool(id="sim", max_concurrent=2),),
        backends=(BackendConfig(id="sim", type="ollama", base_url=burl, resource_pool="sim"),),
    )
    cfg = cfg.model_copy(update={"server": cfg.server.model_copy(update={"port": args.port or free_port()}), "config_path": str(tmp / "config.yaml"), "config_hash": "demo"})
    write_config_atomic(cfg, tmp / "config.yaml")
    gw = GatewayThread(cfg)
    url = gw.start()
    print("*** SIMULATED DEMO: the 'models' are fake backends that echo structure; no real inference happens. ***")
    print(f"gateway:   {url}/v1     config: {tmp / 'config.yaml'}")
    print(f"API key:   {api_key}")
    print(f"admin key: {admin_key}")
    print(f"status UI: {url}/admin/ui")
    print(f"try:  curl -s {url}/v1/chat/completions -H 'Authorization: Bearer {api_key}' -H 'Content-Type: application/json' -d '{{\"model\":\"auto\",\"messages\":[{{\"role\":\"user\",\"content\":\"Write a Python function\"}}]}}'")
    print(f"      MODELSAAR_CONFIG={tmp / 'config.yaml'} modelsaar explain --message 'refactor this python code' --tools")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        gw.stop()
        fake.stop()


def cmd_uninstall(args: argparse.Namespace) -> None:
    path = Path(args.config) if args.config else default_config_path()
    home = path.parent
    print("ModelSaar uninstall removes ONLY the gateway's own files:")
    print(f"  {home}  (config.yaml, keys/, state/)")
    print("It does NOT remove models from your inference runtime, nor any client configuration.")
    print("Client configs changed with `client-config --apply` have .bak-<timestamp> backups next to them.")
    print("Afterwards remove the package with: pip uninstall modelsaar   (or `uv tool uninstall modelsaar`)")
    if not args.yes:
        ans = input(f"delete {home}? [y/N] ").strip().lower()
        if ans != "y":
            print("aborted")
            return
    if not home.exists():
        print(f"{home} does not exist; nothing to remove")
        return
    known = {"config.yaml", "config.yaml.tmp", "keys", "state"}
    known |= {n for n in os.listdir(home) if n.startswith("config.yaml.bak")}
    others = sorted(set(os.listdir(home)) - known)
    if others:
        sys.exit(
            f"{home} contains files ModelSaar did not create: {others}. Refusing to delete the directory; "
            "remove config.yaml, keys/ and state/ manually if you want them gone."
        )
    for name in sorted(set(os.listdir(home))):
        target = home / name
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        print(f"removed {target}")
    try:
        home.rmdir()
        print(f"removed {home}")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="modelsaar", description="ModelSaar - intelligent routing for local AI models")
    p.add_argument("--config", help="path to config.yaml (default: $MODELSAAR_CONFIG or ~/.modelsaar/config.yaml)")
    p.add_argument("--version", action="version", version=f"modelsaar {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create config + keys, discover an endpoint")
    s.add_argument("--endpoint", help="backend base URL (e.g. http://127.0.0.1:11434)")
    s.add_argument("--type", choices=["ollama", "openai_compatible"], default="ollama")
    s.add_argument("--backend-id", default="ollama")
    s.add_argument("--port", type=int, default=8484)
    s.add_argument("--profile", choices=["quality", "balanced", "fast"], default="quality")
    s.add_argument("--max-concurrent", type=int, default=1, help="concurrent inferences on the local machine pool")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("discover", help="discover deployments and show states/capabilities")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_discover)

    s = sub.add_parser("probe", help="verify capabilities with live probes (uses local compute)")
    s.add_argument("deployment", nargs="*", help="deployment id(s)")
    s.add_argument("--all", action="store_true")
    s.add_argument("--which", nargs="*", choices=["streaming", "tools", "parallel_tools", "json_object", "json_schema", "vision", "latency"])
    s.add_argument("--timeout", type=float, default=120.0)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_probe)

    s = sub.add_parser("serve", help="start the gateway")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("status", help="status of a running gateway")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("doctor", help="diagnose configuration, backends, context and capability issues")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("explain", help="dry-run routing for a request and show the decision")
    s.add_argument("--model", default="auto")
    s.add_argument("--message", "-m")
    s.add_argument("--file", help="JSON file with a full chat completions body")
    s.add_argument("--tools", action="store_true", help="add a sample agent tool")
    s.add_argument("--image", action="store_true", help="add a sample image part")
    s.add_argument("--json-schema", action="store_true", help="request strict JSON schema output")
    s.add_argument("--live", action="store_true", help="ask the running gateway instead of routing offline")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_explain)

    s = sub.add_parser("decisions", help="recent decisions from a running gateway")
    s.add_argument("request_id", nargs="?")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(fn=cmd_decisions)

    s = sub.add_parser("test", help="send a test request through a running gateway")
    s.add_argument("--model", default="auto")
    s.add_argument("--message", default="Reply with one word: ready")
    s.set_defaults(fn=cmd_test)

    s = sub.add_parser("client-config", help="generate (and optionally apply) client configuration")
    s.add_argument("client", choices=["open-webui", "openclaw", "opencode", "opencode-v2", "hermes"])
    s.add_argument("--docker", action="store_true", help="client runs in a container (use host.docker.internal)")
    s.add_argument("--path", help="config file to merge into (default: the client's documented location)")
    s.add_argument("--dry-run", action="store_true", help="show the merged file without writing")
    s.add_argument("--apply", action="store_true", help="write the merged file (backup created)")
    s.set_defaults(fn=cmd_client_config)

    s = sub.add_parser("keys", help="show or rotate keys")
    ks = s.add_subparsers(dest="keys_cmd", required=True)
    k = ks.add_parser("show")
    k.add_argument("--reveal", action="store_true")
    k = ks.add_parser("rotate")
    k.add_argument("--admin", action="store_true")
    s.set_defaults(fn=cmd_keys)

    s = sub.add_parser("config", help="validate/show/migrate the config")
    cs = s.add_subparsers(dest="config_cmd", required=True)
    for name in ("validate", "show", "example", "migrate"):
        cs.add_parser(name)
    s.set_defaults(fn=cmd_config)

    s = sub.add_parser("eval", help="run the evaluation harness")
    s.add_argument("--mode", choices=["simulated", "live"], default="simulated")
    s.add_argument("--tasks", help="JSONL task file (default: built-in synthetic fixtures)")
    s.add_argument("--out", help="write the JSON report here")
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--save-measurements", action="store_true", help="live mode: store per-deployment quality/latency evidence for routing")
    s.add_argument("--probe", action="store_true", help="live mode: run capability probes on every deployment first")
    s.add_argument("--deployments", nargs="*", help="live mode: restrict the sweep, baselines and the `auto` alias to these deployment ids")
    s.set_defaults(fn=cmd_eval)

    s = sub.add_parser("demo", help="start a SIMULATED backend + gateway to try the UX without models")
    s.add_argument("--port", type=int, default=0)
    s.set_defaults(fn=cmd_demo)

    s = sub.add_parser("uninstall", help="remove ModelSaar's own files (never models or client configs)")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_uninstall)
    return p


def main(argv: list[str] | None = None) -> None:
    p = build_parser()
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    main()
