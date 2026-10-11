"""Transparent, configurable ranking of eligible deployments.

Each candidate gets a breakdown: expected quality (with evidence level and
uncertainty), latency cost, residency/load cost, overhead cost, and any
affinity/switching adjustment. The top candidate wins unless it is tied with
a cheaper candidate within the evidence's uncertainty, in which case the
lower-overhead option is preferred.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from ..config import ProfileWeights, RoutingConfig
from ..registry import Deployment


@dataclass
class Candidate:
    deployment: Deployment
    quality: float
    uncertainty: float
    evidence: str  # measured:<n> | prior:<provenance> | uncalibrated
    latency_cost: float
    residency_cost: float
    overhead_cost: float
    affinity_adjust: float
    score: float = 0.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "deployment": self.deployment.id,
            "quality": round(self.quality, 3),
            "uncertainty": round(self.uncertainty, 3),
            "evidence": self.evidence,
            "latency_cost": round(self.latency_cost, 3),
            "residency_cost": round(self.residency_cost, 3),
            "overhead_cost": round(self.overhead_cost, 3),
            "affinity_adjust": round(self.affinity_adjust, 3),
            "score": round(self.score, 4),
            "notes": self.notes,
        }


_SIZE_RX = re.compile(r"([\d.]+)\s*([bBmM])")


def param_count_b(dep: Deployment) -> float | None:
    m = _SIZE_RX.search(dep.parameter_size or "")
    if not m:
        return None
    n = float(m.group(1))
    return n / 1000.0 if m.group(2).lower() == "m" else n


def quality_estimate(dep: Deployment, task: str, cfg: RoutingConfig) -> tuple[float, float, str]:
    """Return (quality, uncertainty, evidence). Never presents a prior as a measurement."""
    m = dep.measurements.get(task)
    if m and m.quality is not None and m.samples > 0:
        unc = min(0.5, 1.0 / (m.samples**0.5))
        return float(m.quality), unc, f"measured:{m.samples}"
    # fall back to "any task" measurement as weak evidence
    anym = [x for x in dep.measurements.values() if x.quality is not None and x.samples > 0]
    if anym:
        q = sum(x.quality for x in anym) / len(anym)  # type: ignore[misc]
        return float(q), 0.3, f"measured-other-task:{sum(x.samples for x in anym)}"
    if task in dep.quality_prior:
        return float(dep.quality_prior[task]), 0.25, f"prior:{dep.quality_prior_provenance}"
    if "general" in dep.quality_prior:
        return float(dep.quality_prior["general"]), 0.3, f"prior-general:{dep.quality_prior_provenance}"
    pb = param_count_b(dep)
    if pb is not None:
        # Labelled hypothesis, not a measurement: slightly favour larger checkpoints until measured.
        return min(0.75, cfg.uncalibrated_prior + 0.05 * math.log10(1.0 + pb)), 0.35, "uncalibrated:size-heuristic"
    return float(cfg.uncalibrated_prior), 0.35, "uncalibrated"


def latency_estimate_ms(dep: Deployment, task: str) -> tuple[float, str]:
    m = dep.measurements.get(task)
    if m and m.p50_ms:
        return float(m.p50_ms), "measured"
    anym = [x.p50_ms for x in dep.measurements.values() if x.p50_ms]
    if anym:
        return float(sum(anym) / len(anym)), "measured-other-task"
    pb = param_count_b(dep)
    if pb is not None:
        # Rough heuristic only used for relative ordering: ~ linear in parameter count.
        return 500.0 + 150.0 * pb, "size-heuristic"
    return 3000.0, "unknown-default"


def load_estimate_ms(dep: Deployment) -> tuple[float, str]:
    for m in dep.measurements.values():
        if m.load_ms:
            return float(m.load_ms), "measured"
    if dep.memory_gb_estimate:
        return 800.0 * dep.memory_gb_estimate, "memory-heuristic"
    return 8000.0, "unknown-default"


def blended_quality(dep: Deployment, tasks: dict[str, float], cfg: RoutingConfig) -> tuple[float, float, str]:
    """Confidence-weighted blend over the candidate task labels (robust for ambiguous requests)."""
    if not tasks:
        return quality_estimate(dep, "conversation", cfg)
    total = sum(tasks.values()) or 1.0
    q = u = 0.0
    evs: list[str] = []
    for t, w in tasks.items():
        qt, ut, et = quality_estimate(dep, t, cfg)
        q += w * qt
        u += w * ut
        evs.append(f"{t}={et}")
    top = max(tasks.items(), key=lambda kv: kv[1])[0]
    _, _, top_ev = quality_estimate(dep, top, cfg)
    ev = top_ev if len(tasks) == 1 else f"{top_ev} (blend: {', '.join(evs)})"
    return q / total, u / total, ev


def rank(
    eligible: list[Deployment],
    task: str,
    weights: ProfileWeights,
    cfg: RoutingConfig,
    affinity_dep: str | None = None,
    tasks: dict[str, float] | None = None,
) -> list[Candidate]:
    if not eligible:
        return []
    lat = {d.id: latency_estimate_ms(d, task) for d in eligible}
    load = {d.id: load_estimate_ms(d) for d in eligible}
    max_lat = max(v[0] for v in lat.values()) or 1.0
    max_load = max(v[0] for v in load.values()) or 1.0
    max_mem = max((d.memory_gb_estimate or 0.0) for d in eligible) or 1.0
    cands: list[Candidate] = []
    for d in eligible:
        q, unc, ev = blended_quality(d, tasks or {task: 1.0}, cfg)
        lcost = lat[d.id][0] / max_lat
        rcost = 0.0 if d.loaded else (load[d.id][0] / max_load)
        ocost = (d.memory_gb_estimate or 0.0) / max_mem
        aff = 0.0
        notes = [f"latency:{lat[d.id][1]}", f"load:{load[d.id][1]}"]
        if affinity_dep:
            if d.id == affinity_dep:
                aff = cfg.switching_penalty
                notes.append("affinity: current deployment for this session")
            else:
                aff = -cfg.switching_penalty
                notes.append("switching penalty applied (hysteresis)")
        c = Candidate(d, q, unc, ev, lcost, rcost, ocost, aff, notes=notes)
        c.score = (
            weights.quality * q
            - weights.latency * lcost
            - weights.residency * rcost
            - weights.overhead * ocost
            + aff
        )
        cands.append(c)
    cands.sort(key=lambda c: c.score, reverse=True)
    # Tie-break: candidates whose quality is within the evidence uncertainty of
    # the best quality are "effectively tied"; among those prefer lower overhead.
    best = cands[0]
    # Measured evidence: tolerance follows sampling uncertainty. Priors: a fixed small band.
    tol = best.uncertainty / 2 if best.evidence.startswith("measured") else 0.03
    tied = [c for c in cands if abs(c.quality - best.quality) <= tol and abs(c.score - best.score) <= tol]
    if len(tied) > 1:
        cheapest = min(tied, key=lambda c: (c.residency_cost + c.latency_cost + c.overhead_cost - c.affinity_adjust))
        if cheapest is not best:
            cheapest.notes.append("tie-break: effectively tied on quality; lower overhead preferred")
            cands.remove(cheapest)
            cands.insert(0, cheapest)
    return cands
