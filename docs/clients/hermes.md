# NousResearch Hermes Agent → ModelSaar

Verified against hermes-agent.nousresearch.com docs and `cli-config.yaml.example` on 2026-10-11
(sources in [research/clients-2026-10-11.md](../research/clients-2026-10-11.md), §4). Test status:
configuration keys **documented**; live Hermes tool round trip **NOT RUN** in this build.

Generate the snippet: `modelsaar client-config hermes` (`--apply` merges into `~/.hermes/config.yaml`
with a backup, preserving unrelated keys).

## Key facts

* `~/.hermes/config.yaml` is the single source of truth; secrets go in `~/.hermes/.env`.
* **Each provider has its own credential setting** (`key_env`, `api_key`, or `key_cmd`). There is no
  generic `HERMES_*` variable for custom endpoints; `OPENAI_BASE_URL` applies to the built-in
  `openai-api` provider only (the docs are inconsistent on this point — the `providers:` block
  avoids the ambiguity).
* `transport: chat_completions` (default) is what ModelSaar implements; do not use
  `codex_responses` or `anthropic_messages`.
* `session_affinity_header: <Header-Name>` makes Hermes send its conversation id in that header on
  every request ("off unless set"). ModelSaar reads `X-ModelSaar-Session` by default.
* Hermes passes `reasoning_effort` through; if a backend rejects it you get the HTTP 400 unchanged.

```yaml
# ~/.hermes/config.yaml
model:
  default: auto
  provider: custom
  base_url: http://127.0.0.1:8484/v1
  key_env: MODELSAAR_API_KEY
  context_length: 32768          # use the alias contract minimum printed by client-config
providers:
  modelsaar:
    api: http://127.0.0.1:8484/v1
    key_env: MODELSAAR_API_KEY
    transport: chat_completions
    default_model: auto
    context_length: 32768
    session_affinity_header: X-ModelSaar-Session
```

```env
# ~/.hermes/.env
MODELSAAR_API_KEY=<first line of ~/.modelsaar/keys/api_keys>
```

Interactive alternative: `hermes model` → *Custom endpoint* → URL `http://127.0.0.1:8484/v1`, key,
model `auto`, context length, API mode *chat completions*.

## Tools

Hermes uses native tools over Chat Completions and documents backend requirements (llama.cpp
`--jinja`, vLLM `--enable-auto-tool-choice --tool-call-parser hermes`). ModelSaar only routes tool
requests to deployments whose tool support is verified (`modelsaar probe`). Whether Hermes sends
`tool_choice` or parallel calls is not documented; a `required` tool choice would make Ollama-backed
deployments ineligible (422 with blocker).

## Model listing

`/model custom` queries `GET /v1/models`; ModelSaar's entries include a `modelsaar` object with
`context_length`/`tools`/`vision` metadata. Which field Hermes parses for context length is not
documented, so set `context_length` in `config.yaml` explicitly.
