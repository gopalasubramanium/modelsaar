"""Hard eligibility filters. A failed constraint can never be overridden by a score."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..config import AliasConfig, SecurityConfig
from ..registry import Deployment
from .requirements import Requirements


@dataclass
class Exclusion:
    deployment_id: str
    reasons: list[str] = field(default_factory=list)
    remedies: list[str] = field(default_factory=list)


@dataclass
class EligibilityResult:
    eligible: list[Deployment]
    exclusions: list[Exclusion]

    def blockers_summary(self) -> dict[str, list[str]]:
        return {e.deployment_id: e.reasons for e in self.exclusions}


# Capabilities a live probe can establish (``modelsaar probe <deployment> --which <capability>``). Kept in
# step with ``probes.PROBE_NAMES`` minus the latency measurement (checked by a unit test); the remedy text
# must never point at a probe that does not exist.
_PROBEABLE = frozenset({"streaming", "tools", "parallel_tools", "json_object", "json_schema", "vision", "continuation"})


def _cap_check(dep: Deployment, key: str, label: str, ex: Exclusion) -> None:
    v = dep.cap(key)
    if v == "unsupported":
        ex.reasons.append(f"{label} required; capability {key} is unsupported ({dep.capabilities[key].provenance})")
        ex.remedies.append(f"use a deployment whose {key} capability is supported")
    elif v == "unknown":
        ex.reasons.append(f"{label} required; capability {key} is unknown (treated conservatively as not eligible)")
        override = f"declare `capabilities: {{{key}: supported}}` for {dep.model} under deployments[] (operator provenance)"
        if key in _PROBEABLE:
            ex.remedies.append(f"run `modelsaar probe {dep.id} --which {key}` to verify {key}, or {override}")
        else:
            ex.remedies.append(f"no live probe exists for {key}; {override}")
        if key == "continuation":
            ex.remedies.append(
                "a context-length exclusion on the same deployment is separate: raising context_length/num_ctx does not "
                "establish continuation support, and probing continuation does not change the context limit"
            )


def filter_deployments(
    deps: list[Deployment],
    req: Requirements,
    security: SecurityConfig,
    alias: AliasConfig | None = None,
    explicit_model: str | None = None,
    feasibility: Callable[[Deployment], str | None] | None = None,
    backend_unsupported_fields: Callable[[Deployment], frozenset[str]] | None = None,
    request_fields: set[str] | None = None,
    exact_input_tokens: dict[str, int] | None = None,
) -> EligibilityResult:
    eligible: list[Deployment] = []
    exclusions: list[Exclusion] = []
    for dep in deps:
        # The reasoning allowance only applies to deployments that can think.
        total_tokens = 0
        input_tokens = req.tokens.input_estimate if req.tokens else 0
        method = req.tokens.method if req.tokens else ""
        if exact_input_tokens and dep.id in exact_input_tokens:
            input_tokens = exact_input_tokens[dep.id]
            method = f"tokenize:{dep.backend_id}+template-estimate"
        if req.tokens:
            total_tokens = input_tokens + req.tokens.output_allowance
            if dep.cap("thinking") == "supported":
                total_tokens += req.tokens.reasoning_allowance
        ex = Exclusion(dep.id)
        if explicit_model and dep.id != explicit_model and dep.model != explicit_model:
            continue  # not a candidate at all; no exclusion record
        if alias and alias.deployments and dep.id not in alias.deployments:
            continue
        if not dep.enabled:
            ex.reasons.append("deployment disabled by configuration")
        if not dep.healthy:
            ex.reasons.append(f"backend unhealthy: {dep.last_error or 'health check failed'}")
            ex.remedies.append("check that the inference server is running (`modelsaar doctor`)")
        if dep.role != req.role:
            ex.reasons.append(f"role mismatch: request needs {req.role}, deployment role is {dep.role}")
        if security.locality_mode == "local_only" and dep.locality != "local":
            ex.reasons.append(
                f"locality policy local_only; deployment locality is {dep.locality} ({dep.locality_evidence[:80]})"
            )
            ex.remedies.append("set security.locality_mode: allow_remote only if remote inference is acceptable")
        if alias and alias.require_tags and not set(alias.require_tags) <= set(dep.tags):
            ex.reasons.append(f"alias requires tags {list(alias.require_tags)}; deployment has {dep.tags}")
        if alias and alias.require_vision and dep.cap("vision") != "supported":
            ex.reasons.append("alias requires vision; capability vision is not supported/verified")
        if req.role == "generative":
            if req.needs_tools and req.tool_choice_mode != "none":
                _cap_check(dep, "tools", "tool calling", ex)
            if req.tool_choice_mode in ("required", "named"):
                _cap_check(dep, "tool_choice_required", "tool_choice=required/named", ex)
            if req.needs_parallel_tools:
                _cap_check(dep, "parallel_tools", "parallel tool calls", ex)
            if req.needs_json_schema:
                _cap_check(dep, "json_schema", "strict JSON schema output", ex)
            if req.needs_json_object:
                _cap_check(dep, "json_object", "JSON object output", ex)
            if req.needs_streaming:
                _cap_check(dep, "streaming", "streaming", ex)
            if req.needs_vision:
                _cap_check(dep, "vision", "image input", ex)
                if req.has_remote_image_url and not security.fetch_remote_media:
                    ex.reasons.append(
                        "request references a remote image URL; the gateway does not fetch remote media "
                        "and the backend path requires inline base64 images"
                    )
                    ex.remedies.append("send images as data: URLs (base64)")
            if req.needs_audio:
                _cap_check(dep, "audio_in", "audio input", ex)
            if req.needs_continuation:
                _cap_check(dep, "continuation", "reasoning continuation state", ex)
            if dep.context_length is None:
                ex.reasons.append("effective context length unknown (treated conservatively as not eligible)")
                ex.remedies.append(
                    f"declare context_length for {dep.model} under backends[].models or deployments[] overrides"
                )
            elif total_tokens > dep.context_length:
                ex.reasons.append(
                    f"effective context {dep.context_length} < required {total_tokens} "
                    f"(input~{input_tokens} + output {req.tokens.output_allowance}"
                    f"{' + reasoning ' + str(req.tokens.reasoning_allowance) if dep.cap('thinking') == 'supported' else ''}; "
                    f"{method})"
                )
                ex.remedies.append("shorten the conversation, lower max_tokens, or serve the model with a larger context")
            if dep.max_output_tokens and req.tokens and req.tokens.output_allowance > dep.max_output_tokens:
                ex.reasons.append(
                    f"requested output {req.tokens.output_allowance} exceeds deployment max_output_tokens {dep.max_output_tokens}"
                )
            if backend_unsupported_fields and request_fields:
                bad = sorted(request_fields & backend_unsupported_fields(dep))
                if bad:
                    ex.reasons.append(f"backend path cannot honour request field(s) {bad}")
                    ex.remedies.append("remove the field or choose a backend that supports it")
        if feasibility:
            why = feasibility(dep)
            if why:
                ex.reasons.append(why)
        if ex.reasons:
            exclusions.append(ex)
        else:
            eligible.append(dep)
    return EligibilityResult(eligible=eligible, exclusions=exclusions)
