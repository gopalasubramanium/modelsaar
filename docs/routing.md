# Routing: how a deployment is chosen and how to inspect it

## A. Requirements

`routing/requirements.py` reads the whole request structurally (never the model's output, never
instructions inside prompts):

* role needed (`generative` for chat, `embedding` for `/v1/embeddings`)
* `tools` present and `tool_choice` mode (`auto` / `none` / `required` / `named`), `parallel_tool_calls`
* `response_format` → strict `json_schema` or `json_object`
* `stream`
* image parts (`image_url` / `input_image`) → vision; remote `http(s)` image URLs flagged
* `input_audio` → audio (no 0.1 deployment supports it; clear rejection)
* `reasoning_content` in assistant history → continuation state must be preserved
* outstanding tool-call ids: assistant `tool_calls` answered by `tool` messages in this turn
* task labels (multi-label, 0..1): conversation, coding, agent, math, extraction, document_vision,
  translation, summarization, rag, decision; `ambiguous` when the top label is weak or contested
* languages (script detection + light lexical hints) and a `multilingual` flag
* token budget: `input_estimate` (chars/3 for Latin text, 1 token per CJK/other wide character, + per-message, per-tool and per-image overheads, +5 %; refined with the runtime's `/tokenize` for deployments that passed every policy/capability filter and whose estimate lands within ±50 % of their context, under one deadline `token_estimate.exact_count_deadline_s`; the result is labelled `tokenize:<backend>+template-estimate` because template/image overheads stay estimated),
  `output_allowance` (`max_tokens`/`max_completion_tokens` or default 1024), `reasoning_allowance`
  (applied only to deployments whose `thinking` capability is supported)

Length is never used to infer difficulty; a short "Is 97 prime?" is `math`, a 300-sentence
"summarize" is `summarization`.

## B. Hard filters (`routing/eligibility.py`)

Per deployment, each failed check adds a reason and a remedy. Checks: enabled, healthy, role,
locality policy (`security.locality_mode`), alias constraints (`require_tags`, `require_vision`,
explicit `deployments`), capabilities (`tools`, `tool_choice_required`, `parallel_tools`,
`json_schema`, `json_object`, `streaming`, `vision`, `audio_in`, `continuation`), remote image URLs,
effective context (`input + output [+ reasoning] <= context_length`), `max_output_tokens`, request
fields the backend path cannot honour, and admission feasibility (non-reserving).

Capability values: `supported` passes; `unsupported` fails; **`unknown` fails** (conservative) with
the remedy "run `modelsaar probe <id>` or declare it under `deployments[]`".

Explicit deployment selection goes through the same checks.

## C. Classification

Deterministic signals handle clear cases at ~0.3–0.6 ms overhead. The optional local classifier
(`routing.classifier`) runs only when `enabled` and (by default) only when the deterministic result
is ambiguous. Contract:

* input: structural facts + a truncated excerpt of the last user text (`max_input_chars`)
* output, `mode: chat` (default): `{"task": <one of the closed label set>, "confidence": 0..1}` via
  `response_format` (`json_schema` if the deployment supports it, else `json_object`), `temperature 0`,
  `max_tokens 64`
* output, `mode: decision`: the deployment must be a decision model (`role=decision`, e.g. Ollama's
  `nimble`, `clef`, `laya`, discovered from the `decision` capability); the gateway asks its native
  decision endpoint (Ollama `POST /v1/systemone`) one `choice` question whose criteria are the closed
  label set and takes the answer's arg-max label with that label's probability as the confidence —
  no free text is generated or parsed
* `timeout_s`; any timeout, error, or out-of-contract answer → deterministic result stands
* it calls its configured deployment directly (never `auto`), cannot invent endpoints, change
  requirements/capabilities or policy, and its memory/latency is visible in `/admin/status`

A text-only classifier never claims to inspect image contents; it only sees `has_images`.

## D. Ranking (`routing/scoring.py`)

For each eligible deployment:

| component | source | label |
|---|---|---|
| `quality` | measured success for the task (eval/probe, keyed by fingerprint) → else catalogue/operator prior → else uncalibrated prior (0.5 + small size heuristic, capped 0.75) | `measured:<n>`, `prior:<provenance>`, `uncalibrated[:size-heuristic]` |
| `uncertainty` | `1/sqrt(n)` for measured; 0.25 prior; 0.35 uncalibrated | |
| `latency_cost` | measured p50 for the task → else parameter-size heuristic, normalised among candidates | `latency:measured` / `size-heuristic` |
| `residency_cost` | 0 if loaded, else normalised load-time estimate (measured or memory heuristic) | |
| `overhead_cost` | normalised memory estimate | |
| `affinity_adjust` | ± `routing.switching_penalty` for the session's current deployment (hysteresis) | |

`score = w_q·quality − w_lat·latency_cost − w_res·residency_cost − w_over·overhead_cost + affinity`

Profiles (`routing.profiles`): quality (1.0, 0.15, 0.10, 0.05), balanced (1.0, 0.45, 0.30, 0.10),
fast (0.6, 1.0, 0.6, 0.2). When the quality of two candidates is within the evidence tolerance
(`uncertainty/2` for measured, 0.03 for priors) the lower-overhead one wins — which means that with no
measurements, `auto` prefers the cheaper of effectively-tied models. Run `modelsaar eval --mode live
--save-measurements` to replace priors with measurements on your hardware.

For ambiguous requests quality is blended across the candidate task labels weighted by confidence.

## E. Affinity and continuity

* Session keys come only from explicit sources, in a fixed order of precedence: `modelsaar.session`
  in the body, the client-compatibility body field `session_id` (llama.cpp-style clients such as
  Odysseus; validated as a non-empty printable string ≤ 256 characters), configured headers
  (`X-ModelSaar-Session`, `X-OpenWebUI-Chat-Id`, …), configured body fields (`prompt_cache_key`).
  When sources carry different ids the first wins and the rest appear in the decision as
  `affinity.ignored_hints`. Keys are scoped to the authenticated caller. API keys and system prompts
  are never session ids. Entries expire after `affinity.ttl_s`.
* `cache_prompt` (same clients) is consumed, never forwarded: `true` is an advisory hint recorded in
  the decision (`compat.cache_prompt`; the backend manages its own prompt cache, no hit is promised);
  `false` is refused with `400 unsupported_capability` because no shipped backend path can guarantee
  a per-request cache bypass. See [Odysseus](clients/odysseus.md).
* Tool round trips keep their deployment even without a session id: the gateway remembers the
  tool-call ids it returned and pins the follow-up carrying their results. If the pinned deployment
  is no longer eligible, the request fails (`affinity_broken`) rather than handing a tool workflow
  to another model.
* Pinned requests are still revalidated against health and hard policy every time.
* Without any identifier, general chat is request-routed (documented stateless policy). For
  clients that cannot send an identifier, request a concrete deployment id instead of `auto`.
* Affinity does not require residency: a model may unload between turns and remain selected.

## F. Decision record

```json
{
  "request_id": "req_…", "config_hash": "…", "registry_version": 3,
  "requested_model": "auto", "alias": "auto", "profile": "quality",
  "requirements": {"primary_task": "coding", "tasks": {"coding": 0.7}, "needs_tools": true, "tokens": {...}},
  "exclusions": {"ollama/plain:3b": ["tool calling required; capability tools is unsupported (source_claim)"]},
  "candidates": [{"deployment": "ollama/big:27b", "quality": 0.72, "evidence": "prior:catalogue …", "score": 0.61, "notes": [...]}],
  "chosen": "ollama/big:27b", "evidence": "prior:catalogue",
  "reasons": ["task=coding (clear); required: tool support; context need ~1600 tokens",
              "1 deployment(s) excluded by hard filters; 2 eligible",
              "ollama/big:27b ranked first on profile quality: quality 0.72 (prior:catalogue), latency cost 1.00, not resident"],
  "overhead_ms": 0.41, "outcome": "ok", "failover": []
}
```

Inspect with `modelsaar explain` (offline dry run), `modelsaar explain --live` (running gateway),
`modelsaar decisions [request_id]`, `GET /admin/decisions`, or `/admin/ui`. Responses carry
`X-ModelSaar-Request-Id`, `X-ModelSaar-Deployment`, `X-ModelSaar-Profile`; the `model` field keeps
the requested alias by default (`server.response_model_field: deployment` to change). Routing
commentary is never injected into assistant content.

## Embeddings

`/v1/embeddings` routes an alias defined under `embeddings:` to the contract's deployments only.
Members must be **one verified identity**: the Ollama digest, or `backends[].models[].identity` for
generic endpoints. The alias's identity is established **before any request is dispatched**:
`embeddings[].identity` when declared, else the identity recorded for the alias, else the verified
identity of the first member *in contract order* whose identity is known — recorded synchronously
at that moment, so two concurrent first requests see the same anchor and cannot bind two embedding
spaces (nothing learned from a response ever becomes the anchor). A member with an unknown identity
is never used as a replica (a model-name match is not an identity); a member whose identity differs
is excluded with a re-indexing remedy, whatever its dimensions — never a silent switch to a different
space. When members declare several identities the decision says which one was anchored and asks
for an explicit `embeddings[].identity`.
After you change the model deliberately, re-index and set `embeddings[].identity` to the new value.
Request-level `dimensions` that differ from the alias and `encoding_format` other than `float` are
rejected (`400 unsupported_contract_option`). Every response is validated (vector count, indices,
dimensions, finite values, unit norm when `normalized: true`); a violation is `502
embedding_contract_violation`, never a 200. `query_prefix`/`document_prefix` are not applied by the
gateway (inputs are forwarded verbatim) and are rejected when non-empty. A concrete embedding
deployment id can also be requested directly.

## Memory budgets

A `resource_pools[].memory_gb` is a hard admission constraint: resident weights (deployments the
runtime reports loaded), every distinct deployment currently reserved (incl. an uncertain hold after
a timeout/disconnect and the classifier), every deployment **assumed resident** since its last
completed dispatch, and the candidate, plus `memory_margin_gb`, must fit. A request slot and weight
residency are different events: when a response ends the slot is released but the weights stay
loaded, so the pool keeps counting them until the runtime's residency observation (Ollama `/api/ps`
on the periodic refresh or `/admin/refresh`) reconciles the registry. Runtimes that cannot report
residency keep the assumption indefinitely unless `assumed_residency_ttl_s` is set — the gateway
cannot see when such a runtime evicts a model, so the conservative choice is the default. A *failed*
residency query (`/api/ps` errors while the runtime is otherwise healthy) is not an observation: known
and assumed occupancy is kept until the query succeeds again. A reservation released because the
connection was refused before the request was sent (`connect` failure) does not assume residency —
nothing reached the runtime — so failover to another deployment is not blocked by phantom weights;
any outcome where loading or computation may have started keeps the conservative assumption. The
estimates are weights-only (`memory_gb_estimate` with its provenance: Ollama size × 1.15, operator
declaration or override); KV cache, workspace and runtime overhead are covered only by the margin, so
this is a budget, not an OOM guarantee, and nothing here measures physical memory. Unified memory is
counted once per pool; a deployment is counted once however many requests it serves. Unknown
estimates follow `unknown_memory_policy`: `allow` counts them as 0 and labels the decision; `reject`
refuses admission whenever *any* counted member — the candidate, a resident or a reservation — has an
unknown estimate, because one unknown model makes the budget unverifiable. The check runs atomically
with the pool slot; `/admin/status` shows `memory_reserved_gb`, the holders and
`memory_assumed_resident`.

## Continuity and failover

Pre-commit failover (one attempt, same candidate list) is refused when the request is bound to the
deployment that started the exchange: a tool-result turn whose tool-call ids were issued by that
deployment, a conversation carrying `reasoning_content`, or a session pinned by affinity. The
decision records `failover_allowed` and `failover_note`; the client gets the backend's error and
decides. A timeout — before the first byte, **while streaming**, on an embedding request or inside a
capability probe — converts the reservation into an uncertain hold (`admission.uncertain_hold_s`)
because the backend may still be generating; a probe run stops at the first uncertain timeout and
reports the probes it skipped. Every upstream call has a deadline: the tighter of
`server.request_timeout_s` and the backend's `timeout_s` (never "no timeout"). Circuit-breaker
success and session pinning are recorded only after a validated completion: a parsed
`choices[0].message`, or a stream that contained at least one completion chunk, no malformed data
frame, and a finish reason or `[DONE]`. SSE comments and keepalives are ignored, usage-only frames
are accepted; a data frame that is not a completion structure is not relayed, invalidates the
stream (`stream_invalid_after_commit`, circuit failure, no pin) and is reported in the `error`
frame. The upstream terminal marker is held back: the client receives exactly one `data: [DONE]`,
emitted by the gateway after validation, so an error frame always precedes it. An HTTP 200 that is
not a completion is `502 upstream_bad_response`.
