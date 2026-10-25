# Extending ModelSaar

See [catalogue.md](catalogue.md) for adding deployments, catalogue entries and adapters.

## Aliases

```yaml
aliases:
  auto-reasoning:
    profile: quality
    require_tags: [reasoning]
    description: "deployments tagged reasoning"
  auto-small:
    profile: fast
    deployments: ["ollama/gemma4:e4b", "ollama/granite4.2:3b"]
```

Alias names must start with `auto`. An alias is advertised only when at least one usable deployment
satisfies its constraints; its `/v1/models` contract reports the minimum context and whether tools,
vision and json_schema are supported by every member (`supported`), some (`partial`) or none.

## Profiles

`routing.profiles.{quality,balanced,fast}` hold the weights `quality`, `latency`, `residency`,
`overhead`. `routing.switching_penalty` controls session hysteresis.

## Per-request hints

Clients may add a `modelsaar` object to the request body (never forwarded to backends):

```json
{"model": "auto", "messages": [...], "modelsaar": {"session": "run-42", "profile": "fast"}}
```

## Optional classifier

```yaml
routing:
  classifier:
    enabled: true
    backend: ollama
    model: "gemma4:e4b"       # a small local model that honours response_format
    timeout_s: 2.0
    only_when_ambiguous: true
```

To use a decision model instead of a chat model — a model whose Ollama `/api/show` capabilities
list `decision` (nimble, clef, laya, …; discovered with `role: decision`, never offered for chat) —
set `mode: decision`; the gateway then asks Ollama's `POST /v1/systemone` (Ollama ≥ 0.35.0) one
`choice` question over the task labels and reads the per-label probabilities:

```yaml
routing:
  classifier:
    enabled: true
    mode: decision
    backend: ollama
    model: "nimble"            # role=decision; a generative model here is refused ("unavailable")
    timeout_s: 2.0
    only_when_ambiguous: true
```

`modelsaar doctor` checks that the configured deployment matches the mode. Backends without a
decision endpoint (`openai_compatible`) report the classifier as `unavailable` and routing continues.

Its calls, timeouts and failures are visible in `/admin/status` → `classifier` (with the `mode`). If
it does not improve routing in `modelsaar eval`, leave it disabled: the deterministic path is the
simple mode.
