# OpenClaw → ModelSaar

Verified against docs.openclaw.ai on 2026-10-11 (sidebar release v2026.9.9; sources in
[research/clients-2026-10-11.md](../research/clients-2026-10-11.md), §2). OpenClaw is the project
formerly released as Warelay → Clawdbot → Moltbot (renamed OpenClaw 2026-01-30). Test status:
configuration keys **documented**; live OpenClaw tool round trip **NOT RUN** in this build.

Generate the snippet: `modelsaar client-config openclaw` (`--apply` merges into
`~/.openclaw/openclaw.json` with a backup when the file is plain JSON; JSON5 files with comments must
be merged by hand).

## Key facts

* Config file `~/.openclaw/openclaw.json` (JSON5). Provider block `models.providers.<id>` with
  `baseUrl` (**include `/v1`**), `apiKey` (`${ENV_VAR}` substitution), `api: "openai-completions"`
  (Chat Completions — the default when omitted; do **not** use `openai-responses`, ModelSaar returns
  501 for `/v1/responses`).
* Custom provider models are **not auto-discovered**: declare each alias under `models[]` with
  `id`, `name`, `reasoning`, `input` (`["text"]` or `["text","image"]`), `contextWindow`, `maxTokens`,
  `cost {input, output, cacheRead, cacheWrite}` (zeros for local).
* `compat.supportsPromptCacheKey: true` makes OpenClaw send `prompt_cache_key` (session id +
  boundary count) to a custom endpoint; ModelSaar reads it (`affinity.body_fields`) to keep a run on
  one deployment. `compat.supportsTools` should mirror the alias contract.
* Default model: `agents.defaults.model.primary: "modelsaar/auto"`; aliases via
  `agents.defaults.models."modelsaar/auto".alias`.
* `request.allowPrivateNetwork` defaults to false but a custom `baseUrl` origin is trusted exactly.

```json5
{
  agents: { defaults: { model: { primary: "modelsaar/auto" } } },
  models: {
    mode: "merge",
    providers: {
      modelsaar: {
        baseUrl: "http://127.0.0.1:8484/v1",
        apiKey: "${MODELSAAR_API_KEY}",
        api: "openai-completions",
        timeoutSeconds: 300,
        models: [
          { id: "auto", name: "ModelSaar auto", reasoning: false, input: ["text"],
            contextWindow: 32768, maxTokens: 8192,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
            compat: { supportsTools: true, supportsPromptCacheKey: true } },
          { id: "auto-code", name: "ModelSaar auto-code", reasoning: false, input: ["text"],
            contextWindow: 32768, maxTokens: 8192,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
            compat: { supportsTools: true, supportsPromptCacheKey: true } }
        ]
      }
    }
  }
}
```

`export MODELSAAR_API_KEY=$(head -1 ~/.modelsaar/keys/api_keys)` in the shell that runs OpenClaw.

Use the `contextWindow` printed by `client-config` (the alias contract's minimum across members) so
OpenClaw's own context management stays within what every eligible deployment can serve.

## Notes

* OpenClaw streams and uses a 300 s first-response budget for local endpoints; `timeoutSeconds`
  above matches it.
* `utilityModel` (OpenClaw's cheap internal-task model) can point at `modelsaar/auto-fast`.
* Whether OpenClaw sends `tool_choice`/`parallel_tool_calls` is not documented; if it does send
  `tool_choice: required`, Ollama-backed deployments are ineligible and ModelSaar returns 422 with
  that blocker.
