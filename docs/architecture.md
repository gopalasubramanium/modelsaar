# Architecture

One process, one versioned YAML config, a CLI, optional SQLite state. No external services.

```
                 ┌────────────────────────────────────────────────────────────────────┐
  clients        │ modelsaar.server (Starlette)                                       │
  Open WebUI     │  /v1/models /v1/chat/completions /v1/embeddings /v1/decisions /healthz│
  OpenClaw  ───▶ │  /admin/{status,decisions,explain,refresh,ui}   (admin key)        │
  OpenCode       │        │ auth (security.py)   commitment rules   SSE relay (sse.py)│
  Hermes         └────────┼───────────────────────────────────────────────────────────┘
                          ▼
                 ┌──────────────────── routing/router.py ───────────────────┐
                 │ requirements.py ─▶ eligibility.py ─▶ classifier.py ─▶    │
                 │   (tokens.py)        (hard filters)   (optional, local)   │
                 │                 ─▶ scoring.py ─▶ decision.py             │
                 │ affinity.py (sessions, tool round trips)                  │
                 │ admission.py (pools, queues, reservations, circuits)      │
                 └───────┬──────────────────────────────┬───────────────────┘
                         │ registry.py (deployments,     │ store.py (SQLite:
                         │ tri-state caps, fingerprints) │ probes, measurements, decisions)
                         ▼                               ▼
                 ┌─ adapters/ ───────────────────────────────────────────────┐
                 │ ollama.py: /api/tags /api/show /api/ps /api/version       │
                 │            + /v1/chat/completions, /v1/embeddings, /v1/systemone │
                 │ openai_compat.py: /models /chat/completions /embeddings   │
                 │                   /tokenize (vLLM)                        │
                 │ register_adapter() plugin hook                            │
                 └──────────────┬────────────────────────────────────────────┘
                                ▼
                  user-managed runtimes: Ollama, vLLM, llama.cpp server, LM Studio, …
   catalogue/starter.yaml ─ priors/tags/roles (model-card evidence, dated)
   probes.py ─ live capability checks keyed by fingerprint
   evaluation/ ─ harness, synthetic fixtures, scorers; clientconfig/ ─ generators; doctor.py
```

## Modules

| module | responsibility |
|---|---|
| `config.py` | Versioned, typed configuration (`version: 1`); atomic write; loopback/LAN guard; aliases, pools, backends, overrides, embedding contracts |
| `registry.py` | `Deployment` records: identity (backend, model, digest, runtime version, template hash, quantization, context, pool), states (configured/discovered/available/loaded/healthy), three-state capabilities with provenance, measurements, fingerprint |
| `store.py` | SQLite (stdlib) for probe evidence and measurements per fingerprint, bounded decision log (metadata only) |
| `adapters/` | Backend protocol handling; typed, allow-listed translation; URL confinement to the configured host |
| `protocol/openai.py` | Request validation; unknown fields are rejected, never dropped |
| `protocol/sse.py` | Incremental SSE parser tolerant of partial frames/CRLF/UTF-8 boundaries; relay observer |
| `routing/requirements.py` | Structural requirements and deterministic multi-label task signals; language detection |
| `routing/tokens.py` | Documented conservative token estimates (script-aware); `router._exact_counts` refines borderline cases via a runtime's `/tokenize` when available |
| `routing/eligibility.py` | Hard filters with per-deployment reasons and remedies |
| `routing/classifier.py` | Optional local classifier with strict contract, timeout, deterministic fallback |
| `routing/scoring.py` | Transparent ranking; evidence levels; tie-break to lower overhead |
| `routing/affinity.py` | Caller-scoped session affinity from explicit identifiers; tool round-trip continuity |
| `routing/admission.py` | Bounded queues, backend/pool concurrency, atomic reservation, uncertain occupancy, circuit breakers |
| `routing/decision.py` | Decision record |
| `routing/router.py` | Orchestration, discovery refresh (atomic registry swap), alias contracts, `/v1/models` truth |
| `server.py` | HTTP surface, auth, commitment rules, failover, streaming relay, admin API, status page |
| `probes.py` | Capability probes and latency/load measurement |
| `catalogue/` | Verified starter catalogue + matcher (priors only) |
| `clientconfig/` | Verified client configuration generators with safe apply |
| `doctor.py` | Diagnostics |
| `evaluation/` | Harness, fixtures, scorers, baselines |
| `cli.py` | `modelsaar` commands |
| `testing/fakebackend.py` | Controlled Ollama/OpenAI-compatible fixture with fault injection (tests + `demo`) |

## Deployment identity and state

A deployment id is `<backend_id>/<model_name>`. Its fingerprint hashes backend, model, digest,
runtime + version, template hash, quantization, served context and pool. Probe results and
measurements are stored against the fingerprint; when any of those change, stored evidence no longer
applies and is listed under `invalidated_probe_fingerprints` for transparency.

States are distinct: *configured* (declared in config), *discovered* (listed by the runtime),
*available on disk*, *loaded* (resident per `/api/ps`), *healthy* (backend reachable), and
*eligible for a particular request* (only decided per request by the filters).

## Configuration snapshots

`load_config` returns an immutable object with a content hash. A request captures the router/config
snapshot at entry and uses it throughout; registry refreshes replace the deployment map atomically
and never change a request midway. Configuration changes take effect by restarting `modelsaar serve`
(no hot reload in 0.1).

## Response commitment rules

* Before any header/byte is sent: on connection failure or upstream 5xx, at most
  `routing.max_failover_attempts` (default 1) retries to the next candidate that passed the same
  hard filters. Only chat completions (stateless, repeatable) are retried.
* After the first byte: no retries, no switching. Upstream failure ends the stream with an SSE
  `error` frame and `[DONE]`; the decision records `stream_failed_after_commit`.
* Client disconnect or read timeout mid-stream: the reservation becomes *uncertain* for
  `admission.uncertain_hold_s` because the backend may still be generating (same for embedding
  timeouts and probe timeouts; a probe run stops after one).
