# OpenCode → ModelSaar (V1 and V2 configuration)

Verified against opencode.ai/docs (updated Oct 8 2026), opencode.ai/v2/docs, the live config schema
and the `dev` source on 2026-10-11 (sources in [research/clients-2026-10-11.md](../research/clients-2026-10-11.md), §3).
Test status: configuration keys **documented**; live OpenCode tool round trip **NOT RUN** in this build.

**Never mix the two schemas.** `modelsaar client-config opencode` emits V1; `opencode-v2` emits V2;
`--apply` refuses to write a V1 block into a V2 file and vice versa.

## V1 (`opencode.ai/docs`)

File: `~/.config/opencode/opencode.json` (global) or `./opencode.json` (project); JSON or JSONC.
Top-level **`provider`** (singular). Use `npm: "@ai-sdk/openai-compatible"` → Chat Completions
(`@ai-sdk/openai` defaults to the Responses API, which ModelSaar does not implement). Include `/v1`.
Models are declared manually.

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "modelsaar/auto",
  "provider": {
    "modelsaar": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "ModelSaar",
      "options": { "baseURL": "http://127.0.0.1:8484/v1", "apiKey": "{env:MODELSAAR_API_KEY}", "setCacheKey": true },
      "models": {
        "auto":      { "name": "ModelSaar auto", "tool_call": true, "reasoning": false, "attachment": false,
                       "modalities": { "input": ["text"], "output": ["text"] },
                       "limit": { "context": 32768, "output": 8192 }, "cost": { "input": 0, "output": 0 } },
        "auto-code": { "name": "ModelSaar auto-code", "tool_call": true,
                       "limit": { "context": 32768, "output": 8192 }, "cost": { "input": 0, "output": 0 } }
      }
    }
  }
}
```

## V2 (`opencode.ai/v2/docs`)

Top-level **`providers`** (plural); `package`, `settings`, `env`, model `capabilities`. V1 fields
`attachment`, `reasoning`, `temperature`, `interleaved`, `release_date` are ignored in V2.

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "providers": {
    "modelsaar": {
      "name": "ModelSaar",
      "env": ["MODELSAAR_API_KEY"],
      "package": "@opencode/ai/providers/openai-compatible",
      "settings": { "baseURL": "http://127.0.0.1:8484/v1" },
      "models": {
        "auto": { "name": "ModelSaar auto", "capabilities": { "tools": true, "input": ["text"], "output": ["text"] } }
      }
    }
  }
}
```

(`limit` sub-keys for V2 were not shown in the fetched docs; omit them unless your schema validator
accepts them.)

## Session continuity

OpenCode sets `toolChoice` only when a caller asks (none by default) and streams tool deltas.
`options.setCacheKey: true` (V1) attaches the session id as a prompt cache key *inside the AI SDK*;
whether `@ai-sdk/openai-compatible` emits `prompt_cache_key` on the wire is **not documented**, so do
not rely on it. ModelSaar still keeps every tool round trip on the deployment that issued the tool
calls (tool-call-id continuity), which is what matters for agent loops. For whole-session pinning,
request a concrete deployment id (e.g. `modelsaar/ollama/qwen3.8:27b` declared as a model) instead of
`auto`.

## Pitfalls

* Missing `/v1` → 404s from the gateway.
* `tool_call: true` is required for agent use; use the alias contract's `tools` value from
  `modelsaar client-config` (only `supported` aliases should be marked).
* Ollama users: tool calls fail on small contexts — set `num_ctx` ≥ 16–32k in the Modelfile; the
  gateway's 422 "effective context" blocker tells you when the served context is too small.
