# Odysseus → ModelSaar

Status: the **request shape is supported and fixture-tested** (`tests/test_client_compat_odysseus.py`,
2026-10-13); a chat through the installed Odysseus client itself was **NOT RUN by the project** — it ran
on the owner's GX10 and is recorded in the verification report when executed.

Odysseus talks plain OpenAI Chat Completions, so it needs no generator: point it at the gateway
(`http://<gateway-host>:8484/v1`, API key = the line printed by `head -1 ~/.modelsaar/keys/api_keys`,
model `auto`). Model discovery (`/v1/models`) worked unchanged.

## What was failing

For an endpoint it considers self-hosted, Odysseus's `src/llm_core.py` (`_apply_local_cache_affinity()`)
adds two llama.cpp-style fields to every chat request: `session_id` (its conversation id) and
`cache_prompt: true`. ModelSaar forwards only allow-listed fields and does not drop unknown ones
silently, so the gateway answered `HTTP 400: unsupported request field(s): ['cache_prompt', 'session_id']`.

## The compatibility contract (gateway-owned; nothing to edit in Odysseus)

| field | validation | meaning in ModelSaar | forwarded? |
|---|---|---|---|
| `session_id` | non-empty printable string, ≤ 256 characters; anything else → `400` naming the field | **conversation affinity**, scoped to the authenticated caller (same semantics as `modelsaar.session`): follow-up turns with the same id stay on the deployment that answered, revalidated against health and policy every time; tool round-trip continuity is unchanged | never |
| `cache_prompt: true` | must be a JSON boolean; strings/numbers → `400` | **advisory** hint; the backend manages its own prompt cache, the gateway promises no cache hit and records the disposition in the routing decision (`compat.cache_prompt`) | never |
| `cache_prompt: false` | JSON boolean | asks for a guaranteed cache bypass; no shipped backend path (Ollama, generic OpenAI-compatible) can honour that per request, so the gateway answers `400 unsupported_capability` naming `cache_prompt` **before anything is sent** | never |

Precedence when several session hints are present (fixed, independent of field order):
`modelsaar.session` → `session_id` → configured headers (`X-ModelSaar-Session`, `X-OpenWebUI-Chat-Id`) →
configured body fields (`prompt_cache_key`). Other sources carrying a *different* id are listed in the
decision as `affinity.ignored_hints`; identical values are not a conflict.

Everything else stays strict: any other unknown field (for example llama.cpp's `id_slot`) is still
rejected, and the request Ollama receives contains only the fields its adapter supports.

A private address does not mean the backend implements llama.cpp's extensions, so neither field is
passed through to any backend; a llama.cpp slot identity is not guaranteed by the gateway.

## Check it

```bash
curl -sS http://127.0.0.1:8484/v1/chat/completions -H "Authorization: Bearer $(head -1 ~/.modelsaar/keys/api_keys)" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello"}],"session_id":"demo-1","cache_prompt":true}'
modelsaar decisions --limit 1     # shows session_source=body:session_id and the cache_prompt disposition
```
