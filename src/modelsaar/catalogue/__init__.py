"""Verified starter catalogue: model-card evidence (sources + dates), kept
separate from locally probed capabilities and measured task performance.

Matching a discovered deployment to a catalogue entry only supplies *priors*
(labelled ``catalogue``) and tags. It never asserts a capability as
"supported" on its own: card claims become ``source_claim`` evidence, which
the eligibility filter still treats as a claim, not a probe. Operators can
promote a claim with an override or verify it with ``modelsaar probe``.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml

from ..registry import Deployment, merge_capabilities

_CATALOGUE_PATH = Path(__file__).parent / "starter.yaml"


def load_catalogue(extra_paths: list[Path] | None = None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for p in [_CATALOGUE_PATH, *(extra_paths or [])]:
        if p.exists():
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            entries.extend(data.get("entries", []))
    return entries


def match_entry(dep: Deployment, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    name = dep.model.lower()
    for e in entries:
        for pat in e.get("match", {}).get("ollama", []) or []:
            if fnmatch.fnmatch(name, pat.lower()):
                return e
        for pat in e.get("match", {}).get("names", []) or []:
            if fnmatch.fnmatch(name, pat.lower()):
                return e
    return None


def apply_catalogue(dep: Deployment, entries: list[dict[str, Any]]) -> str | None:
    e = match_entry(dep, entries)
    if not e:
        return None
    if e.get("enabled_by_default") is False or e.get("availability") != "released_weights":
        # Unresolved/announced entries never contribute defaults.
        return None
    dep.catalogue_id = e["id"]
    dep.publisher = dep.publisher or e.get("publisher", "")
    for t in e.get("tags", []) or []:
        if t not in dep.tags:
            dep.tags.append(t)
    if e.get("role") and dep.role == "generative" and e["role"] != "generative":
        dep.role = e["role"]
    # The card's context length is informational only; the *served* context comes from the runtime
    # or an operator override, never from the catalogue.
    if e.get("context_length"):
        dep.raw_metadata["catalogue_context_length"] = int(e["context_length"])
    claims = {k: v for k, v in (e.get("capability_claims") or {}).items()}
    if claims:
        merge_capabilities(dep, claims, "source_claim", note=f"catalogue {e['id']} (model card)")
    priors = e.get("quality_prior") or {}
    if priors and not dep.quality_prior:
        dep.quality_prior = {k: float(v) for k, v in priors.items()}
        dep.quality_prior_provenance = "catalogue"  # model-card/vendor derived hypothesis, NOT a local measurement
    if e.get("intended_use_note"):
        dep.intended_use_note = e["intended_use_note"]
    return e["id"]
