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

import hashlib
import json
import random
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from . import sandbox
from .scoring import SCORER_VERSION, score

FIXTURES = Path(__file__).parent / "fixtures" / "tasks.jsonl"
MAX_TOKENS = 400
TEMPERATURE = 0


def load_tasks(path: Path | None = None, limit: int = 0) -> list[dict[str, Any]]:
    p = path or FIXTURES
    tasks = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return tasks[:limit] if limit else tasks


def dataset_revision(tasks: list[dict[str, Any]], path: Path | None = None) -> dict[str, str | None]:
    """sha256 of the task file (when known) and of the canonical JSON of the tasks actually run."""
    p = path or FIXTURES
    file_sha = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    canon = "\n".join(json.dumps(t, sort_keys=True, ensure_ascii=False) for t in tasks)
    return {"tasks_file": str(p), "tasks_file_sha256": file_sha, "tasks_run_sha256": hashlib.sha256(canon.encode("utf-8")).hexdigest()}


def _git_commit() -> str | None:
    try:
        p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    return p.stdout.strip() or None


def resolve_selectors(deployments: list[dict[str, Any]], selectors: list[str] | None) -> list[str]:
    """Map user-supplied deployment selectors to canonical deployment ids, once.

    A selector may be a full id (``ollama/qwen3.6:latest``) or a bare model name
    (``qwen3.6:latest``). Unknown or ambiguous selectors raise ``ValueError`` so a typo cannot
    silently shrink the sweep or leave the ``auto`` alias unrestricted.
    """
    out: list[str] = []
    ids = [d["id"] for d in deployments]
    for sel in selectors or []:
        if sel in ids:
            hits = [sel]
        else:
            hits = [d["id"] for d in deployments if d["id"].split("/", 1)[-1] == sel or d.get("model") == sel]
        if not hits:
            raise ValueError(f"unknown deployment selector {sel!r}; discovered deployments: {ids}")
        if len(hits) > 1:
            raise ValueError(f"ambiguous deployment selector {sel!r} matches {hits}; use the full id")
        if hits[0] not in out:
            out.append(hits[0])
    return out


def _request_body(task: dict[str, Any], model: str, simulated: bool) -> dict[str, Any]:
    body: dict[str, Any] = {"model": model, "messages": json.loads(json.dumps(task["messages"])), "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}
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


CHECKPOINT_FORMAT = 2  # records carry task_sha256 + conditions_key; format-1 records are never resumed


def task_identity(task: dict[str, Any]) -> str:
    """sha256 of the task content that determines a result: messages, expected (type, values,
    harness, schema), tools, category/split. Ephemeral fields are not part of a task."""
    return hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def conditions_key(policy: str, *, scorer_version: str = SCORER_VERSION, max_tokens: int = MAX_TOKENS, temperature: float = TEMPERATURE,
                   seed: int | None = None, routing_config_hash: str | None = None) -> str:
    """Stable identity of the experiment conditions a record depends on: scorer version, request
    budgets and, for routed policies (``auto`` and other aliases), the gateway's routing configuration
    hash. Fixed-deployment sweeps do not depend on routing configuration. The seed matters only for
    the random baseline. Ports, timestamps and paths are deliberately excluded so an unchanged run
    stays resumable."""
    parts: dict[str, Any] = {"format": CHECKPOINT_FORMAT, "scorer": scorer_version, "max_tokens": max_tokens, "temperature": temperature}
    if policy.startswith("random"):
        parts["seed"] = seed
    if not policy.startswith(("sweep:", "calib:")):
        parts["routing_config_hash"] = routing_config_hash
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()[:24]


class EvalRun:
    """Issues requests, scores them and keeps per-request records.

    Records are sanitized (ids, status, latency, scorer detail; never prompt text). With a
    ``checkpoint`` path every record is appended as one JSON line immediately; with
    ``resume=True`` a record already in that file is reused only when it is bound to the same
    experiment: same ``(policy, task)`` key, same task content (``task_sha256``), same conditions
    (``conditions_key``: scorer version, budgets, routing configuration for routed policies) and,
    for records that name a deployment, that deployment is still eligible in this run with the
    same fingerprint. Anything else — a changed task or scorer, a removed or changed deployment,
    a format-1 (legacy) record — is re-run and counted in ``resume_rejected``.
    """

    def __init__(self, gateway_url: str, api_key: str, admin_key: str, simulated: bool, seed: int = 7, checkpoint: Path | None = None, resume: bool = False) -> None:
        self.c = httpx.Client(base_url=gateway_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=300)
        self.admin = httpx.Client(base_url=gateway_url, headers={"Authorization": f"Bearer {admin_key}"}, timeout=60)
        self.simulated = simulated
        self.seed = seed
        self.rng = random.Random(seed)
        self.records: list[dict[str, Any]] = []
        self.fingerprints: dict[str, str] = {}
        self.routing_config_hash: str | None = None  # set from /admin/status by run_live/run_simulated
        self.checkpoint = Path(checkpoint) if checkpoint else None
        self.resumed = 0
        self.resume_rejected: dict[str, int] = {}
        self._done: dict[tuple[str, str], dict[str, Any]] = {}
        if resume:
            if not self.checkpoint:
                raise ValueError("--resume needs a checkpoint path (--checkpoint PATH or --out)")
            if self.checkpoint.exists():
                for ln in self.checkpoint.read_text(encoding="utf-8").splitlines():
                    if ln.strip():
                        rec = json.loads(ln)
                        self._done[(rec["policy"], rec["task"])] = rec
        if self.checkpoint:
            self.checkpoint.parent.mkdir(parents=True, exist_ok=True)

    def deployments(self) -> list[dict[str, Any]]:
        s = self.admin.get("/admin/status").json()
        return [d for d in s["deployments"] if d["role"] == "generative" and d["state"]["healthy"] and d["enabled"] and d["locality"] == "local"]

    def all_deployments(self) -> list[dict[str, Any]]:
        return list(self.admin.get("/admin/status").json()["deployments"])

    def _finish(self, rec: dict[str, Any]) -> dict[str, Any]:
        self.records.append(rec)
        if self.checkpoint:
            with open(self.checkpoint, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
        return rec

    def _conditions_key(self, policy: str) -> str:
        return conditions_key(policy, seed=self.seed, routing_config_hash=self.routing_config_hash)

    def _reject(self, reason: str) -> None:
        self.resume_rejected[reason] = self.resume_rejected.get(reason, 0) + 1

    def _resumable(self, task: dict[str, Any] | str, policy: str) -> dict[str, Any] | None:
        """Return the checkpoint record to reuse for ``(policy, task)`` or None (re-run). ``task`` is
        the task dict; a bare task id (legacy callers/tests) can only match on the id and the
        deployment conditions, and a format-2 record then still requires the task hash."""
        task_id = task if isinstance(task, str) else task["id"]
        prev = self._done.get((policy, task_id))
        if not prev:
            return None
        if prev.get("checkpoint_format") != CHECKPOINT_FORMAT or not prev.get("task_sha256"):
            self._reject("legacy_record_format")
            return None
        if not isinstance(task, str) and prev.get("task_sha256") != task_identity(task):
            self._reject("task_changed")
            return None
        if prev.get("conditions_key") != self._conditions_key(policy):
            self._reject("conditions_changed")
            return None
        dep, fp = prev.get("deployment"), prev.get("fingerprint")
        if dep:
            if self.simulated:
                # The simulated backend is deterministic by construction and is started on a fresh
                # loopback port per run, so its endpoint (part of the fingerprint) differs every time;
                # the deployment must still exist in this run.
                if dep not in self.fingerprints:
                    self._reject("deployment_not_eligible")
                    return None
                return prev
            if dep not in self.fingerprints:
                self._reject("deployment_not_eligible")
                return None
            if fp and self.fingerprints[dep] != fp:
                self._reject("deployment_changed")
                return None
            if not fp:
                self._reject("record_without_fingerprint")
                return None
        return prev

    def run_one(self, task: dict[str, Any], model: str, policy: str, enrich: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        prev = self._resumable(task, policy)
        if prev is not None:
            self.resumed += 1
            rec = dict(prev)
            rec["resumed"] = True
            self.records.append(rec)  # already in the checkpoint file
            return rec
        body = _request_body(task, model, self.simulated)
        t0 = time.monotonic()
        try:
            r = self.c.post("/v1/chat/completions", json=body)
        except httpx.HTTPError as e:
            rec = {"task": task["id"], "category": task["category"], "split": task["split"], "policy": policy, "model": model, "status": 0, "ok": False, "detail": f"transport: {e}", "latency_ms": (time.monotonic() - t0) * 1000}
            return self._finish(self._bind(rec, task, policy))
        ms = (time.monotonic() - t0) * 1000
        print(f"[eval] {policy:40s} {task['id']:12s} HTTP {r.status_code} {ms/1000:6.1f}s", file=sys.stderr, flush=True)
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
        if rec["deployment"] and rec["deployment"] in self.fingerprints:
            rec["fingerprint"] = self.fingerprints[rec["deployment"]]
        if r.status_code == 200:
            ok, detail = score(task, r.json())
            rec["ok"], rec["detail"] = ok, detail
            if ok is None:
                rec["skipped"] = True
        else:
            rec["ok"] = False
            try:
                err = r.json().get("error", {})
                rec["detail"] = f"HTTP {r.status_code}: {err.get('code')}: {str(err.get('message'))[:160]}"
                rec["violation"] = r.status_code == 422
            except Exception:
                rec["detail"] = f"HTTP {r.status_code}"
        if enrich is not None:
            enrich(rec)
        return self._finish(self._bind(rec, task, policy))

    def _bind(self, rec: dict[str, Any], task: dict[str, Any], policy: str) -> dict[str, Any]:
        """Attach the experiment identity a later --resume must match."""
        rec["checkpoint_format"] = CHECKPOINT_FORMAT
        rec["task_sha256"] = task_identity(task)
        rec["conditions_key"] = self._conditions_key(policy)
        rec["scorer_version"] = SCORER_VERSION
        return rec

    def sweep(self, tasks: list[dict[str, Any]], dep_ids: list[str], policy_prefix: str = "sweep") -> dict[str, dict[str, dict[str, Any]]]:
        """Return results[dep_id][task_id] = record."""
        out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for d in dep_ids:
            for t in tasks:
                out[d][t["id"]] = self.run_one(t, d, f"{policy_prefix}:{d}")
        return out

    def run_auto(self, tasks: list[dict[str, Any]], alias: str = "auto") -> dict[str, dict[str, Any]]:
        def enrich(rec: dict[str, Any]) -> None:
            if rec.get("request_id"):
                try:
                    dec = self.admin.get(f"/admin/decisions/{rec['request_id']}").json()
                    rec["overhead_ms"] = dec.get("overhead_ms")
                    rec["evidence"] = dec.get("evidence")
                    rec["inferred_task"] = (dec.get("requirements") or {}).get("primary_task")
                    rec["classifier"] = dec.get("classifier")
                except Exception:
                    pass

        return {t["id"]: self.run_one(t, alias, "auto", enrich=enrich) for t in tasks}


def _is_skipped(r: dict[str, Any]) -> bool:
    return bool(r.get("skipped")) or r.get("ok") is None


def summarize(records_by_task: dict[str, dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate one policy. ``success`` and its CI are computed over *scored* tasks only
    (``n_scored``); tasks the scorer could not judge are counted in ``skipped`` with the reason,
    so the denominator is always visible."""
    cats: dict[str, list[bool]] = defaultdict(list)
    cat_skipped: dict[str, int] = defaultdict(int)
    lat: list[float] = []
    n_ok = n = n_scored = n_complete = n_viol = n_skipped = 0
    skip_reasons: dict[str, int] = defaultdict(int)
    for t in tasks:
        r = records_by_task.get(t["id"])
        if not r:
            continue
        n += 1
        n_complete += r.get("status") == 200
        n_viol += bool(r.get("violation"))
        if r.get("status") == 200:
            lat.append(r["latency_ms"])
        if _is_skipped(r):
            n_skipped += 1
            cat_skipped[t["category"]] += 1
            skip_reasons[str(r.get("detail") or "skipped")] += 1
            continue
        n_scored += 1
        ok = bool(r.get("ok"))
        n_ok += ok
        cats[t["category"]].append(ok)
    lo, hi = _wilson(n_ok, n_scored)
    per_cat = {}
    for c in sorted(set(cats) | set(cat_skipped)):
        v = cats.get(c, [])
        k = sum(v)
        clo, chi = _wilson(k, len(v))
        per_cat[c] = {"success": round(k / len(v), 3) if v else None, "n": len(v), "skipped": cat_skipped.get(c, 0), "ci95": [round(clo, 3), round(chi, 3)]}
    return {
        "n": n,
        "n_scored": n_scored,
        "skipped": n_skipped,
        "skip_reasons": dict(skip_reasons),
        "success": round(n_ok / n_scored, 3) if n_scored else None,
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


def evaluate(
    run: EvalRun,
    tasks: list[dict[str, Any]],
    save_measurements_store=None,  # type: ignore[no-untyped-def]
    only: list[str] | None = None,
    conditions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``only`` must already hold canonical deployment ids (see :func:`resolve_selectors`)."""
    deps = run.deployments()
    if only:
        eligible = {d["id"] for d in deps}
        missing = [i for i in only if i not in eligible]
        if missing:
            raise ValueError(f"selected deployments are not eligible (must be local, healthy, enabled, generative): {missing}")
        deps = [d for d in deps if d["id"] in only]
    dep_ids = [d["id"] for d in deps]
    run.fingerprints = {d["id"]: d["fingerprint"] for d in deps}
    try:
        run.routing_config_hash = run.admin.get("/admin/status").json().get("config_hash")
    except Exception:  # pragma: no cover - status is required anyway above
        run.routing_config_hash = None
    calib = [t for t in tasks if t["split"] == "calib"]
    test = [t for t in tasks if t["split"] == "test"]
    backend, backend_reason = sandbox.available()
    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "simulated" if run.simulated else "live",
        "deployments": [
            {
                "id": d["id"],
                "family": d["family"],
                "parameter_size": d["parameter_size"],
                "quantization": d["quantization"],
                "runtime": d["backend_type"],
                "runtime_version": d.get("runtime_version"),
                "context_length": d["context_length"],
                "fingerprint": d["fingerprint"],
                "identity": d.get("identity"),
                "endpoint": d.get("endpoint"),
                "tags": d.get("tags"),
                "memory_gb_estimate": d.get("memory_gb_estimate"),
            }
            for d in deps
        ],
        "n_calib": len(calib),
        "n_test": len(test),
        "sandbox": {"backend": backend, "reason": backend_reason, "code_exec_tasks": sum(1 for t in tasks if t["expected"]["type"] == "code_exec")},
        "conditions": {
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "seed": run.seed,
            "scorer_version": SCORER_VERSION,
            "checkpoint_format": CHECKPOINT_FORMAT,
            "routing_config_hash": run.routing_config_hash,
            "git_commit": _git_commit(),
            "sandbox_backend": backend,
            "deployment_fingerprints": dict(run.fingerprints),
            **(conditions or {}),
        },
        "checkpoint": str(run.checkpoint) if run.checkpoint else None,
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
        by_id = {d["id"]: d for d in deps}
        for d in dep_ids:
            cond = {
                k: v for k, v in report["conditions"].items() if k != "deployment_fingerprints"
            } | {
                "split": "calib",
                "effective_context": by_id[d].get("context_length"),
                "runtime": f"{by_id[d].get('runtime', '')} {by_id[d].get('runtime_version', '')}".strip(),
                "endpoint": by_id[d].get("endpoint"),
            }
            for cat, v in cal_summary[d]["per_category"].items():
                if v["success"] is None:
                    continue  # nothing scored in this category (e.g. code_exec skipped): no evidence
                save_measurements_store.save_measurement(
                    d,
                    by_fp[d],
                    {"task": cat, "quality": v["success"], "samples": v["n"], "p50_ms": cal_summary[d]["p50_ms"], "p95_ms": cal_summary[d]["p95_ms"], "source": "eval", "conditions": cond},
                )
        try:
            run.admin.post("/admin/refresh")
        except Exception:
            pass
    # 2. test sweep (oracle + per-deployment)
    sw = run.sweep(test, dep_ids, "test")
    oracle: dict[str, dict[str, Any]] = {}
    for t in test:
        recs = [sw[d][t["id"]] for d in dep_ids]
        if all(_is_skipped(r) for r in recs):
            oracle[t["id"]] = {"ok": None, "skipped": True, "detail": recs[0].get("detail"), "status": 200, "latency_ms": min(r["latency_ms"] for r in recs)}
        else:
            oracle[t["id"]] = {"ok": any(r["ok"] for r in recs if not _is_skipped(r)), "status": 200, "latency_ms": min(r["latency_ms"] for r in recs)}
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
        "routing_mistakes": [t["id"] for t in test if auto[t["id"]]["ok"] is False and oracle[t["id"]]["ok"] is True],
        "classifier": {"used": sum(1 for r in auto.values() if (r.get("classifier") or {}).get("used")), "timeouts": sum(1 for r in auto.values() if (r.get("classifier") or {}).get("status") == "timeout")},
    }
    report["resumed_records"] = run.resumed
    report["resume_rejected"] = dict(run.resume_rejected)
    report["records"] = run.records
    return report


def _fmt(v: Any, width: int, prec: int, na: str = "n/a") -> str:
    """Right-aligned fixed-point number, or ``na`` when there is nothing to show (e.g. all skipped)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:>{width}.{prec}f}"
    return f"{na:>{width}s}"


def render_report(rep: dict[str, Any]) -> str:
    lines = [f"ModelSaar evaluation ({rep['mode']}) - {rep['generated_at']}", ""]
    if rep.get("error"):
        return "\n".join(lines + [f"ERROR: {rep['error']}"])
    lines.append("deployments: " + ", ".join(f"{d['id']} [{d['parameter_size']} {d['quantization']} ctx={d['context_length']}]" for d in rep["deployments"]))
    lines.append(f"calibration: fixed-strong={rep['calibration']['fixed_strong']}  fixed-fast={rep['calibration']['fixed_fast']}  (n_calib={rep['n_calib']}, n_test={rep['n_test']})")
    sb = rep.get("sandbox") or {}
    if sb.get("backend"):
        lines.append(f"sandbox: {sb['backend']} ({sb.get('reason')}); code_exec tasks executed in isolation")
    else:
        lines.append(f"sandbox: NONE - {sb.get('code_exec_tasks', 0)} code_exec task(s) SKIPPED and excluded from every denominator: {sb.get('reason')}")
    cond = rep.get("conditions") or {}
    lines.append(
        f"conditions: max_tokens={cond.get('max_tokens')} temperature={cond.get('temperature')} seed={cond.get('seed')} "
        f"scorer={cond.get('scorer_version')} tasks_sha256={str(cond.get('tasks_file_sha256') or cond.get('tasks_run_sha256') or '')[:12]} git={str(cond.get('git_commit') or 'unknown')[:12]}"
    )
    if rep.get("checkpoint"):
        rej = rep.get("resume_rejected") or {}
        lines.append(f"checkpoint: {rep['checkpoint']} (resumed {rep.get('resumed_records', 0)} record(s)"
                     + (f"; re-run instead of resumed: {', '.join(f'{k}={v}' for k, v in sorted(rej.items()))}" if rej else "") + ")")
    lines.append("")
    lines.append(f"{'policy':55s} {'success':>9s} {'95% CI':>15s} {'scored':>7s} {'skip':>5s} {'complete':>9s} {'viol':>5s} {'p50 ms':>8s} {'p95 ms':>8s}")
    for name, s in rep["results"].items():
        lines.append(
            f"{name:55s} {_fmt(s['success'], 9, 3)} {s['ci95']!s:>15s} {s['n_scored']:>7d} {s['skipped']:>5d} "
            f"{_fmt(s['completion_rate'], 9, 3)} {s['capability_violations']:>5d} {s['p50_ms']!s:>8s} {s['p95_ms']!s:>8s}"
        )
    lines.append("")
    cats = sorted({c for s in rep["results"].values() for c in s["per_category"]})
    lines.append(f"{'per category (success over scored; -- = all skipped)':55s} " + " ".join(f"{c[:10]:>10s}" for c in cats))
    for name, s in rep["results"].items():
        lines.append(f"{name:55s} " + " ".join(_fmt((s["per_category"].get(c) or {}).get("success"), 10, 2, na="--") for c in cats))
    skipped_any = {reason for s in rep["results"].values() for reason in s.get("skip_reasons", {})}
    if skipped_any:
        lines.append("")
        lines.append("skipped (not counted as success or failure): " + "; ".join(sorted(skipped_any)))
    r = rep["routing"]
    lines.append("")
    lines.append(f"routing overhead: mean {r['overhead_ms_mean']} ms, p95 {r['overhead_ms_p95']} ms; task-label accuracy {r['task_label_accuracy']}; evidence levels {r['evidence_levels']}")
    lines.append(f"routing mistakes (auto failed, oracle succeeded): {r['routing_mistakes']}")
    lines.append(f"classifier: {r['classifier']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
def _checkpoint_path(args) -> Path | None:  # type: ignore[no-untyped-def]
    explicit = getattr(args, "checkpoint", None)
    if explicit:
        return Path(explicit)
    out = getattr(args, "out", None)
    return Path(str(out) + ".records.jsonl") if out else None


def run_eval_cli(args) -> None:  # type: ignore[no-untyped-def]
    tasks_path = Path(args.tasks) if args.tasks else None
    tasks = load_tasks(tasks_path, args.limit)
    checkpoint = _checkpoint_path(args)
    resume = bool(getattr(args, "resume", False))
    if resume and not checkpoint:
        raise SystemExit("--resume needs --checkpoint PATH (or --out, whose checkpoint is <out>.records.jsonl)")
    conditions = dataset_revision(tasks, tasks_path)
    if args.mode == "simulated":
        rep = run_simulated(tasks, seed=args.seed, checkpoint=checkpoint, resume=resume, conditions=conditions)
    else:
        rep = run_live(args, tasks, checkpoint=checkpoint, resume=resume, conditions=conditions)
    print(render_report(rep))
    if args.out:
        Path(args.out).write_text(json.dumps(rep, indent=2), encoding="utf-8")
        print(f"\nreport written to {args.out}")


def run_simulated(
    tasks: list[dict[str, Any]], seed: int = 7, checkpoint: Path | None = None, resume: bool = False, conditions: dict[str, Any] | None = None
) -> dict[str, Any]:
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
        run = EvalRun(url, api_key, admin_key, simulated=True, seed=seed, checkpoint=checkpoint, resume=resume)
        rep = evaluate(run, tasks, save_measurements_store=gw.store, conditions=conditions or dataset_revision(tasks))
        rep["probes"] = probes
        rep["note"] = (
            "SIMULATED: deployments are fake backends whose correctness is scripted per category; this validates the "
            "harness and the routing policy mechanics, NOT real model quality."
        )
        return rep
    finally:
        gw.stop()
        fake.stop()


def restrict_auto_alias(cfg, dep_ids: list[str]):  # type: ignore[no-untyped-def]
    """Return a config whose ``auto`` alias may only choose among ``dep_ids`` (canonical ids)."""
    aliases = dict(cfg.aliases)
    aliases["auto"] = aliases["auto"].model_copy(update={"deployments": tuple(dep_ids)})
    return cfg.model_copy(update={"aliases": aliases})


def run_live(args, tasks: list[dict[str, Any]], checkpoint: Path | None = None, resume: bool = False, conditions: dict[str, Any] | None = None) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    from ..cli import _load
    from ..config import read_keys
    from ..runtime import GatewayThread, free_port

    cfg = _load(args)
    # The live evaluation runs its own in-process gateway (own admission) against the same
    # backends. A gateway already listening on the configured port would run uncoordinated
    # inference next to it, so that is refused unless the operator accepts it explicitly.
    from ..cli import _gateway_listening

    listening = _gateway_listening(cfg)
    if listening is not None and not getattr(args, "allow_concurrent", False):
        what = "a ModelSaar gateway" if listening == "gateway" else "another process"
        raise SystemExit(
            f"{what} is listening on {cfg.server.host}:{cfg.server.port}; a live evaluation would run inference "
            "outside its admission control. Stop it first, or pass --allow-concurrent to accept that."
        )
    cfg = cfg.model_copy(update={"server": cfg.server.model_copy(update={"port": free_port()})})
    api = read_keys(cfg.resolve(cfg.server.api_keys_file))
    adm = read_keys(cfg.resolve(cfg.server.admin_key_file))
    if not api or not adm:
        raise SystemExit("keys missing; run `modelsaar init`")
    selected: list[str] | None = None
    if args.deployments:
        # Resolve selectors ONCE against the discovered registry, then restrict the `auto` alias to the
        # same canonical ids that calibration and every baseline sweep use (fair comparison). The
        # alias lives in the immutable config, so discover, resolve, stop, rebuild, start again.
        gw0 = GatewayThread(cfg)
        url0 = gw0.start()
        try:
            discovered = EvalRun(url0, api[0], adm[0], simulated=False).all_deployments()
        finally:
            gw0.stop()
        try:
            selected = resolve_selectors(discovered, list(args.deployments))
        except ValueError as e:
            raise SystemExit(f"--deployments: {e}") from None
        cfg = restrict_auto_alias(cfg, selected)
    gw = GatewayThread(cfg)
    url = gw.start()
    try:
        probes = probe_all(gw) if args.probe else []
        run = EvalRun(url, api[0], adm[0], simulated=False, seed=args.seed, checkpoint=checkpoint, resume=resume)
        try:
            rep = evaluate(run, tasks, save_measurements_store=gw.store if args.save_measurements else None, only=selected, conditions=conditions or dataset_revision(tasks))
        except ValueError as e:
            raise SystemExit(f"--deployments: {e}") from None
        if selected:
            rep["deployment_filter"] = {"selectors": list(args.deployments), "resolved": selected}
        rep["probes"] = probes
        rep["note"] = "LIVE: real backends from your config; results are specific to the exact deployments/fingerprints listed."
        return rep
    finally:
        gw.stop()
