"""Regenerate evaluation aggregates from a saved per-request checkpoint and compare with a report.

    python scripts/eval_aggregate.py RUN_DIR/eval-live.json.records.jsonl [RUN_DIR/eval-live.json]

Recomputes, from the sanitised records alone: per-deployment calibration and test summaries, the
fixed-strong / fixed-fast selection, oracle, rules, random (same seed as the report) and auto. Prints
the policy table and, when a report is given, every field that differs. Exit 1 on any difference, so
the published numbers are demonstrably reproducible from the raw data.
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from modelsaar.evaluation.harness import _is_skipped, load_tasks, rules_policy, summarize


def main() -> int:
    records_path = Path(sys.argv[1])
    report = json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 else None
    tasks = load_tasks()
    calib = [t for t in tasks if t["split"] == "calib"]
    test = [t for t in tasks if t["split"] == "test"]
    recs = [json.loads(ln) for ln in records_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    by_policy: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in recs:
        by_policy[r["policy"]][r["task"]] = r
    dep_ids = sorted({p.split(":", 1)[1] for p in by_policy if p.startswith("calib:")})
    if report:
        dep_ids = [d["id"] for d in report["deployments"]]  # keep the report's order (rules/random depend on it)
    cal_summary = {d: summarize(by_policy[f"calib:{d}"], calib) for d in dep_ids}
    strong = max(dep_ids, key=lambda d: (cal_summary[d]["success"] or 0.0, -(cal_summary[d]["p50_ms"] or 1e9)))
    fast = min(dep_ids, key=lambda d: (cal_summary[d]["p50_ms"] or 1e9))
    sw = {d: by_policy[f"test:{d}"] for d in dep_ids}
    oracle = {}
    for t in test:
        rs = [sw[d][t["id"]] for d in dep_ids]
        if all(_is_skipped(r) for r in rs):
            oracle[t["id"]] = {"ok": None, "skipped": True, "detail": rs[0].get("detail"), "status": 200, "latency_ms": min(r["latency_ms"] for r in rs)}
        else:
            oracle[t["id"]] = {"ok": any(r["ok"] for r in rs if not _is_skipped(r)), "status": 200, "latency_ms": min(r["latency_ms"] for r in rs)}
    deps_meta = report["deployments"] if report else [{"id": d, "tags": [], "capabilities": {}} for d in dep_ids]
    if any(d.get("tags") is None for d in deps_meta):
        # Reports written before ba1069c did not carry tags; the run folder's discover JSON does.
        disc = records_path.parent / "14-discover-after-probe.txt"
        if disc.exists():
            raw = json.loads(disc.read_text())
            raw = raw.get("deployments", raw) if isinstance(raw, dict) else raw
            tags = {d["id"]: d.get("tags") or [] for d in raw}
            deps_meta = [{**d, "tags": tags.get(d["id"], [])} for d in deps_meta]
            print(f"tags taken from {disc.name} (report predates tag recording)")
    # rules needs tags/capabilities; the report carries tags (since 0f8af84+docs) and the records carry the choice
    seed = report["conditions"]["seed"] if report else 7
    rng = random.Random(seed)
    # The harness consumes rng.choice once per test task in test order, after the sweeps.
    rnd = {t["id"]: sw[rng.choice(dep_ids)][t["id"]] for t in test}

    def rules_deps():
        out = []
        for d in deps_meta:
            out.append({"id": d["id"], "tags": d.get("tags") or [], "capabilities": {"vision": {"value": "supported" if d["id"] in vision_ids else "unknown"}}})
        return out

    vision_ids = {d for d in dep_ids if (by_policy[f"test:{d}"].get("vis-02") or {}).get("status") == 200}
    rules = {t["id"]: sw[rules_policy(t, rules_deps(), strong, fast)][t["id"]] for t in test}
    policies = {
        "auto (live routing)": by_policy["auto"],
        "fixed-strong (calibrated)": sw[strong],
        "fixed-fast (calibrated)": sw[fast],
        "rules (gold label, specialist tags)": rules,
        "random (diagnostic)": rnd,
        "oracle (offline upper bound, not available at runtime)": oracle,
    }
    results = {k: summarize(v, test) for k, v in policies.items()}
    print(f"records: {len(recs)}  deployments: {dep_ids}  fixed-strong={strong} fixed-fast={fast}")
    print(f"{'policy':58s} {'success':>8} {'ci95':>16} {'complete':>9} {'viol':>5} {'p50':>8} {'p95':>9}")
    for k, v in results.items():
        print(f"{k:58s} {v['success']:>8} {str(v['ci95']):>16} {v['completion_rate']:>9} {v['capability_violations']:>5} {v['p50_ms']:>8} {v['p95_ms']:>9}")
    if not report:
        return 0
    diffs = []
    for k, v in results.items():
        rv = report["results"].get(k)
        if rv is None:
            diffs.append(f"{k}: missing in report")
            continue
        for f in ("success", "ci95", "completion_rate", "capability_violations", "p50_ms", "p95_ms", "n", "n_scored", "skipped"):
            if v.get(f) != rv.get(f):
                diffs.append(f"{k}.{f}: recomputed {v.get(f)} != report {rv.get(f)}")
        for cat, cv in v["per_category"].items():
            if cv != rv["per_category"].get(cat):
                diffs.append(f"{k}.per_category.{cat}: {cv} != {rv['per_category'].get(cat)}")
    for d in dep_ids:
        if cal_summary[d] != report["calibration"]["per_deployment"][d]:
            diffs.append(f"calibration.{d} differs")
        if summarize(sw[d], test) != report["per_deployment_test"][d]:
            diffs.append(f"per_deployment_test.{d} differs")
    if report["calibration"]["fixed_strong"] != strong or report["calibration"]["fixed_fast"] != fast:
        diffs.append("fixed-strong/fast selection differs")
    if diffs:
        print("DIFFERENCES:\n  " + "\n  ".join(diffs))
        return 1
    print("all aggregates in the report match the records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
