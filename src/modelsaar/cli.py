"""`modelsaar` command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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
    # The `auto` alias carries its own profile; the advertised default must be what `auto` does.
    aliases = dict(cfg.aliases)
    aliases["auto"] = aliases["auto"].model_copy(update={"profile": args.profile})
    cfg = cfg.model_copy(update={"aliases": aliases, "config_path": str(path)})
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


def _gateway_listening(cfg: Config) -> str | None:
    """'gateway' when a ModelSaar gateway answers /healthz on the configured address, 'other' when
    something else holds the port, None when the port is free."""
    url = f"http://{cfg.server.host}:{cfg.server.port}"
    try:
        r = httpx.get(f"{url}/healthz", timeout=2.0)
    except httpx.ConnectError:
        return None
    except httpx.HTTPError:
        return "other"
    try:
        return "gateway" if r.status_code == 200 and r.json().get("status") == "ok" and "version" in r.json() else "other"
    except ValueError:
        return "other"


def _print_probe_report(rep: dict[str, Any]) -> None:
    for res in rep.get("results", []):
        print(f"  {res['capability']:16s} {res['value']:12s} {res['latency_ms']:7.0f}ms  {res.get('note', '')}")
    for m in rep.get("measurements", []):
        p50, ttft, load = m.get("p50_ms"), m.get("ttft_ms"), m.get("load_ms")
        print(f"  latency           p50={p50 and round(p50)}ms ttft={ttft and round(ttft)}ms load~{load and round(load)}ms (samples={m.get('samples')})")
    for e in rep.get("errors", []):
        print(f"  error: {e}")
    if rep.get("skipped"):
        print(f"  not run (uncertain timeout): {', '.join(rep['skipped'])}")


def cmd_probe(args: argparse.Namespace) -> None:
    """Probes use inference. While a gateway is running they go through POST /admin/probe so the
    gateway's admission (slots, queue, memory budget) coordinates them with live traffic. Direct
    (offline) probing is only allowed when no gateway listens on the configured port, or with
    --allow-concurrent (the operator accepts uncoordinated concurrent inference)."""
    cfg = _load(args)
    listening = _gateway_listening(cfg)
    if listening == "gateway" and not args.offline:
        _probe_via_gateway(cfg, args)
        return
    if listening is not None and not args.allow_concurrent:
        what = "a ModelSaar gateway" if listening == "gateway" else "another process"
        sys.exit(
            f"{what} is listening on {cfg.server.host}:{cfg.server.port}; direct probing would run inference "
            "outside the gateway's admission control. Drop --offline to probe through the gateway, stop it, "
            "or pass --allow-concurrent to accept uncoordinated concurrent inference."
        )
    if listening is None:
        print(f"no gateway at {cfg.server.host}:{cfg.server.port}; probing directly (offline, uncoordinated with any other inference)")
    _probe_offline(cfg, args)


def _probe_via_gateway(cfg: Config, args: argparse.Namespace) -> None:
    reports: list[dict[str, Any]] = []
    with _admin_client(cfg) as c:
        c.timeout = httpx.Timeout(args.timeout * 8 + 60)
        status = c.get("/admin/status")
        if status.status_code != 200:
            sys.exit(f"gateway at {c.base_url} refused the admin key ({status.status_code}); check {cfg.server.admin_key_file}")
        deps = status.json().get("deployments", [])
        targets = [
            d["id"]
            for d in deps
            if d.get("role") == "generative" and (d.get("state") or {}).get("healthy") and (args.all or d["id"] in args.deployment)
        ]
        if cfg.security.locality_mode == "local_only":
            targets = [d["id"] for d in deps if d["id"] in targets and d.get("locality") == "local"]
        if not targets:
            print("no matching generative deployments (check `modelsaar discover`)")
        for dep_id in targets:
            print(f"probing {dep_id} via gateway {c.base_url} (admission-coordinated) ...")
            r = c.post("/admin/probe", json={"deployment": dep_id, "which": args.which or None, "timeout": args.timeout})
            if r.status_code != 200:
                print(f"  refused ({r.status_code}): {r.json().get('error', {}).get('message', r.text[:200])}")
                continue
            rep = r.json()
            _print_probe_report(rep)
            reports.append(rep)
    if args.json:
        _out(reports, True)


def _probe_offline(cfg: Config, args: argparse.Namespace) -> None:
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
            # The offline path still respects this process's own admission (pool memory budget, slots).
            reservation = await r.admission.acquire(d, timeout=None)
            try:
                rep = await run_probes(r.adapters[d.backend_id], d, store, args.which or None, timeout=args.timeout)
            except BaseException:
                await reservation.release()
                raise
            if rep.uncertain:
                # The backend may still be computing: in this offline process the hold only delays the
                # next deployment's probes; the gateway-coordinated path holds the real slot.
                await reservation.mark_uncertain()
                await asyncio.sleep(min(r.admission.cfg.uncertain_hold_s, 5.0))
            else:
                await reservation.release()
            _print_probe_report(rep.as_dict())
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
        sys.exit("API/admin key files are missing; run `modelsaar keys ensure` (or `modelsaar init`)")
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


HEALTH_SERVICE = "modelsaar"


def gateway_identity(base_url: str, timeout: float = 5.0) -> tuple[str, dict[str, Any] | None]:
    """Identify what listens at ``base_url`` WITHOUT sending a key: ``("modelsaar", health)`` when
    GET /healthz returns the ModelSaar health contract (JSON with service=modelsaar); ``("none",
    None)`` when nothing accepts connections; ``("other", None)`` for any other listener (a plain
    200 is not enough — an unrelated service must be treated as a port collision)."""
    try:
        r = httpx.get(base_url.rstrip("/") + "/healthz", timeout=timeout, headers={"Accept": "application/json"})
    except httpx.ConnectError:
        return "none", None
    except httpx.HTTPError:
        return "other", None
    try:
        body = r.json()
    except ValueError:
        return "other", None
    if r.status_code == 200 and isinstance(body, dict) and body.get("service") == HEALTH_SERVICE:
        return "modelsaar", body
    return "other", None


def cmd_test(args: argparse.Namespace) -> None:
    cfg = _load(args)
    base = f"http://{cfg.server.host}:{cfg.server.port}"
    kind, health = gateway_identity(base)
    if kind == "none":
        sys.exit(
            f"no gateway is listening at {base} — start it with `modelsaar serve` "
            "(in another terminal, or under launchd/systemd; see examples/) and run `modelsaar test` again"
        )
    if kind == "other":
        sys.exit(
            f"something that is not a ModelSaar gateway is listening at {base} (GET /healthz did not return the "
            "ModelSaar health contract). No key was sent. Port collision: stop that service or set server.port to "
            "a free port in the config and restart `modelsaar serve`."
        )
    print(f"GET /healthz -> modelsaar {health.get('version', '?')}")
    with _api_client(cfg) as c:
        r = c.get("/v1/models")
        if r.status_code == 401:
            sys.exit(f"the gateway at {base} rejected the API key from {cfg.resolve(cfg.server.api_keys_file)}; restart the gateway after `modelsaar keys rotate`")
        print(f"GET /v1/models -> {r.status_code}: {[m['id'] for m in r.json().get('data', [])]}")
        body = {"model": args.model, "messages": [{"role": "user", "content": args.message}], "max_tokens": 64}
        t0 = time.monotonic()
        r = c.post("/v1/chat/completions", json=body)
        ms = (time.monotonic() - t0) * 1000
        dep, rid = r.headers.get("x-modelsaar-deployment"), r.headers.get("x-modelsaar-request-id")
        print(f"POST /v1/chat/completions -> {r.status_code} in {ms:.0f}ms; deployment={dep} request={rid}")
        if r.status_code != 200:
            _out(r.json(), True)
            sys.exit(1)
        if not rid or not dep:
            # A 200 without ModelSaar attribution did not come from this gateway's router.
            sys.exit("the response carries no ModelSaar routing attribution (X-ModelSaar-Request-Id / X-ModelSaar-Deployment); this is not a ModelSaar-routed completion")
        try:
            content = r.json()["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError, ValueError):
            sys.exit("the response is not a chat completion envelope")
        print(f"routed: {args.model!r} -> {dep} (request {rid})")
        print("content:", content[:300])


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
    elif args.keys_cmd == "ensure":
        # Idempotent first-run bootstrap: create missing key files, never rotate existing ones,
        # touch nothing but the key files (the config may be a read-only mount).
        for label, p, prefix in (("API key", api_p, "msk"), ("admin key", adm_p, "msa")):
            if read_keys(p):
                print(f"{label}: unchanged ({p})")
            else:
                write_key_file(p, [generate_key(prefix)])
                print(f"{label}: created ({p})")
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


def _owned_files(home: Path, cfg: Config | None) -> tuple[list[Path], list[Path]]:
    """Files ModelSaar creates under its home, and the directories it creates for them."""
    api = cfg.resolve(cfg.server.api_keys_file) if cfg else home / "keys/api_keys"
    adm = cfg.resolve(cfg.server.admin_key_file) if cfg else home / "keys/admin_key"
    db = cfg.resolve(cfg.server.state_db) if cfg else home / "state/modelsaar.db"
    files = [home / "config.yaml", home / "config.yaml.tmp", api, api.with_name(api.name + ".tmp"), adm, adm.with_name(adm.name + ".tmp")]
    files += [db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm"), db.with_name(db.name + ".tmp")]
    files += sorted(home.glob("config.yaml.bak*")) if home.exists() else []
    dirs = sorted({api.parent, adm.parent, db.parent} - {home}, key=lambda d: len(d.parts), reverse=True)
    return files, dirs


def cmd_uninstall(args: argparse.Namespace) -> None:
    path = Path(args.config) if args.config else default_config_path()
    home = path.parent
    print("ModelSaar uninstall removes ONLY the gateway's own files:")
    print(f"  {home}  (config.yaml and its backups, its key files, its state database)")
    print("It does NOT remove models from your inference runtime, nor any client configuration,")
    print("nor any other file you placed under that directory.")
    print("Client configs changed with `client-config --apply` have .bak-<timestamp> backups next to them.")
    print("Afterwards remove the package with: pip uninstall modelsaar   (or `uv tool uninstall modelsaar`)")
    if not args.yes:
        ans = input(f"delete ModelSaar's files under {home}? [y/N] ").strip().lower()
        if ans != "y":
            print("aborted")
            return
    if not home.exists():
        print(f"{home} does not exist; nothing to remove")
        return
    cfg: Config | None
    try:
        cfg = load_config(path) if path.exists() else None
    except Exception:
        cfg = None  # unparseable config: fall back to the default layout
    files, dirs = _owned_files(home, cfg)
    # Safety boundaries: never operate through symlinks, never outside home.
    for p in [home, *dirs]:
        if p.is_symlink():
            sys.exit(f"{p} is a symlink; refusing to delete through it. Remove ModelSaar's files manually.")
    for f in files:
        try:
            f.resolve().relative_to(home.resolve())
        except ValueError:
            sys.exit(f"{f} resolves outside {home}; refusing. Remove ModelSaar's files manually.")
    for f in files:
        if f.is_symlink():
            print(f"skipped {f} (symlink)")
            continue
        if f.exists():
            f.unlink()
            print(f"removed {f}")
    for d in [*dirs, home]:
        try:
            d.rmdir()
            print(f"removed {d}")
        except OSError:
            if d.exists():
                left = sorted(os.listdir(d))
                print(f"left in place: {d} (not created by ModelSaar or not empty: {left[:5]}{'...' if len(left) > 5 else ''})")


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
    s.add_argument("--offline", action="store_true", help="probe directly instead of through a running gateway (refused while a gateway listens unless --allow-concurrent)")
    s.add_argument("--allow-concurrent", action="store_true", help="accept uncoordinated inference next to a running gateway/other process")
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
    k = ks.add_parser("ensure", help="create missing key files (idempotent; never rotates). Used by the container entrypoint.")
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
    s.add_argument(
        "--deployments",
        nargs="*",
        help="live mode: restrict the sweep, baselines and the `auto` alias to these deployment ids (or bare model names when unambiguous)",
    )
    s.add_argument("--checkpoint", help="per-task record file (JSONL) for resumable runs; default <out>.records.jsonl when --out is given")
    s.add_argument("--resume", action="store_true", help="skip tasks already recorded in the checkpoint file")
    s.add_argument("--allow-concurrent", action="store_true", help="live mode: run even if a gateway/other process listens on the configured port")
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
