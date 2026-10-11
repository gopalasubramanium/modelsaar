"""Executable evaluation harness.

Procedure (identical in simulated and live mode):

1. Sweep the *calib* split over every eligible generative deployment -> per-deployment,
   per-category quality and latency. These calibrate the fixed-strong / fixed-fast baselines
   and (optionally) are stored as routing evidence.
2. Sweep the *test* split over every deployment -> per-deployment results and the offline
   per-task oracle (upper bound; NOT available at runtime).
3. Run ``auto`` live through the gateway on the test split (real routing, overhead measured).
4. Derive fixed-strong, fixed-fast, deterministic specialist rules and seeded random from the
   test sweep (same requests, same eligibility checks, temperature 0).

Every request goes through the real HTTP gateway so hard constraints apply equally to all policies.
"""

from __future__ import annotations

import json
import random
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from .scoring import score

FIXTURES = Path(__file__).parent / "fixtures" / "tasks.jsonl"


def load_tasks(path: Path | None = None, limit: int = 0) -> list[dict[str, Any]]:
    p = path or FIXTURES
    tasks = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return tasks[:limit] if limit else tasks


def _request_body(task: dict[str, Any], model: str, simulated: bool) -> dict[str, Any]:
    body: dict[str, Any] = {"model": model, "messages": json.loads(json.dumps(task["messages"])), "temperature": 0, "max_tokens": 400}
    if task.get("tools"):
        body["tools"] = task["tools"]
    if task.get("response_format"):
        body["response_format"] = task["response_format"]
    if simulated:
        # The fake backend decides correctness from this marker (simulation artefact only).
        marker = f" <!-- eval:{task['category']} -->"
        for m in reversed(body["messages"]):
            if m["role"] == "user":
                if isinstance(m["content"], str):
                    m["content"] += marker
                elif isinstance(m["content"], list):
                    for p in m["content"]:
                        if p.get("type") == "text":
                            p["text"] += marker
                            break
                break
    return body


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


class EvalRun:
    def __init__(self, gateway_url: str, api_key: str, admin_key: str, simulated: bool, seed: int = 7) -> None:
        self.c = httpx.Client(base_url=gateway_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=300)
        self.admin = httpx.Client(base_url=gateway_url, headers={"Authorization": f"Bearer {admin_key}"}, timeout=60)
        self.simulated = simulated
        self.rng = random.Random(seed)
        self.records: list[dict[str, Any]] = []

    def deployments(self) -> list[dict[str, Any]]:
        s = self.admin.get("/admin/status").json()
        return [d for d in s["deployments"] if d["role"] == "generative" and d["state"]["healthy"] and d["enabled"] and d["locality"] == "local"]

    def run_one(self, task: dict[str, Any], model: str, policy: str) -> dict[str, Any]:
        body = _request_body(task, model, self.simulated)
        t0 = time.monotonic()
        try:
            r = self.c.post("/v1/chat/completions", json=body)
        except httpx.HTTPError as e:
            rec = {"task": task["id"], "category": task["category"], "split": task["split"], "policy": policy, "model": model, "status": 0, "ok": False, "detail": f"transport: {e}", "latency_ms": (time.monotonic() - t0) * 1000}
            self.records.append(rec)
            return rec
        ms = (time.monotonic() - t0) * 1000
        rec: dict[str, Any] = {
            "task": task["id"],
            "category": task["category"],
            "split": task["split"],
            "policy": policy,
            "model": model,
            "status": r.status_code,
            "deployment": r.headers.get("x-modelsaar-deployment"),
            "request_id": r.headers.get("x-modelsaar-request-id"),
            "latency_ms": round(ms, 1),
        }
        if r.status_code == 200:
            ok, detail = score(task, r.json())
            rec["ok"], rec["detail"] = ok, detail
        else:
            rec["ok"] = False
            try:
                err = r.json().get("error", {})
                rec["detail"] = f"HTTP {r.status_code}: {err.get('code')}: {str(err.get('message'))[:160]}"
                rec["violation"] = r.status_code == 422
            except Exception:
                rec["detail"] = f"HTTP {r.status_code}"
        self.records.append(rec)
        return rec

    def sweep(self, tasks: list[dict[str, Any]], dep_ids: list[str], policy_prefix: str = "sweep") -> dict[str, dict[str, dict[str, Any]]]:
        """Return results[dep_id][task_id] = record."""
        out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for d in dep_ids:
            for t in tasks:
                out[d][t["id"]] = self.run_one(t, d, f"{policy_prefix}:{d}")
        return out

    def run_auto(self, tasks: list[dict[str, Any]], alias: str = "auto") -> dict[str, dict[str, Any]]:
        out = {}
        for t in tasks:
            rec = self.run_one(t, alias, "auto")
            if rec.get("request_id"):
                try:
                    dec = self.admin.get(f"/admin/decisions/{rec['request_id']}").json()
                    rec["overhead_ms"] = dec.get("overhead_ms")
                    rec["evidence"] = dec.get("evidence")
                    rec["inferred_task"] = (dec.get("requirements") or {}).get("primary_task")
                    rec["classifier"] = dec.get("classifier")
                except Exception:
                    pass
            out[t["id"]] = rec
        return out


def summarize(records_by_task: dict[str, dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    cats: dict[str, list[bool]] = defaultdict(list)
    lat: list[float] = []
    n_ok = n = n_complete = n_viol = 0
    for t in tasks:
        r = records_by_task.get(t["id"])
        if not r:
            continue
        n += 1
        ok = bool(r.get("ok"))
        n_ok += ok
        n_complete += r.get("status") == 200
        n_viol += bool(r.get("violation"))
        cats[t["category"]].append(ok)
        if r.get("status") == 200:
            lat.append(r["latency_ms"])
    lo, hi = _wilson(n_ok, n)
    per_cat = {}
    for c, v in sorted(cats.items()):
        k = sum(v)
        clo, chi = _wilson(k, len(v))
        per_cat[c] = {"success": round(k / len(v), 3), "n": len(v), "ci95": [round(clo, 3), round(chi, 3)]}
    return {
        "n": n,
        "success": round(n_ok / n, 3) if n else None,
        "ci95": [round(lo, 3), round(hi, 3)],
        "completion_rate": round(n_complete / n, 3) if n else None,
        "capability_violations": n_viol,
        "p50_ms": round(statistics.median(lat), 1) if lat else None,
        "p95_ms": round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)], 1) if lat else None,
        "per_category": per_cat,
    }


def rules_policy(task: dict[str, Any], deps: list[dict[str, Any]], strong: str, fast: str) -> str:
    """Deterministic specialist rules. NOTE: receives the gold category label (an advantage auto lacks)."""
    cat = task["category"]
    by_id = {d["id"]: d for d in deps}
    if cat in ("coding", "agent"):
        tagged = [d["id"] for d in deps if "code" in (d.get("tags") or [])]
        return tagged[0] if tagged else strong
    if cat == "document_vision":
        vis = [d["id"] for d in deps if d["capabilities"]["vision"]["value"] == "supported"]
        return vis[0] if vis else strong
    if cat in ("math", "extraction", "rag"):
        return strong
    return fast if fast in by_id else strong


def probe_all(gw) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """Verify capabilities of every local generative deployment before evaluating (as `modelsaar probe --all` would)."""

    from ..probes import run_probes

    async def _run() -> list[dict[str, Any]]:
        out = []
        for d in gw.router.registry.all():
            if d.role == "generative" and d.healthy and d.locality == "local":
                rep = await run_probes(gw.router.adapters[d.backend_id], d, gw.store, ["streaming", "tools", "json_object", "json_schema", "vision"], timeout=120)
                out.append(rep.as_dict())
        return out

    return gw.run(_run())


def evaluate(run: EvalRun, tasks: list[dict[str, Any]], save_measurements_store=None) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    deps = run.deployments()
    dep_ids = [d["id"] for d in deps]
    calib = [t for t in tasks if t["split"] == "calib"]
    test = [t for t in tasks if t["split"] == "test"]
    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "simulated" if run.simulated else "live",
        "deployments": [
            {"id": d["id"], "family": d["family"], "parameter_size": d["parameter_size"], "quantization": d["quantization"], "runtime": d["backend_type"], "context_length": d["context_length"], "fingerprint": d["fingerprint"]}
            for d in deps
        ],
        "n_calib": len(calib),
        "n_test": len(test),
    }
    if not dep_ids:
        report["error"] = "no eligible local generative deployments"
        return report
    # 1. calibration sweep
    cal = run.sweep(calib, dep_ids, "calib")
    cal_summary = {d: summarize(cal[d], calib) for d in dep_ids}
    strong = max(dep_ids, key=lambda d: (cal_summary[d]["success"] or 0.0, -(cal_summary[d]["p50_ms"] or 1e9)))
    fast = min(dep_ids, key=lambda d: (cal_summary[d]["p50_ms"] or 1e9))
    report["calibration"] = {"per_deployment": cal_summary, "fixed_strong": strong, "fixed_fast": fast}
    # optional: persist measured evidence for routing (per category + latency)
    if save_measurements_store is not None:
        by_fp = {d["id"]: d["fingerprint"] for d in deps}
        for d in dep_ids:
            for cat, v in cal_summary[d]["per_category"].items():
                save_measurements_store.save_measurement(d, by_fp[d], {"task": cat, "quality": v["success"], "samples": v["n"], "p50_ms": cal_summary[d]["p50_ms"], "p95_ms": cal_summary[d]["p95_ms"], "source": "eval"})
        try:
            run.admin.post("/admin/refresh")
        except Exception:
            pass
    # 2. test sweep (oracle + per-deployment)
    sw = run.sweep(test, dep_ids, "test")
    oracle = {t["id"]: {"ok": any(sw[d][t["id"]]["ok"] for d in dep_ids), "status": 200, "latency_ms": min(sw[d][t["id"]]["latency_ms"] for d in dep_ids)} for t in test}
    # 3. auto live
    auto = run.run_auto(test, "auto")
    # 4. derived policies
    fixed_strong = {t["id"]: sw[strong][t["id"]] for t in test}
    fixed_fast = {t["id"]: sw[fast][t["id"]] for t in test}
    rules = {t["id"]: sw[rules_policy(t, deps, strong, fast)][t["id"]] for t in test}
    rnd = {t["id"]: sw[run.rng.choice(dep_ids)][t["id"]] for t in test}
    policies = {
        "auto (live routing)": auto,
        "fixed-strong (calibrated)": fixed_strong,
        "fixed-fast (calibrated)": fixed_fast,
        "rules (gold label, specialist tags)": rules,
        "random (diagnostic)": rnd,
        "oracle (offline upper bound, not available at runtime)": oracle,
    }
    report["results"] = {name: summarize(recs, test) for name, recs in policies.items()}
    report["per_deployment_test"] = {d: summarize(sw[d], test) for d in dep_ids}
    overheads = [r["overhead_ms"] for r in auto.values() if r.get("overhead_ms") is not None]
    report["routing"] = {
        "overhead_ms_mean": round(statistics.mean(overheads), 2) if overheads else None,
        "overhead_ms_p95": round(sorted(overheads)[max(0, int(len(overheads) * 0.95) - 1)], 2) if overheads else None,
        "choices": {t["id"]: auto[t["id"]].get("deployment") for t in test},
        "evidence_levels": dict(sorted(defaultdict(int, {e: sum(1 for r in auto.values() if r.get("evidence") == e) for e in {r.get("evidence") for r in auto.values()}}).items(), key=lambda kv: str(kv[0]))),
        "task_label_accuracy": round(sum(1 for t in test if auto[t["id"]].get("inferred_task") == t["category"]) / len(test), 3) if test else None,
        "routing_mistakes": [t["id"] for t in test if not auto[t["id"]]["ok"] and oracle[t["id"]]["ok"]],
        "classifier": {"used": sum(1 for r in auto.values() if (r.get("classifier") or {}).get("used")), "timeouts": sum(1 for r in auto.values() if (r.get("classifier") or {}).get("status") == "timeout")},
    }
    report["records"] = run.records
    return report


def render_report(rep: dict[str, Any]) -> str:
    lines = [f"ModelSaar evaluation ({rep['mode']}) - {rep['generated_at']}", ""]
    if rep.get("error"):
        return "\n".join(lines + [f"ERROR: {rep['error']}"])
    lines.append("deployments: " + ", ".join(f"{d['id']} [{d['parameter_size']} {d['quantization']} ctx={d['context_length']}]" for d in rep["deployments"]))
    lines.append(f"calibration: fixed-strong={rep['calibration']['fixed_strong']}  fixed-fast={rep['calibration']['fixed_fast']}  (n_calib={rep['n_calib']}, n_test={rep['n_test']})")
    lines.append("")
    lines.append(f"{'policy':55s} {'success':>9s} {'95% CI':>15s} {'complete':>9s} {'viol':>5s} {'p50 ms':>8s} {'p95 ms':>8s}")
    for name, s in rep["results"].items():
        lines.append(f"{name:55s} {s['success']:>9.3f} {s['ci95']!s:>15s} {s['completion_rate']:>9.3f} {s['capability_violations']:>5d} {s['p50_ms']!s:>8s} {s['p95_ms']!s:>8s}")
    lines.append("")
    cats = sorted({c for s in rep["results"].values() for c in s["per_category"]})
    lines.append(f"{'per category':55s} " + " ".join(f"{c[:10]:>10s}" for c in cats))
    for name, s in rep["results"].items():
        lines.append(f"{name:55s} " + " ".join(f"{(s['per_category'].get(c) or {}).get('success', float('nan')):>10.2f}" for c in cats))
    r = rep["routing"]
    lines.append("")
    lines.append(f"routing overhead: mean {r['overhead_ms_mean']} ms, p95 {r['overhead_ms_p95']} ms; task-label accuracy {r['task_label_accuracy']}; evidence levels {r['evidence_levels']}")
    lines.append(f"routing mistakes (auto failed, oracle succeeded): {r['routing_mistakes']}")
    lines.append(f"classifier: {r['classifier']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
def run_eval_cli(args) -> None:  # type: ignore[no-untyped-def]
    tasks = load_tasks(Path(args.tasks) if args.tasks else None, args.limit)
    if args.mode == "simulated":
        rep = run_simulated(tasks, seed=args.seed)
    else:
        rep = run_live(args, tasks)
    print(render_report(rep))
    if args.out:
        Path(args.out).write_text(json.dumps(rep, indent=2), encoding="utf-8")
        print(f"\nreport written to {args.out}")


def run_simulated(tasks: list[dict[str, Any]], seed: int = 7) -> dict[str, Any]:
    import tempfile

    from ..config import BackendConfig, Config, ResourcePool, generate_key, write_key_file
    from ..runtime import GatewayThread, free_port
    from ..testing.fakebackend import FakeBackend, FakeModel

    fake = FakeBackend(
        [
            FakeModel("sim-small:1b", ["completion", "tools"], 8192, parameter_size="1.0B", loaded=True, token_delay_s=0.0, good_at=["conversation", "summarization", "translation", "decision"]),
            FakeModel("sim-code:7b", ["completion", "tools"], 16384, parameter_size="7B", size_bytes=4_500_000_000, token_delay_s=0.002, good_at=["coding", "agent", "conversation", "rag"]),
            FakeModel("sim-large:27b", ["completion", "tools", "vision", "thinking"], 32768, parameter_size="27B", size_bytes=18_000_000_000, token_delay_s=0.005, good_at=["coding", "math", "extraction", "document_vision", "rag", "summarization", "translation"]),
        ]
    )
    burl = fake.start()
    tmp = Path(tempfile.mkdtemp(prefix="modelsaar-eval-"))
    api_key, admin_key = generate_key("msk"), generate_key("msa")
    write_key_file(tmp / "keys/api_keys", [api_key])
    write_key_file(tmp / "keys/admin_key", [admin_key])
    cfg = Config(
        resource_pools=(ResourcePool(id="sim", max_concurrent=2),),
        backends=(BackendConfig(id="sim", type="ollama", base_url=burl, resource_pool="sim"),),
        deployments=(),
    )
    cfg = cfg.model_copy(update={"server": cfg.server.model_copy(update={"port": free_port()}), "config_path": str(tmp / "config.yaml"), "config_hash": "eval-sim"})
    # Give the code model a 'code' tag so the rules baseline and auto-code alias can use it.
    from ..config import DeploymentOverride

    cfg = cfg.model_copy(update={"deployments": (DeploymentOverride(backend="sim", model="sim-code:7b", tags=("code",)),)})
    gw = GatewayThread(cfg)
    url = gw.start()
    try:
        probes = probe_all(gw)
        run = EvalRun(url, api_key, admin_key, simulated=True, seed=seed)
        rep = evaluate(run, tasks, save_measurements_store=gw.store)
        rep["probes"] = probes
        rep["note"] = (
            "SIMULATED: deployments are fake backends whose correctness is scripted per category; this validates the "
            "harness and the routing policy mechanics, NOT real model quality."
        )
        return rep
    finally:
        gw.stop()
        fake.stop()


def run_live(args, tasks: list[dict[str, Any]]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    from ..cli import _load
    from ..config import read_keys
    from ..runtime import GatewayThread, free_port

    cfg = _load(args)
    # Run an in-process gateway on a free port so evaluation never disturbs a running instance.
    cfg = cfg.model_copy(update={"server": cfg.server.model_copy(update={"port": free_port()})})
    api = read_keys(cfg.resolve(cfg.server.api_keys_file))
    adm = read_keys(cfg.resolve(cfg.server.admin_key_file))
    if not api or not adm:
        raise SystemExit("keys missing; run `modelsaar init`")
    gw = GatewayThread(cfg)
    url = gw.start()
    try:
        probes = probe_all(gw) if args.probe else []
        run = EvalRun(url, api[0], adm[0], simulated=False, seed=args.seed)
        rep = evaluate(run, tasks, save_measurements_store=gw.store if args.save_measurements else None)
        rep["probes"] = probes
        rep["note"] = "LIVE: real backends from your config; results are specific to the exact deployments/fingerprints listed."
        return rep
    finally:
        gw.stop()
