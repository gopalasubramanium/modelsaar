"""Router: orchestrates discovery, evidence, eligibility, classification, ranking
and decision recording. It never dispatches; the server does that so that
response-commitment rules stay in one place.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Any
from urllib.parse import urlsplit

from ..adapters import ADAPTER_TYPES, BaseAdapter
from ..catalogue import apply_catalogue, load_catalogue
from ..config import Config
from ..registry import Deployment, Measurement, Registry, merge_capabilities
from ..store import Store
from .admission import Admission, AdmissionRejected
from .affinity import AffinityStore
from .classifier import LocalClassifier
from .decision import Decision
from .eligibility import filter_deployments
from .requirements import Requirements, analyze_chat
from .scoring import rank

log = logging.getLogger("modelsaar.router")


class NoEligibleDeployment(Exception):
    def __init__(self, decision: Decision) -> None:
        super().__init__("no eligible deployment")
        self.decision = decision


class Router:
    def __init__(self, cfg: Config, store: Store | None = None) -> None:
        self.cfg = cfg
        self.store = store
        self.registry = Registry()
        allowed = set(cfg.security.allowed_backend_hosts)
        for b in cfg.backends:
            parts = urlsplit(b.base_url)
            allowed.add(parts.netloc)
            if parts.hostname:
                allowed.add(parts.hostname)
        self.allowed_hosts = allowed
        self.adapters: dict[str, BaseAdapter] = {}
        for b in cfg.backends:
            cls = ADAPTER_TYPES.get(b.type)
            if not cls:
                raise ValueError(f"unknown backend type {b.type}")
            self.adapters[b.id] = cls(b, allowed)
        self.admission = Admission(cfg.admission, list(cfg.resource_pools), list(cfg.backends))
        self.affinity = AffinityStore(cfg.affinity)
        self.classifier = LocalClassifier(cfg.routing.classifier)
        self.catalogue = load_catalogue()
        self._refresh_lock = asyncio.Lock()
        self.last_refresh_error: str = ""

    async def aclose(self) -> None:
        for a in self.adapters.values():
            await a.aclose()

    # ------------------------------------------------------------------ #
    # Discovery & evidence
    # ------------------------------------------------------------------ #
    async def refresh(self) -> None:
        async with self._refresh_lock:
            deps: list[Deployment] = []
            errors: list[str] = []
            results = await asyncio.gather(
                *[self._discover_backend(bid, a) for bid, a in self.adapters.items()], return_exceptions=True
            )
            for (bid, _), res in zip(self.adapters.items(), results, strict=True):
                if isinstance(res, Exception):
                    errors.append(f"{bid}: {res}")
                    # keep previous records for this backend but mark unhealthy
                    for d in self.registry.by_backend(bid):
                        d.healthy = False
                        d.last_error = str(res)[:200]
                        deps.append(d)
                else:
                    deps.extend(res)
            for d in deps:
                self._apply_overrides(d)
                apply_catalogue(d, self.catalogue)
                d.compute_fingerprint()
                self._apply_stored_evidence(d)
            self.registry.replace(deps)
            self.last_refresh_error = "; ".join(errors)

    async def _discover_backend(self, bid: str, adapter: BaseAdapter) -> list[Deployment]:
        return await adapter.discover()

    def _apply_overrides(self, d: Deployment) -> None:
        for o in self.cfg.deployments:
            if o.backend != d.backend_id or o.model != d.model:
                continue
            d.configured = True
            if o.enabled is not None:
                d.enabled = o.enabled
            if o.role:
                d.role = o.role
            if o.context_length:
                d.context_length = o.context_length
                d.raw_metadata["num_ctx_source"] = "operator override"
            if o.max_output_tokens:
                d.max_output_tokens = o.max_output_tokens
            if o.tags is not None:
                d.tags = list(o.tags)
            if o.catalogue_id:
                d.catalogue_id = o.catalogue_id
            if o.memory_gb_estimate:
                d.memory_gb_estimate = o.memory_gb_estimate
                d.memory_estimate_provenance = "operator override"
            if o.capabilities:
                merge_capabilities(
                    d, {k: v for k, v in o.capabilities.model_dump().items() if v != "unknown"}, "operator",
                    note="config deployments[] override",
                )
            if o.quality_prior:
                d.quality_prior = dict(o.quality_prior)
                d.quality_prior_provenance = "operator"
            if o.intended_use_note:
                d.intended_use_note = o.intended_use_note

    def _apply_stored_evidence(self, d: Deployment) -> None:
        if not self.store:
            return
        probes = self.store.load_probes(d.id, d.fingerprint)
        caps = {k: v["value"] for k, v in probes.items()}
        if caps:
            merge_capabilities(d, caps, "probe", note="stored probe for current fingerprint")  # type: ignore[arg-type]
        stale = self.store.stale_probe_fingerprints(d.id, d.fingerprint)
        if stale:
            d.raw_metadata["invalidated_probe_fingerprints"] = stale
        for m in self.store.load_measurements(d.id, d.fingerprint):
            d.measurements[m["task"]] = Measurement(**m)

    async def refresh_residency(self) -> None:
        """Cheap update of loaded/healthy flags without full discovery."""
        for bid, a in self.adapters.items():
            ok, msg = await a.health()
            loaded = await a.loaded_models() if ok else {}
            for d in self.registry.by_backend(bid):
                d.healthy = ok
                d.health_checked_at = time.time()
                d.last_error = "" if ok else msg
                d.loaded = d.model in loaded
                if d.loaded:
                    d.loaded_observed_at = time.time()

    # ------------------------------------------------------------------ #
    # Alias availability (truthful /v1/models)
    # ------------------------------------------------------------------ #
    def usable_generative(self) -> list[Deployment]:
        return [
            d
            for d in self.registry.all()
            if d.enabled and d.healthy and d.role == "generative"
            and (self.cfg.security.locality_mode == "allow_remote" or d.locality == "local")
        ]

    def alias_contract(self, name: str) -> dict[str, Any] | None:
        a = self.cfg.aliases.get(name)
        if not a:
            return None
        pool = self.usable_generative()
        if a.deployments:
            pool = [d for d in pool if d.id in a.deployments]
        if a.require_tags:
            pool = [d for d in pool if set(a.require_tags) <= set(d.tags)]
        if a.require_vision:
            pool = [d for d in pool if d.cap("vision") == "supported"]
        if not pool:
            return None
        ctx = [d.context_length for d in pool if d.context_length]
        return {
            "id": name,
            "profile": a.profile,
            "deployments": [d.id for d in pool],
            # Truthful contract: the alias guarantees only what *every* member provides.
            "context_length_min": min(ctx) if ctx else None,
            "context_length_max": max(ctx) if ctx else None,
            "tools": "supported" if all(d.cap("tools") == "supported" for d in pool) else (
                "partial" if any(d.cap("tools") == "supported" for d in pool) else "unsupported"
            ),
            "vision": "supported" if all(d.cap("vision") == "supported" for d in pool) else (
                "partial" if any(d.cap("vision") == "supported" for d in pool) else "unsupported"
            ),
            "json_schema": "supported" if all(d.cap("json_schema") == "supported" for d in pool) else (
                "partial" if any(d.cap("json_schema") == "supported" for d in pool) else "unsupported"
            ),
            "description": a.description,
        }

    def models_listing(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        now = int(time.time())
        for name in self.cfg.aliases:
            c = self.alias_contract(name)
            if c:
                out.append({"id": name, "object": "model", "created": now, "owned_by": "modelsaar", "modelsaar": c})
        for d in self.registry.all():
            if not (d.enabled and d.healthy):
                continue
            if self.cfg.security.locality_mode == "local_only" and d.locality != "local":
                continue
            out.append(
                {
                    "id": d.id,
                    "object": "model",
                    "created": now,
                    "owned_by": d.backend_id,
                    "modelsaar": {
                        "role": d.role,
                        "context_length": d.context_length,
                        "tools": d.cap("tools"),
                        "vision": d.cap("vision"),
                        "json_schema": d.cap("json_schema"),
                        "locality": d.locality,
                    },
                }
            )
        return out

    # ------------------------------------------------------------------ #
    # Routing
    # ------------------------------------------------------------------ #
    def resolve_model(self, requested: str) -> tuple[str | None, Deployment | None]:
        """Return (alias_name, explicit_deployment)."""
        if requested in self.cfg.aliases:
            return requested, None
        d = self.registry.get(requested)
        if d:
            return None, d
        # Allow bare model names when unambiguous across backends.
        matches = [x for x in self.registry.all() if x.model == requested]
        if len(matches) == 1:
            return None, matches[0]
        return None, None

    async def route_chat(self, body: dict[str, Any], headers: dict[str, str], caller_id: str) -> Decision:
        t0 = time.monotonic()
        dec = Decision(config_hash=self.cfg.config_hash, registry_version=self.registry.version)
        dec.requested_model = str(body.get("model", ""))
        dec.stream = bool(body.get("stream"))
        alias_name, explicit = self.resolve_model(dec.requested_model)
        if alias_name is None and explicit is None:
            dec.outcome = "unknown_model"
            dec.reasons.append(f"model {dec.requested_model!r} is neither an alias nor a known deployment")
            dec.remedies.append("GET /v1/models lists the available aliases and deployments")
            dec.overhead_ms = (time.monotonic() - t0) * 1000
            raise NoEligibleDeployment(dec)
        alias = self.cfg.aliases.get(alias_name) if alias_name else None
        dec.alias = alias_name
        dec.explicit = explicit is not None
        hint = body.get("modelsaar") if isinstance(body.get("modelsaar"), dict) else {}
        profile = hint.get("profile") if hint else None
        if profile not in ("quality", "balanced", "fast"):
            profile = alias.profile if alias else self.cfg.routing.default_profile
        dec.profile = profile

        thinking_possible = any(d.cap("thinking") == "supported" for d in self.registry.all())
        req = analyze_chat(body, self.cfg.routing.token_estimate, thinking_possible)
        request_fields = set(body.keys())

        # --- exact token counts where the runtime offers them (bounded: borderline cases only) ---
        exact = await self._exact_counts(body, req)
        if exact:
            dec.requirements_note = f"exact token counts used for {sorted(exact)}"

        # --- hard filters --------------------------------------------------
        deps = self.registry.all()
        res = filter_deployments(
            deps,
            req,
            self.cfg.security,
            alias=alias,
            explicit_model=explicit.id if explicit else None,
            feasibility=self.admission.feasibility,
            backend_unsupported_fields=lambda d: self.adapters[d.backend_id].unsupported_fields(),
            request_fields=request_fields,
            exact_input_tokens=exact or None,
        )
        dec.exclusions = res.blockers_summary()
        dec.remedies = sorted({r for e in res.exclusions for r in e.remedies})

        # --- optional classifier (only refines the task label) ------------
        if res.eligible and self.classifier.should_run(req):
            cdep = self._classifier_deployment()
            if cdep is None:
                dec.classifier = {"used": False, "status": "unavailable", "note": "configured classifier deployment not found"}
            else:
                try:
                    reservation = await self.admission.acquire(cdep, timeout=self.cfg.routing.classifier.timeout_s)
                except AdmissionRejected:
                    reservation = None
                    dec.classifier = {"used": False, "status": "skipped", "note": "classifier deployment at capacity"}
                if reservation is not None:
                    try:
                        out = await self.classifier.classify(self.adapters[cdep.backend_id], cdep, body, req)
                    finally:
                        await reservation.release()
                    dec.classifier = out.as_dict()
                    if out.used and out.task and out.confidence is not None and out.confidence >= 0.5:
                        req.tasks[out.task] = max(req.tasks.get(out.task, 0.0), round(out.confidence, 2))
                        req.primary_task = out.task
                        req.signals.append(f"classifier:{out.task}@{out.confidence:.2f}")
        elif self.cfg.routing.classifier.enabled:
            dec.classifier = {"used": False, "status": "skipped", "note": "deterministic classification was not ambiguous"}
        dec.requirements = req.as_dict()

        if not res.eligible:
            only_admission = [
                e for e in res.exclusions if e.reasons and all(r.startswith(("admission queue", "circuit open")) for r in e.reasons)
            ]
            if only_admission:
                dec.outcome = "admission_rejected"
                dec.reasons.append(
                    f"{len(only_admission)} otherwise-eligible deployment(s) are at capacity or circuit-broken; retry shortly"
                )
            else:
                dec.outcome = "no_eligible"
                dec.reasons.append("no deployment satisfies all hard requirements")
            dec.overhead_ms = (time.monotonic() - t0) * 1000
            self._record(dec)
            raise NoEligibleDeployment(dec)

        # --- affinity ------------------------------------------------------
        affinity_dep: str | None = None
        session_key, source = self.affinity.extract_session_key(headers, body)
        if self.cfg.affinity.mode == "session" and session_key:
            e = self.affinity.get(caller_id, session_key)
            if e:
                affinity_dep = e.deployment_id
                dec.affinity = {"session_source": source, "pinned": e.deployment_id, "status": "found"}
            else:
                dec.affinity = {"session_source": source, "status": "new"}
        else:
            dec.affinity = {"session_source": source, "status": "stateless" if not session_key else "disabled"}
        if self.cfg.affinity.tool_round_trip_affinity and req.is_tool_result_turn and req.outstanding_tool_call_ids:
            e = self.affinity.lookup_tool_round(caller_id, req.outstanding_tool_call_ids)
            if e:
                affinity_dep = e.deployment_id
                dec.affinity["tool_round_trip"] = e.deployment_id
        eligible_ids = {d.id for d in res.eligible}
        if affinity_dep and affinity_dep not in eligible_ids:
            # Hard policy is revalidated every request: a pinned deployment that no longer
            # qualifies is not used; a tool round trip must not be handed to another model.
            if req.is_tool_result_turn and dec.affinity.get("tool_round_trip"):
                dec.outcome = "affinity_broken"
                dec.reasons.append(
                    f"tool round trip was started on {affinity_dep}, which is no longer eligible; refusing cross-model handover"
                )
                dec.remedies.append("retry once the original deployment is healthy, or start a new run")
                dec.overhead_ms = (time.monotonic() - t0) * 1000
                self._record(dec)
                raise NoEligibleDeployment(dec)
            dec.affinity["status"] = "pinned_ineligible_rerouted"
            affinity_dep = None

        # --- rank ----------------------------------------------------------
        weights = getattr(self.cfg.routing.profiles, profile)
        cands = rank(res.eligible, req.primary_task, weights, self.cfg.routing, affinity_dep, tasks=req.tasks)
        # A pinned deployment that is still eligible always wins (continuity beats score).
        if affinity_dep:
            for i, c in enumerate(cands):
                if c.deployment.id == affinity_dep:
                    if i != 0:
                        cands.insert(0, cands.pop(i))
                    c.notes.append("affinity: pinned deployment kept")
                    break
        dec.candidates = [c.as_dict() for c in cands]
        chosen = cands[0]
        dec.chosen = chosen.deployment.id
        dec.evidence = chosen.evidence.split(' (blend')[0]
        dec.reasons.extend(self._reasons(dec, chosen, len(res.eligible), len(res.exclusions)))
        dec.overhead_ms = (time.monotonic() - t0) * 1000
        dec.outcome = "routed"
        # Session pinning happens after a successful dispatch (server calls pin_session), so a
        # pre-commit failover pins the deployment that actually answered.
        if self.cfg.affinity.mode == "session" and session_key:
            dec._session = (session_key, source)  # type: ignore[attr-defined]  # not serialized
        return dec

    def pin_session(self, dec: Decision, caller_id: str, dep_id: str) -> None:
        sess = getattr(dec, "_session", None)
        if sess:
            self.affinity.set(caller_id, sess[0], dep_id, sess[1])

    async def _exact_counts(self, body: dict[str, Any], req: Requirements) -> dict[str, int]:
        """Ask runtimes with a tokenizer endpoint (vLLM /tokenize) for exact input counts, only for
        deployments where the estimate is within +-50% of the context limit (the cases where an
        estimate could wrongly include or exclude them)."""
        if not req.tokens:
            return {}
        from .tokens import _text_of

        text: str | None = None
        out: dict[str, int] = {}
        for d in self.registry.all():
            if not (d.enabled and d.healthy and d.role == "generative" and d.context_length):
                continue
            est_total = req.tokens.input_estimate + req.tokens.output_allowance + (
                req.tokens.reasoning_allowance if d.cap("thinking") == "supported" else 0
            )
            if not (0.5 * d.context_length <= est_total <= 1.5 * d.context_length):
                continue
            adapter = self.adapters.get(d.backend_id)
            if adapter is None or adapter.tokenize.__func__ is BaseAdapter.tokenize:  # type: ignore[attr-defined]
                continue
            if text is None:
                parts = []
                for m in body.get("messages") or []:
                    if isinstance(m, dict):
                        t, _ = _text_of(m.get("content"))
                        parts.append(t)
                        if m.get("tool_calls"):
                            parts.append(json.dumps(m["tool_calls"]))
                for t in body.get("tools") or []:
                    parts.append(json.dumps(t))
                text = "\n".join(parts)
            try:
                n = await adapter.tokenize(d, text)
            except Exception:  # noqa: BLE001 - exact counting is best effort; the estimate stands
                n = None
            if isinstance(n, int) and n > 0:
                # Keep the per-message/template/image overheads on top of the exact text count.
                overhead = req.tokens.input_estimate - math.ceil(len(text) / self.cfg.routing.token_estimate.chars_per_token)
                out[d.id] = n + max(0, overhead)
        return out

    def _classifier_deployment(self) -> Deployment | None:
        c = self.cfg.routing.classifier
        d = self.registry.get(f"{c.backend}/{c.model}")
        if d and d.healthy and d.enabled and (self.cfg.security.locality_mode == "allow_remote" or d.locality == "local"):
            return d
        return None

    def _reasons(self, dec: Decision, chosen, n_eligible: int, n_excluded: int) -> list[str]:
        r = []
        req = dec.requirements
        needs = []
        if req.get("needs_tools"):
            needs.append("tool support")
        if req.get("needs_vision"):
            needs.append("image input")
        if req.get("needs_json_schema"):
            needs.append("strict JSON schema")
        if req.get("needs_continuation"):
            needs.append("reasoning continuation")
        r.append(
            f"task={req.get('primary_task')} ({'ambiguous' if req.get('ambiguous') else 'clear'}); "
            f"required: {', '.join(needs) if needs else 'no special capabilities'}; "
            f"context need ~{(req.get('tokens') or {}).get('total')} tokens"
        )
        if n_excluded:
            r.append(f"{n_excluded} deployment(s) excluded by hard filters; {n_eligible} eligible")
        if n_eligible == 1:
            r.append("single eligible deployment; ranking skipped (minimal overhead)")
        else:
            r.append(
                f"{chosen.deployment.id} ranked first on profile {dec.profile}: quality {chosen.quality:.2f} "
                f"({chosen.evidence}), latency cost {chosen.latency_cost:.2f}, "
                f"{'resident' if chosen.deployment.loaded else 'not resident'}"
            )
        if chosen.evidence == "uncalibrated":
            r.append("evidence level: UNCALIBRATED prior - run `modelsaar eval` to measure this deployment")
        return r

    def _record(self, dec: Decision) -> None:
        if self.store and self.cfg.observability.decision_log:
            try:
                self.store.save_decision(dec.request_id, dec.as_dict(), self.cfg.observability.retention_days)
            except Exception as e:  # pragma: no cover
                log.warning("decision log write failed: %s", e)

    def record(self, dec: Decision) -> None:
        self._record(dec)

    # ------------------------------------------------------------------ #
    async def route_embeddings(self, body: dict[str, Any], caller_id: str) -> Decision:
        t0 = time.monotonic()
        dec = Decision(config_hash=self.cfg.config_hash, registry_version=self.registry.version, endpoint="embeddings")
        dec.requested_model = str(body.get("model", ""))
        req = Requirements(role="embedding")
        contract = next((c for c in self.cfg.embeddings if c.alias == dec.requested_model), None)
        candidates: list[Deployment] = []
        if contract:
            dec.alias = contract.alias
            for did in contract.deployments:
                d = self.registry.get(did)
                if d:
                    candidates.append(d)
                else:
                    dec.exclusions[did] = ["deployment not discovered"]
        else:
            _, explicit = self.resolve_model(dec.requested_model)
            if explicit:
                candidates = [explicit]
                dec.explicit = True
        if not candidates and contract:
            dec.outcome = "no_eligible"
            dec.reasons.append(
                f"embedding contract {contract.alias!r} references deployments that are not discovered; "
                "fallback to a different model is refused"
            )
            dec.remedies.append("restore the contract's model or run an explicit re-indexing migration")
            dec.overhead_ms = (time.monotonic() - t0) * 1000
            self._record(dec)
            raise NoEligibleDeployment(dec)
        if not candidates:
            dec.outcome = "unknown_model"
            dec.reasons.append(f"embedding model/alias {dec.requested_model!r} not found")
            dec.remedies.append("declare an embeddings contract in config or use a discovered embedding deployment id")
            dec.overhead_ms = (time.monotonic() - t0) * 1000
            raise NoEligibleDeployment(dec)
        res = filter_deployments(candidates, req, self.cfg.security, feasibility=self.admission.feasibility)
        dec.exclusions.update(res.blockers_summary())
        if contract and contract.dimensions:
            keep = []
            for d in res.eligible:
                if d.embedding_dimensions and d.embedding_dimensions != contract.dimensions:
                    dec.exclusions[d.id] = [
                        f"embedding dimensions {d.embedding_dimensions} differ from contract {contract.dimensions}"
                    ]
                else:
                    keep.append(d)
            res.eligible = keep
        if not res.eligible:
            dec.outcome = "no_eligible"
            dec.reasons.append("no deployment satisfies the embedding contract; fallback to an incompatible model is refused")
            dec.remedies.append("restore the contract's model or run an explicit re-indexing migration")
            dec.overhead_ms = (time.monotonic() - t0) * 1000
            self._record(dec)
            raise NoEligibleDeployment(dec)
        # Prefer resident deployment among contract members (all are the same model revision by contract).
        res.eligible.sort(key=lambda d: (not d.loaded, d.id))
        dec.chosen = res.eligible[0].id
        dec.evidence = "contract"
        dec.reasons.append(
            f"embedding contract {'alias ' + contract.alias if contract else 'explicit deployment'}; "
            f"{dec.chosen} selected ({'resident' if res.eligible[0].loaded else 'not resident'})"
        )
        dec.overhead_ms = (time.monotonic() - t0) * 1000
        dec.outcome = "routed"
        return dec
